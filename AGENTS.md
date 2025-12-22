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
- `Dockerfile` – Container for the Headless Public API.
- `Dockerfile.admin` – Container for the Admin Dashboard.

## Google Cloud Infrastructure

The project interacts with the following GCP services:

| Category | Service | Technical Role |
| :--- | :--- | :--- |
| **Compute** | **Cloud Run** | Managed serverless hosting for `fih-rules-api` and `fih-rules-admin`. |
| **Storage** | **Cloud SQL** | Postgres instance with `pgvector` for localized semantic search. |
| **AI (LLM)** | **Vertex AI** | Gemini 2.0 Flash Lite for reasoning, routing, and synthesis. |
| **AI (Embeds)**| **Vertex AI** | `text-multilingual-embedding-002` for generating vector representations. |
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

## Coding Style
- Python 3.10+, 4-space indentation, PEP 8.
- Use `black` and `ruff` for formatting and linting (`make fmt`, `make lint`).
- Maintain strict separation between the Public API and Admin logic. Shared logic belongs in `rag_engine.py` or sub-modules in `loaders/`.

## Deployment
The project builds two separate container images:
- `app-public`: Contains `api.py` and the core RAG engine logic.
- `app-admin`: Contains `Query.py`, `evals/`, and admin utilities.
