"""
database.py
-----------
CiteRAG Lab storage layer.

Vector store : ChromaDB  (persists to ./chroma_data/)
Eval store   : SQLite    (persists to ./citerag_eval.db)

No PostgreSQL, no extensions required.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_data")
SQLITE_PATH = os.getenv("SQLITE_PATH", "./citerag_eval.db")
COLLECTION_NAME = "document_chunks"

# ── ChromaDB singleton ────────────────────────────────────────────────────────
_chroma_client     = None
_chroma_collection = None


def get_chroma():
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        _chroma_collection = _chroma_client.get_or_create_collection(
            name     = COLLECTION_NAME,
            metadata = {"hnsw:space": "cosine"},
        )
    return _chroma_collection


# ── SQLite for eval runs ──────────────────────────────────────────────────────
def get_sqlite():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Init ──────────────────────────────────────────────────────────────────────
def init_db():
    """Initialise ChromaDB collection and SQLite eval table."""
    # Touch Chroma collection (creates it if needed)
    get_chroma()
    log.info(f"ChromaDB ready at {CHROMA_DIR}")

    # SQLite eval table
    conn = get_sqlite()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eval_runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name   TEXT NOT NULL,
            config     TEXT NOT NULL,
            results    TEXT,
            summary    TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()
    log.info(f"SQLite ready at {SQLITE_PATH}")


# ── Chunk CRUD ────────────────────────────────────────────────────────────────
def upsert_chunks(chunks: list[dict]) -> int:
    """
    Insert or replace chunks in ChromaDB.
    Each chunk: { doc_title, doc_type, version, industry,
                  section_name, chunk_text, embedding,
                  notion_url, notion_page_id }
    Returns count inserted.
    """
    if not chunks:
        return 0

    col = get_chroma()

    # Delete existing chunks for these page IDs
    page_ids = list({c["notion_page_id"] for c in chunks})
    for pid in page_ids:
        existing = col.get(where={"notion_page_id": {"$eq": pid}})
        if existing["ids"]:
            col.delete(ids=existing["ids"])

    # Build Chroma batch
    ids         = []
    embeddings  = []
    documents   = []
    metadatas   = []

    for i, c in enumerate(chunks):
        chunk_id = f"{c['notion_page_id']}_{i}"
        ids.append(chunk_id)
        embeddings.append(c["embedding"])
        documents.append(c["chunk_text"])
        metadatas.append({
            "doc_title":      c["doc_title"],
            "doc_type":       c.get("doc_type", "word"),
            "version":        c.get("version", 1),
            "industry":       c.get("industry", ""),
            "section_name":   c.get("section_name", ""),
            "notion_url":     c.get("notion_url", ""),
            "notion_page_id": c["notion_page_id"],
            "ingested_at":    datetime.now().isoformat(),
        })

    # Chroma max batch = 5000
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        col.add(
            ids        = ids[i:i+batch_size],
            embeddings = embeddings[i:i+batch_size],
            documents  = documents[i:i+batch_size],
            metadatas  = metadatas[i:i+batch_size],
        )

    return len(ids)


def semantic_search(embedding: list[float], top_k: int = 5,
                    filters: dict = None) -> list[dict]:
    """
    Cosine similarity search with optional metadata filters.
    filters: { doc_type, industry, version, doc_title }
    """
    col = get_chroma()

    # Build Chroma where clause
    where = None
    if filters:
        conditions = []
        if filters.get("doc_type"):
            conditions.append({"doc_type": {"$eq": filters["doc_type"]}})
        if filters.get("industry"):
            conditions.append({"industry": {"$eq": filters["industry"]}})
        if filters.get("version"):
            conditions.append({"version": {"$eq": int(filters["version"])}})
        if filters.get("doc_title"):
            conditions.append({"doc_title": {"$eq": filters["doc_title"]}})
        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

    kwargs = {
        "query_embeddings": [embedding],
        "n_results":        min(top_k, col.count() or 1),
        "include":          ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    res = col.query(**kwargs)

    results = []
    for i, doc_id in enumerate(res["ids"][0]):
        meta  = res["metadatas"][0][i]
        dist  = res["distances"][0][i]
        score = round(1 - dist, 4)   # cosine distance → similarity
        results.append({
            "id":           doc_id,
            "doc_title":    meta.get("doc_title", ""),
            "doc_type":     meta.get("doc_type", "word"),
            "version":      meta.get("version", 1),
            "industry":     meta.get("industry", ""),
            "section_name": meta.get("section_name", ""),
            "chunk_text":   res["documents"][0][i],
            "notion_url":   meta.get("notion_url", ""),
            "notion_page_id": meta.get("notion_page_id", ""),
            "score":        score,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)


def list_ingested_docs() -> list[dict]:
    """Return distinct ingested documents with chunk counts."""
    col  = get_chroma()
    data = col.get(include=["metadatas"])

    # Group by notion_page_id
    pages = {}
    for meta in data["metadatas"]:
        pid = meta.get("notion_page_id", "")
        if pid not in pages:
            pages[pid] = {
                "doc_title":      meta.get("doc_title", ""),
                "doc_type":       meta.get("doc_type", "word"),
                "version":        meta.get("version", 1),
                "industry":       meta.get("industry", ""),
                "notion_page_id": pid,
                "notion_url":     meta.get("notion_url", ""),
                "chunk_count":    0,
                "ingested_at":    meta.get("ingested_at", ""),
            }
        pages[pid]["chunk_count"] += 1

    return sorted(pages.values(), key=lambda x: x["ingested_at"], reverse=True)


def delete_chunks_by_page(notion_page_id: str) -> int:
    """Delete all chunks for a specific Notion page."""
    col      = get_chroma()
    existing = col.get(where={"notion_page_id": {"$eq": notion_page_id}})
    count    = len(existing["ids"])
    if count:
        col.delete(ids=existing["ids"])
    return count


def get_all_titles() -> list[str]:
    col  = get_chroma()
    data = col.get(include=["metadatas"])
    return sorted({m.get("doc_title", "") for m in data["metadatas"] if m.get("doc_title")})


def get_all_industries() -> list[str]:
    col  = get_chroma()
    data = col.get(include=["metadatas"])
    return sorted({m.get("industry", "") for m in data["metadatas"] if m.get("industry")})


# ── Eval CRUD (SQLite) ────────────────────────────────────────────────────────
def save_eval_run(run_name: str, config: dict,
                  results: list[dict], summary: dict) -> int:
    conn = get_sqlite()
    cur  = conn.execute(
        "INSERT INTO eval_runs (run_name, config, results, summary) VALUES (?,?,?,?)",
        (run_name, json.dumps(config), json.dumps(results), json.dumps(summary))
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def list_eval_runs() -> list[dict]:
    conn = get_sqlite()
    rows = conn.execute(
        "SELECT id, run_name, config, summary, created_at FROM eval_runs ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "id":         r["id"],
            "run_name":   r["run_name"],
            "config":     json.loads(r["config"]),
            "summary":    json.loads(r["summary"]) if r["summary"] else {},
            "created_at": r["created_at"],
        })
    return result


def get_eval_run(run_id: int) -> dict | None:
    conn = get_sqlite()
    row  = conn.execute(
        "SELECT id, run_name, config, results, summary, created_at FROM eval_runs WHERE id = ?",
        (run_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id":         row["id"],
        "run_name":   row["run_name"],
        "config":     json.loads(row["config"]),
        "results":    json.loads(row["results"]) if row["results"] else [],
        "summary":    json.loads(row["summary"]) if row["summary"] else {},
        "created_at": row["created_at"],
    }