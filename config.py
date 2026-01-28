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

TOP_50_NATIONS = {
    "International (Official)": None,
    "Argentina": "ARG", "Australia": "AUS", "Austria": "AUT", "Bangladesh": "BAN",
    "Belarus": "BLR", "Belgium": "BEL", "Brazil": "BRA", "Canada": "CAN",
    "Chile": "CHI", "China": "CHN", "Chinese Taipei": "TPE", "Croatia": "CRO",
    "Cuba": "CUB", "Czech Republic": "CZE", "Egypt": "EGY", "England": "ENG",
    "Finland": "FIN", "France": "FRA", "Germany": "GER", "Ghana": "GHA",
    "Guatemala": "GUA", "Hong Kong": "HKG", "India": "IND", "Ireland": "IRL",
    "Italy": "ITA", "Japan": "JPN", "Korea": "KOR", "Malaysia": "MAS",
    "Mexico": "MEX", "Netherlands": "NED", "New Zealand": "NZL", "Nigeria": "NGR",
    "Oman": "OMA", "Pakistan": "PAK", "Poland": "POL", "Russia": "RUS",
    "Scotland": "SCO", "South Africa": "RSA", "Spain": "ESP", "Sri Lanka": "SRI",
    "Switzerland": "SUI", "Thailand": "THA", "Trinidad & Tobago": "TTO",
    "Turkey": "TUR", "Ukraine": "UKR", "United States": "USA", "Uruguay": "URU",
    "Wales": "WAL", "Zimbabwe": "ZIM"
}
