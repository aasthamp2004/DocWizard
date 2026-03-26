"""
qa_service.py
--------------
RAG-based Q&A with grounded citations.
Retrieves relevant chunks, builds a context window,
calls Azure OpenAI GPT, returns answer + cited sources.
"""

import logging
from langchain_core.messages import SystemMessage, HumanMessage
from backend.services.langchain import llm as _llm
from backend.services.p2.retrieval import search

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are CiteRAG, a precise document Q&A assistant.

You answer questions ONLY using the provided context chunks.
For every claim in your answer, cite the source using [Source N] notation.
If the answer cannot be found in the context, say so clearly.

Rules:
- Be concise and factual
- Always include citations [Source 1], [Source 2], etc.
- Cite names of sources, not generic labels (e.g. Annual Expense Report, not [Source 1])
- If multiple sources support a point, cite all of them
- Never fabricate information not present in the context
- End with a "Sources" section listing each cited source
"""


def ask(question: str, top_k: int = 6, filters: dict = None) -> dict:
    """
    Answer a question using RAG over the vector index.

    Returns:
    {
        answer:   str,
        sources:  [ { id, doc_title, section_name, chunk_text,
                      notion_url, version, score } ],
        context_used: int   # number of chunks in context
    }
    """
    # Retrieve relevant chunks
    chunks = search(question, top_k=top_k, filters=filters)
    if not chunks:
        return {
            "answer":       "No relevant documents found in the index. Try ingesting documents first.",
            "sources":      [],
            "context_used": 0,
        }

    # Build numbered context string
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        header = (
            f"[Source {i}] {chunk['doc_title']} "
            f"(v{chunk['version']}) — {chunk['section_name']}"
        )
        context_parts.append(f"{header}\n{chunk['chunk_text']}")

    context_str = "\n\n---\n\n".join(context_parts)

    # Call LLM
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n\n{context_str}\n\nQuestion: {question}"),
    ]

    response = _llm.invoke(messages)
    answer   = response.content.strip()

    return {
        "answer":       answer,
        "sources":      chunks,
        "context_used": len(chunks),
    }


def refine_answer(question: str, answer: str, feedback: str,
                  sources: list[dict]) -> dict:
    """
    Refine a previous answer based on user feedback.
    Reuses the same source chunks — no new retrieval.
    """
    context_parts = []
    for i, chunk in enumerate(sources, 1):
        header = (
            f"[Source {i}] {chunk['doc_title']} "
            f"(v{chunk['version']}) — {chunk['section_name']}"
        )
        context_parts.append(f"{header}\n{chunk['chunk_text']}")
    context_str = "\n\n---\n\n".join(context_parts)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Context:\n\n{context_str}\n\n"
            f"Original question: {question}\n"
            f"Previous answer: {answer}\n"
            f"User feedback: {feedback}\n\n"
            f"Please refine the answer based on the feedback."
        )),
    ]

    response = _llm.invoke(messages)
    return {
        "answer":       response.content.strip(),
        "sources":      sources,
        "context_used": len(sources),
    }