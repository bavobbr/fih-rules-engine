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
            
            # 4. Create Index on Metadata (for efficient country filtering)
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {table_name}_meta_country_idx ON {table_name} USING GIN((metadata->'country'));"))

            # 5. Alter Table (Self-Healing for existing tables)
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
            # Determine FTS Configuration
            # Official Rules (no country) -> 'english' (Stemming enabled)
            # Local Rules (country set) -> 'simple' (No stemming, safe for mixed languages)
            country = meta.get("country")
            fts_config = 'simple' if country else 'english'
            
            # Build search string from content + key metadata (rule, section)
            search_parts = [content]
            if meta.get("rule"): search_parts.append(meta.get("rule"))
            if meta.get("section"): search_parts.append(meta.get("section"))
            search_text = " ".join(search_parts)
            
            data.append({
                "content": content,
                "embedding": str(vector),
                "variant": variant,
                "metadata": import_json_dump(meta),
                "search_text": search_text,
                "fts_config": fts_config
            })

        with self.pool.connect() as conn:
            # Group by config to batch efficiently
            import itertools
            data.sort(key=lambda x: x["fts_config"])
            for config_name, group in itertools.groupby(data, key=lambda x: x["fts_config"]):
                group_list = list(group)
                stmt = text(f"""
                    INSERT INTO {config.TABLE_NAME} (content, embedding, variant, metadata, tsv)
                    VALUES (:content, :embedding, :variant, :metadata, to_tsvector('{config_name}', :search_text))
                """)
                conn.execute(stmt, group_list)
                
            conn.commit()

    def delete_scoped_data(self, variant, country_code=None):
        """Delete chunks for a specific scope (Country OR Official).
        
        If country_code is provided: Delete ONLY that country's data for this variant.
        If country_code is None: Delete ONLY Official data (where country is NULL or type='official') for this variant.
        """
        table = config.TABLE_NAME
        with self.pool.connect() as conn:
            if country_code:
                # Delete National Rulebook
                logger.info(f"Deleting scoped data for variant='{variant}', country='{country_code}'")
                stmt = text(f"DELETE FROM {table} WHERE variant = :variant AND metadata->>'country' = :country")
                conn.execute(stmt, {"variant": variant, "country": country_code})
            else:
                # Delete Official Rulebook (Safe: Don't touch countries)
                logger.info(f"Deleting scoped Official data for variant='{variant}'")
                stmt = text(f"""
                    DELETE FROM {table} 
                    WHERE variant = :variant 
                    AND (metadata->>'country' IS NULL OR metadata->>'type' = 'official')
                """)
                conn.execute(stmt, {"variant": variant})
            conn.commit()

    def variant_exists(self, variant, country_code=None) -> bool:
        """Check if any data exists for the given variant/scope."""
        with self.pool.connect() as conn:
            if country_code:
                stmt = text(f"SELECT 1 FROM {config.TABLE_NAME} WHERE variant = :variant AND metadata->>'country' = :country LIMIT 1")
                result = conn.execute(stmt, {"variant": variant, "country": country_code}).scalar()
            else:
                stmt = text(f"""
                    SELECT 1 FROM {config.TABLE_NAME} 
                    WHERE variant = :variant 
                      AND (metadata->>'country' IS NULL OR metadata->>'type' = 'official') 
                    LIMIT 1
                """)
                result = conn.execute(stmt, {"variant": variant}).scalar()
            return result is not None

    def search_hybrid(self, query_text, query_vector, variant, country_code=None, k=15):
        """Perform Hybrid Search using Reciprocal Rank Fusion (RRF).
        
        Scope:
        - If country_code is None: Global Search (Official Rules Only).
        - If country_code is SET: Local Search (Specific Country Rules Only).
        
        The calling engine is responsible for merging these if a Dual-Path strategy is desired.
        """
        table = config.TABLE_NAME
        
        # SQL Filter Condition
        # STRICT FILTERING for Dual-Path retrieval support.
        if country_code:
            filter_condition = "metadata->>'country' = :country"
            boost_logic = "1.0" 
            fts_config = 'simple'  # Local rules might be mixed language -> No stemming
        else:
            filter_condition = "(metadata->>'country' IS NULL OR metadata->>'type' = 'official')"
            boost_logic = "1.0"
            fts_config = 'english' # Official rules are English -> Use stemming

        with self.pool.connect() as conn:
            # Combine Vector Search and FTS using Reciprocal Rank Fusion
            stmt = text(f"""
                WITH vector_search AS (
                    SELECT id, 1.0 / (ROW_NUMBER() OVER (ORDER BY embedding <=> :vector) + 60) as score
                    FROM {table}
                    WHERE variant = :variant AND {filter_condition}
                    ORDER BY embedding <=> :vector
                    LIMIT 50
                ),
                keyword_search AS (
                    SELECT id, 1.0 / (ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, websearch_to_tsquery('{fts_config}', :query)) DESC) + 60) as score
                    FROM {table}
                    WHERE variant = :variant AND {filter_condition} 
                      AND tsv @@ websearch_to_tsquery('{fts_config}', :query)
                    ORDER BY ts_rank(tsv, websearch_to_tsquery('{fts_config}', :query)) DESC
                    LIMIT 50
                )
                SELECT content, variant, metadata, 
                       COALESCE(vector_search.score, 0) + COALESCE(keyword_search.score, 0) as rrf_score
                FROM vector_search
                FULL OUTER JOIN keyword_search ON vector_search.id = keyword_search.id
                JOIN {table} ON {table}.id = COALESCE(vector_search.id, keyword_search.id)
                ORDER BY rrf_score DESC
                LIMIT :k
            """)

            
            params = {
                "variant": variant,
                "vector": str(query_vector),
                "query": query_text,
                "k": k
            }
            if country_code:
                params["country"] = country_code
            
            result = conn.execute(stmt, params)
            
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

    def clear_table(self):
        """Truncate the table, deleting all rows and resetting ID counters."""
        with self.pool.connect() as conn:
            stmt = text(f"TRUNCATE TABLE {config.TABLE_NAME} RESTART IDENTITY;")
            conn.execute(stmt)
            conn.commit()
            logger.warning(f"Truncated table {config.TABLE_NAME}.")

    def get_active_jurisdictions(self):
        """Return a list of distinct country codes present in the database."""
        with self.pool.connect() as conn:
            # Query the JSONB content to find all non-null country values
            stmt = text(f"""
                SELECT DISTINCT metadata->>'country' as country_code 
                FROM {config.TABLE_NAME} 
                WHERE metadata->>'country' IS NOT NULL
            """)
            result = conn.execute(stmt).fetchall()
            return [row[0] for row in result]

    def get_source_stats(self):
        """Return statistics on ingested documents.
        
        Returns:
            List of dicts: [{
                'source_file': str, 
                'variant': str, 
                'country': str (or 'Official'), 
                'chunk_count': int
            }, ...]
        """
        with self.pool.connect() as conn:
            # Group by source_file and key metadata
            # We treat NULL country as 'Official'
            stmt = text(f"""
                SELECT 
                    metadata->>'source_file' as source_file,
                    variant,
                    COALESCE(metadata->>'country', 'Official') as country,
                    COUNT(*) as chunk_count
                FROM {config.TABLE_NAME}
                GROUP BY 1, 2, 3
                ORDER BY 3, 2, 1
            """)
            result = conn.execute(stmt).fetchall()
            
            return [
                {
                    "source_file": row[0] or "Unknown Source", 
                    "variant": row[1], 
                    "country": row[2], 
                    "chunk_count": row[3]
                } 
                for row in result
            ]

    def delete_source_file(self, filename):
        """Delete all chunks belonging to a specific source file."""
        with self.pool.connect() as conn:
            logger.info(f"Deleting source file: {filename}")
            stmt = text(f"DELETE FROM {config.TABLE_NAME} WHERE metadata->>'source_file' = :filename")
            conn.execute(stmt, {"filename": filename})
            conn.commit()

import json
def import_json_dump(d):
    return json.dumps(d)
