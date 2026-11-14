import json
from unittest.mock import MagicMock

import prompts
from rag_engine import FIHRulesEngine
from tests.test_rag_engine import mock_engine  # noqa: F401  (pytest fixture)

ANSWER = {
    "reasoning": "R.",
    "is_refusal": False,
    "direct_answer": "D.",
    "key_rules": [{"rule": "14.1", "source_file": "a.pdf", "page": "45", "is_local": True, "explanation": "E."}],
}


# --- Planner detects the language ---

def test_plan_includes_language_code():
    plan = FIHRulesEngine._parse_query_plan(
        '{"variant": "outdoor", "language": "NL", "standalone_query": "Q", "keywords": []}', "q")
    assert plan["language"] == "nl"


def test_plan_language_accepts_names_and_defaults_to_english():
    assert FIHRulesEngine._parse_query_plan('{"language": "French", "standalone_query": "Q"}', "q")["language"] == "fr"
    assert FIHRulesEngine._parse_query_plan('{"language": "Nederlands", "standalone_query": "Q"}', "q")["language"] == "nl"
    assert FIHRulesEngine._parse_query_plan('{"standalone_query": "Q"}', "q")["language"] == "en"
    assert FIHRulesEngine._parse_query_plan("not json", "q")["language"] == "en"


def test_planning_prompt_asks_for_language():
    assert '"language"' in prompts.get_query_planning_prompt("", "Hoe lang duurt een groene kaart?")


# --- Answer prompt names the language explicitly ---

def _answer_prompt(language):
    return prompts.get_rag_answer_prompt(
        detected_variant="outdoor", jurisdiction_label="International", country_code=None,
        context_text="CTX", standalone_query="Q", language=language)


def test_answer_prompt_names_language():
    prompt = _answer_prompt("nl")
    assert "Write every text field in Dutch" in prompt
    assert "usually English" not in prompt
    assert "The user asks about" not in prompt  # English example text pulled reasoning into English


def test_answer_prompt_unknown_language_uses_code():
    assert "language with ISO code 'es'" in _answer_prompt("es")


# --- Rendered labels follow the language ---

def test_render_dutch_labels():
    text = FIHRulesEngine._render_answer(ANSWER, language="nl")
    assert text.startswith("**Antwoord**\nD.")
    assert "**Belangrijkste regels**" in text
    assert "**Redenering**\nR." in text
    assert text.count("(lokale regel)") == 1


def test_render_french_labels():
    text = FIHRulesEngine._render_answer(ANSWER, language="fr")
    assert text.startswith("**Réponse**\nD.")
    assert "**Règles clés**" in text
    assert "**Raisonnement**" in text
    assert "(règle locale)" in text


def test_render_unknown_language_falls_back_to_english_labels():
    text = FIHRulesEngine._render_answer(ANSWER, language="es")
    assert text.startswith("**Direct Answer**")
    assert "(local rule)" in text


# --- Engine passes the language through ---

def _plan(mock_engine, language):  # noqa: F811
    mock_engine._plan_query = MagicMock(return_value={
        "variant": "outdoor", "standalone_query": "Q", "keywords": [], "language": language})
    mock_engine.embeddings.embed_query.return_value = [0.1]
    mock_engine._rerank_documents = MagicMock(side_effect=lambda q, docs: docs)


def test_query_returns_language_and_localized_answer(mock_engine):  # noqa: F811
    _plan(mock_engine, "fr")
    mock_engine.db.search_hybrid.return_value = [
        {"content": "Rule text", "variant": "outdoor", "metadata": {}, "hybrid_score": 0.5}]
    mock_engine.llm.invoke = MagicMock(return_value=json.dumps(ANSWER))

    response = mock_engine.query("Combien de temps dure un carton vert ?")

    assert response["language"] == "fr"
    assert response["answer"].startswith("**Réponse**")
    assert "Write every text field in French" in mock_engine.llm.invoke.call_args.args[0]


def test_no_context_message_is_localized(mock_engine):  # noqa: F811
    _plan(mock_engine, "nl")
    mock_engine.db.search_hybrid.return_value = []

    response = mock_engine.query("Hoe lang duurt een groene kaart?")

    assert response["language"] == "nl"
    assert "outdoor" in response["answer"]
    assert "couldn't find" not in response["answer"]
