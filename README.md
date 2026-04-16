# DocForgeHub

A unified AI-powered enterprise document generation and retrieval system that combines intelligent document creation with retrieval-augmented generation (RAG) capabilities and a conversational assistant with LangGraph orchestration.

## 📑 Table of Contents

- [🎯 Overview](#-overview)
- [✨ Key Features](#-key-features)
- [🏛️ System Architecture](#️-system-architecture)
- [🚀 Installation & Setup](#-installation--setup)
- [📖 Detailed Workflows & Usage](#-detailed-workflows--usage)
  - [Workflow A: Document Generation (P1)](#workflow-a-document-generation-docforge--p1)
  - [Workflow B: Document Ingestion (P2)](#workflow-b-document-ingestion-citerag--p2)
  - [Workflow C: Q&A & Retrieval (P2)](#workflow-c-semantic-search--qa-citerag--p2)
  - [Workflow D: Conversational Assistant (P3)](#workflow-d-stateful-conversational-assistant-p3---langgraph)
- [📡 Complete API Reference](#-complete-api-reference)
  - [DocForge Routes (P1)](#docforge-routes-p1--document-generation)
  - [CiteRAG Routes (P2)](#citerag-routes-p2--qa--retrieval)
  - [Assistant Routes (P3)](#assistant-routes-p3--stateful-conversational-ai)
- [⚙️ Configuration & Environment](#️-configuration--environment)
- [📚 Development & Architecture](#-development--architecture)
- [🤝 Contributing](#-contributing)
- [🆘 Troubleshooting](#-troubleshooting)
- [📋 License](#-license)
- [🙋 Support & Contact](#-support--contact)
- [🚀 Roadmap](#-roadmap)

## 🎯 Overview

DocForgeHub integrates three complementary workflows into a single platform:

- **DocForge (P1)**: AI-driven document generation through structured planning, questioning, iterative refinement, and multi-format export
- **CiteRAG (P2)**: Retrieval-Augmented Generation system for intelligent Q&A with cited sources, semantic search, and auto-ingestion from Notion
- **Intelligent Assistant (P3)**: Stateful conversational agent with LangGraph orchestration, memory management, intent classification, and support ticket creation

## ✨ Key Features

### Document Generation (DocForge - P1)
- **AI Planning**: Generate structured document outlines from natural language prompts using Azure OpenAI
- **Targeted Questioning**: Create specific input questions for each document section
- **Content Generation**: AI-powered writing with support for prose, narrative, and tabular content
- **Iterative Refinement**: User feedback loop for progressive content improvement
- **Multi-format Export**: Generate Word (.docx) documents and Excel (.xlsx) spreadsheets with smart formatting
- **Notion Integration**: Sync generated documents with Notion databases and auto-ingest for RAG
- **Version Control**: Track document versions with full versioning history and parent-child relationships
- **Rate Limiting**: Throttle-based rate limiting on refinement operations to prevent abuse
- **Smart Extraction**: Automatic detection of tabular vs. narrative content

### Retrieval-Augmented Generation (CiteRAG - P2)
- **Semantic Search**: Vector-based search using 3072D embeddings over enterprise document chunks
- **Cited Q&A**: Answer generation with automated [Source N] citations to retrieved chunks
- **Metadata Filtering**: Search with filters by document type, industry, title, and version
- **Auto-Ingestion**: Background daemon automatically ingests Notion docs with change detection (skip unchanged)
- **Multi-Query Expansion**: Retrieve broader context by generating query variants
- **Document Comparison**: Side-by-side comparison with LLM-generated insights
- **Evaluation Framework**: RAGAS-based evaluation (faithfulness, answer relevancy) with run history
- **Caching**: Multi-tier caching (Redis 24hr for Q&A, PostgreSQL for persistence)

### Intelligent Assistant (P3)
- **Multi-turn Conversations**: Stateful chat with full conversation history and context awareness
- **Intent Classification**: LLM-based classification (question/request/problem/feedback) with confidence scoring
- **Context-Aware Retrieval**: Semantic search with referential pronoun understanding ("it", "that", "them")
- **Smart Clarification**: Avoids redundant clarifications when context is clear from previous messages
- **Ticket Creation**: Offers support ticket creation for unresolved queries or complex issues
- **Duplicate Detection**: Checks for similar previous questions to avoid redundant ticket creation
- **Memory Hierarchy**: Redis (30-min L1) + PostgreSQL (permanent L4) for session and persistent state
- **LangGraph Orchestration**: Conditional routing through 8+ nodes for intelligent conversation flow
- **Thread Management**: Full thread lifecycle with user isolation and conversation logging

## 🏛️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Streamlit)                         │
│  • Overview Dashboard  • Document Generation  • Retrieval Q&A   │
│  • Assistant Chat      • Document Management  • Evaluation      │
└────────────┬────────────────────────────────────────────────────┘
             │
             │ HTTP (port 8501)
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   BACKEND (FastAPI - port 8080)                 │
├──────────────────┬──────────────────┬──────────────────┐        │
│  P1: DocForge    │  P2: CiteRAG     │  P3: Assistant   │        │
├──────────────────┼──────────────────┼──────────────────┤        │
│ • Planner        │ • Ingestion      │ • Graph (Lang)   │ LLM    │
│ • Questions      │ • Retrieval      │ • Nodes (8+)     │─────┐  │
│ • Generator      │ • QA Pipelines   │ • State Mgmt     │     │  │
│ • Refinement     │ • Evaluation     │ • Memory (L1-L4) │ ◄───┤  │
│ • Excel Ops      │ • Comparisons    │ • Tickets        │ Azure  │
│ • Notion Sync    │ • Notion Logs    │ • Logging        │ OpenAI │
│ • Redis Cache    │ • Redis Cache    │ • TBD Ticket     │     │  │
└──────────────────┴──────────────────┴──────────────────┘     │  │
             │                                                 └──┘
     ┌───────┼───────────────────────────────────┐
     │       │                                   │
     ▼       ▼                                   ▼
┌────────────────────┐   ┌──────────────┐   ┌─────────────┐
│  PostgreSQL DB     │   │ Redis Cache  │   │ ChromaDB    │
│                    │   │              │   │  + SQLite   │
│ • Documents        │   │ • P1 Plans   │   │             │
│ • Assistant State  │   │ • P1 Qs      │   │ • Embeddings│
│ • Thread Data      │   │ • P1 Gen     │   │ • Chunks    │
│ • Ticket Records   │   │ • P2 Q&A     │   │ • Eval      │
│ • Eval Runs        │   │ • P3 State   │   │   Runs      │
│ • QA Log           │   │ • Locks      │   │ • Ingestion │
│ • Chat Log         │   │ • Context    │   │   Status    │
└────────────────────┘   │   Windows    │   └─────────────┘
                         └──────────────┘
                             ▲
                             │
                      (30-min TTL)
                             │
                         ┌───┴────┐
                         │ Redis  │
                         │ Server │
                         └────────┘
     External API Integrations:
           • Notion API (sync, document source)
           • Azure OpenAI (LLM, embeddings)
```

### Backend Components Structure

```
backend/
├── services/
│   ├── p1/                    # DocForge: Document Generation
│   │   ├── planner.py         # Document outline generation
│   │   ├── question.py        # Section-specific question generation
│   │   ├── generator.py       # AI content writing (prose)
│   │   ├── excel_generator.py # Tabular content generation
│   │   ├── refinement.py      # Iterative content improvement
│   │   ├── excel_exporter.py  # Export to .xlsx format
│   │   ├── notion.py          # Notion database sync + creation
│   │   ├── redis.py           # Caching + rate limiting
│   │   └── orchestrator.py    # High-level P1 wrapper
│   │
│   ├── p2/                    # CiteRAG: Retrieval-Augmented QA
│   │   ├── for_ingestion.py   # Notion → chunks → embeddings
│   │   ├── for_retrieval.py   # Semantic search using ChromaDB
│   │   ├── for_qa.py          # Q&A answer generation + citations
│   │   ├── for_comparison.py  # Document comparison pipeline
│   │   ├── for_evaluation.py  # RAGAS evaluation framework
│   │   ├── qa_log.py          # Notion QA log + fetch
│   │   └── multi_query.py     # Query expansion helpers
│   │
│   ├── p3/                    # Assistant: Stateful Conversational AI
│   │   ├── for_state.py       # AssistantState TypedDict + CRUD
│   │   ├── for_memory.py      # Redis + PostgreSQL memory hierarchy
│   │   ├── for_graph.py       # LangGraph definition + run_turn()
│   │   ├── nodes.py           # 8+ node implementations (classify, retrieve, etc.)
│   │   ├── for_tickets.py     # Notion ticket fetching + updates
│   │   └── assistant_log.py   # Conversation logging
│   │
│   └── langchain.py           # Global Azure OpenAI LLM instance
│
├── chroma_db.py               # ChromaDB collection interface + SQLite eval storage
├── database.py                # PostgreSQL interface (documents, state, etc.)
└── __init__.py
```

## 🚀 Installation & Setup

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Azure OpenAI API credentials (LLM + Embeddings)
- Notion API token and database access
- PostgreSQL (via Docker)
- Redis (via Docker)

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd FullProject
   ```

2. **Configure environment variables**
   Create a `.env` file with all required variables:
   ```bash
   # Azure OpenAI LLM Configuration
   AZURE_OPENAI_API_KEY=your_api_key
   AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
   AZURE_OPENAI_DEPLOYMENT=gpt-4  # or your deployment name
   AZURE_OPENAI_API_VERSION=2023-12-01-preview

   # Azure OpenAI Embeddings Configuration
   AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
   AZURE_OPENAI_EMBEDDING_API_VERSION=2023-12-01-preview

   # Database Configuration
   POSTGRES_HOST=db
   POSTGRES_PORT=5432
   POSTGRES_DB=docforge
   POSTGRES_USER=docforge
   POSTGRES_PASSWORD=your_secure_password

   # Redis Configuration
   REDIS_HOST=redis
   REDIS_PORT=6379
   REDIS_DB=0
   REDIS_PASSWORD=""

   # Notion Configuration
   NOTION_API_TOKEN=your_notion_integration_token
   NOTION_DATABASE_ID=your_docforge_database_id

   # Archive Configuration (optional)
   ENABLE_ARCHIVE=false
   ARCHIVE_MAX_VERSIONS=10

   # ChromaDB Configuration
   CHROMA_DATA_PATH=./chroma_data
   ```

3. **Start Docker services (PostgreSQL, Redis)**
   ```bash
   docker-compose up -d
   ```

4. **Create Python virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

5. **Run the application**
   ```bash
   # Terminal 1: Start FastAPI backend on port 8080
   uvicorn main:app --reload --port 8080

   # Terminal 2: Start Streamlit frontend on port 8501
   streamlit run frontend/mainstream.py
   ```

6. **Access the application**
   - **Frontend UI**: http://localhost:8501
   - **Backend API**: http://localhost:8080
   - **API Docs**: http://localhost:8080/docs
   - **ReDoc**: http://localhost:8080/redoc

### System Initialization Flow
On backend startup, the following initialization sequence automatically runs:
1. PostgreSQL database initialization (`documents`, `assistant_state` tables)
2. Redis connection verification
3. ChromaDB collection setup + SQLite evaluation runs table
4. Assistant state table creation
5. Initial auto-ingest of Notion documents (skips unchanged)
6. Background daemon starts for periodic ingest polling (every 15 minutes)

## 📖 Detailed Workflows & Usage

### Workflow A: Document Generation (DocForge - P1)

**Complete end-to-end document creation flow:**

```
1. User generates document outline
   POST /plan {prompt: "Create a business plan for a tech startup"}
   ↓ Returns: {title, sections[], doc_format, show_headings}

2. User reviews outline and generates section questions
   POST /questions {title, sections}
   ↓ Returns: {section_title: [question1, question2, ...]}

3. User answers questions (via UI)
   ↓ Accumulates responses

4. Backend generates content
   POST /generate {title, sections, answers, doc_format, show_headings}
   ↓ Calls LLM for each section with context
   ↓ Returns: {section1_title: full_content, section2_title: ..., __section_order__: [...]}

5. User optionally refines sections
   POST /refine-section {section_name, original_text, feedback, doc_format}
   ↓ Calls LLM with original text + user feedback
   ↓ Returns refined section text
   ↓ Rate limited: max 5 refines per section per hour

6. Save or export document
   Option A: POST /documents/save {title, content, file_format, save_mode: "new_version"}
     → Stores in PostgreSQL with auto-versioning (v1, v2, ...)
   Option B: POST /export/excel → Streams .xlsx bytes
   Option C: POST /notion/push → Creates Notion page + triggers auto-ingest
```

**Caching at each step:**
- `/plan` results cached 1 week
- `/questions` results cached 1 week
- `/generate` results cached 1 week
- Redis invalidation on new user prompt

---

### Workflow B: Document Ingestion (CiteRAG - P2, Background)

**Auto-ingestion pipeline from Notion:**

```
STARTUP PHASE:
  1. init_db() initializes ChromaDB collection (cosine similarity, 3072-D embeddings)
  2. _auto_ingest(force=False) runs in background thread
     → Fetches all pages from Notion DocForge Documents database
     → For each page: compare last_edited_time vs stored ingested_at
     → Skip unchanged pages (efficient checksum logic)
     → Changed pages:
        a. Fetch full page content from Notion
        b. Semantic chunking (500 chars, 50-char overlap)
        c. Generate chunks: {doc_title, doc_type, version, industry, section_name, chunk_text, notion_url, ...}
        d. embed_batch(texts) → Azure OpenAI 3072-D embeddings
        e. upsert_chunks() into ChromaDB (replace if exists, insert new)
     
BACKGROUND POLLING:
  3. _ingest_poll_loop() runs every 15 minutes
     → Calls _auto_ingest() without force flag
     → Skips unchanged pages (cost-effective)
     
MANUAL TRIGGER:
  4. After POST /notion/push success:
     → thread: _auto_ingest(page_ids=[new_page_id], force=True)
     → Immediately re-ingests the new/updated page with embeddings
```

**Data transformation:**
- Notion page → raw text → chunks → embeddings → ChromaDB

---

### Workflow C: Semantic Search & Q&A (CiteRAG - P2)

**Complete Q&A pipeline with citations:**

```
1. User submits query
   POST /rag/search {query: "What are Q4 expenses?", top_k: 5, filters: {doc_type: "Report"}}
   ↓ Check Redis cache first
   ↓ embed_text(query) → 3072-D embedding
   ↓ semantic_search() in ChromaDB with cosine similarity
   ↓ Apply metadata filters: {doc_type: "Report", ...}
   ↓ Return top_k chunks sorted by score (descending)
   ↓ Cache result in Redis (24-hour TTL)

2. User asks question with sources
   POST /rag/ask {question: "What are Q4 expenses?", top_k: 6, filters: {...}}
   ↓ Check Redis cache for exact question
   ↓ If cache miss:
      a. search(question) → retrieve top chunks with scores
      b. Build context window:
         [Source 1] Document Title (v2) — Section Name
         {chunk_text_1}
         
         [Source 2] Document Title (v2) — Section Name
         {chunk_text_2}
      
      c. Construct LLM prompt:
         System: "You are CiteRAG. Use sources to answer. Add [Source N] citations."
         User: f"Context:\n{context_window}\n\nQuestion: {question}"
      
      d. LLM generates answer with citations:
         "Based on Q4 reports [Source 1], expenses totaled $500k. 
          Breakdown: Personnel [Source 2], Operations [Source 3]."
      
      e. Extract sources with scores
      f. log_qa() to Notion QA Log
      g. cache_ask() in Redis
   
   ↓ Return: {answer, sources: [{doc_title, section_name, chunk_text, score, url}], context_used_count}

3. User refines answer (optional)
   POST /rag/ask/refine {question, answer, feedback: "Make it more concise", sources}
   ↓ NO NEW RETRIEVAL (reuse same sources)
   ↓ LLM rewrites answer with original sources
   ↓ Return refined answer

4. User compares two documents
   POST /rag/compare {title_a: "Budget 2024", title_b: "Budget 2023", focus: "expenses"}
   ↓ Check Redis cache
   ↓ get_doc_chunks(title_a) → retrieve for Budget 2024
   ↓ get_doc_chunks(title_b) → retrieve for Budget 2023
   ↓ LLM generates comparison:
      - Summary of both
      - Similarities
      - Differences
      - Recommendation
   ↓ log_compare() to Notion
   ↓ Return comparison with chunks
```

**Key thresholds:**
- MIN_CHUNKS = 2 (minimum retrieved chunks for Q&A)
- MIN_AVG_SCORE = 0.35 (minimum average cosine similarity)
- CHUNK_SIZE = 500 chars, OVERLAP = 50 chars

---

### Workflow D: Stateful Conversational Assistant (P3 - LangGraph)

**Multi-turn intelligent conversation flow:**

```
SETUP: User starts chat
  → POST /assistant/chat {message: "What's the budget?", thread_id: null}
  → If no thread_id: new_state() creates fresh AssistantState
  → If thread_id provided: restore_state(thread_id)
    a. Try: get_cached_state() from Redis (< 1ms hit)
    b. Fallback: load_state() from PostgreSQL

STATE PERSISTENCE:
  → acquire_lock(thread_id) prevents concurrent mutations
  → add_message(state, role="user", content=message)
  → persist_state() to PostgreSQL
  → cache_state() in Redis (30-min TTL)

LANGGRAPH NODES (execute sequentially with conditional routing):

  NODE 1: check_ticket_decision()
    → Is user responding to prior ticket creation question?
    → Checks if last_assistant_msg asked about ticket
    → If yes: call _user_wants_ticket() to parse yes/no
    → If user said yes: route to create_ticket_node()
    → If user said no: set _user_declined_ticket=True, continue
    → Otherwise: proceed to normal flow

  NODE 2: classify_intent()
    → LLM classifies user message:
       * "question" (asking for info)
       * "request" (summarize/analyze/compare)
       * "problem" (unable to find info)
       * "feedback" (commenting on prior answer)
    ↓ Also tracks previous_user message for context awareness
    ↓ Smart prompt: "Avoid clarification if referential context is clear"
    ↓ Confidence threshold: 0.6 (below = needs clarification)
    ↓ Returns: {intent, confidence, _clarification_question?}

  NODE 3: DECISION POINT
    ↓ If pending_clarification == True:
      → ask_clarification() node
      → reply = "I'm not sure I understand. Could you clarify...?"
      → add_message(state, role="assistant", content=reply)
      → RETURN (wait for next user message on next /assistant/chat call)
    ↓ Else: continue to retrieve

  NODE 4: retrieve()
    → embed_text(user_message) → 3072-D embedding
    → Check context: does user's message reference prior topic?
       * Detect referential pronouns: "it", "that", "this", "them", "summarize", "analyze"
       * If referential + previous_user exists: combine
         search_query = f"{previous_user}. {user_message}"
       * Else: use user_message as-is
    ↓ semantic_search() in ChromaDB
    ↓ Apply doc_filters if provided
    ↓ Check for similar_previous_questions in history
    ↓ state.last_retrieved = chunks
    ↓ Returns: {chunks, scores, similar_questions?}

  NODE 5: check_sufficiency()
    → Evaluate: do we have enough context to answer?
    → Thresholds:
       * len(chunks) >= MIN_CHUNKS (2)
       * avg(chunk_scores) >= MIN_AVG_SCORE (0.35)
    ↓ If both true: route to "answer"
    ↓ Else: route to "ask_ticket" (insufficient info)

  NODE 6a: generate_answer() [if sufficient]
    → Detect if is_action_request: summarize/analyze/compare/extract/list/identify/explain
    → LLM generates answer with [Source N] citations
    → system_prompt includes: "For action requests, provide structured output with bullet points"
    ↓ For summaries: format as bullet points with key sections
    ↓ For analysis: provide structured breakdown
    ↓ For compare: provide side-by-side or tabular format
    ↓ add_message(state, role="assistant", content=answer)
    ↓ Returns: {answer_with_citations, sources}

  NODE 6b: post_answer_check()
    → LLM evaluates: "Should this create a support ticket?"
    → Logic: if user's question suggests unresolved complexity
    ↓ Sets: _needs_ticket_decision = True/False
    ↓ Returns: {needs_ticket: bool}

  NODE 6c: DECISION POINT
    ↓ If _needs_ticket_decision == True:
      → ask_create_ticket() node
    ↓ Else:
      → END (return answer to user)

  NODE 7: ask_create_ticket()
    → Check similar_previous_questions to avoid duplicates
    → If duplicates exist: mention them ("I found similar tickets: ...")
    → reply = "Would you like me to create a support ticket? Reply with 'yes' or 'no'"
    → add_message(state, role="assistant", content=reply)
    → state._waiting_for_ticket_decision = True
    → RETURN (wait for user response)

  NODE 7b: [User responds to ticket question]
    → On next /assistant/chat call:
      → check_ticket_decision() intercepts response
      → _user_wants_ticket() parses yes/no
         * yes_phrases: "yes", "sure", "create ticket", "absolutely", "okay let's do it"
         * no_phrases: "no", "nope", "skip", "pass", "decline", "no thanks"
    
    ↓ If YES:
      → create_ticket_node()
        a. _find_similar_previous_questions()
        b. If found similar: log and return (skip duplicate)
        c. Else: create_ticket() on Notion Tickets DB
        d. Store ticket_id in PostgreSQL
        e. Return: {ticket_id, ticket_url}
    
    ↓ If NO:
      → reply = "No problem! Feel free to ask if you need anything else."
      → END

FINAL RESPONSE:
  → release_lock(thread_id)
  → Return HTTP response:
     {
       thread_id: "uuid-abc123",
       reply: "Here's the answer...",
       sources: [{doc_title, section_name, score, url}, ...],
       ticket_id: "notion-page-id" | null,
       ticket_url: "https://notion.so/..." | null,
       intent: "question" | "request" | "problem",
       messages: [{role, content, timestamp}, ...],
       trace_id: "uuid-trace"
     }

PERSISTENCE:
  → persist_state() after each node
  → save_state() → PostgreSQL
  → cache_state() + cache_context_window(last_10_msgs) → Redis
```

**State Hierarchy (Memory):**
| Layer | Storage | TTL | Speed | Purpose |
|-------|---------|-----|-------|---------|
| L1 | Redis state | 30 min | <1ms | Active session, instant resume |
| L2 | Redis lock | 10 sec | <1ms | Concurrent write prevention |
| L3 | Redis context | 30 min | <1ms | Quick message window access |
| L4 | PostgreSQL | ∞ | ~10ms | Permanent record, offline queries |

## 📡 Complete API Reference

### DocForge Routes (P1) — Document Generation

#### POST /plan
Generate structured document outline from a natural language prompt.

**Request:**
```json
{
  "prompt": "Create a business plan for an AI startup with details on market opportunity, team, financials"
}
```

**Response:**
```json
{
  "title": "AI Startup Business Plan",
  "sections": [
    {"title": "Executive Summary", "description": "High-level overview"},
    {"title": "Market Opportunity", "description": "TAM and competitive landscape"},
    {"title": "Product & Team", "description": "Technical capabilities"},
    {"title": "Financial Projections", "description": "3-year forecasts"}
  ],
  "doc_format": "word",
  "show_headings": true
}
```

#### POST /questions
Generate targeted questions for each document section to gather user input.

**Request:**
```json
{
  "title": "AI Startup Business Plan",
  "sections": [
    {"title": "Executive Summary"},
    {"title": "Market Opportunity"}
  ]
}
```

**Response:**
```json
{
  "Executive Summary": [
    "What specific AI problem does your product solve?",
    "Who are the primary customers?",
    "What is your go-to-market strategy?"
  ],
  "Market Opportunity": [
    "What is the total addressable market (TAM)?",
    "Who are your top 3 competitors?"
  ]
}
```

#### POST /generate
Generate full document content for all sections based on user answers.

**Request:**
```json
{
  "title": "AI Startup Business Plan",
  "sections": [{"title": "Executive Summary"}, {"title": "Market Opportunity"}],
  "user_answers": {
    "Executive Summary": ["Sentiment analysis platform", "Enterprise compliance teams", "Direct sales"],
    "Market Opportunity": ["$5B TAM", "Clear Compliance, Alteryx, Relativity"]
  },
  "doc_format": "word",
  "show_headings": true
}
```

**Response:**
```json
{
  "Executive Summary": "Our company provides enterprise sentiment analysis...",
  "Market Opportunity": "The sentiment analysis market for compliance...",
  "__section_order__": ["Executive Summary", "Market Opportunity"],
  "__show_headings__": true
}
```

#### POST /refine-section
Refine a specific section based on user feedback.

**Request:**
```json
{
  "section_name": "Executive Summary",
  "original_text": "Our company provides...",
  "feedback": "Make it more concise and focus on ROI",
  "doc_format": "word"
}
```

**Response:**
```json
{
  "updated_text": "Our AI platform delivers 40% faster sentiment analysis with 99% accuracy, reducing compliance review costs by $500k annually for enterprise teams."
}
```

#### POST /export/excel
Export document as Excel spreadsheet (streaming response).

**Request:**
```json
{
  "title": "Q4 Financial Report",
  "sheets": [
    {
      "sheet_name": "Income Statement",
      "headers": ["Item", "Q4 2024", "Q4 2023"],
      "rows": [["Revenue", "1000000", "850000"], ["Expenses", "600000", "520000"]]
    }
  ]
}
```

**Response:** Binary Excel file (.xlsx bytes)

#### POST /documents/save
Save document to PostgreSQL with auto-versioning.

**Request:**
```json
{
  "title": "Q4 Financial Report",
  "content": {"Executive Summary": "Lorem ipsum...", "__section_order__": [...]},
  "doc_type": "Financial",
  "doc_format": "word",
  "file_bytes": "base64_encoded_docx_bytes",
  "file_ext": "docx",
  "save_mode": "new_version"
}
```

**Response:**
```json
{
  "id": 42,
  "title": "Q4 Financial Report",
  "version": 3,
  "parent_id": 40,
  "message": "Document saved as v3"
}
```

#### GET /documents
List all documents with version information.

**Response:**
```json
{
  "documents": [
    {
      "id": 42,
      "title": "Q4 Financial Report",
      "version": 3,
      "doc_type": "Financial",
      "doc_format": "word",
      "created_at": "2026-04-16 10:30 AM",
      "parent_id": 40
    }
  ]
}
```

#### GET /documents/{doc_id}
Fetch full document details including content.

**Response:**
```json
{
  "id": 42,
  "title": "Q4 Financial Report",
  "version": 3,
  "content": {"Executive Summary": "...", "...": "..."},
  "doc_type": "Financial",
  "doc_format": "word",
  "file_ext": "docx"
}
```

#### GET /documents/{doc_id}/download
Download document as binary file (.docx or .xlsx).

**Response:** Binary file with Content-Disposition: attachment header

#### PATCH /documents/{doc_id}/rename
Rename document (updates all versions with same title).

**Request:**
```json
{
  "title": "Q4 2026 Financial Report (Updated)"
}
```

**Response:**
```json
{
  "message": "Renamed to 'Q4 2026 Financial Report (Updated)' (3 version(s) updated)"
}
```

#### POST /documents/check-version
Check if document exists and get latest version info.

**Request:**
```json
{
  "title": "Q4 Financial Report"
}
```

**Response:**
```json
{
  "exists": true,
  "latest_id": 42,
  "latest_version": 3
}
```

#### POST /notion/push
Push document to Notion database and trigger auto-ingest.

**Request:**
```json
{
  "title": "Q4 Financial Report",
  "content": {"Executive Summary": "...", "...": "..."},
  "doc_format": "word",
  "doc_type": "Financial"
}
```

**Response:**
```json
{
  "page_id": "notion-page-uuid",
  "url": "https://notion.so/...",
  "database": "DocForge Documents",
  "message": "Pushed to Notion"
}
```

#### POST /notion/update
Update existing Notion page with new content.

**Request:**
```json
{
  "page_id": "notion-page-uuid",
  "title": "Q4 Financial Report (Revised)",
  "content": {"Executive Summary": "...", "...": "..."},
  "version": 2,
  "doc_type": "Financial"
}
```

**Response:**
```json
{
  "page_id": "notion-page-uuid",
  "url": "https://notion.so/...",
  "message": "Updated on Notion"
}
```

---

### CiteRAG Routes (P2) — Q&A & Retrieval

#### POST /rag/search
Perform semantic search across all ingested documents.

**Request:**
```json
{
  "query": "What are the Q4 expenses?",
  "top_k": 5,
  "filters": {
    "doc_type": "Report",
    "industry": "Finance",
    "doc_title": "Q4 Financial Summary"
  }
}
```

**Response:**
```json
{
  "query": "What are the Q4 expenses?",
  "total": 5,
  "cached": false,
  "chunks": [
    {
      "id": "chunk-uuid",
      "doc_title": "Q4 Financial Summary",
      "section_name": "Expenses",
      "chunk_text": "Q4 expenses totaled $500,000: Personnel $280k, Operations $160k, Contingency $60k",
      "score": 0.89,
      "notion_url": "https://notion.so/chunk-page",
      "version": 1
    }
  ]
}
```

#### POST /rag/ask
Ask a question with RAG-based answering and source citations.

**Request:**
```json
{
  "question": "What were the main expense categories in Q4?",
  "top_k": 6,
  "filters": {"doc_type": "Report", "industry": "Finance"}
}
```

**Response:**
```json
{
  "question": "What were the main expense categories in Q4?",
  "answer": "According to Q4 reports, the main expense categories were: [Source 1] Personnel accounted for $280,000 (56% of total), [Source 1] Operations was $160,000 (32%), and [Source 1] Contingency reserve was $60,000 (12%), totaling $500,000. [Source 2] Year-over-year, this represents a 12% increase from Q3.",
  "cached": false,
  "sources": [
    {
      "id": "chunk-uuid-1",
      "doc_title": "Q4 Financial Summary",
      "section_name": "Expenses",
      "chunk_text": "Q4 expenses totaled $500,000: Personnel $280k...",
      "score": 0.89,
      "notion_url": "https://notion.so/...",
      "version": 1
    },
    {
      "id": "chunk-uuid-2",
      "doc_title": "Q3-Q4 Comparison",
      "section_name": "Year-over-Year Analysis",
      "chunk_text": "Q4 saw a 12% quarter-over-quarter increase...",
      "score": 0.78,
      "notion_url": "https://notion.so/...",
      "version": 1
    }
  ],
  "context_used": 2,
  "notion_log_url": "https://notion.so/qa-log-entry"
}
```

#### POST /rag/ask/refine
Refine a prior answer based on feedback without new retrieval.

**Request:**
```json
{
  "question": "What were the main expense categories in Q4?",
  "answer": "...full prior answer...",
  "feedback": "Make it more concise and add percentage breakdowns",
  "sources": [...prior sources...]
}
```

**Response:**
```json
{
  "refined_answer": "[Source 1] Q4 expenses totaled $500k: Personnel 56% ($280k), Operations 32% ($160k), Contingency 12% ($60k).",
  "sources": [...same sources...]
}
```

#### POST /rag/compare
Compare two documents side-by-side with LLM insights.

**Request:**
```json
{
  "title_a": "Q4 2024 Budget",
  "title_b": "Q4 2023 Budget",
  "focus": "expense categories and growth trends"
}
```

**Response:**
```json
{
  "title_a": "Q4 2024 Budget",
  "title_b": "Q4 2023 Budget",
  "focus": "expense categories and growth trends",
  "comparison": {
    "summary": "Both budgets follow similar structures with notable increases in cloud infrastructure spending.",
    "similarities": "Both allocate ~55% to personnel costs and maintain 10% contingency reserves.",
    "differences": "2024 increased cloud/infrastructure from 15% to 24% due to AI initiatives.",
    "recommendation": "2024 budget reflects strategic shift to AI infrastructure. Monitor cloud costs closely."
  },
  "doc_a_chunks": [...chunks from Q4 2024...],
  "doc_b_chunks": [...chunks from Q4 2023...],
  "cached": false
}
```

#### POST /rag/ingest
Manually trigger document ingestion from Notion.

**Request:**
```json
{
  "page_ids": ["notion-uuid-1", "notion-uuid-2"],
  "force": true
}
```

**Response:**
```json
{
  "ingested": 2,
  "skipped": 0,
  "chunks": 24,
  "message": "Successfully ingested 2 documents with 24 chunks"
}
```

#### POST /rag/eval/run
Run RAGAS evaluation on Q&A quality.

**Request:**
```json
{
  "questions": [
    "What are Q4 expenses?",
    "Who are the top customers?",
    "What is our market share?"
  ],
  "config": {
    "run_name": "Q4 Eval Run",
    "top_k": 5
  }
}
```

**Response:**
```json
{
  "run_id": 1,
  "summary": {
    "faithfulness": 0.87,
    "answer_relevancy": 0.92,
    "context_precision": 0.85,
    "context_recall": 0.79
  },
  "results": [
    {
      "question": "What are Q4 expenses?",
      "answer": "...",
      "faithfulness": 0.89,
      "answer_relevancy": 0.95,
      "context_precision": 0.90,
      "context_recall": 0.82
    }
  ]
}
```

---

### Assistant Routes (P3) — Stateful Conversational AI

#### POST /assistant/chat
Send a message to the stateful assistant (main entry point).

**Request:**
```json
{
  "message": "What were our Q4 expenses?",
  "thread_id": null,
  "user_id": "user@company.com",
  "filters": {
    "doc_type": "Financial Report",
    "industry": "Technology"
  },
  "industry": "Technology"
}
```

**Response (First Turn):**
```json
{
  "thread_id": "uuid-abc123-new",
  "reply": "According to our Q4 reports, expenses totaled $500,000 across three categories [Source 1]. Personnel costs were 56% ($280k), operations 32% ($160k), and contingency 12% ($60k). Would you like me to break this down further or create a support ticket for detailed analysis?",
  "sources": [
    {
      "id": "chunk-1",
      "doc_title": "Q4 Financial Report",
      "section_name": "Executive Summary - Expenses",
      "chunk_text": "Q4 expenses totaled $500,000...",
      "score": 0.91
    }
  ],
  "intent": "question",
  "ticket_id": null,
  "ticket_url": null,
  "messages": [
    {"role": "user", "content": "What were our Q4 expenses?", "timestamp": "2026-04-16T15:30:00Z"},
    {"role": "assistant", "content": "According to our Q4 reports...", "timestamp": "2026-04-16T15:30:02Z"}
  ],
  "trace_id": "trace-uuid-123"
}
```

**Response (Follow-up Turn with Clarification):**
```json
{
  "thread_id": "uuid-abc123",
  "reply": "I'm not entirely sure which aspect of the expenses you'd like me to focus on. Would you like me to: (1) compare Q4 to Q3, (2) provide industry benchmarks, or (3) break down by department?",
  "sources": [],
  "intent": "clarification",
  "ticket_id": null,
  "ticket_url": null,
  "messages": [
    {"role": "user", "content": "What were our Q4 expenses?", "timestamp": "2026-04-16T15:30:00Z"},
    {"role": "assistant", "content": "According to our Q4 reports...", "timestamp": "2026-04-16T15:30:02Z"},
    {"role": "user", "content": "Tell me more", "timestamp": "2026-04-16T15:31:00Z"},
    {"role": "assistant", "content": "I'm not entirely sure which aspect...", "timestamp": "2026-04-16T15:31:02Z"}
  ],
  "trace_id": "trace-uuid-124"
}
```

**Response (Ticket Offer):**
```json
{
  "thread_id": "uuid-abc123",
  "reply": "I wasn't able to find detailed information about future budget projections in our current documents. Would you like me to create a support ticket to have the finance team gather this information for you? (Reply with 'yes' or 'no')",
  "sources": [],
  "intent": "question",
  "ticket_id": null,
  "ticket_url": null,
  "messages": [...],
  "trace_id": "trace-uuid-125"
}
```

**Response (Ticket Created):**
```json
{
  "thread_id": "uuid-abc123",
  "reply": "Perfect! I've created a support ticket for you. The finance team will reach out within 24 hours to discuss your budget projection needs.",
  "sources": [],
  "intent": "question",
  "ticket_id": "notion-ticket-uuid-456",
  "ticket_url": "https://notion.so/tickets/456",
  "messages": [...],
  "trace_id": "trace-uuid-126"
}
```

#### GET /assistant/thread/{thread_id}
Retrieve full conversation history for a thread.

**Response:**
```json
{
  "thread_id": "uuid-abc123",
  "messages": [
    {"role": "user", "content": "What were Q4 expenses?", "timestamp": "2026-04-16T15:30:00Z"},
    {"role": "assistant", "content": "Q4 expenses totaled $500k...", "timestamp": "2026-04-16T15:30:02Z"},
    {"role": "user", "content": "Can you summarize by department?", "timestamp": "2026-04-16T15:35:00Z"},
    {"role": "assistant", "content": "By department: [Source 2]...", "timestamp": "2026-04-16T15:35:03Z"}
  ],
  "intent": "question",
  "industry": "Technology",
  "ticket_id": null
}
```

#### GET /assistant/threads
List recent assistant threads for a user.

**Response:**
```json
{
  "threads": [
    {
      "thread_id": "uuid-abc123",
      "intent": "question",
      "industry": "Technology",
      "ticket_id": null,
      "updated_at": "2026-04-16T15:35:00Z"
    },
    {
      "thread_id": "uuid-def456",
      "intent": "request",
      "industry": "Finance",
      "ticket_id": "notion-ticket-xyz",
      "updated_at": "2026-04-15T10:22:00Z"
    }
  ],
  "total": 2
}
```

#### GET /assistant/tickets
Fetch support tickets from Notion Ticket DB.

**Response:**
```json
{
  "tickets": [
    {
      "ticket_id": "notion-ticket-uuid-456",
      "title": "Q1 Budget Projection Request",
      "status": "Open",
      "created_at": "2026-04-16T15:30:00Z",
      "thread_id": "uuid-abc123"
    }
  ],
  "total": 1
}
```

#### PATCH /assistant/tickets/{ticket_id}/status
Update ticket status.

**Request:**
```json
{
  "status": "In Progress"
}
```

**Response:**
```json
{
  "message": "Ticket updated to 'In Progress'"
}
```

---

### Utility Routes

#### GET /health
Check overall service health.

**Response:**
```json
{
  "status": "ok",
  "service": "DocForgeHub",
  "redis": true
}
```

#### GET /assistant/debug/retrieval
Debug what documents are retrieved for a query.

**Query Parameters:**
- `q`: query string (e.g., "agile team participants")
- `top_k`: number of results (default: 5)

**Response:**
```json
{
  "query": "agile team participants",
  "total": 3,
  "chunks": [
    {
      "doc_title": "Team Structure Document",
      "section_name": "Dev Team",
      "score": 0.87,
      "preview": "The agile development team consists of 8 engineers..."
    }
  ]
}
```

## ⚙️ Configuration & Environment

### Required Environment Variables

**Azure OpenAI (LLM)**
```env
AZURE_OPENAI_API_KEY=your_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2023-12-01-preview
```

**Azure OpenAI (Embeddings)**
```env
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_EMBEDDING_API_VERSION=2023-12-01-preview
```

**PostgreSQL**
```env
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_DB=docforge
POSTGRES_USER=docforge
POSTGRES_PASSWORD=your_secure_password
```

**Redis**
```env
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
```

**Notion**
```env
NOTION_API_TOKEN=your_notion_integration_token
NOTION_DATABASE_ID=your_docforge_database_id
```

**Optional Parameters**
```env
CHROMA_DATA_PATH=./chroma_data
ENABLE_ARCHIVE=false
ARCHIVE_MAX_VERSIONS=10
INGEST_POLL_INTERVAL=900
```

### Database Schemas

#### PostgreSQL - documents table
```sql
CREATE TABLE documents (
  id          SERIAL PRIMARY KEY,
  title       TEXT NOT NULL,
  version     INTEGER DEFAULT 1,
  parent_id   INTEGER REFERENCES documents(id),
  doc_type    TEXT DEFAULT 'General',
  doc_format  TEXT DEFAULT 'word',
  content     JSONB DEFAULT '{}',
  file_bytes  BYTEA,
  file_ext    TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_title_version ON documents(title, version);
CREATE INDEX idx_parent_id ON documents(parent_id);
```

#### PostgreSQL - assistant_state table
```sql
CREATE TABLE assistant_state (
  id           SERIAL PRIMARY KEY,
  thread_id    TEXT UNIQUE NOT NULL,
  user_id      TEXT,
  industry     TEXT,
  doc_filters  JSONB,
  messages     JSONB NOT NULL,
  intent       TEXT,
  ticket_id    TEXT,
  trace_id     TEXT,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_thread_id ON assistant_state(thread_id);
CREATE INDEX idx_user_id ON assistant_state(user_id);
CREATE INDEX idx_updated_at ON assistant_state(updated_at DESC);
```

#### ChromaDB Collection - document_chunks
**Metadata stored with each chunk:**
```python
{
  "doc_title": str,           # From Notion page title
  "doc_type": str,            # "Report", "Financial", "Strategy", etc.
  "version": int,             # Document version number
  "industry": str,            # "Finance", "Technology", "Healthcare", etc.
  "section_name": str,        # Document section/heading
  "notion_page_id": str,      # UUID of source Notion page
  "notion_url": str,          # Full page URL for citations
  "ingested_at": timestamp    # When indexed
}
```

**Vector Database Configuration:**
- Model: text-embedding-3-large (3072 dimensions)
- Similarity: cosine
- Chunking: 500 char size, 50 char overlap
- Persistence: ./chroma_data/

### Cache Configuration

**Multi-Tier Caching Strategy:**

| Layer | Storage | TTL | Data | Purpose |
|-------|---------|-----|------|---------|
| L1 | Redis | 30 min | Conversation state | Active sessions |
| L2 | Redis | 10 sec | Concurrency locks | Write coordination |
| L3 | Redis | 30 min | Last 10 messages | Context window |
| L4 | PostgreSQL | ∞ | Full state | Permanent record |

**P1 DocForge Caching:**
- Plans: cached 1 week (keyed by prompt hash)
- Questions: cached 1 week (keyed by title + sections hash)
- Generated content: cached 1 week (keyed by title + sections + format hash)

**P2 CiteRAG Caching:**
- Search results: cached 24 hours
- Q&A answers: cached 24 hours
- Document comparisons: cached 24 hours

**P3 Assistant Caching:**
- Conversation state: 30 min (Redis)
- Full history: permanent (PostgreSQL)
- Context windows: 30 min (Redis, last 10 messages)

## 📚 Development & Architecture

### Project Structure

```
FullProject/
├── backend/
│   ├── services/
│   │   ├── p1/                      # DocForge: Document Generation
│   │   │   ├── planner.py           # Function: plan_document()
│   │   │   ├── question.py          # Function: generate_questions()
│   │   │   ├── generator.py         # Function: generate_document_sections()
│   │   │   ├── excel_generator.py   # Functions: generate_excel_sections(), refine_excel_section()
│   │   │   ├── refinement.py        # Function: refine_section()
│   │   │   ├── excel_exporter.py    # Function: generate_excel_file()
│   │   │   ├── notion.py            # Functions: push_to_notion(), update_notion_page()
│   │   │   ├── redis.py             # Class: RedisService (caching + rate limiting)
│   │   │   └── orchestrator.py      # Class: DocumentOrchestrator (P1 wrapper)
│   │   │
│   │   ├── p2/                      # CiteRAG: RAG Q&A
│   │   │   ├── for_ingestion.py     # Functions: ingest_notion(), embed_batch()
│   │   │   ├── for_retrieval.py     # Functions: search(), search_multi_query()
│   │   │   ├── for_qa.py            # Functions: ask(), refine_answer()
│   │   │   ├── for_comparison.py    # Function: compare_documents()
│   │   │   ├── for_evaluation.py    # Function: run_evaluation()
│   │   │   ├── qa_log.py            # Functions: log_qa(), fetch_qa_log()
│   │   │   └── (helpers)
│   │   │
│   │   ├── p3/                      # Assistant: Stateful Conversation
│   │   │   ├── for_state.py         # Functions: new_state(), add_message(), save_state()
│   │   │   ├── for_memory.py        # Dual-tier memory: cache_state(), persist_state()
│   │   │   ├── for_graph.py         # Function: run_turn() + LangGraph definition
│   │   │   ├── nodes.py             # Node implementations (8+ nodes)
│   │   │   │                         #   - check_ticket_decision()
│   │   │   │                         #   - classify_intent()
│   │   │   │                         #   - ask_clarification()
│   │   │   │                         #   - retrieve()
│   │   │   │                         #   - check_sufficiency()
│   │   │   │                         #   - generate_answer()
│   │   │   │                         #   - post_answer_check()
│   │   │   │                         #   - ask_create_ticket()
│   │   │   │                         #   - create_ticket_node()
│   │   │   ├── for_tickets.py       # Functions: fetch_tickets(), update_ticket_status()
│   │   │   └── assistant_log.py     # Function: fetch_assistant_log()
│   │   │
│   │   └── langchain.py             # Global Azure OpenAI LLM instance
│   │
│   ├── chroma_db.py                 # ChromaDB interface + SQLite eval storage
│   ├── database.py                  # PostgreSQL interface (documents, state)
│   └── __init__.py
│
├── frontend/
│   └── mainstream.py                # Streamlit UI (multiple tabs)
│
├── main.py                          # FastAPI application + routes
├── requirements.txt                 # Python dependencies
├── docker-compose.yml               # Docker services (PostgreSQL, Redis, API, UI)
├── Dockerfile                       # Container definition
├── .env.example                     # Environment template
└── README.md                        # This file
```

### Key Backend Functions & Modules

**Phase 1 (DocForge) - Document Generation:**
- `plan_document(prompt: str)` → Generate outline structure
- `generate_questions(title, sections)` → Create input questions
- `generate_document_sections(title, sections, answers, show_headings)` → Generate content
- `refine_section(section_name, original_text, feedback)` → Improve section
- `generate_excel_file(content_dict)` → Export to Excel
- `push_to_notion(title, doc_format, content, ...)` → Sync to Notion
- `RedisService.cache_*()` & `RedisService.get_cached_*()` → Caching

**Phase 2 (CiteRAG) - Q&A & Retrieval:**
- `ingest_notion(page_ids?, force?)` → Fetch → chunk → embed → ChromaDB
- `search(query, top_k, filters)` → Semantic search
- `ask(question, top_k, filters)` → RAG-based Q&A with citations
- `refine_answer(question, answer, feedback, sources)` → Answer refinement
- `compare_documents(title_a, title_b, focus)` → Document comparison
- `run_evaluation(questions, config)` → RAGAS evaluation

**Phase 3 (Assistant) - Stateful Conversation:**
- `run_turn(user_message, thread_id?, user_id?, filters?, industry?)` → Main entry point
- `classify_intent(state)` → Classify user intent (LangGraph node)
- `retrieve(state)` → Semantic search (LangGraph node)
- `generate_answer(state)` → LLM response generation (LangGraph node)
- `ask_create_ticket(state)` → Offer ticket creation (LangGraph node)
- `create_ticket_node(state)` → Create Notion ticket (LangGraph node)
- `restore_state(thread_id)` / `persist_state(state)` → State management

### Frontend Components (Streamlit)

**Pages/Tabs:**
1. **Overview** — Dashboard with status, recent activity
2. **Generate** — Document generation workflow (plan → questions → generate → refine)
3. **Retrieve** — Search documents + semantic search interface
4. **Ask** — Q&A interface with follow-ups and refinement
5. **Manage** — Document versioning, deletion, downloads
6. **Settings** — Cache management, ingestion status, evaluation runs

**Key Session State Variables:**
```python
st.session_state = {
  "current_page": str,
  "thread_id": str,
  "doc_plan": dict,
  "doc_sections": list,
  "user_answers": dict,
  "generated_content": dict,
  "asst_messages": list,
  "search_results": list,
  # ... + 20+ more
}
```

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest

# Run specific test suites
pytest tests/test_p1/           # DocForge tests
pytest tests/test_p2/           # CiteRAG tests
pytest tests/test_p3/           # Assistant tests

# Run with coverage
pytest --cov=backend --cov=frontend

# Run specific test
pytest tests/test_p1/test_generation.py::test_generate_document_sections
```

### Code Quality Standards

```bash
# Format code with Black
black backend/ frontend/ main.py

# Lint with Flake8
flake8 backend/ frontend/ main.py --max-line-length=100

# Type checking with MyPy
mypy backend/ frontend/ main.py --ignore-missing-imports

# Security scanning
bandit -r backend/ frontend/
```

### Key Constants & Performance Thresholds

| Constant | Value | Module | Purpose |
|----------|-------|--------|---------|
| `MIN_CHUNKS` | 2 | nodes.py | Minimum chunks for answer sufficiency |
| `MIN_AVG_SCORE` | 0.35 | nodes.py | Minimum cosine similarity threshold |
| `CLARIFY_THRESHOLD` | 0.6 | nodes.py | Intent confidence for clarification |
| `CHUNK_SIZE` | 500 | for_ingestion.py | Characters per chunk |
| `CHUNK_OVERLAP` | 50 | for_ingestion.py | Character overlap between chunks |
| `INGEST_POLL_INTERVAL` | 900 | main.py | Seconds (15 min) between polls |
| `STATE_TTL` | 1800 | for_memory.py | Seconds (30 min) Redis state cache |
| `LOCK_TTL` | 10 | for_memory.py | Seconds: thread write lock |
| `CTX_WINDOW` | 10 | for_memory.py | Messages in context cache |
| `REFINE_RATE_LIMIT` | 5/hour | redis.py | Refines per section per hour |

## 🤝 Contributing

We welcome contributions! Here's how to get involved:

### Getting Started

1. **Fork the repository**
   ```bash
   git clone https://github.com/yourusername/FullProject.git
   cd FullProject
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-amazing-feature
   ```

3. **Set up development environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # pytest, black, flake8, mypy
   ```

4. **Make your changes**
   - Follow the project structure
   - Add type hints to all functions
   - Write descriptive commit messages

5. **Test your changes**
   ```bash
   pytest tests/
   black . && flake8 . && mypy .
   ```

6. **Submit a Pull Request**
   ```bash
   git commit -m "feat: add amazing feature"
   git push origin feature/your-amazing-feature
   ```

### Development Guidelines

**Code Standards:**
- PEP 8 compliance (enforced by Black + Flake8)
- Type hints on all functions (str, int, dict, list, etc.)
- Docstrings for public functions and classes
- Max line length: 100 characters
- Use f-strings for string formatting

**Commit Message Convention:**
```
feat:     new feature
fix:      bug fix
docs:     documentation
refactor: code refactoring
test:     adding/updating tests
perf:     performance improvement
chore:    build/dependency updates
```

**Pull Request Checklist:**
- [ ] Tests pass (`pytest tests/`)
- [ ] Code formatted (`black .`)
- [ ] Linted (`flake8 .`)
- [ ] Type checked (`mypy .`)
- [ ] Documentation updated
- [ ] No breaking changes (or documented migration)

### Adding New Features

**For DocForge (P1):**
1. Add function to `backend/services/p1/`
2. Add Redis caching if applicable
3. Add corresponding POST/GET route to `main.py`
4. Update FastAPI docs in docstring
5. Add tests to `tests/test_p1/`

**For CiteRAG (P2):**
1. Add function to `backend/services/p2/`
2. Update ChromaDB schema if needed
3. Add logging to Notion if applicable
4. Add route to `main.py`
5. Add tests to `tests/test_p2/`

**For Assistant (P3):**
1. Add node function to `backend/services/p3/nodes.py`
2. Update LangGraph in `backend/services/p3/for_graph.py`
3. Update AssistantState if adding new fields
4. Add tests to `tests/test_p3/`

### Reporting Bugs

When reporting bugs, include:
1. Clear title and description
2. Steps to reproduce
3. Expected vs actual behavior
4. Environment (OS, Python version, Docker version)
5. Logs and error messages
6. Screenshots (if UI-related)

---

## 🆘 Troubleshooting

### Common Issues & Solutions

**Issue: "Connection refused" for Redis/PostgreSQL**
```bash
# Check if Docker containers are running
docker-compose ps

# If not running, start them
docker-compose up -d

# Check logs
docker-compose logs redis
docker-compose logs db
```

**Issue: "AZURE_OPENAI_API_KEY not found"**
```bash
# Verify .env file exists and is in project root
ls -la .env

# Check if variables are loaded
python -c "import os; print(os.getenv('AZURE_OPENAI_API_KEY'))"

# Make sure backend reads from .env
source .env
```

**Issue: Notion integration not working**
```bash
# Verify Notion token is valid
curl -H "Authorization: Bearer YOUR_TOKEN" https://api.notion.com/v1/users/me

# Check database ID format (should be valid UUID)
# Check that integration is added to database (share settings)
```

**Issue: Embeddings failing with 404 errors**
```bash
# Verify deployment name matches your Azure setup
# Check Azure OpenAI service status
# Ensure embedding model is text-embedding-3-large
```

**Issue: LangGraph or threading issues**
```bash
# Check that threads are properly cleaned up
import gc; gc.collect()

# Verify state persistence
SELECT COUNT(*) FROM assistant_state;

# Check Redis locks aren't stuck
redis-cli KEYS "lock:*"
```

### Performance Troubleshooting

**Slow Q&A responses:**
1. Check ChromaDB collection size: `chroma_data/` directory
2. Verify embedding batch efficiency
3. Check PostgreSQL query performance: `EXPLAIN ANALYZE`
4. Monitor Redis memory usage: `redis-cli INFO memory`
5. Consider adding metadata filters to narrow search space

**High latency on document generation:**
1. Check Azure OpenAI API latency
2. Verify network connectivity to Azure
3. Check local machine resources (CPU, memory)
4. Review LLM prompt complexity
5. Consider increasing parallelization

**Redis cache not improving performance:**
1. Verify Redis is connected: `redis-cli ping`
2. Check cache hit rate: `info stats`
3. Monitor TTL expiration
4. Ensure cache keys are consistent
5. Review invalidation logic

### Debugging Tips

**Enable verbose logging:**
```python
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.debug(f"State: {state}")
```

**Inspect API responses:**
```bash
# FastAPI server running at 8080
curl -X POST http://localhost:8080/rag/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 5}'

# View interactive API docs
open http://localhost:8080/docs
```

**Database inspection:**
```bash
# PostgreSQL
psql -h localhost -U docforge -d docforge -c "SELECT * FROM assistant_state LIMIT 5;"

# Redis
redis-cli KEYS "*"
redis-cli GET "plan:{hash}"
```

**Check ChromaDB:**
```python
from backend.chroma_db import get_chroma
collection = get_chroma()
print(f"Collection count: {collection.count()}")
```

---

## 📋 License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## 🙋 Support & Contact

### Getting Help

**Documentation:**
- Check the [API Documentation](http://localhost:8080/docs) after starting the server
- Review [Architecture section](#-system-architecture) for system overview
- See [Workflows & Usage](#-detailed-workflows--usage) for detailed flows

**Reporting Issues:**
- GitHub Issues: [Create an issue](https://github.com/yourusername/FullProject/issues)
- Include environment info, reproduction steps, and error logs

**Community:**
- Discussions: GitHub Discussions (coming soon)
- Questions: Tag as "question" when creating issues

### Key Resources

- **API Reference**: Start the backend and visit `/docs`
- **FastAPI ReDoc**: Start the backend and visit `/redoc`
- **Code Examples**: See Workflow sections above
- **Database Schemas**: See [Configuration & Environment](#⚙️-configuration--environment)

---

## 🚀 Roadmap

### Near Term (Q2 2026)
- [ ] Multi-language document generation
- [ ] Advanced document templates (proposal, RFP, etc.)
- [ ] Batch document processing
- [ ] Performance optimizations for large document sets

### Mid Term (Q3-Q4 2026)
- [ ] Real-time collaboration on documents
- [ ] Integration with additional document sources (Google Drive, SharePoint)
- [ ] Enhanced evaluation metrics (BLEU, ROUGE)
- [ ] Advanced fine-tuning for domain-specific content
- [ ] Webhook support for event-driven workflows

### Long Term (2027+)
- [ ] Voice interface for the assistant
- [ ] Mobile application (iOS/Android)
- [ ] On-premise deployment options
- [ ] Advanced RAG with knowledge graphs
- [ ] Multi-modal document support (images, tables)
- [ ] Semantic document clustering & discovery
- [ ] Automated ticket routing & assignment

### Current Tracking
- Track progress in [Discussions](https://github.com/yourusername/FullProject/discussions) or Project board
- Community requests welcome via GitHub issues