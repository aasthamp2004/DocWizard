"""
qa_log_service.py
------------------
Saves every RAG interaction to the "CiteRAG Q&A Log" Notion database.

Logs three interaction types:
  Ask     — Q&A with citations
  Compare — two-document comparison
  Eval    — RAGAS evaluation question

Schema:
  Question    — title
  Type        — select  (Ask / Compare / Eval)
  Answer      — rich_text
  Sources     — rich_text
  Filters     — rich_text
  Confidence  — number (percent)
  Asked At    — date
"""

import os
import requests
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

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
DB_NAME  = "CiteRAG Q&A Log"
IST      = timezone(timedelta(hours=5, minutes=30))

_qa_db_id = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _notion_request(method: str, url: str, **kwargs) -> dict:
    fn  = getattr(requests, method)
    res = fn(url, headers=NOTION_HEADERS, **kwargs)
    if not res.ok:
        raise RuntimeError(
            f"Notion {method.upper()} {url} → {res.status_code}: {res.text[:300]}"
        )
    return res.json()


def truncate(text: str, limit: int = 1900) -> str:
    return text[:limit] + "…" if len(text) > limit else text


def _build_sources_text(sources: list[dict]) -> tuple[str, float]:
    """Build a formatted sources string and compute avg confidence score."""
    parts  = []
    scores = []
    for i, src in enumerate(sources, 1):
        label = f"[{i}] {src.get('doc_title', '')} — {src.get('section_name', '')}"
        parts.append(label)
        if src.get("score"):
            scores.append(float(src["score"]))
    text      = "\n".join(parts) if parts else "None"
    avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0
    return text, avg_score


# ── Database setup ────────────────────────────────────────────────────────────

def _ensure_type_property(db_id: str):
    """Add Type select property to existing DB if it doesn't have one."""
    try:
        db_info = _notion_request("get", f"{BASE_URL}/databases/{db_id}")
        if "Type" not in db_info.get("properties", {}):
            _notion_request("patch", f"{BASE_URL}/databases/{db_id}", json={
                "properties": {
                    "Type": {
                        "select": {
                            "options": [
                                {"name": "Ask",     "color": "blue"},
                                {"name": "Compare", "color": "purple"},
                                {"name": "Eval",    "color": "yellow"},
                            ]
                        }
                    }
                }
            })
            log.info("Added 'Type' property to existing Q&A Log DB")
    except Exception as e:
        log.warning(f"Could not ensure Type property: {e}")


def _get_or_create_qa_db() -> str:
    global _qa_db_id
    if _qa_db_id:
        return _qa_db_id

    # Search for existing DB
    results = _notion_request("post", f"{BASE_URL}/search", json={
        "query":  DB_NAME,
        "filter": {"property": "object", "value": "database"},
    }).get("results", [])

    for r in results:
        title_arr = r.get("title", [])
        title_txt = title_arr[0].get("plain_text", "") if title_arr else ""
        if title_txt == DB_NAME:
            _qa_db_id = r["id"]
            log.info(f"Found existing Q&A Log DB: {_qa_db_id}")
            # Migrate: add Type property if missing
            _ensure_type_property(_qa_db_id)
            return _qa_db_id

    # Create new DB with Type property
    if not NOTION_PAGE_ID:
        raise ValueError(
            "NOTION_PAGE_ID not set. Add it to your .env — "
            "it's the ID of the Notion page where the Q&A Log DB will be created."
        )

    payload = {
        "parent": {"type": "page_id", "page_id": NOTION_PAGE_ID},
        "title":  [{"type": "text", "text": {"content": DB_NAME}}],
        "icon":   {"type": "emoji", "emoji": "🔬"},
        "properties": {
            "Question":  {"title": {}},
            "Type": {
                "select": {
                    "options": [
                        {"name": "Ask",     "color": "blue"},
                        {"name": "Compare", "color": "purple"},
                        {"name": "Eval",    "color": "yellow"},
                    ]
                }
            },
            "Answer":     {"rich_text": {}},
            "Sources":    {"rich_text": {}},
            "Filters":    {"rich_text": {}},
            "Confidence": {"number": {"format": "percent"}},
            "Asked At":   {"date": {}},
        },
    }

    res       = _notion_request("post", f"{BASE_URL}/databases", json=payload)
    _qa_db_id = res["id"]
    log.info(f"Created Q&A Log DB: {_qa_db_id}")
    return _qa_db_id


# ── Core log entry creator ────────────────────────────────────────────────────

def _create_log_entry(question: str, entry_type: str, answer: str,
                      sources_text: str, filters_text: str,
                      confidence: float, emoji: str) -> dict:
    """Create a single log page in the Notion DB."""
    db_id   = _get_or_create_qa_db()
    now_ist = datetime.now(IST).isoformat()

    page_payload = {
        "parent": {"database_id": db_id},
        "icon":   {"type": "emoji", "emoji": emoji},
        "properties": {
            "Question": {
                "title": [{"text": {"content": truncate(question, 200)}}]
            },
            "Type": {
                "select": {"name": entry_type}
            },
            "Answer": {
                "rich_text": [{"text": {"content": truncate(answer)}}]
            },
            "Sources": {
                "rich_text": [{"text": {"content": truncate(sources_text)}}]
            },
            "Filters": {
                "rich_text": [{"text": {"content": filters_text}}]
            },
            "Confidence": {
                "number": confidence
            },
            "Asked At": {
                "date": {"start": now_ist}
            },
        },
    }

    page = _notion_request("post", f"{BASE_URL}/pages", json=page_payload)
    return {"page_id": page["id"], "url": page.get("url", "")}


# ── Public API ────────────────────────────────────────────────────────────────

def log_qa(question: str, answer: str, sources: list[dict],
           filters: dict = None) -> dict:
    """Log an Ask Q&A interaction."""
    try:
        sources_text, avg_score = _build_sources_text(sources)
        filters_text = ", ".join(
            f"{k}={v}" for k, v in (filters or {}).items()
        ) or "None"
        return _create_log_entry(
            question     = question,
            entry_type   = "Ask",
            answer       = answer,
            sources_text = sources_text,
            filters_text = filters_text,
            confidence   = avg_score,
            emoji        = "💬",
        )
    except Exception as e:
        log.error(f"log_qa failed: {e}")
        raise


def log_compare(title_a: str, title_b: str, focus: str,
                comparison: str, chunks_a: list[dict],
                chunks_b: list[dict]) -> dict:
    """Log a Compare interaction."""
    try:
        question = f"Compare: {title_a} vs {title_b}"
        if focus and focus != "overall content and structure":
            question += f" — Focus: {focus}"

        all_chunks   = chunks_a + chunks_b
        sources_text, avg_score = _build_sources_text(all_chunks)
        filters_text = f"Doc A={title_a}, Doc B={title_b}, Focus={focus}"

        return _create_log_entry(
            question     = question,
            entry_type   = "Compare",
            answer       = comparison,
            sources_text = sources_text,
            filters_text = filters_text,
            confidence   = avg_score,
            emoji        = "⚖️",
        )
    except Exception as e:
        log.error(f"log_compare failed: {e}")
        raise


def log_eval(question: str, answer: str, sources: list[dict],
             scores: dict, run_name: str = "") -> dict:
    """Log a single Eval question with RAGAS scores."""
    try:
        sources_text, avg_retrieval = _build_sources_text(sources)

        score_lines = "\n".join(
            f"  {k.replace('_', ' ').title()}: {v:.2%}"
            if isinstance(v, float) else f"  {k.replace('_', ' ').title()}: {v}"
            for k, v in scores.items()
        )
        answer_text = f"RAGAS Scores:\n{score_lines}"
        if answer:
            answer_text += f"\n\nGenerated Answer:\n{answer}"

        filters_text = f"Run={run_name}" if run_name else "Eval run"

        confidence = scores.get("faithfulness", avg_retrieval)
        if isinstance(confidence, str):
            confidence = avg_retrieval

        return _create_log_entry(
            question     = question,
            entry_type   = "Eval",
            answer       = answer_text,
            sources_text = sources_text,
            filters_text = filters_text,
            confidence   = float(confidence) if confidence else 0.0,
            emoji        = "🧪",
        )
    except Exception as e:
        log.error(f"log_eval failed: {e}")
        raise


def fetch_qa_log(limit: int = 50) -> list[dict]:
    """Fetch recent entries from the Notion Q&A Log DB."""
    try:
        db_id = _get_or_create_qa_db()
    except Exception as e:
        log.error(f"Could not access Q&A Log DB: {e}")
        return []

    payload = {
        "page_size": min(limit, 100),
        "sorts":     [{"property": "Asked At", "direction": "descending"}],
    }
    results = _notion_request(
        "post", f"{BASE_URL}/databases/{db_id}/query", json=payload
    ).get("results", [])

    entries = []
    for page in results:
        props = page.get("properties", {})

        def get_title(p):
            arr = props.get(p, {}).get("title", [])
            return arr[0].get("plain_text", "") if arr else ""

        def get_rich(p):
            arr = props.get(p, {}).get("rich_text", [])
            return arr[0].get("plain_text", "") if arr else ""

        def get_select(p):
            sel = props.get(p, {}).get("select")
            return sel.get("name", "") if sel else ""

        def get_number(p):
            return props.get(p, {}).get("number", 0) or 0

        def get_date(p):
            d = props.get(p, {}).get("date")
            return d.get("start", "") if d else ""

        entries.append({
            "question":   get_title("Question"),
            "type":       get_select("Type") or "Ask",
            "answer":     get_rich("Answer"),
            "sources":    get_rich("Sources"),
            "filters":    get_rich("Filters"),
            "confidence": get_number("Confidence"),
            "asked_at":   get_date("Asked At"),
            "url":        page.get("url", ""),
        })

    return entries