"""
redis_service.py
-----------------
Complete Redis integration for DocForge — connection, caching,
rate-limiting, backoff, and high-level service methods in one file.

Usage:
    from backend.services.redis import redis_svc

    # Health
    redis_svc.is_available()

    # Dedupe cache
    cached = redis_svc.get_cached_plan(prompt)
    redis_svc.cache_plan(prompt, result)

    cached = redis_svc.get_cached_questions(title, sections)
    redis_svc.cache_questions(title, sections, result)

    cached = redis_svc.get_cached_generation(title, sections, doc_format)
    redis_svc.cache_generation(title, sections, doc_format, result)
    redis_svc.invalidate_generation(title, sections, doc_format)

    # Rate limiting
    redis_svc.check_refine_limit(section_name)   # raises ThrottleExceeded
    redis_svc.check_notion_limit()               # raises ThrottleExceeded

    # Notion requests with auto throttle + backoff
    redis_svc.notion_request(lambda: requests.post(...))
"""

import os
import json
import time
import hashlib
import logging
from typing import Any, Callable

import redis
import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


# =============================================================================
# 1. Connection
# =============================================================================

def _make_client() -> redis.Redis:
    return redis.Redis(
        host                   = os.getenv("REDIS_HOST", "localhost"),
        port                   = int(os.getenv("REDIS_PORT", 6379)),
        db                     = int(os.getenv("REDIS_DB", 0)),
        password               = os.getenv("REDIS_PASSWORD") or None,
        decode_responses       = True,
        socket_connect_timeout = 1,
        socket_timeout         = 1,
        retry_on_timeout       = False,
    )


_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    """Return a Redis client. Auto-reconnects if connection is stale."""
    global _client
    if _client is None:
        _client = _make_client()
    else:
        try:
            _client.ping()
        except Exception:
            log.warning("Redis connection lost — reconnecting")
            _client = _make_client()
    return _client


# =============================================================================
# 2. Safe primitives  (never raise, never block > 1s)
# =============================================================================

def _safe_get(key: str) -> str | None:
    try:
        return _get_client().get(key)
    except Exception:
        return None


def _safe_set(key: str, ttl: int, value: str) -> bool:
    try:
        _get_client().setex(key, ttl, value)
        return True
    except Exception:
        return False


def _safe_delete(key: str) -> bool:
    try:
        _get_client().delete(key)
        return True
    except Exception:
        return False


def _safe_ping() -> bool:
    try:
        return _get_client().ping()
    except Exception:
        return False


# =============================================================================
# 3. Helpers — fingerprint, TTLs
# =============================================================================

_DEDUPE_TTL_SHORT = 60 * 5     # 5 min  — plan / questions
_DEDUPE_TTL_LONG  = 60 * 60    # 60 min — generated documents
_DEDUPE_TTL_RAG   = 60 * 10    # 10 min — RAG ask / search / compare
_BACKOFF_TTL      = 60 * 10    # 10 min — retry attempt counter


def _fingerprint(*args) -> str:
    """Stable 32-char SHA-256 fingerprint of any JSON-serialisable args."""
    raw = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _dedupe_get(fp: str) -> Any | None:
    raw = _safe_get(f"dedupe:{fp}")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return None


def _dedupe_set(fp: str, result: Any, ttl: int) -> bool:
    try:
        return _safe_set(f"dedupe:{fp}", ttl, json.dumps(result, default=str))
    except Exception:
        return False


def _dedupe_invalidate(fp: str):
    _safe_delete(f"dedupe:{fp}")


# =============================================================================
# 4. Throttle  (sliding-window rate limiter)
# =============================================================================

class ThrottleExceeded(Exception):
    def __init__(self, scope: str, limit: int, window: int):
        self.scope  = scope
        self.limit  = limit
        self.window = window
        super().__init__(
            f"Rate limit exceeded for '{scope}': {limit} calls per {window}s"
        )


def _throttle_check(scope: str, limit: int, window_seconds: int):
    """
    Increment call counter. Raises ThrottleExceeded if over limit.
    Fails open (skips) if Redis is unavailable.
    """
    if not _safe_ping():
        return
    try:
        r    = _get_client()
        key  = f"throttle:{scope}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        count, _ = pipe.execute()
        if count > limit:
            raise ThrottleExceeded(scope, limit, window_seconds)
        log.debug(f"Throttle [{scope}]: {count}/{limit} in {window_seconds}s")
    except ThrottleExceeded:
        raise
    except Exception as e:
        log.warning(f"Throttle check failed (skipping): {e}")


# =============================================================================
# 5. Backoff  (exponential retry)
# =============================================================================

def _backoff_increment(scope: str) -> int:
    try:
        r    = _get_client()
        key  = f"backoff:{scope}"
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _BACKOFF_TTL)
        count, _ = pipe.execute()
        return count
    except Exception:
        return 1


def _backoff_reset(scope: str):
    _safe_delete(f"backoff:{scope}")


def _with_backoff(
    scope:        str,
    fn:           Callable,
    max_attempts: int   = 4,
    base:         float = 1.0,
    cap:          float = 16.0,
    retryable:    tuple = (Exception,),
) -> Any:
    """
    Call fn() with exponential backoff on failure.
    Delay formula: min(base * 2^(attempt-1), cap) seconds.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            _backoff_reset(scope)
            return result
        except retryable as exc:
            count = _backoff_increment(scope)
            if attempt == max_attempts:
                log.error(f"Backoff [{scope}]: all {max_attempts} attempts exhausted — {exc}")
                raise
            delay = min(base * (2 ** (attempt - 1)), cap)
            log.warning(
                f"Backoff [{scope}]: attempt {count} failed ({exc}), "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)


# =============================================================================
# 6. RedisService  (high-level API used by main.py and notion_service.py)
# =============================================================================

class RedisService:
    """
    Single interface for all Redis operations in DocForge.
    Import the module-level singleton: from backend.services.redis_service import redis_svc
    """

    # ── Health ────────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return _safe_ping()

    def status(self) -> dict:
        available = _safe_ping()
        return {
            "available": available,
            "message":   "Redis connected" if available else "Redis unavailable — running in degraded mode",
        }

    # ── Dedupe: Plan ──────────────────────────────────────────────────────────

    def get_cached_plan(self, prompt: str) -> dict | None:
        return _dedupe_get(_fingerprint("plan", prompt))

    def cache_plan(self, prompt: str, result: dict) -> bool:
        return _dedupe_set(_fingerprint("plan", prompt), result, _DEDUPE_TTL_SHORT)

    # ── Dedupe: Questions ─────────────────────────────────────────────────────

    def get_cached_questions(self, title: str, sections: list) -> dict | None:
        return _dedupe_get(_fingerprint("questions", title, sections))

    def cache_questions(self, title: str, sections: list, result: dict) -> bool:
        return _dedupe_set(_fingerprint("questions", title, sections), result, _DEDUPE_TTL_SHORT)

    # ── Dedupe: Generate ──────────────────────────────────────────────────────

    def get_cached_generation(self, title: str, sections: list, doc_format: str) -> dict | None:
        return _dedupe_get(_fingerprint("generate", title, sections, doc_format))

    def cache_generation(self, title: str, sections: list, doc_format: str, result: dict) -> bool:
        return _dedupe_set(_fingerprint("generate", title, sections, doc_format), result, _DEDUPE_TTL_LONG)

    def invalidate_generation(self, title: str, sections: list, doc_format: str):
        """Call after a refinement so the next /generate produces fresh content."""
        _dedupe_invalidate(_fingerprint("generate", title, sections, doc_format))

    # ── Throttle: Refine ──────────────────────────────────────────────────────

    _REFINE_LIMIT  = 10
    _REFINE_WINDOW = 60   # seconds

    def check_refine_limit(self, section_name: str):
        """Raises ThrottleExceeded if section refined > 10x/min. Fails open if Redis down."""
        _throttle_check(f"refine:{section_name}", self._REFINE_LIMIT, self._REFINE_WINDOW)

    # ── Throttle + Backoff: Notion ────────────────────────────────────────────

    _NOTION_LIMIT       = 3     # req/sec (Notion enforced)
    _NOTION_WINDOW      = 1     # second
    _NOTION_MAX_RETRIES = 4
    _NOTION_BACKOFF_BASE = 1.0
    _NOTION_BACKOFF_CAP  = 16.0

    def check_notion_limit(self):
        """Raises ThrottleExceeded if Notion rate limit exceeded."""
        _throttle_check("notion_api", self._NOTION_LIMIT, self._NOTION_WINDOW)

    def notion_request(self, fn: Callable) -> Any:
        """
        Execute a Notion API call with throttle + exponential backoff.
        fn must be a zero-argument callable returning the parsed JSON response.

        Example:
            redis_svc.notion_request(lambda: _do_post(url, payload))
        """
        def _guarded():
            try:
                self.check_notion_limit()
            except ThrottleExceeded:
                time.sleep(1)   # wait out the 1s window before backoff retries
                raise
            return fn()

        return _with_backoff(
            scope        = "notion_api",
            fn           = _guarded,
            max_attempts = self._NOTION_MAX_RETRIES,
            base         = self._NOTION_BACKOFF_BASE,
            cap          = self._NOTION_BACKOFF_CAP,
            retryable    = (ThrottleExceeded, requests.HTTPError, ConnectionError),
        )

    def reset_notion_backoff(self):
        """Clear Notion retry counter after a successful operation."""
        _backoff_reset("notion_api")

    # ── Dedupe: RAG Ask ──────────────────────────────────────────────────────

    def get_cached_ask(self, question: str, top_k: int,
                       filters: dict) -> dict | None:
        """Cache RAG Q&A results for 10 min — skips embedding + ChromaDB lookup."""
        return _dedupe_get(_fingerprint("rag_ask", question, top_k, filters))

    def cache_ask(self, question: str, top_k: int,
                  filters: dict, result: dict) -> bool:
        return _dedupe_set(
            _fingerprint("rag_ask", question, top_k, filters),
            result, _DEDUPE_TTL_RAG
        )

    # ── Dedupe: RAG Search ────────────────────────────────────────────────────

    def get_cached_search(self, query: str, top_k: int,
                          filters: dict) -> dict | None:
        """Cache semantic search results for 10 min."""
        return _dedupe_get(_fingerprint("rag_search", query, top_k, filters))

    def cache_search(self, query: str, top_k: int,
                     filters: dict, result: list) -> bool:
        return _dedupe_set(
            _fingerprint("rag_search", query, top_k, filters),
            result, _DEDUPE_TTL_RAG
        )

    # ── Dedupe: RAG Compare ───────────────────────────────────────────────────

    def get_cached_compare(self, title_a: str, title_b: str,
                           focus: str) -> dict | None:
        """Cache document comparison for 10 min."""
        return _dedupe_get(_fingerprint("rag_compare", title_a, title_b, focus))

    def cache_compare(self, title_a: str, title_b: str,
                      focus: str, result: dict) -> bool:
        return _dedupe_set(
            _fingerprint("rag_compare", title_a, title_b, focus),
            result, _DEDUPE_TTL_RAG
        )

    # ── Raw access ────────────────────────────────────────────────────────────

    def raw_get(self, key: str) -> str | None:
        return _safe_get(key)

    def raw_set(self, key: str, ttl: int, value: str) -> bool:
        return _safe_set(key, ttl, value)

    def raw_delete(self, key: str) -> bool:
        return _safe_delete(key)


# ── Singleton ─────────────────────────────────────────────────────────────────
redis_svc = RedisService()