"""
state.py
---------
AssistantState — the single source of truth for a conversation thread.

Persisted in PostgreSQL (durable) and cached in Redis (fast short-term).

Schema:
  thread_id       — UUID, one per conversation session
  user_id         — optional user identifier
  industry        — detected or user-set industry filter
  doc_filters     — active metadata filters { doc_title, industry, doc_type }
  messages        — full conversation history [ {role, content, ts} ]
  last_retrieved  — chunks from the most recent retrieval
  intent          — latest classified intent string
  pending_clarification — True if assistant is waiting for user to clarify
  ticket_id       — Notion ticket page_id if a ticket was created
  trace_id        — UUID for log correlation / observability
  created_at      — ISO timestamp
  updated_at      — ISO timestamp
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import TypedDict, Optional

log = logging.getLogger(__name__)

IST_OFFSET = "+05:30"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── State schema ──────────────────────────────────────────────────────────────

class AssistantState(TypedDict):
    thread_id:             str
    user_id:               Optional[str]
    industry:              Optional[str]
    doc_filters:           dict
    messages:              list          # [ {role, content, timestamp} ]
    last_retrieved:        list          # chunks from last retrieval
    intent:                Optional[str]
    pending_clarification: bool
    ticket_id:             Optional[str]
    trace_id:              str
    created_at:            str
    updated_at:            str


def new_state(thread_id: str = None, user_id: str = None) -> AssistantState:
    """Create a fresh state for a new conversation thread."""
    return AssistantState(
        thread_id             = thread_id or str(uuid.uuid4()),
        user_id               = user_id,
        industry              = None,
        doc_filters           = {},
        messages              = [],
        last_retrieved        = [],
        intent                = None,
        pending_clarification = False,
        ticket_id             = None,
        trace_id              = str(uuid.uuid4()),
        created_at            = now_iso(),
        updated_at            = now_iso(),
    )


def add_message(state: AssistantState, role: str, content: str) -> AssistantState:
    """Append a message to the conversation history and update timestamp."""
    state["messages"].append({
        "role":      role,
        "content":   content,
        "timestamp": now_iso(),
    })
    state["updated_at"] = now_iso()
    return state


# ── PostgreSQL persistence ────────────────────────────────────────────────────

def _get_conn():
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv()
    return psycopg2.connect(
        host     = os.getenv("POSTGRES_HOST", "localhost"),
        port     = int(os.getenv("POSTGRES_PORT", 5432)),
        dbname   = os.getenv("POSTGRES_DB", "docforge"),
        user     = os.getenv("POSTGRES_USER", "postgres"),
        password = os.getenv("POSTGRES_PASSWORD", ""),
    )

def _release_conn(conn):
    try:
        conn.close()
    except Exception:
        pass


def init_assistant_table():
    """Create assistant_threads table if it doesn't exist."""
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv()
    try:
        conn = psycopg2.connect(
            host     = os.getenv("POSTGRES_HOST", "localhost"),
            port     = int(os.getenv("POSTGRES_PORT", 5432)),
            dbname   = os.getenv("POSTGRES_DB", "docforge"),
            user     = os.getenv("POSTGRES_USER", "postgres"),
            password = os.getenv("POSTGRES_PASSWORD", ""),
        )
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS assistant_threads (
                    thread_id   TEXT PRIMARY KEY,
                    user_id     TEXT,
                    state_json  JSONB    NOT NULL DEFAULT '{}',
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()
        conn.close()
        log.info("assistant_threads table ready")
    except Exception as e:
        log.error(f"init_assistant_table failed: {e}")


def save_state(state: AssistantState):
    """Persist full state to PostgreSQL."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO assistant_threads (thread_id, user_id, state_json, updated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (thread_id) DO UPDATE
                    SET state_json = EXCLUDED.state_json,
                        updated_at = NOW()
            """, (
                state["thread_id"],
                state.get("user_id"),
                json.dumps(state, default=str),
            ))
        conn.commit()
    finally:
        _release_conn(conn)


def load_state(thread_id: str) -> Optional[AssistantState]:
    """Load state from PostgreSQL. Returns None if not found."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state_json FROM assistant_threads WHERE thread_id = %s",
                (thread_id,)
            )
            row = cur.fetchone()
            if row:
                return row[0]  # psycopg2 returns JSONB as dict
            return None
    finally:
        _release_conn(conn)


def list_threads(user_id: str = None, limit: int = 20) -> list[dict]:
    """List recent threads, optionally filtered by user_id."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            if user_id:
                cur.execute("""
                    SELECT thread_id, user_id, state_json->>'intent' as intent,
                           state_json->>'ticket_id' as ticket_id,
                           updated_at
                    FROM assistant_threads
                    WHERE user_id = %s
                    ORDER BY updated_at DESC LIMIT %s
                """, (user_id, limit))
            else:
                cur.execute("""
                    SELECT thread_id, user_id, state_json->>'intent' as intent,
                           state_json->>'ticket_id' as ticket_id,
                           updated_at
                    FROM assistant_threads
                    ORDER BY updated_at DESC LIMIT %s
                """, (limit,))
            rows = cur.fetchall()
            cols = ["thread_id", "user_id", "intent", "ticket_id", "updated_at"]
            return [dict(zip(cols, r)) for r in rows]
    finally:
        _release_conn(conn)