"""
ticket_service.py
------------------
Creates and manages support tickets in a Notion database:
  "StateCase Support Tickets"

Ticket schema:
  Title       — question / issue summary (title property)
  Status      — select: Open / In Progress / Resolved
  Priority    — select: Low / Medium / High
  Type        — select: Unanswered / Clarification / Feature / Other
  Assigned To — rich_text
  Thread ID   — rich_text  (for idempotency + linking back to session)
  Question    — rich_text  (full user question)
  Sources     — rich_text  (attempted retrieval sources)
  Summary     — rich_text  (conversation context summary)
  Created At  — date

Idempotency: before creating, checks if ticket already exists for thread_id.
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
BASE_URL    = "https://api.notion.com/v1"
DB_NAME     = "StateCase Support Tickets"
IST         = timezone(timedelta(hours=5, minutes=30))

_ticket_db_id = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _notion(method: str, url: str, **kwargs) -> dict:
    fn  = getattr(http, method)
    res = fn(url, headers=NOTION_HEADERS, **kwargs)
    if not res.ok:
        raise RuntimeError(f"Notion {method.upper()} {url} → {res.status_code}: {res.text[:300]}")
    return res.json()


def _trunc(text: str, limit: int = 1900) -> str:
    return text[:limit] + "…" if len(text) > limit else text


def _rt(text: str) -> list:
    """Notion rich_text block."""
    return [{"text": {"content": _trunc(str(text or ""))}}]


# ── DB setup ──────────────────────────────────────────────────────────────────

def _get_or_create_ticket_db() -> str:
    global _ticket_db_id
    if _ticket_db_id:
        return _ticket_db_id

    results = _notion("post", f"{BASE_URL}/search", json={
        "query":  DB_NAME,
        "filter": {"property": "object", "value": "database"},
    }).get("results", [])

    for r in results:
        title_arr = r.get("title", [])
        title_txt = title_arr[0].get("plain_text", "") if title_arr else ""
        if title_txt == DB_NAME:
            _ticket_db_id = r["id"]
            log.info(f"Found existing Ticket DB: {_ticket_db_id}")
            return _ticket_db_id

    if not NOTION_PAGE_ID:
        raise ValueError("NOTION_PAGE_ID not set in .env")

    payload = {
        "parent": {"type": "page_id", "page_id": NOTION_PAGE_ID},
        "title":  [{"type": "text", "text": {"content": DB_NAME}}],
        "icon":   {"type": "emoji", "emoji": "🎫"},
        "properties": {
            "Title":       {"title": {}},
            "Status": {
                "select": {"options": [
                    {"name": "Open",        "color": "red"},
                    {"name": "In Progress", "color": "yellow"},
                    {"name": "Resolved",    "color": "green"},
                ]}
            },
            "Priority": {
                "select": {"options": [
                    {"name": "Low",    "color": "gray"},
                    {"name": "Medium", "color": "orange"},
                    {"name": "High",   "color": "red"},
                ]}
            },
            "Type": {
                "select": {"options": [
                    {"name": "Unanswered",    "color": "red"},
                    {"name": "Clarification", "color": "blue"},
                    {"name": "Feature",       "color": "purple"},
                    {"name": "Other",         "color": "gray"},
                ]}
            },
            "Assigned To": {"rich_text": {}},
            "Thread ID":   {"rich_text": {}},
            "Question":    {"rich_text": {}},
            "Sources":     {"rich_text": {}},
            "Summary":     {"rich_text": {}},
            "Created At":  {"date": {}},
        },
    }
    res           = _notion("post", f"{BASE_URL}/databases", json=payload)
    _ticket_db_id = res["id"]
    log.info(f"Created Ticket DB: {_ticket_db_id}")
    return _ticket_db_id


# ── Idempotency check ─────────────────────────────────────────────────────────

def find_ticket_by_thread(thread_id: str) -> dict | None:
    """Check if a ticket already exists for this thread_id."""
    try:
        db_id = _get_or_create_ticket_db()
        results = _notion("post", f"{BASE_URL}/databases/{db_id}/query", json={
            "filter": {
                "property": "Thread ID",
                "rich_text": {"equals": thread_id}
            },
            "page_size": 1,
        }).get("results", [])
        return results[0] if results else None
    except Exception as e:
        log.warning(f"find_ticket_by_thread failed: {e}")
        return None


def _normalise_question(q: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace for fuzzy matching."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", q.lower())).strip()


def find_ticket_by_question(question: str, status_filter: str = None) -> dict | None:
    """
    Check if an Open/In-Progress ticket with a very similar question already exists.
    Compares normalised question text — prevents duplicate tickets for the
    same unanswered query asked in different sessions.

    status_filter: if set, only match tickets with that status.
    """
    try:
        db_id  = _get_or_create_ticket_db()
        # Fetch recent Open + In Progress tickets to compare against
        filter_payload = {
            "or": [
                {"property": "Status", "select": {"equals": "Open"}},
                {"property": "Status", "select": {"equals": "In Progress"}},
            ]
        }
        if status_filter:
            filter_payload = {"property": "Status", "select": {"equals": status_filter}}

        results = _notion("post", f"{BASE_URL}/databases/{db_id}/query", json={
            "filter":    filter_payload,
            "page_size": 50,
            "sorts":     [{"property": "Created At", "direction": "descending"}],
        }).get("results", [])

        norm_q = _normalise_question(question)

        for page in results:
            props = page.get("properties", {})
            existing_q_arr = props.get("Question", {}).get("rich_text", [])
            existing_q = existing_q_arr[0].get("plain_text", "") if existing_q_arr else ""
            norm_existing = _normalise_question(existing_q)

            # Exact match after normalisation
            if norm_q == norm_existing:
                log.info(f"Duplicate ticket found (exact question match): {page['id']}")
                return page

            # Fuzzy match: if one is a substring of the other (handles slight rewording)
            if len(norm_q) > 20 and len(norm_existing) > 20:
                shorter = norm_q if len(norm_q) < len(norm_existing) else norm_existing
                longer  = norm_existing if len(norm_q) < len(norm_existing) else norm_q
                if shorter in longer:
                    log.info(f"Duplicate ticket found (substring match): {page['id']}")
                    return page

        return None
    except Exception as e:
        log.warning(f"find_ticket_by_question failed: {e}")
        return None


# ── CRUD ──────────────────────────────────────────────────────────────────────

def create_ticket(
    question:   str,
    thread_id:  str,
    sources:    list[dict]  = None,
    summary:    str         = "",
    priority:   str         = "Medium",
    assigned_to: str        = "",
    ticket_type: str        = "Unanswered",
) -> dict:
    """
    Create a support ticket in Notion.
    Idempotent: returns existing ticket if one already exists for thread_id.

    Returns { ticket_id, url, existed }
    """
    # Idempotency check 1: same thread
    existing = find_ticket_by_thread(thread_id)
    if existing:
        log.info(f"Ticket already exists for thread {thread_id}: {existing['id']}")
        return {
            "ticket_id": existing["id"],
            "url":       existing.get("url", ""),
            "existed":   True,
        }

    # Idempotency check 2: same question in another open/in-progress ticket
    existing_q = find_ticket_by_question(question)
    if existing_q:
        log.info(f"Duplicate question ticket found: {existing_q['id']} — skipping creation")
        return {
            "ticket_id": existing_q["id"],
            "url":       existing_q.get("url", ""),
            "existed":   True,
        }

    db_id = _get_or_create_ticket_db()

    # Format sources
    src_lines = []
    if sources:
        for i, s in enumerate(sources[:10], 1):
            src_lines.append(
                f"[{i}] {s.get('doc_title', '')} — {s.get('section_name', '')} "
                f"(score: {s.get('score', 0):.0%})"
            )
    sources_text = "\n".join(src_lines) if src_lines else "No sources retrieved"

    # Title = first 150 chars of question
    title = question[:150] + ("…" if len(question) > 150 else "")

    page_payload = {
        "parent": {"database_id": db_id},
        "icon":   {"type": "emoji", "emoji": "🎫"},
        "properties": {
            "Title":       {"title": [{"text": {"content": title}}]},
            "Status":      {"select": {"name": "Open"}},
            "Priority":    {"select": {"name": priority}},
            "Type":        {"select": {"name": ticket_type}},
            "Assigned To": {"rich_text": _rt(assigned_to or "Unassigned")},
            "Thread ID":   {"rich_text": _rt(thread_id)},
            "Question":    {"rich_text": _rt(question)},
            "Sources":     {"rich_text": _rt(sources_text)},
            "Summary":     {"rich_text": _rt(summary or "No summary available")},
            "Created At":  {"date": {"start": datetime.now(IST).isoformat()}},
        },
    }

    page = _notion("post", f"{BASE_URL}/pages", json=page_payload)
    log.info(f"Created ticket {page['id']} for thread {thread_id}")
    return {
        "ticket_id": page["id"],
        "url":       page.get("url", ""),
        "existed":   False,
    }


def update_ticket_status(ticket_id: str, status: str) -> dict:
    """Update ticket status: Open / In Progress / Resolved."""
    return _notion("patch", f"{BASE_URL}/pages/{ticket_id}", json={
        "properties": {
            "Status": {"select": {"name": status}}
        }
    })


def fetch_tickets(user_id: str = None, limit: int = 20) -> list[dict]:
    """
    Fetch tickets from Notion, newest first.
    Returns simplified list for the UI.
    """
    try:
        db_id = _get_or_create_ticket_db()
        payload = {
            "page_size": min(limit, 100),
            "sorts":     [{"property": "Created At", "direction": "descending"}],
        }
        results = _notion("post", f"{BASE_URL}/databases/{db_id}/query",
                          json=payload).get("results", [])

        tickets = []
        for page in results:
            props = page.get("properties", {})

            def gt(p):   # get title
                arr = props.get(p, {}).get("title", [])
                return arr[0].get("plain_text", "") if arr else ""

            def gr(p):   # get rich_text
                arr = props.get(p, {}).get("rich_text", [])
                return arr[0].get("plain_text", "") if arr else ""

            def gs(p):   # get select
                sel = props.get(p, {}).get("select")
                return sel.get("name", "") if sel else ""

            def gd(p):   # get date
                d = props.get(p, {}).get("date")
                return d.get("start", "")[:16].replace("T", " ") if d else ""

            tickets.append({
                "ticket_id":   page["id"],
                "title":       gt("Title"),
                "status":      gs("Status"),
                "priority":    gs("Priority"),
                "type":        gs("Type"),
                "assigned_to": gr("Assigned To"),
                "thread_id":   gr("Thread ID"),
                "question":    gr("Question"),
                "summary":     gr("Summary"),
                "created_at":  gd("Created At"),
                "url":         page.get("url", ""),
            })
        return tickets
    except Exception as e:
        log.error(f"fetch_tickets failed: {e}")
        return []