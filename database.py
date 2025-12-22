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
            # We add 'metadata' as JSONB.
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding vector(768),
                    variant TEXT,
                    metadata JSONB DEFAULT '{{}}'::jsonb
                );
            """))
            
            # 3. Alter Table (Self-Healing for existing tables)
            # Check if metadata column exists, if not, add it.
            # This handles the migration for your existing empty table.
            check_col = text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='{table_name}' AND column_name='metadata';
            """)
            if not conn.execute(check_col).scalar():
                logger.warning(f"Migrating schema: Adding 'metadata' column to {table_name}...")
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN metadata JSONB DEFAULT '{{}}'::jsonb;"))
            
            conn.commit()

    def insert_batch(self, contents, vectors, variant, metadatas=None):
        """Insert a batch of text chunks, embeddings, and metadata.

        contents: list[str] — raw text chunks
        vectors: list[list[float]] — embedding vectors
        variant: str — ruleset label
        metadatas: list[dict] — optional metadata (heading, source, etc.)
        """
        if metadatas is None:
            # Default empty dicts if not provided
            metadatas = [{} for _ in contents]
            
        data = []
        for content, vector, meta in zip(contents, vectors, metadatas):
            data.append({
                "content": content,
                "embedding": str(vector),
                "variant": variant,
                "metadata": import_json_dump(meta) # Helper to stringify JSON
            })

        with self.pool.connect() as conn:
            stmt = text(f"""
                INSERT INTO {config.TABLE_NAME} (content, embedding, variant, metadata)
                VALUES (:content, :embedding, :variant, :metadata)
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

    def search(self, query_vector, variant, k=15):
        """Return top-k similar chunks + metadata for a variant."""
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
            
            # Unpack results
            # row[0]=content, row[1]=variant, row[2]=metadata (dict)
            return [
                {"content": row[0], "variant": row[1], "metadata": row[2]} 
                for row in result
            ]

import json
def import_json_dump(d):
    return json.dumps(d)
