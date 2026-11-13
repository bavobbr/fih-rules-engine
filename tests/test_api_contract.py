import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api
from api import app
from tests.test_api_endpoints import client, mock_engine_class  # noqa: F401  (pytest fixtures)

OPENAPI_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def test_openapi_file_matches_api():
    """docs/openapi.json is the published contract: regenerate it with `make openapi` after API changes."""
    assert json.loads(OPENAPI_PATH.read_text()) == app.openapi()


def test_health_ok_when_engine_ready(client):  # noqa: F811
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_503_when_engine_failed_to_start():
    api.engine = None  # earlier tests leave their mock engine on the shared app module
    with patch("api.FIHRulesEngine", side_effect=RuntimeError("no db")):
        with TestClient(app) as test_client:
            response = test_client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Engine not ready"}
    api.engine = None
