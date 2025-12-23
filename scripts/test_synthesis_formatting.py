import sys
import os
from unittest.mock import MagicMock, patch

# Add the current directory to sys.path
sys.path.append(os.getcwd())

from rag_engine import FIHRulesEngine
from langchain_core.documents import Document

def test_synthesis_formatting():
    engine = FIHRulesEngine()
    
    # Mock LLM response with Summary and Details but NO labels
    mock_answer = """Yellow card suspensions are temporary penalties for misconduct, lasting at least 5 minutes.

- A player can be temporarily suspended for a minimum of 5 minutes of playing time, indicated by a yellow card **(rules.pdf p.42)**.
- The duration of a yellow card suspension for a minor offence must have a clear difference from the duration for a more serious and/or physical offence **(rules.pdf p.46)**.
- For specific field play violations, a suspension may be issued **(Rule 9.12 | PLAYING THE GAME)**."""
    
    engine.llm.invoke = MagicMock(return_value=mock_answer)
    engine._contextualize_query = MagicMock(return_value="Yellow card suspension duration?")
    engine._route_query = MagicMock(return_value="outdoor")
    engine.embeddings.embed_query = MagicMock(return_value=[0.1]*768)
    
    # Mock DB results
    mock_docs = [
        {"content": "Yellow card suspension is min 5 mins", "metadata": {"source_file": "rules.pdf", "page": "42", "rule": "No number", "chapter": "CONDUCT OF PLAY"}},
        {"content": "Yellow card duration must differ for minor vs major offence", "metadata": {"source_file": "rules.pdf", "page": "46", "rule": "No number", "chapter": "CONDUCT OF PLAY"}},
        {"content": "Rule 9.12 description", "metadata": {"source_file": "rules.pdf", "page": "12", "rule": "9.12", "chapter": "PLAYING THE GAME"}}
    ]
    engine.db.search_hybrid = MagicMock(return_value=mock_docs)
    
    # Run query
    print("Running query simulation...")
    response = engine.query("Yellow card suspension duration?")
    
    print("\n--- STANDALONE QUERY ---")
    print(response["standalone_query"])
    
    print("\n--- GENERATED ANSWER ---")
    print(response["answer"])
    
    # Assertions
    assert "Rule: No number" not in response["answer"]
    assert "**Summary**:" not in response["answer"]
    assert "**Details**:" not in response["answer"]
    assert "1." not in response["answer"]
    assert response["answer"].startswith("Yellow card")
    assert "**(Rule 9.12 | PLAYING THE GAME)**" in response["answer"]
    assert "**(rules.pdf p.42)**" in response["answer"]
    print("\nVerification Successful: Answer follows final aesthetic rules!")

if __name__ == "__main__":
    with patch('rag_engine.PostgresVectorDB'), \
         patch('langchain_google_vertexai.VertexAI'), \
         patch('langchain_google_vertexai.VertexAIEmbeddings'):
        test_synthesis_formatting()
