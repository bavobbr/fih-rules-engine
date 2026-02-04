# Repository Guidelines

This guide helps contributors work efficiently in the FIH Rules Engine project.

## Project Structure & Module Organization

The project is structured around two logical cores: the **Public Core** (Headless API) and the **Admin Core** (Ingestion & Evals).

- `api.py` – **Public API** (FastAPI) providing the RAG engine via REST.
- `Query.py` – **Admin Dashboard** (Streamlit) for internal rule ingestion and maintenance.
- `rag_engine.py` – **Core Logic** orchestrating retrieval and synthesis. Shared by both cores.
- `database.py` – **Data Layer** for Cloud SQL / Postgres.
- `config.py` – **Configuration** for GCP projects, models, and DB parameters.
- `loaders/` – **Vertex AI Loader** logic for structural rule ingestion.
- `evals/` – **Evaluation Pipeline** for RAGAS metrics and dataset generation.
- `scripts/` – **Maintenance Scripts** (DB cleanup and ingestion previews).
- `pages/` – **Admin Pages** (Knowledge Base and metrics UI).
- `deployment.md` – **Infrastructure Guide** for detailed setup.
- `Dockerfile` – Container for the Headless Public API.
- `Dockerfile.admin` – Container for the Admin Dashboard.

## Google Cloud Infrastructure

The project interacts with the following GCP services:

| Category | Service | Technical Role |
| :--- | :--- | :--- |
| **Compute** | **Cloud Run** | Managed serverless hosting for `fih-rules-api` and `fih-rules-admin`. |
| **Storage** | **Cloud SQL** | Postgres with `pgvector` for semantic search and FTS for keyword search. |
| **AI (LLM)** | **Vertex AI** | Gemini 2.0 Flash Lite for reasoning, routing, and synthesis. |
| **AI (Embeds)**| **Vertex AI** | `text-embedding-004` for generating vector representations. |
| **Ranking** | **Discovery Engine** | Vertex AI Ranking API for cross-encoder reranking. |
| **Parsing** | **Document AI** | Layout analysis for accurate PDF-to-chunk transformation. |
| **Storage** | **Cloud Storage** | Persistent bucket for DocAI processing (configured via `GCS_BUCKET_NAME`). |
| **Build** | **Cloud Build** | Pipeline for building images from source. |

---

## Build and Operation Commands

### Setup
1. Create venv: `python3 -m venv .venv`
2. Source venv: `source .venv/bin/activate`
3. Install production deps: `make install`
4. Install dev/admin deps: `make dev-install`

### Development & Maintenance
- **Public API**: `make api`
- **Admin App**: `make admin`
- **Run Evals**: `make evals`
- **DB Cleanup**: `make db-clean`
- **Ingestion Preview**: `make ingest-preview`
- **Run Tests**: `make test`

## Deployment & Infrastructure Preferences

- **Build Pipeline**: Prefer **Cloud Build** for custom Dockerfiles. Standard `gcloud run deploy --source` only supports `Dockerfile`.
- **Compute Resources**: Python RAG services require **2GiB Memory** and **1 CPU** minimum to avoid OOM errors during ingestion and reasoning.
- **Environment Variables**: Use `--update-env-vars` for incremental updates. Avoid `--set-env-vars` unless a full reset is intended, as it overwrites existing variables.
- **Database Setup**: The application database `hockey_db` must exist on the Cloud SQL instance before the engine can initialize.
- **Security**:
    - Avoid special characters like `!` in passwords passed via shell to prevent expansion issues.
    - `GCP_PROJECT_ID` must be explicitly provided to distinguish between the runtime environment and the AI platform project.

## Coding Style
- Python 3.10+, 4-space indentation, PEP 8.
- Use `black` and `ruff` for formatting and linting (`make fmt`, `make lint`).
- Maintain strict separation between the Public API and Admin logic. Shared logic belongs in `rag_engine.py` or sub-modules in `loaders/`.

## Deployment
The project builds two separate container images:
- `app-public`: Contains `api.py` and the core RAG engine logic.
- `app-admin`: Contains `Query.py`, `evals/`, and admin utilities (built via `cloudbuild.admin.yaml`).

---

## 🧠 Agent Context & Workflows

**Context for AI Assistants (Antigravity/Gemini):** This section provides high-density information to reduce discovery time.

### ⚡ Critical Workflows
**ALWAYS activate the virtual environment** before running python scripts or make commands (unless using `make` which handles some paths, but explicit activation is safer).
```bash
source .venv/bin/activate
```

| Goal | Command Chain |
| :--- | :--- |
| **Verify Code** | `source .venv/bin/activate && make fmt lint test` |
| **Run API** | `make api` (Runs uvicorn with reload) |
| **Run Admin** | `make admin` (Runs Streamlit) |
| **Reset DB** | `make db-clean` (Truncates all vectors) |
| **Run Evals** | `make evals` (Runs RAGAS pipeline) |
| **Deploy API** | `gcloud run deploy ...` (See `deployment.md`) |

### 🗺️ Critical File Map
| Feature | Primary File(s) |
| :--- | :--- |
| **RAG Logic** | `rag_engine.py` (Core class `FIHRulesEngine`) |
| **Ingestion** | `loaders/` and `pages/2_Knowledge_Base.py` |
| **DB Layer** | `database.py` (Postgres + pgvector wrapper) |
| **Prompts** | `prompts.py` (Centralized system prompts) |
| **Config** | `config.py` (Env vars and constants) |
| **UI** | `api.py` (Public REST), `Query.py` (Admin Main), `pages/` (Admin features) |

### 🛡️ Architectural Invariants
1.  **Headless API**: `api.py` MUST remain pure REST/FastAPI. No HTML serving.
2.  **Dual-Core**: Admin features (`Query.py`) and Public features (`api.py`) are deployed separately. Shared logic goes in `rag_engine.py`.
3.  **Secrets**: NEVER hardcode API keys or DB passwords. Use `config.py` which reads `os.getenv`.
4.  **Deps**: Use `requirements.txt` for minimal prod deps, `requirements-dev.txt` for dev/admin tools.
