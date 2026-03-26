"""
compare_service.py
-------------------
Side-by-side document comparison using RAG.
Given two document titles, retrieves their chunks and
asks the LLM to compare them on specific dimensions.
"""

import logging
from langchain_core.messages import SystemMessage, HumanMessage
from backend.services.langchain import llm as _llm
from backend.chroma_db import semantic_search
from backend.services.p2.ingestion import embed_text

log = logging.getLogger(__name__)

COMPARE_SYSTEM = """You are a precise document analyst.
You are given content from two documents and a comparison focus.
Produce a clear, structured comparison using this format:

## Summary
One paragraph summarising the key difference.

## Similarities
- Bullet points of what they share

## Differences
- Bullet points of how they differ (be specific)

## Recommendation
Which is more suitable for what scenario, and why.

Cite sources using the actual document names (e.g. Annual Expense Report or Balance Sheet) throughout.
Never use generic labels like "Doc A" or "Doc B" — always use the real document title.
Base your analysis ONLY on the provided content.
"""


def _get_doc_chunks(doc_title: str, query: str, top_k: int = 8) -> list[dict]:
    """Retrieve top_k chunks from a specific document matching the query."""
    embedding = embed_text(query)
    return semantic_search(
        embedding, top_k=top_k,
        filters={"doc_title": doc_title}
    )


def compare_documents(title_a: str, title_b: str,
                      focus: str = "overall content and structure") -> dict:
    """
    Compare two documents on a given focus area.

    Returns:
    {
        comparison: str,       # formatted markdown comparison
        doc_a_chunks: list,    # source chunks from doc A
        doc_b_chunks: list,    # source chunks from doc B
    }
    """
    # Retrieve relevant chunks from both docs
    chunks_a = _get_doc_chunks(title_a, focus)
    chunks_b = _get_doc_chunks(title_b, focus)

    if not chunks_a:
        return {"comparison": f"No content found for '{title_a}' in the index.",
                "doc_a_chunks": [], "doc_b_chunks": []}
    if not chunks_b:
        return {"comparison": f"No content found for '{title_b}' in the index.",
                "doc_a_chunks": [], "doc_b_chunks": []}

    # Build context
    def fmt_chunks(chunks, label):
        parts = []
        for c in chunks:
            parts.append(
                f"[{label}] {c['section_name']}\n{c['chunk_text']}"
            )
        return "\n\n".join(parts)

    context = (
        f"=== {title_a} ===\n\n"
        f"{fmt_chunks(chunks_a, title_a)}\n\n"
        f"=== {title_b} ===\n\n"
        f"{fmt_chunks(chunks_b, title_b)}"
    )

    messages = [
        SystemMessage(content=COMPARE_SYSTEM),
        HumanMessage(content=(
            f"Compare '{title_a}' and '{title_b}' focusing on: {focus}\n\n"
            f"Always refer to the documents by their actual names, not as 'Doc A' or 'Doc B'.\n\n"
            f"{context}"
        )),
    ]

    response   = _llm.invoke(messages)
    comparison = response.content.strip()

    return {
        "comparison":   comparison,
        "doc_a_chunks": chunks_a,
        "doc_b_chunks": chunks_b,
    }