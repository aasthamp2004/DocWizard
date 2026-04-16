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
                    → ask_create_ticket → END (wait for user decision)
                    → create_ticket → END (if user says yes)

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


# ── Helper: Find similar previous questions ────────────────────────────────────

def _find_similar_previous_questions(user_id: str, current_question: str, limit: int = 5) -> list[dict]:
    """
    Search for similar questions in the user's previous threads.
    Returns a list of {thread_id, question, ticket_id} for similar questions.
    """
    if not user_id:
        return []
    
    try:
        from backend.services.p3.for_state import list_threads, load_state
        
        # Get user's recent threads
        threads = list_threads(user_id=user_id, limit=20)
        if not threads:
            return []
        
        # Load full state for each thread to get messages
        similar_questions = []
        for thread_info in threads:
            try:
                state = load_state(thread_info["thread_id"])
                if not state or not state.get("messages"):
                    continue
                
                # Get the first user message in that thread (the original question)
                first_user_msg = next(
                    (m["content"] for m in state.get("messages", []) 
                     if m["role"] == "user"),
                    None
                )
                
                if first_user_msg:
                    # Check similarity using LLM
                    is_similar = _check_question_similarity(current_question, first_user_msg)
                    if is_similar:
                        similar_questions.append({
                            "thread_id": thread_info["thread_id"],
                            "question": first_user_msg[:200],  # First 200 chars
                            "ticket_id": thread_info.get("ticket_id"),
                            "intent": thread_info.get("intent"),
                        })
                        if len(similar_questions) >= limit:
                            break
            except Exception as e:
                log.debug(f"Error checking thread {thread_info.get('thread_id')}: {e}")
                continue
        
        return similar_questions
    except Exception as e:
        log.warning(f"find_similar_previous_questions failed: {e}")
        return []


def _check_question_similarity(question1: str, question2: str) -> bool:
    """
    Use LLM to check if two questions are semantically similar.
    Returns True if they're about the same topic.
    """
    try:
        prompt = f"""Are these two questions about the SAME topic or asking for SIMILAR information?

Question 1: "{question1}"
Question 2: "{question2}"

Respond with ONLY "yes" or "no" (lowercase). No explanation."""
        
        response = _llm().invoke([HumanMessage(content=prompt)])
        answer = response.content.strip().lower()
        return answer == "yes"
    except Exception as e:
        log.debug(f"_check_question_similarity failed: {e}")
        return False

# ── Node: check_ticket_decision ────────────────────────────────────────────────
# Run early to intercept ticket decision responses before normal flow

def check_ticket_decision(state: dict) -> dict:
    """
    Check if we're waiting for user to decide on ticket creation.
    If so, route accordingly. Otherwise, pass through.
    """
    messages = state.get("messages", [])
    last_msg_before_user = None
    
    # Find the last assistant message (the ticket question)
    for msg in reversed(messages[:-1]):  # exclude the current user message
        if msg.get("role") == "assistant":
            last_msg_before_user = msg.get("content", "").lower()
            break
    
    # Check if the last assistant message was asking about ticket creation
    if last_msg_before_user and any(phrase in last_msg_before_user for phrase in 
                                     ["create a support ticket", "create a ticket", "support ticket", 
                                      "would you like", "would you like me to create"]):
        # We're answering a ticket decision question
        last_user = next((m["content"] for m in reversed(messages)
                         if m["role"] == "user"), "")
        
        if _user_wants_ticket(last_user):
            # User wants ticket - route to create_ticket directly
            log.info(f"[{state.get('trace_id','')}] User accepted ticket creation")
            return {
                "_skip_normal_flow": True,
                "_user_accepted_ticket": True,
            }
        else:
            # User declined ticket - end conversation
            log.info(f"[{state.get('trace_id','')}] User declined ticket creation")
            response_text = (
                "No problem! If you have any other questions about your documents, feel free to ask."
            )
            new_messages = list(messages)
            new_messages.append({
                "role":      "assistant",
                "content":   response_text,
                "timestamp": _now(),
            })
            return {
                "_skip_normal_flow": True,
                "_user_declined_ticket": True,
                "messages": new_messages,
            }
    
    # Normal flow - no ticket decision pending
    return {"_skip_normal_flow": False}


# ── Node: classify_intent ─────────────────────────────────────────────────────

def classify_intent(state: dict) -> dict:
    """
    Classify the user's latest message into an intent with smart context awareness.
    
    Smart features:
      - Understands relative references ("it", "that", "this") from conversation
      - Avoids redundant clarification questions
      - Contextually groups follow-up requests with previous queries
      - Detects document operations (summarize, compare, analyze) without clarification
    """
    messages   = state.get("messages", [])
    last_user  = next((m["content"] for m in reversed(messages)
                       if m["role"] == "user"), "")
    
    # Get previous user message if exists (for context) 
    previous_user = None
    user_count = 0
    for m in reversed(messages[:-1]):
        if m.get("role") == "user":
            previous_user = m.get("content", "")
            user_count += 1
            if user_count >= 1:
                break

    history = _format_history(messages[:-1])

    prompt = f"""You are an intelligent intent classifier for DocForgeHub, a document management assistant.

Conversation history:
{history}

Latest user message: "{last_user}"
Previous user message: "{previous_user if previous_user else 'N/A'}"

You must classify the INTENT and determine if clarification is truly NEEDED.

Classification options:
  question        — user wants to find/ask something from existing docs
  generate        — user wants to create a new document
  compare         — user wants to compare documents
  clarification   — user is answering a previous clarification question
  chitchat        — greeting or off-topic

Smart context awareness:
  - If user says "summarize it", "summarize that", "analyze it", "compare them" → they refer to previous topic
  - Do NOT ask for clarification if referential context is clear from previous message
  - Do NOT ask for clarification if user mentions specific document keywords/topics
  - Do NOT ask for clarification if user is performing an action (summarize, analyze, compare) with clear context
  - Only ask clarification if the request is genuinely ambiguous (e.g., "give me information" with no context)

Also detect:
  industry: one of [Finance, HR, Legal, Tech, Operations, Sales, General] or null
  needs_clarification: ONLY true if absolutely unavoidable (avoid redundant asks)

Return ONLY valid JSON (no markdown):
{{
  "intent": "question",
  "industry": "General",
  "needs_clarification": false,
  "clarification_question": ""
}}"""

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
    # Log clarification turn to Notion
    try:
        from backend.services.p3.assistant_log import log_turn
        last_user = next((m["content"] for m in reversed(state.get("messages", []))
                          if m["role"] == "user"), "")
        log_turn(
            question  = last_user,
            reply     = q,
            thread_id = state.get("thread_id", ""),
            intent    = state.get("intent", "clarification"),
            outcome   = "Clarification Asked",
        )
    except Exception as _le:
        log.warning(f"assistant log_turn (clarify) failed: {_le}")

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

def _do_search(query: str, top_k: int = 6, filters: dict = None) -> list[dict]:
    """
    Flexible search that tries multiple import paths to find the working retrieval.
    Tries p2.retrieval first (project structure), falls back to retrieval_service.
    """
    # Try p2 path first (matches main.py's working imports)
    try:
        from backend.services.p2.for_retrieval import search
        return search(query=query, top_k=top_k, filters=filters)
    except (ImportError, ModuleNotFoundError):
        pass
    # Fall back to flat services path
    try:
        from backend.services.p2.for_retrieval import search
        return search(query=query, top_k=top_k, filters=filters)
    except Exception as e:
        log.error(f"All retrieval imports failed: {e}")
        return []


def retrieve(state: dict) -> dict:
    """
    Retrieve relevant chunks from ChromaDB with smart context awareness.
    
    Features:
      - Handles referential queries ("summarize it", "compare them")
      - Uses conversation context to understand subject
      - Resolves pronouns and references
      - Applies industry + doc_filters
    """
    messages  = state.get("messages", [])
    last_user = next((m["content"] for m in reversed(messages)
                      if m["role"] == "user"), "")

    # Get previous user message for context resolution
    previous_user = None
    user_count = 0
    for m in reversed(messages[:-1]):
        if m.get("role") == "user":
            previous_user = m.get("content", "")
            user_count += 1
            if user_count >= 1:
                break

    # If current query is referential (it, that, this, summarize, analyze, compare)
    # and previous context exists, combine them for better retrieval
    search_query = last_user
    if previous_user and any(ref in last_user.lower() for ref in 
       ["summarize", "analyze", "compare", "it ", "that ", "this ", "them", "these"]):
        # Combine previous topic with current request for context
        search_query = f"{previous_user}. {last_user}"
        log.debug(f"[{state.get('trace_id','')}] Using contextual query: {search_query[:100]}")

    # Build filters from state
    filters = dict(state.get("doc_filters", {}))
    if state.get("industry") and "industry" not in filters:
        filters["industry"] = state["industry"]
    filters = filters or None

    # Try smart query expansion that's aware of context
    queries = _expand_query_smart(search_query, last_user)

    # Multi-query retrieval — merge and dedupe by chunk id
    seen = {}
    for q in queries:
        for r in _do_search(q, top_k=8, filters=filters):
            cid = r.get("id", "")
            if cid not in seen or r.get("score", 0) > seen[cid].get("score", 0):
                seen[cid] = r
    chunks = sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)[:12]

    if chunks:
        top_docs = list({c.get("doc_title", "") for c in chunks[:5]})
        avg      = sum(c.get("score", 0) for c in chunks) / len(chunks)
        log.info(f"[{state.get('trace_id','')}] retrieved {len(chunks)} chunks "
                 f"avg_score={avg:.2f} from: {top_docs}")
    else:
        log.warning(f"[{state.get('trace_id','')}] NO chunks retrieved — "
                    f"ChromaDB index may be empty or query embedding failed. "
                    f"query={last_user[:80]}")
    return {"last_retrieved": chunks}


def _expand_query_smart(full_query: str, user_query: str) -> list[str]:
    """
    Generate query variants with smart context awareness.
    Uses full query for expansion but keeps user query as primary.
    """
    try:
        response = _llm().invoke([
            SystemMessage(content='''Generate 2-3 alternative search queries that capture the same meaning. 
IMPORTANT: Keep queries concise and focused on the actual request.
Return ONLY a JSON array of strings. Example: ["query 1", "query 2", "query 3"]
No markdown, no explanation, just the JSON array.'''),
            HumanMessage(content=f"Original query: {user_query}\nContext: {full_query[:200]}"),
        ])
        import json, re
        raw = response.content.strip()
        raw = re.sub(r"```[a-z]*", "", raw).replace("```", "").strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            variants = json.loads(m.group(0))
            if isinstance(variants, list):
                # Include user query and context-aware variants
                all_queries = [user_query] + [str(v) for v in variants[:2]]
                return list(dict.fromkeys(all_queries))  # Remove duplicates while preserving order
    except Exception as e:
        log.debug(f"_expand_query_smart failed ({e}), using basic expansion")
    
    # Fallback: basic expansion
    return _expand_query(user_query)


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

# Strong signals that the LLM explicitly couldn't answer
_CANNOT_ANSWER_STRONG = [
    "provided context does not",
    "context does not specify",
    "context does not contain",
    "context does not mention",
    "not found in the provided",
    "not available in the provided",
    "not mentioned in the provided",
    "not included in the provided",
    "not covered in the provided",
    "no information available in",
    "cannot determine from the",
    "unable to find this information",
    "the documents do not contain",
    "the documents do not mention",
    "the documents do not specify",
    "not present in the indexed",
    "no relevant information found",
]

# Weak signals — only count if the answer is also very short (< 200 chars)
_CANNOT_ANSWER_WEAK = [
    "does not specify",
    "not mentioned",
    "not available",
    "cannot find",
    "not found",
    "not covered",
    "not stated",
    "not documented",
    "i don't have",
    "i do not have",
    "cannot determine",
]


def _llm_could_not_answer(answer_text: str) -> bool:
    """
    Return True only when the LLM clearly couldn't answer.
    Uses strong phrases (any match) or weak phrases + short response.
    Avoids false positives on answers that happen to contain these words
    in the middle of a valid cited response.
    """
    lower = answer_text.lower()

    # Strong signal: explicit "provided context does not..." phrasing
    if any(phrase in lower for phrase in _CANNOT_ANSWER_STRONG):
        return True

    # Weak signal: only escalate if the answer is also very short (no real content)
    if len(answer_text.strip()) < 250:
        if any(phrase in lower for phrase in _CANNOT_ANSWER_WEAK):
            return True

    return False


def check_sufficiency(state: dict) -> Literal["answer", "ask_ticket", "ticket"]:
    """
    Edge condition: decide whether retrieval results are sufficient to answer.

    Two-stage check:
      1. Chunk count + similarity score (retrieval quality)
      2. Answer content check — if LLM says "not found", ask user for ticket

    Returns "answer", "ask_ticket", or "ticket".
    """
    chunks = state.get("last_retrieved", [])

    if not chunks:
        log.info(f"[{state.get('trace_id','')}] insufficient: no chunks retrieved")
        return "ask_ticket"

    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)

    if len(chunks) < MIN_CHUNKS or avg_score < MIN_AVG_SCORE:
        log.info(f"[{state.get('trace_id','')}] insufficient: "
                 f"{len(chunks)} chunks, avg_score={avg_score:.2f}")
        return "ask_ticket"

    log.info(f"[{state.get('trace_id','')}] sufficient: "
             f"{len(chunks)} chunks, avg_score={avg_score:.2f}")
    return "answer"


# ── Node: generate_answer ─────────────────────────────────────────────────────

def generate_answer(state: dict) -> dict:
    """
    Generate a grounded answer using retrieved chunks + conversation history.
    Smart features:
      - Detects follow-up requests (summarize, analyze, compare)
      - Adjusts response format based on request type
      - Prioritizes relevance over retrieval warnings
    """
    messages      = state.get("messages", [])
    chunks        = state.get("last_retrieved", [])
    last_user     = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user"), "")

    # Detect if this is a follow-up operation request
    is_action_request = any(action in last_user.lower() for action in 
                           ["summarize", "analyze", "compare", "extract", "list", "identify",
                            "explain", "describe", "detail", "break down"])

    # Build context
    context_parts = []
    for chunk in chunks:
        header = f"[{chunk['doc_title']} — {chunk['section_name']}]"
        context_parts.append(f"{header}\n{chunk['chunk_text']}")
    context_str = "\n\n---\n\n".join(context_parts)

    # Build conversation history for LLM
    from backend.services.p3.for_memory import build_message_history
    lc_history = build_message_history(messages[:-1])

    system_prompt = """You are DocForgeHub Assistant — a precise, helpful document intelligence assistant.

Core principles:
- Answer questions using ONLY the provided context chunks
- Cite sources inline as [Document Title — Section Name]
- If context is insufficient for part of the answer, say so clearly
- Never fabricate data, names, numbers, or policies
- Be concise but complete; use bullet points for lists
- For action requests (summarize, analyze, compare), provide structured output"""

    if is_action_request:
        system_prompt += "\n\nFor this action request, structure your response clearly with sections and bullet points where applicable."

    system = SystemMessage(content=system_prompt)

    human = HumanMessage(content=(
        f"Context:\n\n{context_str}\n\n"
        f"Request: {last_user}"
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

    log.info(f"[{state.get('trace_id','')}] answer generated ({len(answer)} chars, "
             f"action_request={is_action_request})")

    # Log to Notion Assistant Log (non-blocking)
    if not _llm_could_not_answer(answer):
        try:
            from backend.services.p3.assistant_log import log_turn
            log_turn(
                question  = last_user,
                reply     = answer,
                thread_id = state.get("thread_id", ""),
                intent    = state.get("intent", "question"),
                sources   = [{"doc_title": c["doc_title"],
                               "section_name": c["section_name"],
                               "score": c.get("score", 0)}
                              for c in chunks],
                outcome   = "Answered",
            )
        except Exception as _le:
            log.warning(f"assistant log_turn failed (non-fatal): {_le}")

    # Post-answer check: if LLM couldn't find info, escalate to ticket
    if _llm_could_not_answer(answer):
        log.info(f"[{state.get('trace_id','')}] LLM could not answer — escalating to ticket")
        # Remove the "I don't know" answer and route to ask user for ticket instead
        return {
            "messages":          new_messages,
            "_escalate_ticket":  True,          # signal for asking user about ticket
        }

    return {"messages": new_messages}


# ── Node: ask_create_ticket ───────────────────────────────────────────────────

def ask_create_ticket(state: dict) -> dict:
    """
    Ask the user if they want to create a support ticket.
    Also checks for duplicate/similar questions.
    
    Appends assistant message with:
      - Explanation of why we can't find an answer
      - Information about similar previous questions (if any)
      - Options to create a ticket or move on
    """
    messages  = state.get("messages", [])
    last_user = next((m["content"] for m in reversed(messages)
                      if m["role"] == "user"), "")
    
    # Check for similar previous questions
    user_id = state.get("user_id", "")
    similar_questions = _find_similar_previous_questions(user_id, last_user, limit=2)
    
    # Build the response message
    response_parts = [
        "I wasn't able to find a confident answer to your question in the indexed documents."
    ]
    
    # Mention duplicate if found
    if similar_questions:
        response_parts.append(
            "\n\n📌 **I found similar previously asked questions:**"
        )
        for idx, sim_q in enumerate(similar_questions, 1):
            ticket_status = f" [Ticket: {sim_q['ticket_id']}]" if sim_q.get("ticket_id") else ""
            response_parts.append(f"  {idx}. {sim_q['question']}{ticket_status}")
        response_parts.append(
            "\nWould you like to create a support ticket for this question, "
            "or did the previous answer help?"
        )
    else:
        response_parts.append(
            "\n\n💡 Would you like me to create a support ticket? "
            "Our team can investigate and get back to you."
        )
    
    response_parts.append(
        "\n\n**Reply with "
        "\"yes, create a ticket\" or \"no, thanks\"**"
    )
    
    response_text = "".join(response_parts)
    
    new_messages = list(messages)
    new_messages.append({
        "role":      "assistant",
        "content":   response_text,
        "timestamp": _now(),
    })
    
    # Store the flag that we're waiting for user decision
    log.info(f"[{state.get('trace_id','')}] Asked user to create ticket")
    
    return {
        "messages":           new_messages,
        "_waiting_for_ticket_decision": True,
        "_similar_questions": similar_questions,
    }


# ── Helper: Parse user's ticket decision ────────────────────────────────────

def _user_wants_ticket(user_message: str) -> bool:
    """
    Parse user's response to ticket creation question.
    Returns True if user wants to create a ticket.
    Accepts various forms of yes/no responses.
    """
    lower_msg = user_message.lower().strip()
    
    # Explicit no responses
    no_phrases = [
        "no", "nope", "don't create", "dont create", "don't", "dont",
        "no thanks", "no thank you", "nah", "not really", "negative",
        "decline", "pass", "skip", "do not create", "don't want",
        "not needed", "no need", "never mind", "forget it"
    ]
    
    # Explicit yes responses
    yes_phrases = [
        "yes", "yeah", "yep", "sure", "okay", "ok", "create", "plz", "please",
        "go ahead", "do it", "proceed", "create ticket", "raise ticket", "open ticket",
        "support ticket", "create a ticket", "raise a ticket", "absolutely", "definitely",
        "yes please", "sure thing", "let's do it"
    ]
    
    # Check for explicit "no" first
    if any(phrase in lower_msg for phrase in no_phrases):
        return False
    
    # Check for explicit "yes"
    if any(phrase in lower_msg for phrase in yes_phrases):
        return True
    
    # Default to False if unclear
    return False


# ── Node: create_ticket ───────────────────────────────────────────────────────

def create_ticket_node(state: dict) -> dict:
    """
    Create a Notion support ticket when retrieval is insufficient AND user wants one.
    Generates a conversation summary and attaches attempted sources.
    
    First checks if there are similar previous tickets to avoid duplicates.
    """
    from backend.services.p3.for_tickets import create_ticket

    messages  = state.get("messages", [])
    chunks    = state.get("last_retrieved", [])
    thread_id = state.get("thread_id", "")
    user_id   = state.get("user_id", "")
    
    # Get the current question (second-to-last message should be user's ticket decision)
    # First user message in this session is the actual question
    last_user = ""
    for m in messages:
        if m.get("role") == "user":
            last_user = m.get("content", "")
            break

    # Check if similar questions already have tickets
    similar_with_tickets = _find_similar_previous_questions(user_id, last_user, limit=5)
    existing_ticket_ids = [q.get("ticket_id") for q in similar_with_tickets if q.get("ticket_id")]
    
    if existing_ticket_ids:
        log.info(f"[{state.get('trace_id','')}] Found {len(existing_ticket_ids)} "
                 f"existing tickets for similar questions: {existing_ticket_ids}")

    # Special case: no documents ingested at all
    if not chunks:
        log.warning(f"[{state.get('trace_id','')}] Ticket triggered with 0 chunks — "
                    f"ChromaDB index may be empty")

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
        import traceback
        tb = traceback.format_exc()
        log.error(f"Ticket creation failed: {e}\n{tb}")
        ticket_id  = None
        ticket_url = ""
        existed    = False
        _ticket_err = str(e)
    else:
        _ticket_err = None

    # Compose response to user
    if existed:
        response_text = (
            "✓ A support ticket has already been raised for this question. "
            "Our team will follow up.\n\n"
            f"🎫 [View your ticket]({ticket_url})"
        )
    elif ticket_id:
        response_text = (
            "✓ Done! I've created a support ticket with your question, the sources I tried, "
            "and a conversation summary.\n\n"
            f"🎫 **Ticket created** — [Open in Notion]({ticket_url})\n\n"
            "Our team will review and respond. You can track it in the **🎫 My Tickets** tab."
        )
    else:
        # Show actual error so user/dev can diagnose
        err_hint = ""
        if _ticket_err:
            if "NOTION_PAGE_ID" in _ticket_err:
                err_hint = "\n\n⚠️ `NOTION_PAGE_ID` is not set in your `.env` file."
            elif "Unauthorized" in _ticket_err or "401" in _ticket_err:
                err_hint = "\n\n⚠️ Notion token is invalid or expired. Check `NOTION_TOKEN` in `.env`."
            elif "404" in _ticket_err:
                err_hint = "\n\n⚠️ Notion page not found. Check `NOTION_PAGE_ID` in `.env`."
            else:
                err_hint = f"\n\n⚠️ Error: `{_ticket_err[:200]}`"
        response_text = (
            "❌ Ticket creation failed — please check your Notion configuration."
            + err_hint
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

    # Log to Notion Assistant Log
    try:
        from backend.services.p3.assistant_log import log_turn
        log_turn(
            question  = last_user,
            reply     = response_text,
            thread_id = thread_id,
            intent    = state.get("intent", "question"),
            sources   = chunks,
            outcome   = "Ticket Created",
        )
    except Exception as _le:
        log.warning(f"assistant log_turn (ticket) failed: {_le}")

    return {
        "messages":  new_messages,
        "ticket_id": ticket_id,
    }


# ── Node: post_answer_check ───────────────────────────────────────────────────

def post_answer_check(state: dict) -> dict:
    """
    After generate_answer, check if the LLM flagged escalation.
    If yes, signal to ask user about ticket creation instead.
    """
    if state.get("_escalate_ticket"):
        log.info(f"[{state.get('trace_id','')}] post_answer_check: escalating to ticket decision")
        # Remove the last assistant message (the "I don't know" reply)
        messages = list(state.get("messages", []))
        if messages and messages[-1].get("role") == "assistant":
            messages = messages[:-1]
        return {
            "messages":         messages,
            "_escalate_ticket": False,
            "_needs_ticket_decision": True,
        }
    return {"_needs_ticket_decision": False}


def _route_after_answer_check(state: dict) -> Literal["ask_ticket_decision", "__end__"]:
    """Route whether to ask user about ticket or end."""
    if state.get("_needs_ticket_decision"):
        return "ask_ticket_decision"
    return "__end__"


# ── Router: Classify user response for ticket decision ────────────────────────

def _route_ticket_decision(state: dict) -> Literal["create_ticket", "__end__"]:
    """
    After asking about ticket creation, check user's response.
    If user wants a ticket, route to create_ticket.
    Otherwise, route to END.
    """
    messages = state.get("messages", [])
    last_user = next((m["content"] for m in reversed(messages)
                      if m["role"] == "user"), "")
    
    if _user_wants_ticket(last_user):
        return "create_ticket"
    else:
        # User declined ticket creation
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
