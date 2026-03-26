"""
memory.py
----------
Two-tier memory for the assistant:

  Short-term (Redis):
    - Active conversation state cached for 30 min
    - Thread lock to prevent concurrent mutations
    - Last N messages as quick context window

  Long-term (PostgreSQL via state.py):
    - Full state persisted after every turn
    - Used to restore context on reconnect / page refresh
"""

import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

_STATE_TTL    = 60 * 30   # 30 min active session cache
_LOCK_TTL     = 10        # 10 sec write lock
_CTX_WINDOW   = 10        # last N messages kept in Redis for fast access


def _redis():
    from backend.services.p1.redis import _get_client
    return _get_client()


# ── Short-term: Redis ─────────────────────────────────────────────────────────

def cache_state(state: dict):
    """Write full state to Redis with 30 min TTL."""
    try:
        tid = state["thread_id"]
        _redis().setex(f"asst:state:{tid}", _STATE_TTL, json.dumps(state, default=str))
    except Exception as e:
        log.warning(f"cache_state failed (non-fatal): {e}")


def get_cached_state(thread_id: str) -> Optional[dict]:
    """Read state from Redis. Returns None if not cached or Redis down."""
    try:
        raw = _redis().get(f"asst:state:{thread_id}")
        return json.loads(raw) if raw else None
    except Exception as e:
        log.warning(f"get_cached_state failed (non-fatal): {e}")
        return None


def invalidate_state(thread_id: str):
    """Remove state from Redis cache (e.g. after session ends)."""
    try:
        _redis().delete(f"asst:state:{thread_id}")
    except Exception:
        pass


def acquire_lock(thread_id: str) -> bool:
    """
    Acquire a write lock for a thread to prevent concurrent mutations.
    Returns True if lock acquired, False if already locked.
    """
    try:
        r   = _redis()
        key = f"asst:lock:{thread_id}"
        return bool(r.set(key, "1", nx=True, ex=_LOCK_TTL))
    except Exception:
        return True   # fail open — don't block if Redis is down


def release_lock(thread_id: str):
    """Release the write lock for a thread."""
    try:
        _redis().delete(f"asst:lock:{thread_id}")
    except Exception:
        pass


def cache_context_window(thread_id: str, messages: list):
    """Store last N messages as a lightweight context window in Redis."""
    try:
        window = messages[-_CTX_WINDOW:] if len(messages) > _CTX_WINDOW else messages
        _redis().setex(
            f"asst:ctx:{thread_id}", _STATE_TTL,
            json.dumps(window, default=str)
        )
    except Exception as e:
        log.warning(f"cache_context_window failed: {e}")


def get_context_window(thread_id: str) -> list:
    """Get last N messages from Redis context window."""
    try:
        raw = _redis().get(f"asst:ctx:{thread_id}")
        return json.loads(raw) if raw else []
    except Exception:
        return []


# ── Long-term: PostgreSQL (via state.py) ──────────────────────────────────────

def persist_state(state: dict):
    """
    Write state to both Redis (fast) and PostgreSQL (durable).
    Call after every successful turn.
    """
    from backend.services.p3.state import save_state
    cache_state(state)
    cache_context_window(state["thread_id"], state.get("messages", []))
    try:
        save_state(state)
    except Exception as e:
        log.error(f"persist_state DB write failed: {e}")


def restore_state(thread_id: str) -> Optional[dict]:
    """
    Restore state: try Redis first (fast), fall back to PostgreSQL.
    """
    # 1. Try Redis cache
    state = get_cached_state(thread_id)
    if state:
        log.debug(f"State restored from Redis for thread {thread_id}")
        return state

    # 2. Fall back to PostgreSQL
    from backend.services.p3.state import load_state
    state = load_state(thread_id)
    if state:
        log.debug(f"State restored from PostgreSQL for thread {thread_id}")
        cache_state(state)   # warm the cache
        return state

    return None


def build_message_history(messages: list) -> list:
    """
    Convert stored messages to LangChain message format for LLM context.
    Returns last _CTX_WINDOW messages only.
    """
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    window = messages[-_CTX_WINDOW:]
    lc_msgs = []
    for m in window:
        role    = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            lc_msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_msgs.append(AIMessage(content=content))
        elif role == "system":
            lc_msgs.append(SystemMessage(content=content))
    return lc_msgs