"""
assistant_log_service.py
-------------------------
Logs every assistant conversation turn to a dedicated Notion database:
  "StateCase Assistant Log"

Schema:
  Title       — question / user message (title property)
  Reply       — rich_text (assistant's response)
  Intent      — select  (question / generate / compare / clarification / chitchat)
  Sources     — rich_text (doc titles + sections cited)
  Thread ID   — rich_text (links back to session)
  Outcome     — select  (Answered / Ticket Created / Clarification Asked)
  Confidence  — number  (avg similarity score of sources, if any)
  Asked At    — date
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import requests as http

load_dotenv(override=True)
log = logging.getLogger(__name__)

NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
NOTION_VERSION = "2022-06-28"
NOTION_HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type":   "application/json",
}
BASE_URL = "https://api.notion.com/v1"
DB_NAME  = "StateCase Assistant Log"
IST      = timezone(timedelta(hours=5, minutes=30))

_log_db_id = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _notion(method: str, url: str, **kwargs) -> dict:
    fn  = getattr(http, method)
    res = fn(url, headers=NOTION_HEADERS, **kwargs)
    if not res.ok:
        raise RuntimeError(
            f"Notion {method.upper()} {url} → {res.status_code}: {res.text[:300]}"
        )
    return res.json()


def _trunc(text: str, limit: int = 1900) -> str:
    return str(text or "")[:limit] + ("…" if len(str(text or "")) > limit else "")


def _rt(text: str) -> list:
    return [{"text": {"content": _trunc(text)}}]


# ── DB setup ──────────────────────────────────────────────────────────────────

def _get_or_create_log_db() -> str:
    global _log_db_id
    if _log_db_id:
        return _log_db_id

    results = _notion("post", f"{BASE_URL}/search", json={
        "query":  DB_NAME,
        "filter": {"property": "object", "value": "database"},
    }).get("results", [])

    for r in results:
        title_arr = r.get("title", [])
        title_txt = title_arr[0].get("plain_text", "") if title_arr else ""
        if title_txt == DB_NAME:
            _log_db_id = r["id"]
            log.info(f"Found existing Assistant Log DB: {_log_db_id}")
            return _log_db_id

    if not NOTION_PAGE_ID:
        raise ValueError("NOTION_PAGE_ID not set in .env")

    payload = {
        "parent": {"type": "page_id", "page_id": NOTION_PAGE_ID},
        "title":  [{"type": "text", "text": {"content": DB_NAME}}],
        "icon":   {"type": "emoji", "emoji": "🤖"},
        "properties": {
            "Title": {"title": {}},
            "Intent": {
                "select": {"options": [
                    {"name": "question",       "color": "blue"},
                    {"name": "generate",       "color": "green"},
                    {"name": "compare",        "color": "purple"},
                    {"name": "clarification",  "color": "yellow"},
                    {"name": "chitchat",       "color": "gray"},
                ]}
            },
            "Outcome": {
                "select": {"options": [
                    {"name": "Answered",              "color": "green"},
                    {"name": "Ticket Created",        "color": "red"},
                    {"name": "Clarification Asked",   "color": "yellow"},
                ]}
            },
            "Reply":      {"rich_text": {}},
            "Sources":    {"rich_text": {}},
            "Thread ID":  {"rich_text": {}},
            "Confidence": {"number": {"format": "percent"}},
            "Asked At":   {"date": {}},
        },
    }

    res        = _notion("post", f"{BASE_URL}/databases", json=payload)
    _log_db_id = res["id"]
    log.info(f"Created Assistant Log DB: {_log_db_id}")
    return _log_db_id


# ── Public API ────────────────────────────────────────────────────────────────

def log_turn(
    question:  str,
    reply:     str,
    thread_id: str,
    intent:    str        = "question",
    sources:   list[dict] = None,
    outcome:   str        = "Answered",
) -> dict:
    """
    Log one assistant conversation turn to Notion.

    outcome: "Answered" | "Ticket Created" | "Clarification Asked"
    Returns { page_id, url }
    """
    try:
        db_id = _get_or_create_log_db()
    except Exception as e:
        log.error(f"Cannot access Assistant Log DB: {e}")
        raise

    # Build sources summary
    src_lines = []
    scores    = []
    if sources:
        for i, s in enumerate(sources[:8], 1):
            src_lines.append(
                f"[{i}] {s.get('doc_title', '')} — {s.get('section_name', '')}"
            )
            if s.get("score"):
                scores.append(float(s["score"]))
    sources_text = "\n".join(src_lines) if src_lines else "None"
    avg_score    = round(sum(scores) / len(scores), 4) if scores else 0.0

    # Title = first 150 chars of question
    title = question[:150] + ("…" if len(question) > 150 else "")

    page_payload = {
        "parent": {"database_id": db_id},
        "icon":   {"type": "emoji", "emoji": "🤖"},
        "properties": {
            "Title":      {"title": [{"text": {"content": title}}]},
            "Intent":     {"select": {"name": intent or "question"}},
            "Outcome":    {"select": {"name": outcome}},
            "Reply":      {"rich_text": _rt(reply)},
            "Sources":    {"rich_text": _rt(sources_text)},
            "Thread ID":  {"rich_text": _rt(thread_id)},
            "Confidence": {"number": avg_score},
            "Asked At":   {"date": {"start": datetime.now(IST).isoformat()}},
        },
    }

    page = _notion("post", f"{BASE_URL}/pages", json=page_payload)
    log.info(f"Logged assistant turn for thread {thread_id}: {page['id']}")
    return {"page_id": page["id"], "url": page.get("url", "")}


def fetch_assistant_log(limit: int = 50) -> list[dict]:
    """Fetch recent entries from the Assistant Log DB."""
    try:
        db_id = _get_or_create_log_db()
    except Exception as e:
        log.error(f"Cannot access Assistant Log DB: {e}")
        return []

    payload = {
        "page_size": min(limit, 100),
        "sorts":     [{"property": "Asked At", "direction": "descending"}],
    }
    results = _notion("post", f"{BASE_URL}/databases/{db_id}/query",
                      json=payload).get("results", [])

    entries = []
    for page in results:
        props = page.get("properties", {})

        def gt(p):
            arr = props.get(p, {}).get("title", [])
            return arr[0].get("plain_text", "") if arr else ""

        def gr(p):
            arr = props.get(p, {}).get("rich_text", [])
            return arr[0].get("plain_text", "") if arr else ""

        def gs(p):
            sel = props.get(p, {}).get("select")
            return sel.get("name", "") if sel else ""

        def gn(p):
            return props.get(p, {}).get("number", 0) or 0

        def gd(p):
            d = props.get(p, {}).get("date")
            return d.get("start", "")[:16].replace("T", " ") if d else ""

        entries.append({
            "question":   gt("Title"),
            "reply":      gr("Reply"),
            "intent":     gs("Intent"),
            "outcome":    gs("Outcome"),
            "sources":    gr("Sources"),
            "thread_id":  gr("Thread ID"),
            "confidence": gn("Confidence"),
            "asked_at":   gd("Asked At"),
            "url":        page.get("url", ""),
        })

    return entries