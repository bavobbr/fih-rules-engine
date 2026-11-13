import json
from unittest.mock import MagicMock

from rag_engine import FIHRulesEngine
from tests.test_rag_engine import mock_engine  # noqa: F401  (pytest fixture)


ANSWER = {
    "reasoning": "A defender intentionally used the foot inside the circle.",
    "is_refusal": False,
    "direct_answer": "A penalty corner is awarded.",
    "key_rules": [
        {"rule": "Rule 12.3", "source_file": "FIH-Rules-2024.pdf", "page": "42",
         "is_local": False, "explanation": "Intentional offence by a defender in the circle."},
        {"rule": "", "source_file": "spelregels-bel.pdf", "page": "?",
         "is_local": True, "explanation": "Local leagues use a 2-minute green card."},
    ],
}


def test_render_full_answer():
    text = FIHRulesEngine._render_answer(ANSWER)

    assert text.startswith("**Direct Answer**\nA penalty corner is awarded.")
    assert "**Rule 12.3**: Intentional offence by a defender in the circle. *(fih-rules-2024.pdf, p. 42)*" in text
    assert "**Reasoning**\nA defender intentionally used the foot inside the circle." in text
    # Index: Direct Answer before Key Rules before Reasoning
    assert text.index("**Direct Answer**") < text.index("**Key Rules**") < text.index("**Reasoning**")


def test_render_omits_unknown_rule_and_page_and_labels_local():
    text = FIHRulesEngine._render_answer(ANSWER)

    assert "- Local leagues use a 2-minute green card. *(spelregels-bel.pdf)* (local rule)" in text
    assert "p. ?" not in text
    assert "****" not in text


def test_render_ignores_placeholder_rule_labels():
    data = dict(ANSWER, key_rules=[{"rule": "N/A", "source_file": "x.pdf", "page": "1", "explanation": "E."}])
    text = FIHRulesEngine._render_answer(data)
    assert "N/A" not in text
    assert "- E. *(x.pdf, p. 1)*" in text


def test_render_refusal_is_plain_text():
    data = {"is_refusal": True, "direct_answer": "I can only answer questions about hockey rules.",
            "key_rules": [], "reasoning": "Off-topic."}
    assert FIHRulesEngine._render_answer(data) == "I can only answer questions about hockey rules."


def test_query_uses_two_llm_calls_and_renders_json(mock_engine):  # noqa: F811
    mock_engine._plan_query = MagicMock(return_value={
        "variant": "outdoor", "standalone_query": "Q", "keywords": []})
    mock_engine.embeddings.embed_query.return_value = [0.1]
    mock_engine.db.search_hybrid.return_value = [
        {"content": "Rule text", "variant": "outdoor", "metadata": {"rule": "12.3"}, "hybrid_score": 0.5},
    ]
    mock_engine._rerank_documents = MagicMock(side_effect=lambda q, docs: docs)
    mock_engine.llm.invoke = MagicMock(return_value="```json\n" + json.dumps(ANSWER) + "\n```")

    response = mock_engine.query("Q")

    assert mock_engine.llm.invoke.call_count == 1  # planning is mocked; answer only, no reformat pass
    assert response["answer"] == FIHRulesEngine._render_answer(ANSWER)


def test_query_falls_back_to_raw_text_when_answer_is_not_json(mock_engine):  # noqa: F811
    mock_engine._plan_query = MagicMock(return_value={
        "variant": "outdoor", "standalone_query": "Q", "keywords": []})
    mock_engine.embeddings.embed_query.return_value = [0.1]
    mock_engine.db.search_hybrid.return_value = [
        {"content": "Rule text", "variant": "outdoor", "metadata": {}, "hybrid_score": 0.5},
    ]
    mock_engine._rerank_documents = MagicMock(side_effect=lambda q, docs: docs)
    mock_engine.llm.invoke = MagicMock(return_value="Plain answer without JSON.")

    assert mock_engine.query("Q")["answer"] == "Plain answer without JSON."
