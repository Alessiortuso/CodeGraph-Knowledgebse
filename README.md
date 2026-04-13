# Knowledge Base — AI-Powered Code Intelligence

A RAG system that transforms Git repositories into a queryable knowledge base. Ask questions about your codebase in natural language and get answers grounded in the actual code.

## How It Works

1. **Ingest** a Git repository — the system clones it, parses the code with AST (tree-sitter), extracts functions, classes, imports and call relationships, indexes commits, and stores everything in a graph database
2. **Ask** questions in natural language — the system retrieves relevant code snippets and commit history using hybrid search (vector + keyword + graph traversal)
3. **Get answers** synthesized by a local LLM, based exclusively on the actual code

## Features

- AST parsing for Python, Java, JavaScript
- Graph database (Memgraph) with nodes for folders, files, functions, classes, commits
- Hybrid search: HNSW vector search + keyword search + `:calls` graph traversal
- Incremental ingestion — on subsequent runs, only changed files are re-processed
- Pattern detection: architectural patterns, naming conventions, external dependencies
- Onboarding report generator for new team members
- 100% local — no data leaves your machine (Ollama + Memgraph)
- REST API with Swagger UI

## Requirements

- [Docker](https://www.docker.com/) and Docker Compose
- [Ollama](https://ollama.com/) running locally with the following models:

```bash
ollama pull nomic-embed-text   # embeddings
ollama pull llama3.2:3b        # query planner
ollama pull llama3             # answer synthesis
```

## Quick Start

**1. Clone the repository**
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

**2. Configure environment**
```bash
cp .env.example .env
# Edit .env if needed (default values work out of the box with Docker)
```

**3. Start the stack**
```bash
docker-compose up -d --build
```

**4. Check everything is running**
```bash
docker ps   # memgraph_db, memgraph_lab and software_analyzer_app should be "Up"
```

**5. Open the API**

Go to [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive Swagger UI.

## Usage

### Ingest a repository

```
POST /ingest?url=https://github.com/owner/repo.git&name=MY_PROJECT
```

For private repositories (e.g. Azure DevOps), include your PAT in the URL:
```
POST /ingest?url=https://<PAT>@dev.azure.com/org/project/_git/repo&name=MY_PROJECT
```

Wait for the response — ingestion is synchronous. Large repositories may take a few minutes.

### Ask a question

```
GET /ask?question=How does the ingestion work?&project=MY_PROJECT
```

### Other endpoints

| Endpoint | Description |
|---|---|
| `GET /projects` | List all ingested projects |
| `GET /onboarding?project=X` | Generate an onboarding report |
| `GET /patterns?project=X` | Show detected architectural patterns |
| `PUT /update?project=X` | Re-ingest a project (incremental) |

## Configuration

All configuration is done via environment variables (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `MEMGRAPH_HOST` | `memgraph` | Memgraph hostname |
| `MEMGRAPH_PORT` | `7687` | Memgraph port |
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama URL |
| `EMBED_MODEL` | `nomic-embed-text` | Embedding model (must produce 768-dim vectors) |
| `PLANNER_MODEL` | `llama3.2:3b` | Model for query classification |
| `SYNTHESIZER_MODEL` | `llama3` | Model for answer generation |

## Stack

| Component | Technology |
|---|---|
| API | FastAPI |
| Graph DB | Memgraph + MAGE |
| Vector search | HNSW (built into Memgraph via MAGE) |
| Code parsing | tree-sitter |
| LLM / Embeddings | Ollama (local) |
| Containerization | Docker Compose |

## Project Structure

```
├── ingestion/          # Git cloning, AST parsing, document processing
├── knowledge_graph/    # Graph client and builder (nodes, relations, indexes)
├── embeddings/         # Embedding generation via Ollama
├── query/              # Query planner, NSR retrieval, synthesizer, onboarding
├── analytics/          # Commit analysis, hotspot detection, pattern detection
├── tests/              # Unit tests
├── main_api.py         # FastAPI application and endpoints
└── docker-compose.yml  # Memgraph + app stack
```

## Notes

- The `storage/` folder is created automatically to store cloned repositories and is excluded from version control
- Memgraph data is not persisted across `docker-compose down` by default — add a volume to `docker-compose.yml` if you need persistence
- For best results use a 7B+ model as `SYNTHESIZER_MODEL`
