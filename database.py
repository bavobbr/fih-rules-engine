"""Minimal data access layer for Cloud SQL (Postgres + pgvector).

Creates a SQLAlchemy pool via the Cloud SQL Python Connector and exposes
simple batch insert and similarity search operations used by the engine.
"""

from google.cloud.sql.connector import Connector
import sqlalchemy
from sqlalchemy import text
import config
from logger import get_logger

logger = get_logger(__name__)

class PostgresVectorDB:
    """Thin wrapper around a Postgres connection pool with vector ops."""

    def __init__(self):
        self.connector = Connector()
        self.pool = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=self._get_conn,
        )
        # Schema initialization is deferred to 'ensure_schema()' to avoid blocking app startup
        # with synchronous network calls. It is invoked only during data ingestion.

    def _get_conn(self):
        """Return a fresh pg8000 connection via the Cloud SQL connector.

        Raises a clear error if required credentials are missing to avoid
        ambiguous connection failures.
        """
        # Fail fast if required secrets are missing
        if not getattr(config, "DB_PASS", None):
            raise RuntimeError("DB_PASS environment variable is required but not set.")
        if not getattr(config, "DB_USER", None):
            raise RuntimeError("DB_USER environment variable is required but not set.")
        return self.connector.connect(
            f"{config.PROJECT_ID}:{config.REGION}:{config.INSTANCE_NAME}",
            "pg8000",
            user=config.DB_USER,
            password=config.DB_PASS,
            db=config.DATABASE_NAME
        )

    def ensure_schema(self):
        """Ensure the table exists and has the correct schema (Self-Healing)."""
        table_name = config.TABLE_NAME
        with self.pool.connect() as conn:
            # 1. Enable Extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            
            # 2. Create Table (if not exists)
            # We add 'metadata' as JSONB and 'tsv' as TSVECTOR for Full Text Search.
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding vector(768),
                    variant TEXT,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    tsv tsvector
                );
            """))
            
            # 3. Create GIN index for Full Text Search
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {table_name}_tsv_idx ON {table_name} USING GIN(tsv);"))
            
            # 4. Alter Table (Self-Healing for existing tables)
            # Check if columns exist
            cols_to_add = {
                "metadata": "JSONB DEFAULT '{}'::jsonb",
                "tsv": "TSVECTOR"
            }
            for col, col_def in cols_to_add.items():
                check_col = text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='{table_name}' AND column_name='{col}';
                """)
                if not conn.execute(check_col).scalar():
                    logger.warning(f"Migrating schema: Adding '{col}' column to {table_name}...")
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_def};"))
            
            conn.commit()

    def insert_batch(self, contents, vectors, variant, metadatas=None):
        """Insert a batch of text chunks, embeddings, and metadata.
        
        Also populates the 'tsv' column for Full Text Search.
        """
        if metadatas is None:
            metadatas = [{} for _ in contents]
            
        data = []
        for content, vector, meta in zip(contents, vectors, metadatas):
            # Build search string from content + key metadata (heading, section)
            search_parts = [content]
            if meta.get("heading"): search_parts.append(meta.get("heading"))
            if meta.get("section"): search_parts.append(meta.get("section"))
            search_text = " ".join(search_parts)
            
            data.append({
                "content": content,
                "embedding": str(vector),
                "variant": variant,
                "metadata": import_json_dump(meta),
                "search_text": search_text
            })

        with self.pool.connect() as conn:
            stmt = text(f"""
                INSERT INTO {config.TABLE_NAME} (content, embedding, variant, metadata, tv)
                VALUES (:content, :embedding, :variant, :metadata, to_tsvector('english', :search_text))
            """)
            # Fix typo: 'tv' should be 'tsv'
            stmt = text(f"""
                INSERT INTO {config.TABLE_NAME} (content, embedding, variant, metadata, tv)
                VALUES (:content, :embedding, :variant, :metadata, to_tsvector('english', :search_text))
            """)
            # Re-writing to be clean
            stmt = text(f"""
                INSERT INTO {config.TABLE_NAME} (content, embedding, variant, metadata, tsv)
                VALUES (:content, :embedding, :variant, :metadata, to_tsvector('english', :search_text))
            """)
            conn.execute(stmt, data)
            conn.commit()

    def delete_variant(self, variant):
        """Delete all existing chunks for a specific variant (Idempotency)."""
        with self.pool.connect() as conn:
            stmt = text(f"DELETE FROM {config.TABLE_NAME} WHERE variant = :variant")
            conn.execute(stmt, {"variant": variant})
            conn.commit()

    def variant_exists(self, variant) -> bool:
        """Check if any data exists for the given variant."""
        with self.pool.connect() as conn:
            stmt = text(f"SELECT 1 FROM {config.TABLE_NAME} WHERE variant = :variant LIMIT 1")
            result = conn.execute(stmt, {"variant": variant}).scalar()
            return result is not None

    def search_hybrid(self, query_text, query_vector, variant, k=15):
        """Perform Hybrid Search using Reciprocal Rank Fusion (RRF)."""
        with self.pool.connect() as conn:
            # Combine Vector Search and FTS using Reciprocal Rank Fusion
            # We use a CTE to get top candidates from both and then rank them.
            stmt = text(f"""
                WITH vector_search AS (
                    SELECT id, 1.0 / (ROW_NUMBER() OVER (ORDER BY embedding <=> :vector) + 60) as score
                    FROM {config.TABLE_NAME}
                    WHERE variant = :variant
                    ORDER BY embedding <=> :vector
                    LIMIT 50
                ),
                keyword_search AS (
                    SELECT id, 1.0 / (ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, websearch_to_tsquery('english', :query)) DESC) + 60) as score
                    FROM {config.TABLE_NAME}
                    WHERE variant = :variant AND tsv @@ websearch_to_tsquery('english', :query)
                    ORDER BY ts_rank(tsv, websearch_to_tsquery('english', :query)) DESC
                    LIMIT 50
                )
                SELECT content, variant, metadata, 
                       COALESCE(vector_search.score, 0) + COALESCE(keyword_search.score, 0) as combined_score
                FROM {config.TABLE_NAME}
                LEFT JOIN vector_search USING (id)
                LEFT JOIN keyword_search USING (id)
                WHERE vector_search.score IS NOT NULL OR keyword_search.score IS NOT NULL
                ORDER BY combined_score DESC
                LIMIT :k
            """)
            
            result = conn.execute(stmt, {
                "variant": variant,
                "vector": str(query_vector),
                "query": query_text,
                "k": k
            })
            
            return [
                {"content": row[0], "variant": row[1], "metadata": row[2], "hybrid_score": row[3]} 
                for row in result
            ]

    def search(self, query_vector, variant, k=15):
        """Return top-k similar chunks + metadata for a variant (Deprecated: use search_hybrid)."""
        with self.pool.connect() as conn:
            stmt = text(f"""
                SELECT content, variant, metadata
                FROM {config.TABLE_NAME}
                WHERE variant = :variant
                ORDER BY embedding <=> :vector
                LIMIT :k
            """)
            
            result = conn.execute(stmt, {
                "variant": variant,
                "vector": str(query_vector),
                "k": k
            })
            
            return [
                {"content": row[0], "variant": row[1], "metadata": row[2]} 
                for row in result
            ]

import json
def import_json_dump(d):
    return json.dumps(d)
