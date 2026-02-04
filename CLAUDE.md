# CLAUDE.md

This file provides context for Claude Code when working on this project.

## Project Overview

FIH Rules Engine is a production-ready **Retrieval-Augmented Generation (RAG) system** providing expert-level clarity on International Hockey Federation (FIH) rules for Outdoor, Indoor, and Hockey5s variants. It's a cloud-native headless API designed for third-party integration.

## Architecture

**Dual-Core Architecture**:
- **Public API** (`api.py`): FastAPI REST service for RAG queries
- **Admin Dashboard** (`Query.py` + `pages/`): Streamlit app for rule ingestion and metrics

**Key Components**:
| File | Purpose |
|------|---------|
| `rag_engine.py` | Core RAG logic (`FIHRulesEngine` class) - shared by both cores |
| `database.py` | PostgreSQL + pgvector data layer |
| `config.py` | Environment configuration (GCP, DB, models) |
| `prompts.py` | Centralized system prompts |
| `loaders/` | Vertex AI document ingestion logic |
| `evals/` | RAGAS evaluation pipeline |
| `pages/` | Admin UI pages (Knowledge Base, Evals) |

## Tech Stack

- **Compute**: Google Cloud Run (serverless)
- **Database**: Cloud SQL PostgreSQL with `pgvector` (semantic) + FTS (keyword)
- **LLM**: Vertex AI Gemini 2.0 Flash Lite
- **Embeddings**: Vertex AI `text-embedding-004`
- **Reranking**: Vertex AI Ranking API (cross-encoder)
- **Document Parsing**: Document AI
- **Retrieval**: Hybrid search with Reciprocal Rank Fusion (RRF)

## Development Commands

```bash
# Setup
python3 -m venv .venv
source .venv/bin/activate
make install          # Production deps
make dev-install      # Full deps (admin + evals)

# Development
make api              # Run public API (port 8000)
make admin            # Run admin dashboard (port 8501)

# Quality
make fmt              # Format with black
make lint             # Lint with ruff
make test             # Run pytest

# Operations
make evals            # Run RAGAS evaluation
make db-clean         # Truncate vector tables
make ingest-preview   # Preview ingestion pipeline
```

**Important**: Always activate the venv before running commands:
```bash
source .venv/bin/activate && make fmt lint test
```

## Coding Guidelines

- Python 3.10+, 4-space indent, PEP 8
- Format/lint with `black` and `ruff`
- Strict separation: Public API vs Admin logic; shared code goes in `rag_engine.py`
- Never hardcode secrets - use `config.py` which reads `os.getenv`
- `requirements.txt` = prod deps, `requirements-dev.txt` = dev/admin deps

## Architectural Invariants

1. `api.py` must remain pure REST/FastAPI - no HTML serving
2. Admin (`Query.py`) and Public (`api.py`) deploy separately as distinct containers
3. Secrets via environment variables only
4. Two Dockerfiles: `Dockerfile` (public), `Dockerfile.admin` (admin)

## Key Features

- **Variant-Aware**: Auto-detects Outdoor/Indoor/Hockey5s context
- **Local Jurisdictions**: Supports national appendices (e.g., `country: "BEL"`)
- **Two-Pass Formatting**: Answers structured as Direct Answer + Key Rules + Reasoning
- **Hybrid Search**: RRF combining pgvector cosine similarity + PostgreSQL FTS
- **Verifiable Citations**: References rule numbers and source pages

## Testing

- Unit tests: `pytest` in `tests/`
- Evaluation: `evals/evaluate.py` with RAGAS metrics + LLM-as-a-Judge
- Golden dataset: `evals/generated_dataset.json`

## Deployment

See `deployment.md` for full GCP setup. Key points:
- Cloud Run requires **2GiB memory, 1 CPU** minimum
- Use `--update-env-vars` for incremental changes (not `--set-env-vars`)
- Admin uses Cloud Build (`cloudbuild.admin.yaml`) for custom Dockerfile
