"""
ingestion_service.py
---------------------
Fetches pages from the Notion 'DocForge Documents' database,
splits them into chunks, embeds via Azure OpenAI, and stores
in ChromaDB.
"""

import os
import re
import json
import logging
import requests
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()
log = logging.getLogger(__name__)

NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
NOTION_VERSION = "2022-06-28"
NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type":   "application/json",
}
BASE_URL = "https://api.notion.com/v1"

_embed_client = None

CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50


def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        load_dotenv(override=True)
        api_key  = (os.getenv("AZURE_OPENAI_EMB_KEY")             or "").strip() \
                or (os.getenv("AZURE_OPENAI_EMBED_KEY")            or "").strip() \
                or (os.getenv("AZURE_OPENAI_LLM_KEY")              or "").strip()
        endpoint = (os.getenv("AZURE_OPENAI_EMB_ENDPOINT")         or "").strip() \
                or (os.getenv("AZURE_OPENAI_EMBED_ENDPOINT")        or "").strip() \
                or (os.getenv("AZURE_OPENAI_LLM_ENDPOINT")          or "").strip()
        version  = (os.getenv("AZURE_OPENAI_EMB_API_VERSION")       or "").strip() \
                or (os.getenv("AZURE_OPENAI_EMBED_API_VERSION")      or "").strip() \
                or (os.getenv("AZURE_OPENAI_LLM_API_VERSION")        or "").strip() \
                or "2024-02-01"
        if not api_key or not endpoint:
            raise ValueError(
                "Missing embedding credentials. Set AZURE_OPENAI_EMB_KEY + "
                "AZURE_OPENAI_EMB_ENDPOINT in your .env "
                "(or AZURE_OPENAI_LLM_KEY + AZURE_OPENAI_LLM_ENDPOINT as fallback)"
            )
        _embed_client = AzureOpenAI(
            api_key        = api_key,
            azure_endpoint = endpoint,
            api_version    = version,
        )
    return _embed_client


def _embed_deployment():
    return (os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT")   or "").strip() \
        or (os.getenv("AZURE_OPENAI_EMBED_DEPLOYMENT") or "").strip() \
        or "text-embedding-3-large"


# ── Embedding ─────────────────────────────────────────────────────────────────

_EMBED_DIMENSIONS = {
    "text-embedding-ada-002":  1536,
    "text-embedding-3-small":  1536,
    "text-embedding-3-large":  3072,
}

def _embed_dim() -> int:
    deployment = _embed_deployment().lower()
    for key, dim in _EMBED_DIMENSIONS.items():
        if key in deployment:
            return dim
    return 1536


def embed_text(text: str) -> list[float]:
    text = text.replace("\n", " ").strip()
    if not text:
        return [0.0] * _embed_dim()
    client = _get_embed_client()
    resp   = client.embeddings.create(input=text, model=_embed_deployment())
    return resp.data[0].embedding


def embed_batch(texts: list[str]) -> list[list[float]]:
    client     = _get_embed_client()
    deployment = _embed_deployment()
    embeddings = []
    batch_size = 16
    for i in range(0, len(texts), batch_size):
        batch = [t.replace("\n", " ").strip() for t in texts[i:i+batch_size]]
        resp  = client.embeddings.create(input=batch, model=deployment)
        embeddings.extend([r.embedding for r in resp.data])
    return embeddings


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text.strip():
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) < chunk_size * 4:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            if len(para) > chunk_size * 4:
                words = para.split()
                sub   = ""
                for word in words:
                    if len(sub) + len(word) < chunk_size * 4:
                        sub += " " + word
                    else:
                        if sub:
                            chunks.append(sub.strip())
                        sub = word
                if sub:
                    current = sub.strip()
            else:
                current = para
    if current:
        chunks.append(current)
    overlapped = []
    for i, chunk in enumerate(chunks):
        if i > 0 and overlap > 0:
            prev_tail = chunks[i-1][-overlap*4:]
            chunk     = prev_tail + " " + chunk
        overlapped.append(chunk.strip())
    return overlapped


# ── Notion fetching ───────────────────────────────────────────────────────────

def _get_notion_database_id() -> str | None:
    res = requests.post(f"{BASE_URL}/search", headers=NOTION_HEADERS, json={
        "query":  "DocForge Documents",
        "filter": {"property": "object", "value": "database"}
    })
    results = res.json().get("results", [])
    for r in results:
        title_arr = r.get("title", [])
        title_txt = title_arr[0].get("plain_text", "") if title_arr else ""
        if title_txt == "DocForge Documents":
            return r["id"]
    return None


def _fetch_database_pages(database_id: str) -> list[dict]:
    pages   = []
    payload = {"page_size": 100}
    while True:
        res  = requests.post(
            f"{BASE_URL}/databases/{database_id}/query",
            headers=NOTION_HEADERS,
            json=payload
        )
        data = res.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return pages


def _extract_page_metadata(page: dict) -> dict:
    """Pull title, format, doc_type, version, and last_edited_time from page."""
    props   = page.get("properties", {})
    title   = ""
    fmt     = "word"
    version = 1

    title_prop = props.get("Title", {}).get("title", [])
    if title_prop:
        title = title_prop[0].get("plain_text", "")

    fmt_prop = props.get("Format", {}).get("select")
    if fmt_prop:
        fmt = fmt_prop.get("name", "Word").lower()

    ver_prop = props.get("Version", {}).get("number")
    if ver_prop:
        version = int(ver_prop)

    return {
        "title":            title,
        "doc_type":         fmt,
        "version":          version,
        "page_id":          page["id"],
        "notion_url":       page.get("url", ""),
        "last_edited_time": page.get("last_edited_time", ""),  # ISO string from Notion
    }


def _fetch_block_text(page_id: str) -> list[dict]:
    sections = []
    current_section = "Introduction"
    current_text    = []

    def fetch_blocks(block_id: str):
        nonlocal current_section, current_text
        res    = requests.get(
            f"{BASE_URL}/blocks/{block_id}/children",
            headers=NOTION_HEADERS
        )
        blocks = res.json().get("results", [])
        for block in blocks:
            btype = block.get("type", "")
            bdata = block.get(btype, {})
            rich  = bdata.get("rich_text", [])
            text  = "".join(r.get("plain_text", "") for r in rich).strip()

            if btype in ("heading_1", "heading_2"):
                if current_text:
                    sections.append({
                        "section_name": current_section,
                        "text":         "\n".join(current_text).strip()
                    })
                    current_text = []
                current_section = text or current_section

            elif btype == "heading_3":
                if text:
                    current_text.append(f"\n### {text}")

            elif btype in ("paragraph", "bulleted_list_item",
                           "numbered_list_item", "quote"):
                if text:
                    prefix = "• " if btype == "bulleted_list_item" else ""
                    current_text.append(prefix + text)

            elif btype == "table":
                row_res  = requests.get(
                    f"{BASE_URL}/blocks/{block['id']}/children",
                    headers=NOTION_HEADERS
                )
                row_data = row_res.json().get("results", [])
                for row in row_data:
                    cells = row.get("table_row", {}).get("cells", [])
                    row_text = " | ".join(
                        "".join(c.get("plain_text", "") for c in cell)
                        for cell in cells
                    )
                    if row_text.strip():
                        current_text.append(row_text)

            if block.get("has_children"):
                fetch_blocks(block["id"])

    fetch_blocks(page_id)

    if current_text:
        sections.append({
            "section_name": current_section,
            "text":         "\n".join(current_text).strip()
        })

    return sections


def _infer_industry(title: str, sections: list[dict]) -> str:
    combined = (title + " " + " ".join(s["section_name"] for s in sections)).lower()
    tags = {
        "Finance":    ["balance sheet", "cash flow", "income statement", "p&l",
                       "budget", "financial", "revenue", "profit"],
        "HR":         ["employee", "onboarding", "performance", "payroll",
                       "hr ", "human resource", "recruitment"],
        "Legal":      ["contract", "agreement", "clause", "legal", "compliance",
                       "policy", "sow", "msa", "nda"],
        "Tech":       ["software", "api", "system", "architecture", "technical",
                       "deployment", "infrastructure", "product"],
        "Operations": ["sop", "process", "procedure", "operations", "workflow",
                       "checklist", "audit"],
        "Sales":      ["proposal", "quote", "sales", "client", "lead",
                       "pipeline", "crm"],
    }
    for industry, keywords in tags.items():
        if any(kw in combined for kw in keywords):
            return industry
    return "General"


# ── Main ingestion entry point ────────────────────────────────────────────────

def ingest_notion(page_ids: list[str] = None, force: bool = False) -> dict:
    """
    Ingest documents from the Notion DocForge Documents database.

    page_ids : ingest only these specific pages (None = all pages)
    force    : if True, re-ingest even if the doc hasn't changed
               if False (default), skip pages whose last_edited_time
               hasn't advanced past the stored ingested_at timestamp

    Returns { ingested: N, chunks: M, skipped: K }
    """
    from backend.chroma_db import upsert_chunks, list_ingested_docs

    db_id = _get_notion_database_id()
    if not db_id:
        raise ValueError("Could not find 'DocForge Documents' database in Notion.")

    pages = _fetch_database_pages(db_id)

    if page_ids:
        pages = [p for p in pages if p["id"].replace("-", "") in
                 [pid.replace("-", "") for pid in page_ids]]

    # Build lookup: notion_page_id → ingested_at for already-indexed docs
    if not force:
        existing = {
            d["notion_page_id"]: d["ingested_at"]
            for d in list_ingested_docs()
            if d.get("notion_page_id") and d.get("ingested_at")
        }
    else:
        existing = {}

    all_chunks = []
    ingested   = 0
    skipped    = 0

    for page in pages:
        meta = _extract_page_metadata(page)
        if not meta["title"]:
            skipped += 1
            continue

        # ── Skip unchanged pages ──────────────────────────────────────────────
        if not force and meta["page_id"] in existing:
            last_edited   = meta.get("last_edited_time", "")
            last_ingested = existing[meta["page_id"]]
            if last_edited and last_ingested and last_edited <= last_ingested:
                log.debug(f"Skipping unchanged: '{meta['title']}'")
                skipped += 1
                continue

        # Fetch block content
        sections = _fetch_block_text(meta["page_id"])
        if not sections:
            skipped += 1
            continue

        industry = _infer_industry(meta["title"], sections)

        # Chunk each section
        page_chunks = []
        for sec in sections:
            chunks = chunk_text(sec["text"])
            for chunk in chunks:
                if len(chunk.strip()) < 30:
                    continue
                page_chunks.append({
                    "doc_title":      meta["title"],
                    "doc_type":       meta["doc_type"],
                    "version":        meta["version"],
                    "industry":       industry,
                    "section_name":   sec["section_name"],
                    "chunk_text":     chunk,
                    "notion_url":     meta["notion_url"],
                    "notion_page_id": meta["page_id"],
                })

        if not page_chunks:
            skipped += 1
            continue

        # Batch embed
        texts      = [c["chunk_text"] for c in page_chunks]
        embeddings = embed_batch(texts)
        for c, emb in zip(page_chunks, embeddings):
            c["embedding"] = emb

        all_chunks.extend(page_chunks)
        ingested += 1
        log.info(f"Prepared {len(page_chunks)} chunks for '{meta['title']}'")

    total_chunks = upsert_chunks(all_chunks)
    return {"ingested": ingested, "chunks": total_chunks, "skipped": skipped}