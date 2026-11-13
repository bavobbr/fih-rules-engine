from unittest.mock import MagicMock

from rag_engine import FIHRulesEngine
from tests.test_rag_engine import mock_engine  # noqa: F401  (pytest fixture)


def test_parse_plain_json():
    plan = FIHRulesEngine._parse_query_plan(
        '{"variant": "indoor", "standalone_query": "Can I lift the ball indoors?", "keywords": ["raised ball", "lift"]}',
        "can I lift it?",
    )
    assert plan == {
        "variant": "indoor",
        "standalone_query": "Can I lift the ball indoors?",
        "keywords": ["raised ball", "lift"],
    }


def test_parse_fenced_json_and_normalizes_variant():
    raw = '```json\n{"variant": "Indoor.", "standalone_query": "Q", "keywords": ["a"]}\n```'
    plan = FIHRulesEngine._parse_query_plan(raw, "orig")
    assert plan["variant"] == "indoor"


def test_parse_unknown_variant_defaults_to_outdoor():
    raw = '{"variant": "beach", "standalone_query": "Q", "keywords": []}'
    assert FIHRulesEngine._parse_query_plan(raw, "orig")["variant"] == "outdoor"


def test_parse_garbage_falls_back_to_original_query():
    plan = FIHRulesEngine._parse_query_plan("Sorry, I think this is about hockey5s.", "my question")
    assert plan["standalone_query"] == "my question"
    assert plan["variant"] == "hockey5s"
    assert plan["keywords"] == []


def test_query_uses_single_planning_call_and_or_keywords(mock_engine):  # noqa: F811
    mock_engine.llm.invoke = MagicMock(side_effect=[
        '{"variant": "indoor", "standalone_query": "Standalone Q", "keywords": ["foot", "kick"]}',
        "Raw answer",
        "Final Answer",
    ])
    mock_engine.embeddings.embed_query.return_value = [0.1, 0.2]
    mock_engine.db.search_hybrid.return_value = [
        {"content": "Rule 1", "variant": "indoor", "metadata": {"rule": "1.1"}, "hybrid_score": 0.5},
    ]
    mock_engine._rerank_documents = MagicMock(side_effect=lambda q, docs: docs)

    response = mock_engine.query("can I kick it?", history=[("user", "indoor question")])

    assert mock_engine.llm.invoke.call_count == 3  # plan + answer + reformat
    assert response["variant"] == "indoor"
    assert response["standalone_query"] == "Standalone Q"
    _, kwargs = mock_engine.db.search_hybrid.call_args
    assert kwargs["keyword_text"] == "foot or kick"
    mock_engine.embeddings.embed_query.assert_called_with("Standalone Q")


def test_query_without_keywords_falls_back_to_standalone_query(mock_engine):  # noqa: F811
    mock_engine._plan_query = MagicMock(return_value={
        "variant": "outdoor", "standalone_query": "Standalone Q", "keywords": [],
    })
    mock_engine.embeddings.embed_query.return_value = [0.1]
    mock_engine.db.search_hybrid.return_value = []

    mock_engine.query("q")

    _, kwargs = mock_engine.db.search_hybrid.call_args
    assert kwargs["keyword_text"] == "Standalone Q"
