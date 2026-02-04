from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import pytest
from api import app

@pytest.fixture
def mock_engine_class():
    with patch("api.FIHRulesEngine") as mock_class:
        # The mocked class, when called, returns a mock instance
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def client(mock_engine_class):
    # We don't need to patch api.engine manually because the lifespan will run
    # and use the patched FIHRulesEngine class to assign to api.engine.
    with TestClient(app) as client:
        yield client

def test_get_knowledge_base(client, mock_engine_class):
    """Test the GET /knowledge-base endpoint."""
    
    # Setup mock return value
    mock_stats = [
        {
            "source_file": "rules_2024.pdf",
            "variant": "outdoor",
            "country": "Official",
            "chunk_count": 150
        },
        {
            "source_file": "belgium_appendix.pdf",
            "variant": "outdoor",
            "country": "BEL",
            "chunk_count": 20
        }
    ]
    
    # Configure the mock db on the instance created by lifespan
    # mock_engine_class is the instance returned by FIHRulesEngine()
    mock_engine_class.db.get_source_stats.return_value = mock_stats
    
    # Execute request
    response = client.get("/knowledge-base")
    
    # Verify
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["source_file"] == "rules_2024.pdf"
    assert data[0]["chunk_count"] == 150
    assert data[1]["country"] == "BEL"
    
    # Verify db call
    mock_engine_class.db.get_source_stats.assert_called_once()
