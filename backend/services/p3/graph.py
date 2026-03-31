"""
graph.py
---------
LangGraph flow definition for DocForgeHub Assistant.

Flow:
  START
    → classify_intent
        ↓ needs_clarification=True  → ask_clarification → END
        ↓ needs_clarification=False
    → retrieve
    → check_sufficiency
        ↓ "answer"  → generate_answer → END
        ↓ "ticket"  → create_ticket   → END

State is persisted (memory.py) after every node execution.
"""

import logging
import uuid
from typing import Literal

from langgraph.graph import StateGraph, END

from backend.services.p3.state  import AssistantState, new_state, add_message
from backend.services.p3.memory import persist_state, restore_state
from backend.services.p3.nodes  import (
    classify_intent,
    ask_clarification,
    retrieve,
    check_sufficiency,
    generate_answer,
    create_ticket_node,
    post_answer_check,
    _route_after_answer_check,
)

log = logging.getLogger(__name__)


# ── Edge conditions ───────────────────────────────────────────────────────────

def _route_after_classify(state: dict) -> Literal["ask_clarification", "retrieve"]:
    if state.get("pending_clarification"):
        return "ask_clarification"
    return "retrieve"


def _route_after_retrieve(state: dict) -> Literal["answer", "ticket"]:
    result = check_sufficiency(state)

    if result in ["answer","ticket"]:
        return result
    
    return "ticket"


def _route_after_post_check(state: dict) -> Literal["create_ticket", "__end__"]:
    return _route_after_answer_check(state)


# ── Build graph ───────────────────────────────────────────────────────────────

def _build_graph():
    """
    Build the LangGraph assistant flow.
    Uses MessagesState-compatible dict schema with operator.add for list merging.
    """
    from typing import Annotated
    import operator
    from typing_extensions import TypedDict
    from langgraph.graph import StateGraph, END

    # Define schema so LangGraph knows how to merge partial updates
    class GraphState(TypedDict, total=False):
        thread_id:             str
        user_id:               str
        industry:              str
        doc_filters:           dict
        messages:              list
        last_retrieved:        list
        intent:                str
        pending_clarification: bool
        ticket_id:             str
        trace_id:              str
        created_at:            str
        updated_at:            str
        _clarification_question: str
        _escalate_ticket:        bool
        _needs_ticket:           bool

    g = StateGraph(GraphState)

    # Nodes
    g.add_node("classify_intent",    classify_intent)
    g.add_node("ask_clarification",  ask_clarification)
    g.add_node("retrieve",           retrieve)
    g.add_node("generate_answer",    generate_answer)
    g.add_node("post_answer_check",  post_answer_check)
    g.add_node("create_ticket",      create_ticket_node)

    # Edges
    g.set_entry_point("classify_intent")

    g.add_conditional_edges(
        "classify_intent",
        _route_after_classify,
        {
            "ask_clarification": "ask_clarification",
            "retrieve":          "retrieve",
        }
    )

    g.add_edge("ask_clarification", END)

    g.add_conditional_edges(
        "retrieve",
        _route_after_retrieve,
        {
            "answer": "generate_answer",
            "ticket": "create_ticket",
        }
    )

    # After generate_answer, check if LLM said "I don't know" → maybe ticket
    g.add_edge("generate_answer", "post_answer_check")
    g.add_conditional_edges(
        "post_answer_check",
        _route_after_post_check,
        {
            "create_ticket": "create_ticket",
            "__end__":       END,
        }
    )
    g.add_edge("create_ticket", END)

    return g.compile()


# Singleton compiled graph
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Public API ────────────────────────────────────────────────────────────────

def run_turn(
    user_message: str,
    thread_id:    str  = None,
    user_id:      str  = None,
    filters:      dict = None,
    industry:     str  = None,
) -> dict:
    """
    Process one user turn through the assistant graph.

    Args:
        user_message : the user's input text
        thread_id    : existing thread ID to continue, or None to start new
        user_id      : optional user identifier
        filters      : metadata filters { doc_title, industry, doc_type }
        industry     : industry override

    Returns:
        {
          thread_id     : str,
          reply         : str,           # assistant's response text
          sources       : list[dict],    # retrieved chunks (if any)
          ticket_id     : str | None,    # Notion ticket if created
          ticket_url    : str | None,
          intent        : str,
          messages      : list[dict],    # full conversation history
          trace_id      : str,
        }
    """
    # Restore or create state
    if thread_id:
        state = restore_state(thread_id)
        if not state:
            log.warning(f"Thread {thread_id} not found — starting new")
            state = new_state(thread_id=thread_id, user_id=user_id)
    else:
        state = new_state(user_id=user_id)

    # Apply session overrides
    if filters:
        state["doc_filters"] = filters
    if industry:
        state["industry"] = industry

    # Refresh trace ID for this turn
    state["trace_id"] = str(uuid.uuid4())

    # Append user message
    state = add_message(state, "user", user_message)

    # Run graph — invoke returns the final merged state
    log.info(f"[{state['trace_id']}] turn start — thread={state['thread_id']}")
    try:
        result = get_graph().invoke(state)
        # LangGraph returns the complete final state — use it directly
        if isinstance(result, dict) and result:
            state = result
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.error(f"[{state['trace_id']}] graph error: {e}\n{tb}")
        error_reply = (
            f"I encountered an error processing your request.\n\n"
            f"**Error:** `{str(e)[:300]}`\n\nPlease check the backend logs."
        )
        state = add_message(state, "assistant", error_reply)

    # Persist updated state
    persist_state(state)

    # Extract reply (last assistant message)
    messages  = state.get("messages", [])
    last_asst = next((m for m in reversed(messages) if m["role"] == "assistant"), {})
    reply     = last_asst.get("content", "")
    sources   = last_asst.get("sources", [])
    ticket_id = last_asst.get("ticket_id") or state.get("ticket_id")
    ticket_url = last_asst.get("ticket_url", "")

    log.info(f"[{state['trace_id']}] turn complete — intent={state.get('intent')}")

    return {
        "thread_id": state["thread_id"],
        "reply":     reply,
        "sources":   sources,
        "ticket_id": ticket_id,
        "ticket_url": ticket_url,
        "intent":    state.get("intent"),
        "messages":  messages,
        "trace_id":  state["trace_id"],
    }