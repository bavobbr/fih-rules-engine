import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

from rag_engine import FIHRulesEngine
import config

def test_reranking():
    print("Initializing FIH Rules Engine...")
    engine = FIHRulesEngine()
    
    query = "In indoor hockey, what happens if the ball goes over the sideboards?"
    print(f"\nQuery: {query}")
    
    # We want to see if reranking is actually called and if it works.
    # The logs in rag_engine.py should show this.
    
    print("\nExecuting query...")
    result = engine.query(query)
    
    print(f"\nAnswer: {result['answer'][:200]}...")
    print(f"\nVariant detected: {result['variant']}")
    print(f"\nNumber of source documents: {len(result['source_docs'])}")
    
    print("\nSource Documents Order:")
    for i, doc in enumerate(result['source_docs']):
        print(f"{i+1}. [{doc.metadata.get('rule', 'No Rule')}] {doc.metadata.get('source_file', 'No Source')} p.{doc.metadata.get('page', '?')}")
        # print(f"   Content snippet: {doc.page_content[:100]}...")

if __name__ == "__main__":
    test_reranking()
