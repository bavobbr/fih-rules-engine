# FIH Rules Engine

A production-ready Retrieval-Augmented Generation (RAG) system providing expert-level clarity on **International Hockey Federation (FIH) Rules** for Outdoor, Indoor, and Hockey5s.

## 🚀 Overview

The FIH Rules Engine is a cloud-native headless API designed for integration into third-party applications. It transforms official PDF rulebooks into an interactive, variant-aware AI assistant.

- **Instant Clarification**: Natural language query processing via REST API.
- **Variant-Aware**: Automatic detection of Outdoor, Indoor, or Hockey5s contexts.
- **Verifiable Citations**: Reliable references to rule numbers and source pages.
- **Admin Dashboard**: Secure interface for rule ingestion and performance evaluation.

---

## 🏛️ Architecture

The system follows a **Dual-Core Architecture**, separating the public-facing API from internal administrative tools.

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Public API** | **FastAPI** | Headless RAG service (REST) used by external clients. |
| **Admin Dashboard** | **Streamlit** | Internal tool for rule ingestion and metrics. |
| **Ingestion** | **Vertex AI + DocAI** | Structural parsing and AI-driven enrichment. |
| **Hybrid Search** | **Postgres (FTS + pgvector)** | Multi-stage retrieval combining semantic and keyword search via RRF. |
| **Reranker** | **Vertex AI Ranking** | Cross-encoder reranking to optimize context relevance. |
| **Reasoning** | **Gemini 2.0 Flash Lite** | State-of-the-art LLM for synthesis and reasoning. |

### 🛠️ The Architectural Stack

The engine is built on a "Lean-Core" principle, minimizing long-running state while leveraging Google's powerful AI infrastructure:

*   **Serverless Compute**: **Google Cloud Run** hosts both the API and Admin containers. It scales dynamically, ensuring costs only scale with usage.
*   **Vectorized & Full-Text Storage**: **Cloud SQL (PostgreSQL)** serves a dual purpose: semantic search via `pgvector` and exact keyword matching via PostgreSQL's Full Text Search (FTS).
*   **Hybrid Retrieval**: The system uses **Reciprocal Rank Fusion (RRF)** to combine vector similarity with keyword relevance, ensuring pinpoint accuracy for technical terms and rule numbers.
*   **Intelligent Reranking**: **Vertex AI Ranking API** acts as a cross-encoder, re-ordering retrieved documents to ensure the most relevant context is prioritized for the LLM.
*   **AI Orchestration**: **Vertex AI** powers the entire reasoning loop, from structural document analysis and embedding generation to the final context-aware answer synthesis.
*   **Infrastructure-as-a-Service**: **Document AI** and **Cloud Storage** are used as high-fidelity tools during the administrative ingestion phase to transform raw PDFs into structured knowledge.

---

## 🔄 System Flows

### Ingestion Pipeline (Sequence)
The interaction between the Admin Dashboard, Core Engine, and Google Cloud services.

```mermaid
sequenceDiagram
    participant Admin as Admin Dashboard
    participant Engine as RAG Engine
    participant GCS as Google Cloud Storage
    participant Vertex as Vertex AI (Gemini)
    participant DocAI as Document AI
    participant DB as Cloud SQL (Postgres)

    Admin->>Engine: ingest_pdf(file, variant)
    Engine->>Vertex: analyze_structure(pdf)
    Vertex-->>Engine: Structural Map
    Engine->>Engine: Filter Relevant Pages
    Engine->>GCS: Upload Filtered PDF
    Engine->>DocAI: batch_process(gcs_uri)
    DocAI-->>GCS: JSON Shards
    GCS-->>Engine: Fetch Results
    Engine->>Engine: Semantic Chunking & Summarization
    Note over Engine, DB: Idempotent Variant Overwrite
    Engine->>DB: delete_variant(variant)
    Engine->>Vertex: embed_documents(chunks)
    Vertex-->>Engine: Vectors
    Engine->>DB: insert_batch(vectors, variant)
    Note right of DB: Single Table Isolation
    Engine-->>Admin: Success (Chunk Count)
```

### Query Flow (Sequence)
How a visitor query is processed through the headless API.

```mermaid
sequenceDiagram
    participant Client as External Client
    participant API as Public API (FastAPI)
    participant Engine as RAG Engine
    participant Vertex as Vertex AI (Gemini)
    participant Rank as Vertex AI Ranking
    participant DB as Cloud SQL (Postgres)

    Client->>API: POST /chat {query}
    API->>Engine: query(text, history)
    Engine->>Vertex: _contextualize_query(history)
    Vertex-->>Engine: Standalone Question
    Engine->>Vertex: _route_query(question)
    Vertex-->>Engine: Variant (e.g. "indoor")
    Engine->>Vertex: embed_query(clean_question)
    Vertex-->>Engine: Vector
    Engine->>DB: search_hybrid(question, vector)
    Note over DB: Semantic (pgvector) + Keyword (FTS)
    DB-->>Engine: Ranked Candidates (RRF)
    Engine->>Rank: rank(question, candidates)
    Rank-->>Engine: Re-ordered Top Context
    Engine->>Vertex: Generate Answer (Context + Question)
    Vertex-->>Engine: Expert Response
    Engine-->>API: Result Object
    API-->>Client: 200 OK {answer, sources}
```

---

## 🔍 Hybrid Search Architecture

The engine uses a sophisticated two-stage retrieval process powered by advanced PostgreSQL features to ensure both semantic breadth and keyword precision.

### 1. The PostgreSQL Multi-Lens System
Every document chunk is indexed twice within a single row:
*   **Semantic Lens (`pgvector`)**: Stores high-dimensional embeddings. We use the `<=>` cosine distance operator for lightning-fast similarity lookups based on meaning.
*   **Keyword Lens (`tsvector`)**: Stores a pre-computed lexicon of the content and metadata (rules, rule numbers). We use a **GIN Index** to make keyword lookups near-instantaneous.

### 2. Reciprocal Rank Fusion (RRF)
To combine these two different types of scores (vector distances vs. keyword ranks), we use the **Reciprocal Rank Fusion** algorithm. 

Inside a single SQL transaction using **Common Table Expressions (CTEs)**:
1.  **Recall**: Two parallel searches are performed (Vector and Full-Text).
2.  **Scoring**: Each result is given a score based on its rank: `1.0 / (rank + 60)`.
3.  **Fusion**: Results appearing in both lists get their scores summed, naturally surface chunks that are both semantically relevant and contain exact keyword matches.

### 3. Intelligent Reranking
Finally, the **Vertex AI Ranking API** acts as a cross-encoder judge. It takes the top candidates from the hybrid search and performs a deep analysis of the relationship between the query and the document content, filtering the most vital context for the LLM.

---

## 🛠️ Getting Started

### Prerequisites
- Python 3.10+
- Google Cloud CLI authenticated (`gcloud auth application-default login`)

### Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
make install        # Production dependencies (Public Core only)
make dev-install    # Full dependencies (Admin + Evals + Dev)
```

### Local Development
- **Run Public API**: `make api` (Headless REST backend on port 8000)
- **Run Admin Dashboard**: `make admin` (Ingestion & Metrics on port 8501)

---

## 🧑‍💻 Operations & Maintenance

The Admin Dashboard (`make admin`) provides a specialized interface for:
- **Knowledge Ingestion**: Upload rule PDFs and map them to a variant. 
- **Automated Overwrites**: Ingesting a ruleset automatically replaces any existing data for that variant.
- **Performance Monitoring**: Visualizes RAGAS metrics and query traces.

Maintenance targets:
- `make db-clean`: Securely truncates the vector database tables.
- `make ingest-preview`: Runs a preview of the Vertex AI ingestion pipeline.
- `make evals`: Executes the RAGAS-based evaluation suite.

---

## ☁️ Deployment (Google Cloud Run)

The project is designed for serverless deployment on **Google Cloud Run**. 

Detailed, step-by-step instructions for project initialization, API activation, and final deployment (including custom Cloud Build configurations) can be found in the:

👉 **[Infrastructure Setup Guide (deployment.md)](file:///home/bavobbr/dev/fih-rules-engine/deployment.md)**

---

## 📊 Evaluation & Quality

Accuracy is verified through a synthetic evaluation pipeline:
- **RAGAS Metrics**: Faithfulness, Relevancy, Precision, and Recall.
- **LLM-as-a-Judge**: Custom scoring against curated golden datasets.
- **CI/CD Integration**: Recommended to run `make test` and `make evals` before any deployment.
