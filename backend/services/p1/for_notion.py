"""
notion_agent.py
----------------
Handles all Notion API interactions:
  - Creates a "DocForge Documents" database inside your Notion page on first run
  - Pushes generated Word/Excel documents as formatted Notion pages
  - Updates existing pages when sections are refined
  - Returns the Notion page URL for display in Streamlit
"""

import os
import json
import time
import requests
import logging
import re
from dotenv import load_dotenv
from backend.services.p1.for_redis import redis_svc, ThrottleExceeded

log = logging.getLogger(__name__)

load_dotenv()

NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization":  f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type":   "application/json",
}

BASE_URL = "https://api.notion.com/v1"


def _notion_request(method: str, url: str, **kwargs) -> dict:
    """
    Central HTTP helper for all Notion API calls.
    Throttle + backoff handled by redis_svc.notion_request().
    """
    def _do_request():
        resp = getattr(requests, method)(url, headers=HEADERS, **kwargs)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 1))
            log.warning(f"Notion 429 — will retry after {retry_after}s")
            time.sleep(retry_after)
            raise requests.HTTPError("429 Rate Limited", response=resp)

        if resp.status_code >= 400:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            log.error(f"Notion {resp.status_code} @ {url}: {err_body}")
            raise requests.HTTPError(
                f"{resp.status_code} {err_body}",
                response=resp
            )

        return resp.json() if resp.content else {}

    return redis_svc.notion_request(_do_request)


# ─────────────────────────────────────────────────────────────────────────────
# Database setup
# ─────────────────────────────────────────────────────────────────────────────


def _get_or_create_database() -> str:
    """
    Look for a database named 'DocForge Documents' inside the parent page.
    Creates it if it doesn't exist.
    Also ensures S.No column exists and backfills existing pages.
    Returns the database ID.
    """
    # Search for existing database
    res = _notion_request("post", f"{BASE_URL}/search", json={
            "query": "DocForge Documents",
            "filter": {"property": "object", "value": "database"}
        }
    )
    results = res.get("results", [])
    for r in results:
        if r.get("title", [{}])[0].get("plain_text") == "DocForge Documents":
            return r["id"]

    # Create database inside the parent page
    payload = {
        "parent": {"type": "page_id", "page_id": NOTION_PAGE_ID},
        "title": [{"type": "text", "text": {"content": "DocForge Documents"}}],
        "properties": {
            "Title":    {"title": {}},
            "Format": {
                "select": {
                    "options": [
                        {"name": "Word",  "color": "blue"},
                        {"name": "Excel", "color": "yellow"},
                    ]
                }
            },
            "Version":    {"number": {}},
            "Created At": {"date": {}},
        }
    }
    res = _notion_request("post", f"{BASE_URL}/databases", json=payload)
    return res["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Block builders
# ─────────────────────────────────────────────────────────────────────────────

def _text(content: str, bold: bool = False, color: str = "default") -> dict:
    return {
        "type": "text",
        "text": {"content": str(content)[:2000]},
        "annotations": {"bold": bold, "color": color}
    }


def _heading2(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [_text(text, bold=True, color="yellow")],
            "color": "default"
        }
    }


def _heading3(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [_text(text, bold=True)]}
    }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [_text(text)]}
    }


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [_text(text)]}
    }


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(text: str, emoji: str = "📊") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [_text(text)],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": "blue_background"
        }
    }


def _table_row(cells: list) -> dict:
    return {
        "type": "table_row",
        "table_row": {
            "cells": [[_text(str(c)[:2000])] for c in cells]
        }
    }


def _table(headers: list, rows: list) -> dict:
    """Build a Notion table block with headers + data rows."""
    all_rows = [_table_row(headers)] + [_table_row(r) for r in rows[:50]]
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(headers),
            "has_column_header": True,
            "has_row_header": False,
            "children": all_rows
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Content → Notion blocks
# ─────────────────────────────────────────────────────────────────────────────

_MD_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)\|?\s*$"
)


def _split_markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _parse_markdown_table(table_lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    if len(table_lines) < 2 or not _MD_TABLE_SEPARATOR_RE.match(table_lines[1]):
        return None

    headers = _split_markdown_table_cells(table_lines[0])
    rows = [_split_markdown_table_cells(line) for line in table_lines[2:] if line.strip()]
    row_widths = [len(row) for row in rows]
    width = max([len(headers)] + row_widths)

    headers = headers + [""] * (width - len(headers))
    rows = [row + [""] * (width - len(row)) for row in rows]
    return headers, rows


def _iter_markdown_blocks(content: str):
    lines = content.splitlines()
    i = 0

    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue

        if (
            i + 1 < len(lines)
            and "|" in lines[i]
            and _MD_TABLE_SEPARATOR_RE.match(lines[i + 1])
        ):
            table_lines = [lines[i], lines[i + 1]]
            i += 2
            while i < len(lines) and lines[i].strip():
                if "|" not in lines[i]:
                    break
                table_lines.append(lines[i])
                i += 1
            yield ("table", table_lines)
            continue

        text_lines = []
        while i < len(lines) and lines[i].strip():
            if (
                i + 1 < len(lines)
                and "|" in lines[i]
                and _MD_TABLE_SEPARATOR_RE.match(lines[i + 1])
            ):
                break
            text_lines.append(lines[i].strip())
            i += 1
        yield ("text", text_lines)


def _word_doc_to_blocks(sections: dict) -> list:
    """Convert Word document sections dict to Notion block list."""
    blocks = []
    # Respect __section_order__ if present (survives JSONB round-trip), skip the meta key itself
    _order = sections.get("__section_order__")
    if _order:
        _items = [(k, sections[k]) for k in _order if k in sections]
        _covered = set(_order) | {"__section_order__", "__show_headings__"}
        _items += [(k, v) for k, v in sections.items() if k not in _covered]
    else:
        _items = [(k, v) for k, v in sections.items() if k not in ("__section_order__", "__show_headings__")]
    _show_hdgs_notion = sections.get("__show_headings__", True)
    for section_name, content in _items:
        if _show_hdgs_notion:
            blocks.append(_heading2(section_name.replace("_", " ").title()))

        if isinstance(content, str):
            for block_type, block_lines in _iter_markdown_blocks(content):
                if block_type == "table":
                    parsed_table = _parse_markdown_table(block_lines)
                    if parsed_table:
                        headers, rows = parsed_table
                        blocks.append(_table(headers, rows))
                        continue

                for line in block_lines:
                    if line.startswith(("-", "*", "•", "▸")):
                        blocks.append(_bullet(line.lstrip("-*•▸ ")))
                    else:
                        blocks.append(_paragraph(line))

        elif isinstance(content, list):
            for item in content:
                blocks.append(_bullet(str(item).strip().lstrip("-*•▸ ")))

        elif isinstance(content, dict):
            for k, v in content.items():
                blocks.append(_heading3(str(k).replace("_", " ").title()))
                blocks.append(_paragraph(str(v)))

        blocks.append(_divider())

    return blocks


def _excel_doc_to_blocks(excel_data: dict) -> list:
    """Convert Excel structured data to Notion blocks (tables per sheet)."""
    blocks = []
    sheets = excel_data.get("sheets", [])

    for sheet in sheets:
        sheet_name  = sheet.get("sheet_name", "Sheet")
        description = sheet.get("description", "")
        headers     = sheet.get("headers", [])
        rows        = sheet.get("rows", [])
        notes       = sheet.get("notes", "")

        blocks.append(_heading2(sheet_name))

        if description:
            blocks.append(_callout(description, "📋"))

        if headers and rows:
            # Pad rows to header width
            padded = [r + [""] * max(0, len(headers) - len(r)) for r in rows]
            blocks.append(_table(headers, padded))

        if notes:
            blocks.append(_callout(f"Notes: {notes}", "📝"))

        blocks.append(_divider())

    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# Push document to Notion
# ─────────────────────────────────────────────────────────────────────────────

def push_to_notion(title: str, doc_format: str, content: dict,
                   db_id: int = None, version: int = 1,
                   doc_type: str = "General",
) -> dict:
    """
    Create a new Notion page inside the DocForge Documents database.

    Returns:
      { "page_id": "...", "url": "https://notion.so/..." }
    """
    database_id = _get_or_create_database()

    # Build content blocks
    if doc_format == "excel":
        blocks = _excel_doc_to_blocks(content)
    else:
        blocks = _word_doc_to_blocks(content)

    # Notion API limits: 100 blocks per request
    # We create the page first then append blocks in batches
    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST).isoformat()

    page_payload = {
        "parent": {"database_id": database_id},
        "icon":   {"type": "emoji", "emoji": "📊" if doc_format == "excel" else "📄"},
        "properties": {
            "Title":      {"title": [{"text": {"content": title}}]},
            "Format":     {"select": {"name": "Excel" if doc_format == "excel" else "Word"}},
            "Doc Type":   {"rich_text": [{"type": "text", "text": {"content": doc_type or "General"}}]},
            "Version":    {"number": version},
            "Created At": {"date": {"start": now_ist}},
        },
        # Add first batch of blocks (max 100)
        "children": blocks[:100]
    }

    page = _notion_request("post", f"{BASE_URL}/pages", json=page_payload)
    page_id = page["id"]

    # Append remaining blocks in batches of 100
    remaining = blocks[100:]
    for i in range(0, len(remaining), 100):
        batch = remaining[i:i+100]
        _notion_request("patch", f"{BASE_URL}/blocks/{page_id}/children", json={"children": batch})

    return {
        "page_id": page_id,
        "url":     page.get("url", f"https://notion.so/{page_id.replace('-', '')}")
    }


def update_notion_page(page_id: str, title: str, doc_format: str,
                       content: dict, version: int = 1,
                       doc_type: str = "General") -> dict:
    """
    Replace all content blocks in an existing Notion page.
    Also updates the Version and Doc Type properties.
    If the page no longer exists (404), creates a fresh page instead.
    """
    try:
        check = requests.get(
            f"{BASE_URL}/blocks/{page_id}/children",
            headers=HEADERS,
        )
        if check.status_code == 404:
            return push_to_notion(title=title, doc_format=doc_format,
                                  content=content, version=version,
                                  doc_type=doc_type)

        # Update Version and Doc Type properties on the page
        requests.patch(
            f"{BASE_URL}/pages/{page_id}",
            headers=HEADERS,
            json={"properties": {
                "Version":  {"number": version},
                "Doc Type": {"rich_text": [{"type": "text", "text": {"content": doc_type or "General"}}]},
            }},
        )

        existing = check.json().get("results", [])
        for block in existing:
            _notion_request("delete", f"{BASE_URL}/blocks/{block['id']}")

        if doc_format == "excel":
            blocks = _excel_doc_to_blocks(content)
        else:
            blocks = _word_doc_to_blocks(content)

        for i in range(0, len(blocks), 100):
            batch = blocks[i:i+100]
            _notion_request("patch", f"{BASE_URL}/blocks/{page_id}/children",
                            json={"children": batch})

        return {"page_id": page_id,
                "url": f"https://notion.so/{page_id.replace('-', '')}"}

    except Exception as e:
        if "404" in str(e):
            return push_to_notion(title=title, doc_format=doc_format,
                                  content=content, version=version,
                                  doc_type=doc_type)
        raise
