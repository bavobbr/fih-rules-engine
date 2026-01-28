
import sys
import os
# Add project root to path
sys.path.append(os.getcwd())

from database import PostgresVectorDB
from logger import get_logger

logger = get_logger(__name__)

def run_reset():
    print("WARNING: This will delete ALL data in the database.")
    confirmation = input("Type 'DELETE' to confirm: ")
    
    if confirmation.strip() == "DELETE":
        db = PostgresVectorDB()
        db.clear_table()
        print("Database wiped successfully.")
    else:
        print("Operation cancelled.")

if __name__ == "__main__":
    run_reset()
