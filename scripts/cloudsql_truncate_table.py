"""Truncate the vector table in Cloud SQL (dangerous, for dev use)."""
import sqlalchemy
from database import PostgresVectorDB
from sqlalchemy import text
import config

def wipe_database():
    print(f"🔥 Connecting to {config.INSTANCE_NAME}...")
    
    # 1. Initialize DB (uses shared Connector logic)
    db = PostgresVectorDB()
    table_name = config.TABLE_NAME

    # 2. Execute Truncate
    print(f"⚠️  Wiping table '{table_name}'...")
    
    with db.pool.connect() as conn:
        conn.execute(text(f"TRUNCATE TABLE {table_name};"))
        conn.commit()
        
    print("✅ Database is empty. Ready for new labeled data!")

if __name__ == "__main__":
    wipe_database()
