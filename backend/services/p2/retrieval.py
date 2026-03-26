"""
retrieval_service.py
---------------------
Semantic search with optional metadata filters.
Returns ranked chunks with similarity scores.
"""

import os
import logging
from dotenv import load_dotenv
from backend.services.p2.ingestion import embed_text
from backend.chroma_db import semantic_search

load_dotenv()
log = logging.getLogger(__name__)


def search(query: str, top_k: int = 5, filters: dict = None) -> list[dict]:
    """
    Embed the query and run cosine similarity search against document_chunks.

    filters: { doc_type, industry, version, doc_title }
    Returns list of chunks with score, sorted by relevance.
    """
    if not query.strip():
        return []

    embedding = embed_text(query)
    results   = semantic_search(embedding, top_k=top_k, filters=filters)

    # Round score for display
    for r in results:
        r["score"] = round(float(r.get("score", 0)), 4)

    return results


def search_multi_query(queries: list[str], top_k: int = 5,
                       filters: dict = None) -> list[dict]:
    """
    Run multiple query variants, merge results, and deduplicate by chunk id.
    Useful for compare mode where we want broad retrieval.
    """
    seen    = {}
    for query in queries:
        results = search(query, top_k=top_k, filters=filters)
        for r in results:
            cid = r["id"]
            if cid not in seen or r["score"] > seen[cid]["score"]:
                seen[cid] = r

    # Return sorted by score desc
    return sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:top_k * 2]