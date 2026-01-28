
import sys
import os
# Add project root to path
sys.path.append(os.getcwd())

from rag_engine import FIHRulesEngine
from loaders.sequential_loader import SequentialLoader
import config

def run_verification():
    print("Initializing Engine...")
    engine = FIHRulesEngine()
    
    # 1. Ingest Local Rules (Belgium)
    print("\n--- INGESTION TEST ---")
    file_path = "belgium_rules_test.txt"
    variant = "indoor"
    country = "BEL"
    
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    count = engine.ingest_pdf(file_path, variant, country_code=country)
    print(f"Ingested {count} chunks for {country} {variant}.")
    
    # 2. Query Global (Should not see local rule)
    # Note: This assumes we have some global rules or at least won't find the local one if we don't ask for it.
    # But since we only ingested local in this script run (unless DB persists), we rely on DB state.
    # Assuming DB has persistence.
    
    # query_text = "How long is a green card suspension?"
    
    # 3. Query Local (Should see local rule)
    print("\n--- QUERY TEST (Local: BEL) ---")
    query_text = "How long is a green card suspension in Indoor Hockey?"
    print(f"Question: {query_text}")
    
    result = engine.query(query_text, country_code="BEL")
    print(f"Detected Variant: {result['variant']}")
    
    print("\nANSWER:")
    print(result["answer"])
    
    print("\nSOURCES:")
    for doc in result["source_docs"]:
        meta = doc.metadata
        print(f"- [Country: {meta.get('country')}] [Type: {meta.get('type')}] {doc.page_content[:50]}...")

    # Check if '5 minutes' is in the answer
    if "5 minutes" in result["answer"] or "5 mins" in result["answer"]:
        print("\nSUCCESS: Local rule (5 minutes) was retrieved and used.")
    else:
        print("\nFAILURE: Local rule not found in answer.")

if __name__ == "__main__":
    run_verification()
