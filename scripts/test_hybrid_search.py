import sys
import os
from dotenv import load_dotenv

# Add the current directory to sys.path
sys.path.append(os.getcwd())
load_dotenv()

from rag_engine import FIHRulesEngine
import config

def test_hybrid_search():
    print("Initializing FIH Rules Engine...")
    engine = FIHRulesEngine()
    
    queries = [
        # Semantic query
        "Can a player hit the ball with the back of the stick?",
        # Keyword-specific query
        "Rule 9.12",
        # Technical term query
        "sideboards"
    ]
    
    for query in queries:
        print(f"\n--- Testing Query: {query} ---")
        result = engine.query(query)
        
        print(f"Variant detected: {result['variant']}")
        print(f"Number of source documents: {len(result['source_docs'])}")
        
        print("\nTop 3 Source Documents:")
        for i, doc in enumerate(result['source_docs'][:3]):
            print(f"{i+1}. [{doc.metadata.get('rule', 'No Rule')}] p.{doc.metadata.get('page', '?')} - Score: {getattr(doc.metadata, 'hybrid_score', 'N/A')}")
            # Snippet of content
            content_snippet = doc.page_content[:100].replace('\n', ' ')
            print(f"   Snippet: {content_snippet}...")

if __name__ == "__main__":
    test_hybrid_search()
