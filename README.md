# DocForgeHub

A unified AI-powered enterprise document generation and retrieval system that combines intelligent document creation with retrieval-augmented generation (RAG) capabilities and a conversational assistant.

## Overview

DocForgeHub integrates three complementary workflows:

- **DocForge (P1)**: AI-driven document generation through structured planning, questioning, and iterative refinement
- **CiteRAG (P2)**: Retrieval-Augmented Generation system for Q&A with cited sources from enterprise documents
- **Intelligent Assistant (P3)**: Stateful conversational assistant with memory and ticket creation capabilities

## Features

### Document Generation (DocForge)
- **AI Planning**: Generate structured document outlines from natural language prompts
- **Targeted Questioning**: Create specific questions for each document section
- **Content Generation**: AI-powered writing with support for prose and tabular content
- **Iterative Refinement**: User feedback loop for content improvement
- **Multi-format Export**: Generate Word documents and Excel spreadsheets
- **Notion Integration**: Sync generated documents with Notion databases
- **Version Control**: Track document versions with rollback capabilities

### Retrieval-Augmented Generation (CiteRAG)
- **Semantic Search**: Vector-based search over enterprise documents
- **Cited Q&A**: Answers with source citations and evidence
- **Metadata Filtering**: Search with filters by document type, industry, or title
- **Auto-Ingestion**: Automatic document ingestion from Notion with change detection
- **Evaluation Framework**: RAGAS-based evaluation of Q&A performance

### Intelligent Assistant
- **Multi-turn Conversations**: Stateful chat with conversation memory
- **Intent Classification**: Automatic classification of user queries
- **Contextual Retrieval**: Relevant document retrieval based on conversation context
- **Ticket Creation**: Automatic ticket generation for unresolved queries
- **Dual Memory System**: Redis for short-term caching, PostgreSQL for persistence

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend       │    │   External      │
│   (Streamlit)   │    │   (FastAPI)     │    │   Services      │
│                 │    │                 │    │                 │
│ • Doc Gen UI    │◄──►│ • P1: DocForge  │◄──►│ • Azure OpenAI  │
│ • RAG Q&A UI    │    │ • P2: CiteRAG   │    │ • Notion API    │
│ • Assistant Chat│    │ • P3: Assistant │    │ • PostgreSQL    │
│ • Doc Management│    │ • Orchestration │    │ • Redis         │
└─────────────────┘    └─────────────────┘    │ • ChromaDB      │
                                              └─────────────────┘
```

### Backend Components

#### Phase 1 (P1) - DocForge
- `planner.py`: Document outline generation
- `question.py`: Section-specific question generation
- `generator.py`: AI content writing
- `refinement.py`: Iterative content improvement
- `excel_generator.py`: Tabular content generation
- `notion.py`: Notion database synchronization
- `redis.py`: Caching and rate limiting

#### Phase 2 (P2) - CiteRAG
- `ingestion.py`: Document ingestion and chunking
- `retrieval.py`: Semantic search with metadata filters
- `qa.py`: RAG-based Q&A with citations
- `eval.py`: Performance evaluation
- `qa_log.py`: Interaction logging

#### Phase 3 (P3) - Assistant
- `state.py`: Conversation state management
- `memory.py`: Dual-tier memory system
- `graph.py`: LangGraph orchestration
- `nodes.py`: Conversation flow nodes
- `tickets.py`: Notion ticket creation
- `assistant_log.py`: Conversation logging

## Installation

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Azure OpenAI API access
- Notion API token

### Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd FullProject
   ```

2. **Configure environment variables**
   Create a `.env` file with the following variables:
   ```env
   # Azure OpenAI Configuration
   AZURE_OPENAI_API_KEY=your_api_key
   AZURE_OPENAI_ENDPOINT=your_endpoint
   AZURE_OPENAI_DEPLOYMENT=your_deployment
   AZURE_OPENAI_EMBEDDING_DEPLOYMENT=your_embedding_deployment
   AZURE_OPENAI_API_VERSION=2023-12-01-preview

   # Database Configuration
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=docforge
   POSTGRES_USER=docforge
   POSTGRES_PASSWORD=your_password

   # Redis Configuration
   REDIS_HOST=localhost
   REDIS_PORT=6379
   REDIS_DB=0
   REDIS_PASSWORD=

   # Notion Configuration
   NOTION_API_TOKEN=your_notion_token
   NOTION_DATABASE_ID=your_database_id

   # ChromaDB Configuration
   CHROMA_DATA_PATH=./chroma_data
   ```

3. **Start the services**
   ```bash
   docker-compose up -d
   ```

4. **Install Python dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Run the application**
   ```bash
   # Start the backend API
   python main.py

   # In another terminal, start the frontend
   streamlit run frontend/mainstream.py
   ```

6. **Access the application**
   - Frontend UI: http://localhost:8501
   - Backend API: http://localhost:8080
   - API Documentation: http://localhost:8080/docs

## Usage

### Document Generation
1. Navigate to the "Document Generation" tab in the Streamlit UI
2. Enter a document prompt (e.g., "Create a business plan for a tech startup")
3. Review the generated outline and answer section-specific questions
4. Generate content and optionally refine sections
5. Export to Word/Excel or sync to Notion

### RAG Q&A
1. Go to the "Q&A" tab
2. Enter a question about your documents
3. Optionally apply filters (document type, industry, etc.)
4. View the answer with source citations
5. Explore cited sources for additional context

### Intelligent Assistant
1. Access the "Assistant" tab
2. Start a conversation with natural language queries
3. The assistant maintains context across turns
4. If needed, it will create tickets for complex queries

## API Reference

### Document Generation Endpoints

#### POST /api/v1/generate-plan
Generate a document plan from a prompt.

**Request Body:**
```json
{
  "prompt": "Create a project proposal for a new software development initiative"
}
```

**Response:**
```json
{
  "plan_id": "uuid",
  "sections": [
    {
      "title": "Executive Summary",
      "description": "High-level overview of the project"
    }
  ]
}
```

#### POST /api/v1/generate-questions
Generate questions for document sections.

#### POST /api/v1/generate-content
Generate content for document sections.

#### POST /api/v1/refine-section
Refine a specific section based on feedback.

### RAG Endpoints

#### POST /api/v1/rag/search
Perform semantic search over documents.

#### POST /api/v1/rag/ask
Ask a question with RAG-based answering.

### Assistant Endpoints

#### POST /api/v1/assistant/chat
Send a message to the intelligent assistant.

#### GET /api/v1/assistant/history
Retrieve conversation history.

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key | Required |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL | Required |
| `AZURE_OPENAI_DEPLOYMENT` | GPT model deployment name | Required |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Embedding model deployment | Required |
| `POSTGRES_HOST` | PostgreSQL host | localhost |
| `POSTGRES_PORT` | PostgreSQL port | 5432 |
| `POSTGRES_DB` | Database name | docforge |
| `POSTGRES_USER` | Database user | docforge |
| `POSTGRES_PASSWORD` | Database password | Required |
| `REDIS_HOST` | Redis host | localhost |
| `REDIS_PORT` | Redis port | 6379 |
| `NOTION_API_TOKEN` | Notion API token | Required |
| `NOTION_DATABASE_ID` | Notion database ID | Required |

### Docker Services

The `docker-compose.yml` includes:
- **PostgreSQL**: Primary database for documents and state
- **Redis**: Caching and session management
- **API**: FastAPI backend service
- **UI**: Streamlit frontend service

## Development

### Project Structure
```
FullProject/
├── backend/
│   ├── services/
│   │   ├── p1/          # DocForge components
│   │   ├── p2/          # CiteRAG components
│   │   └── p3/          # Assistant components
│   ├── chroma_db.py     # Vector database interface
│   ├── database.py      # PostgreSQL interface
│   └── __init__.py
├── frontend/
│   └── mainstream.py    # Streamlit UI
├── chroma_data/         # ChromaDB persistence
├── main.py              # FastAPI application
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container definition
├── docker-compose.yml   # Service orchestration
└── README.md
```

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all tests
pytest

# Run specific test suites
pytest tests/test_p1/
pytest tests/test_p2/
pytest tests/test_p3/
```

### Code Quality
```bash
# Format code
black .

# Lint code
flake8 .

# Type checking
mypy .
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guidelines
- Add type hints to new functions
- Write tests for new features
- Update documentation for API changes
- Use conventional commit messages

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For support and questions:
- Create an issue in the GitHub repository
- Check the API documentation at `/docs`
- Review the logs in the Docker containers

## Roadmap

- [ ] Multi-language document generation
- [ ] Advanced document templates
- [ ] Real-time collaboration features
- [ ] Integration with additional document sources
- [ ] Enhanced evaluation metrics
- [ ] Voice interface for the assistant
- [ ] Mobile application