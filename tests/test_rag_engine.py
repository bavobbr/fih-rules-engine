import pytest
from unittest.mock import MagicMock, patch

# We don't need to mock sys.modules for 'database' if 'database.py' is importable.
# database.py imports config, sqlalchemy, etc. It should be safe to import 
# as long as we don't instantiate connection pools at import time.
# rag_engine.py imports database.PostgresVectorDB.

from rag_engine import FIHRulesEngine

@pytest.fixture
def mock_engine():
    # Patch the dependencies where they are DEFINED, because rag_engine imports them 
    # inside __init__ into its local scope, so we can't patch 'rag_engine.VertexAI'
    
    with patch('rag_engine.PostgresVectorDB') as mock_db_cls, \
         patch('langchain_google_vertexai.VertexAI') as mock_llm_cls, \
         patch('langchain_google_vertexai.VertexAIEmbeddings') as mock_emb_cls, \
         patch('config.VARIANTS', new={"indoor": "Indoor Hockey"}), \
         patch('config.RETRIEVAL_K', new=2):
         
        # Instantiate engine
        engine = FIHRulesEngine()
        
        # Manually attach the mocks to the instance if the __init__ assigns them
        # (The __init__ creates instances, so we want to grab those mock instances)
        engine.db = mock_db_cls.return_value
        engine.llm = mock_llm_cls.return_value
        engine.embeddings = mock_emb_cls.return_value
        
        # Mock other internal methods if needed to isolate tests
        # or we can test them via the public methods if we trust the mocked LLM/DB
        
        return engine

def test_ingest_pdf_success(mock_engine):
    """Test full ingestion flow."""
    # Patch the loader BEFORE calling ingest_pdf to prevent it from trying to open the file
    with patch('loaders.get_document_ai_loader') as mock_loader_getter:
        mock_loader = MagicMock()
        mock_loader.load_and_chunk.return_value = [
            MagicMock(page_content="chunk1", metadata={}),
            MagicMock(page_content="chunk2", metadata={})
        ]
        mock_loader_getter.return_value = mock_loader
        
        result = mock_engine.ingest_pdf("dummy.pdf", "indoor")
        
        assert result == 2
        mock_engine.db.delete_variant.assert_called_with("indoor")
        mock_engine.embeddings.embed_documents.assert_called()
        mock_engine.db.insert_batch.assert_called()

def test_query_flow(mock_engine):
    """Test the query routing and context building."""
    # Setup Mocks
    mock_engine._contextualize_query = MagicMock(return_value="Standalone Q")
    mock_engine._route_query = MagicMock(return_value="indoor")
    mock_engine.embeddings.embed_query.return_value = [0.1, 0.2]
    
    mock_engine.db.search.return_value = [
        {"content": "Rule 1", "variant": "indoor", "metadata": {"heading": "1.1"}},
        {"content": "Rule 2", "variant": "indoor", "metadata": {"heading": "1.2"}}
    ]
    
    mock_engine.llm.invoke.return_value = "Final Answer"
    
    # Execute
    response = mock_engine.query("My Question")
    
    # Validate
    assert response["answer"] == "Final Answer"
    assert response["variant"] == "indoor"
    mock_engine.db.search.assert_called()
    assert len(response["source_docs"]) == 2
