"""Centralized configuration for the FIH Rules RAG app.

Loads environment variables (from the OS and optionally .env) and exposes
typed constants for use across the codebase. Secrets such as DB_PASS are
required at runtime and not given insecure defaults.
"""

import os
try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:
    load_dotenv = None

# Load environment variables from a local .env if present
if load_dotenv:
    load_dotenv()

# Google Cloud & Infra
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "fih-rules-engine")
REGION = os.getenv("GCP_REGION", "europe-west1")

# Document AI 
DOCAI_PROCESSOR_ID = os.getenv("DOCAI_PROCESSOR_ID", "f232912f58695fe9")
DOCAI_LOCATION = os.getenv("DOCAI_LOCATION", "eu")

# Staging bucket for Document AI (Batch Processing)
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "fih-rag-staging-fih-rules-engine")

# Database (Cloud SQL Postgres)
INSTANCE_NAME = os.getenv("CLOUDSQL_INSTANCE", "fih-rag-db")
DATABASE_NAME = "hockey_db"
TABLE_NAME = "hockey_rules_vectors"
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS")  # Required; do not set a default here

# Model Config
EMBEDDING_MODEL = "text-embedding-004"
LLM_MODEL = "gemini-2.5-flash-lite"
RANKING_MODEL = "semantic-ranker-512@latest"
RETRIEVAL_K = 15
RANKING_TOP_N = 10

# Supported Variants (key = DB label, value = UI label)
VARIANTS = {
    "outdoor": "Outdoor Hockey",
    "indoor": "Indoor Hockey",
    "hockey5s": "Hockey 5s"
}

# Logging
# Valid values: "JSON" (default), "HUMAN"
LOG_FORMAT = os.getenv("LOG_FORMAT", "JSON").upper()
