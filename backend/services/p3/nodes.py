"""
nodes.py
---------
LangGraph node functions for the assistant flow.

Flow:
  START
    → classify_intent
    → [needs_clarification?] → ask_clarification → END (await next user turn)
    → retrieve
    → [sufficient?] → generate_answer → END
                    → create_ticket   → END

Each node receives AssistantState and returns a partial update dict.
"""

import logging
import uuid
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_CHUNKS        = 2      # minimum retrieved chunks to attempt an answer
MIN_AVG_SCORE     = 0.35   # minimum avg cosine similarity to consider sufficient
CLARIFY_THRESHOLD = 0.6    # intent confidence below this → ask clarification


# ── Helper: get LLM ──────────────────────────────────────────────────────────

def _llm():
    from backend.services.langchain import llm
    return llm


# ── Node: classify_intent ─────────────────────────────────────────────────────

def classify_intent(state: dict) -> dict:
    """
    Classify the user's latest message into an intent and detect context signals:
      - industry hint
      - doc_type hint
      - is it a question, a doc generation request, or a vague query?
    Updates: intent, industry (if detected), trace_id refresh
    """
    messages   = state.get("messages", [])
    last_user  = next((m["content"] for m in reversed(messages)
                       if m["role"] == "user"), "")

    history = _format_history(messages[:-1])  # all but last

    prompt = f"""You are an intent classifier for DocForgeHub, a document management assistant.

Conversation so far:
{history}

Latest user message: "{last_user}"

Classify into ONE of:
  question        — user wants to find/ask something from existing docs
  generate        — user wants to create a new document
  compare         — user wants to compare two documents
  clarification   — user is answering a previous clarification question
  chitchat        — greeting or off-topic

Also detect:
  industry: one of [Finance, HR, Legal, Tech, Operations, Sales, General] or null
  needs_clarification: true if the request is ambiguous and needs more info before proceeding

Return ONLY valid JSON:
{{
  "intent": "question",
  "industry": "Legal",
  "needs_clarification": false,
  "clarification_question": ""
}}

No explanation. No markdown. Only JSON."""

    import json, re
    try:
        response = _llm().invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        # Strip markdown fences
        if "```" in raw:
            raw = re.sub(r"```[a-z]*", "", raw).replace("```", "").strip()
        # Extract JSON object if extra text around it
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
        result = json.loads(raw)
    except Exception as e:
        log.warning(f"classify_intent failed ({e}), defaulting to 'question'")
        result = {"intent": "question", "industry": None,
                  "needs_clarification": False, "clarification_question": ""}

    update = {
        "intent":                 result.get("intent", "question"),
        "pending_clarification":  result.get("needs_clarification", False),
    }
    if result.get("industry") and not state.get("industry"):
        update["industry"] = result["industry"]
    if result.get("clarification_question"):
        update["_clarification_question"] = result["clarification_question"]

    log.info(f"[{state.get('trace_id','')}] intent={update['intent']} "
             f"clarify={update['pending_clarification']}")
    return update


# ── Node: ask_clarification ───────────────────────────────────────────────────

def ask_clarification(state: dict) -> dict:
    """
    Generate a clarifying question and append it as an assistant message.
    Flow pauses here — next user input resumes from classify_intent.
    """
    q = state.get("_clarification_question") or _generate_clarification(state)
    messages = list(state.get("messages", []))
    messages.append({
        "role":      "assistant",
        "content":   q,
        "timestamp": _now(),
    })
    return {
        "messages":              messages,
        "pending_clarification": True,
    }


def _generate_clarification(state: dict) -> str:
    messages   = state.get("messages", [])
    last_user  = next((m["content"] for m in reversed(messages)
                       if m["role"] == "user"), "")
    response = _llm().invoke([
        SystemMessage(content="You are a helpful assistant. Ask one concise clarifying question."),
        HumanMessage(content=f"User said: '{last_user}'. What one question would help you assist them better?"),
    ])
    return response.content.strip()


# ── Node: retrieve ────────────────────────────────────────────────────────────

def retrieve(state: dict) -> dict:
    """
    Retrieve relevant chunks from ChromaDB using the latest user message.
    Applies industry + doc_filters from state.
    """
    try:
        from backend.services.p2.retrieval import search_multi_query
    except ImportError:
        from backend.services.p2.retrieval import search as _search
        def search_multi_query(queries, top_k=6, filters=None):
            seen = {}
            for q in queries:
                for r in _search(q, top_k=top_k, filters=filters):
                    if r["id"] not in seen or r["score"] > seen[r["id"]]["score"]:
                        seen[r["id"]] = r
            return sorted(seen.values(), key=lambda x: x["score"], reverse=True)[:top_k*2]

    messages  = state.get("messages", [])
    last_user = next((m["content"] for m in reversed(messages)
                      if m["role"] == "user"), "")

    # Build filters from state
    filters = dict(state.get("doc_filters", {}))
    if state.get("industry") and "industry" not in filters:
        filters["industry"] = state["industry"]

    # Multi-query retrieval for better coverage
    queries = _expand_query(last_user)
    chunks  = search_multi_query(
        queries  = queries,
        top_k    = 6,
        filters  = filters or None,
    )

    log.info(f"[{state.get('trace_id','')}] retrieved {len(chunks)} chunks "
             f"for query: {last_user[:60]}")
    return {"last_retrieved": chunks}


def _expand_query(question: str) -> list[str]:
    """Generate 2-3 query variants to improve retrieval coverage."""
    try:
        response = _llm().invoke([
            SystemMessage(content='Generate 2 alternative search queries for the same question. Return ONLY a JSON array of strings. Example: ["query 1", "query 2"]'),
            HumanMessage(content=f"Original: {question}"),
        ])
        import json, re
        raw = response.content.strip()
        raw = re.sub(r"```[a-z]*", "", raw).replace("```", "").strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            variants = json.loads(m.group(0))
            if isinstance(variants, list):
                return [question] + [str(v) for v in variants[:2]]
    except Exception as e:
        log.debug(f"_expand_query failed ({e}), using original query only")
    return [question]


# ── Node: check_sufficiency ───────────────────────────────────────────────────

# Phrases that indicate the LLM couldn't answer from context
_CANNOT_ANSWER_PHRASES = [
    "does not specify", "does not contain", "not mentioned",
    "not found in", "no information", "cannot find", "not available",
    "not provided", "not in the", "unable to find", "no relevant",
    "not covered", "not stated", "not described", "not documented",
    "context does not", "provided context does not",
    "i don't have", "i do not have", "cannot determine",
    "no document", "not addressed",
]


def _llm_could_not_answer(answer_text: str) -> bool:
    """Return True if the LLM's answer signals it couldn't find the information."""
    lower = answer_text.lower()
    return any(phrase in lower for phrase in _CANNOT_ANSWER_PHRASES)


def check_sufficiency(state: dict) -> Literal["answer", "ticket"]:
    """
    Edge condition: decide whether retrieval results are sufficient to answer.

    Two-stage check:
      1. Chunk count + similarity score (retrieval quality)
      2. Answer content check — if LLM says "not found", create ticket

    Returns "answer" or "ticket".
    """
    chunks = state.get("last_retrieved", [])

    if not chunks:
        log.info(f"[{state.get('trace_id','')}] insufficient: no chunks retrieved")
        return "ticket"

    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)

    if len(chunks) < MIN_CHUNKS or avg_score < MIN_AVG_SCORE:
        log.info(f"[{state.get('trace_id','')}] insufficient: "
                 f"{len(chunks)} chunks, avg_score={avg_score:.2f}")
        return "ticket"

    log.info(f"[{state.get('trace_id','')}] sufficient: "
             f"{len(chunks)} chunks, avg_score={avg_score:.2f}")
    return "answer"


# ── Node: generate_answer ─────────────────────────────────────────────────────

def generate_answer(state: dict) -> dict:
    """
    Generate a grounded answer using retrieved chunks + conversation history.
    Appends assistant message to state.
    """
    messages      = state.get("messages", [])
    chunks        = state.get("last_retrieved", [])
    last_user     = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user"), "")

    # Build context
    context_parts = []
    for chunk in chunks:
        header = f"[{chunk['doc_title']} — {chunk['section_name']}]"
        context_parts.append(f"{header}\n{chunk['chunk_text']}")
    context_str = "\n\n---\n\n".join(context_parts)

    # Build conversation history for LLM
    from backend.services.p3.memory import build_message_history
    lc_history = build_message_history(messages[:-1])  # exclude last user msg

    system = SystemMessage(content="""You are DocForgeHub Assistant — a precise, helpful document intelligence assistant.

You answer questions using ONLY the provided context chunks.
Cite sources inline as [Document Title — Section Name].
If context is insufficient for part of the answer, say so clearly for that part.
Never fabricate data, names, numbers, or policies.
Be concise but complete. Use bullet points for lists.""")

    human = HumanMessage(content=(
        f"Context:\n\n{context_str}\n\n"
        f"Question: {last_user}"
    ))

    response = _llm().invoke([system] + lc_history + [human])
    answer   = response.content.strip()

    new_messages = list(messages)
    new_messages.append({
        "role":      "assistant",
        "content":   answer,
        "timestamp": _now(),
        "sources":   [{"doc_title": c["doc_title"],
                       "section_name": c["section_name"],
                       "score": c.get("score", 0),
                       "notion_url": c.get("notion_url", "")}
                      for c in chunks],
    })

    log.info(f"[{state.get('trace_id','')}] answer generated ({len(answer)} chars)")

    # Post-answer check: if LLM couldn't find info, escalate to ticket
    if _llm_could_not_answer(answer):
        log.info(f"[{state.get('trace_id','')}] LLM could not answer — escalating to ticket")
        # Remove the "I don't know" answer and route to ticket instead
        return {
            "messages":          new_messages,
            "_escalate_ticket":  True,          # signal for post-answer ticket creation
        }

    return {"messages": new_messages}


# ── Node: create_ticket ───────────────────────────────────────────────────────

def create_ticket_node(state: dict) -> dict:
    """
    Create a Notion support ticket when retrieval is insufficient.
    Generates a conversation summary and attaches attempted sources.
    """
    from backend.services.p3.tickets import create_ticket

    messages  = state.get("messages", [])
    chunks    = state.get("last_retrieved", [])
    thread_id = state.get("thread_id", "")
    last_user = next((m["content"] for m in reversed(messages)
                      if m["role"] == "user"), "")

    # Summarise conversation for the ticket
    summary = _summarise_conversation(messages)

    # Determine priority from intent/question length
    priority = "High" if len(last_user) > 200 else "Medium"

    try:
        result = create_ticket(
            question    = last_user,
            thread_id   = thread_id,
            sources     = chunks,
            summary     = summary,
            priority    = priority,
            ticket_type = "Unanswered",
        )
        ticket_id  = result["ticket_id"]
        ticket_url = result["url"]
        existed    = result["existed"]
    except Exception as e:
        log.error(f"Ticket creation failed: {e}")
        ticket_id  = None
        ticket_url = ""
        existed    = False

    # Compose response to user
    if existed:
        response_text = (
            "I wasn't able to find a confident answer in your documents. "
            "A support ticket has already been raised for this thread — "
            "our team will follow up.\n\n"
            f"🎫 [View your ticket]({ticket_url})"
        )
    elif ticket_id:
        response_text = (
            "I wasn't able to find a confident answer from your indexed documents. "
            "I've created a support ticket with your question, the sources I tried, "
            "and a conversation summary.\n\n"
            f"🎫 **Ticket created** — [Open in Notion]({ticket_url})\n\n"
            "Our team will review and respond. You can track it in the **🎫 My Tickets** tab."
        )
    else:
        response_text = (
            "I wasn't able to find a confident answer and ticket creation failed. "
            "Please contact support directly."
        )

    new_messages = list(messages)
    new_messages.append({
        "role":      "assistant",
        "content":   response_text,
        "timestamp": _now(),
        "ticket_id": ticket_id,
        "ticket_url": ticket_url,
    })

    log.info(f"[{state.get('trace_id','')}] ticket created: {ticket_id}")
    return {
        "messages":  new_messages,
        "ticket_id": ticket_id,
    }



# ── Node: post_answer_check ───────────────────────────────────────────────────

def post_answer_check(state: dict) -> dict:
    """
    After generate_answer, check if the LLM flagged escalation.
    If yes, replace the "I don't know" reply with a ticket creation message.
    """
    if state.get("_escalate_ticket"):
        log.info(f"[{state.get('trace_id','')}] post_answer_check: escalating to ticket")
        # Remove the last assistant message (the "I don't know" reply)
        messages = list(state.get("messages", []))
        if messages and messages[-1].get("role") == "assistant":
            messages = messages[:-1]
        return {
            "messages":         messages,
            "_escalate_ticket": False,
            "_needs_ticket":    True,
        }
    return {"_needs_ticket": False}


def _route_after_answer_check(state: dict) -> Literal["create_ticket", "__end__"]:
    if state.get("_needs_ticket"):
        return "create_ticket"
    return "__end__"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _summarise_conversation(messages: list) -> str:
    """Generate a short summary of the conversation for the ticket."""
    if len(messages) < 2:
        return messages[-1]["content"] if messages else ""
    try:
        history = _format_history(messages[-6:])  # last 3 turns
        response = _llm().invoke([
            SystemMessage(content="Summarise this conversation in 2-3 sentences for a support ticket."),
            HumanMessage(content=history),
        ])
        return response.content.strip()
    except Exception:
        return messages[-1].get("content", "") if messages else ""


def _format_history(messages: list) -> str:
    lines = []
    for m in messages:
        role    = m.get("role", "user").capitalize()
        content = m.get("content", "")[:500]
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "No prior history."


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()