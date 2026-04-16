"""
database.py
------------
PostgreSQL connection pool and table initialisation.
Uses psycopg2 with a simple connection pool.

Tables:
  documents — stores every generated document with version tracking

Version tracking:
  - Every save of a document with the same title auto-increments version
  - parent_id links all versions of the same document to the first (v1)
  - version=1, parent_id=NULL  → original document
  - version=2, parent_id=1     → second generation of same title
"""

import os
import json
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

# ── Connection pool ───────────────────────────────────────────────────────────
_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            dbname=os.getenv("POSTGRES_DB", "docforge"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
        )
    return _pool


def get_conn():
    return get_pool().getconn()


def release_conn(conn):
    get_pool().putconn(conn)


# ── Table init ────────────────────────────────────────────────────────────────

# Full column spec used both in CREATE TABLE and in the migration loop.
# Order matters — referenced columns (id) must exist before FK columns (parent_id).
_COLUMNS = [
    ("title",      "TEXT",                                              "NOT NULL DEFAULT ''"),
    ("doc_type",   "TEXT",                                              "NOT NULL DEFAULT 'General'"),
    ("doc_format", "TEXT",                                              "NOT NULL DEFAULT 'word'"),
    ("content",    "JSONB",                                             "NOT NULL DEFAULT '{}'::jsonb"),
    ("file_bytes", "BYTEA",                                             ""),
    ("file_ext",   "TEXT",                                              ""),
    ("version",    "INTEGER",                                           "NOT NULL DEFAULT 1"),
    ("parent_id",  "INTEGER REFERENCES documents(id) ON DELETE SET NULL", ""),
    ("created_at", "TIMESTAMPTZ",                                       "DEFAULT NOW()"),
]


def init_db():
    """
    Create the documents table if it doesn't exist, then ensure every
    expected column is present (safe migration for older schemas).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:

            # ── 1. Create table if missing ────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id          SERIAL PRIMARY KEY,
                    title       TEXT         NOT NULL DEFAULT '',
                    doc_type    TEXT         NOT NULL DEFAULT 'General',
                    doc_format  TEXT         NOT NULL DEFAULT 'word',
                    content     JSONB        NOT NULL DEFAULT '{}'::jsonb,
                    file_bytes  BYTEA,
                    file_ext    TEXT,
                    version     INTEGER      NOT NULL DEFAULT 1,
                    parent_id   INTEGER      REFERENCES documents(id) ON DELETE SET NULL,
                    created_at  TIMESTAMPTZ  DEFAULT NOW()
                );
            """)

            # ── 2. Add any missing columns (safe on fresh or legacy tables) ───
            for col_name, col_type, col_constraint in _COLUMNS:
                cur.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'documents' AND column_name = %s
                """, (col_name,))
                if not cur.fetchone():
                    definition = f"{col_type} {col_constraint}".strip()
                    cur.execute(
                        f"ALTER TABLE documents ADD COLUMN {col_name} {definition}"
                    )
            
            
            conn.commit()
    finally:
        release_conn(conn)


# ── Version helpers ───────────────────────────────────────────────────────────

def get_latest_version(title: str) -> dict | None:
    """
    Return the latest version row for a given title, or None if title is new.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, version, parent_id
                FROM documents
                WHERE title = %s
                ORDER BY version DESC
                LIMIT 1
            """, (title,))
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "version": row[1], "parent_id": row[2]}
    finally:
        release_conn(conn)


def list_versions(title: str) -> list[dict]:
    """
    Return all versions of a document by title, oldest first.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, title, doc_format, version, parent_id, file_ext, created_at
                FROM documents
                WHERE title = %s
                ORDER BY version ASC
            """, (title,))
            rows = cur.fetchall()
            cols = ["id", "title", "doc_format", "version",
                    "parent_id", "file_ext", "created_at"]
            result = [dict(zip(cols, row)) for row in rows]
            for doc in result:
                if doc.get("created_at"):
                    doc["created_at"] = doc["created_at"].strftime("%d %b %Y, %I:%M %p")
            return result
    finally:
        release_conn(conn)


def list_versions_by_id(doc_id: int) -> list[dict]:
    """
    Return all versions of the document family that contains doc_id.
    Works whether doc_id is a v1 (parent) or any later version.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Find the root (v1) of this document family
            cur.execute("""
                SELECT COALESCE(parent_id, id), title
                FROM documents
                WHERE id = %s
            """, (doc_id,))
            row = cur.fetchone()
            if not row:
                return []
            root_id, title = row

            # Fetch all versions in family
            cur.execute("""
                SELECT id, title, doc_format, version, parent_id, file_ext, created_at
                FROM documents
                WHERE id = %s OR parent_id = %s
                ORDER BY version ASC
            """, (root_id, root_id))
            rows = cur.fetchall()
            cols = ["id", "title", "doc_format", "version",
                    "parent_id", "file_ext", "created_at"]
            result = [dict(zip(cols, row)) for row in rows]
            for doc in result:
                if doc.get("created_at"):
                    doc["created_at"] = doc["created_at"].strftime("%d %b %Y, %I:%M %p")
            return result
    finally:
        release_conn(conn)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def save_document(title: str, doc_type: str, doc_format: str,
                  content: dict, file_bytes: bytes = None,
                  file_ext: str = None,
                  save_mode: str = "new_version",
                  overwrite_id: int = None) -> dict:
    """
    Save a document with explicit user-chosen save mode.

    save_mode="new_version"  (default)
        - First save of a title: version=1, parent_id=NULL
        - Subsequent save: version=latest+1, parent_id=root (v1 id)

    save_mode="overwrite"
        - Requires overwrite_id (the id of the row to replace)
        - Updates content/file_bytes in-place, version unchanged
        - Use when user explicitly selects "Overwrite current version"

    Returns { id, version, parent_id, mode }
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:

            # ── Overwrite existing version in-place ───────────────────────────
            if save_mode == "overwrite" and overwrite_id:
                cur.execute(
                    """
                    UPDATE documents
                    SET content    = %s::jsonb,
                        file_bytes = %s,
                        file_ext   = %s,
                        doc_format = %s,
                        created_at = NOW()
                    WHERE id = %s
                    RETURNING id, version, parent_id
                    """,
                    (
                        json.dumps(content),
                        psycopg2.Binary(file_bytes) if file_bytes else None,
                        file_ext,
                        doc_format,
                        overwrite_id,
                    )
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Document id {overwrite_id} not found for overwrite")
                conn.commit()
                return {"id": row[0], "version": row[1], "parent_id": row[2], "mode": "overwrite"}

            # ── Save as new version ───────────────────────────────────────────
            latest = get_latest_version(title)
            if latest is None:
                version   = 1
                parent_id = None
            else:
                version   = latest["version"] + 1
                parent_id = latest["parent_id"] or latest["id"]

            cur.execute(
                """
                INSERT INTO documents
                    (title, doc_type, doc_format, content, file_bytes,
                     file_ext, version, parent_id)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    title,
                    doc_type   or "General",
                    doc_format or "word",
                    json.dumps(content),
                    psycopg2.Binary(file_bytes) if file_bytes else None,
                    file_ext,
                    version,
                    parent_id,
                )
            )
            doc_id = cur.fetchone()[0]
            conn.commit()
            return {"id": doc_id, "version": version, "parent_id": parent_id, "mode": "new_version"}
    finally:
        release_conn(conn)


def list_documents(limit: int = 200) -> list[dict]:
    """
    Return the latest version of each unique document title only.
    Includes version number so the UI can show e.g. 'v3'.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, doc_type, doc_format, file_ext,
                       version, parent_id, created_at, preview_snippet
                FROM (
                    SELECT DISTINCT ON (title)
                        id, title, doc_type, doc_format, file_ext,
                        version, parent_id, created_at,
                        LEFT(content::text, 200) AS preview_snippet
                    FROM documents
                    ORDER BY title, version DESC, created_at DESC
                ) latest
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,)
            )
            rows = cur.fetchall()
            cols = ["id", "title", "doc_type", "doc_format", "file_ext",
                    "version", "parent_id", "created_at", "preview_snippet"]
            return [dict(zip(cols, row)) for row in rows]
    finally:
        release_conn(conn)


def get_document(doc_id: int) -> dict | None:
    """
    Fetch a single document by id including full content, file bytes, and version info.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, doc_type, doc_format, content,
                       file_bytes, file_ext, version, parent_id, created_at
                FROM documents
                WHERE id = %s
                """,
                (doc_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = ["id", "title", "doc_type", "doc_format", "content",
                    "file_bytes", "file_ext", "version", "parent_id", "created_at"]
            doc = dict(zip(cols, row))
            if isinstance(doc["content"], str):
                doc["content"] = json.loads(doc["content"])
            if doc["file_bytes"] is not None:
                doc["file_bytes"] = bytes(doc["file_bytes"])
            return doc
    finally:
        release_conn(conn)


def delete_document(doc_id: int) -> bool:
    """Delete a single document version by id. Returns True if deleted."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
    finally:
        release_conn(conn)


def delete_all_versions(title: str) -> int:
    """Delete all versions of a document by title. Returns count deleted."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE title = %s", (title,))
            count = cur.rowcount
            conn.commit()
            return count
    finally:
        release_conn(conn)