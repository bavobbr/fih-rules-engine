import prompts
from rag_engine import FIHRulesEngine


def test_rerank_title_combines_rule_chapter_and_section():
    meta = {"rule": "9.12", "chapter": "PLAYING THE GAME", "section": "9 Conduct of play"}
    assert FIHRulesEngine._rerank_title(meta) == "Rule 9.12 | PLAYING THE GAME | 9 Conduct of play"


def test_rerank_title_skips_placeholders():
    meta = {"rule": "N/A", "chapter": "General", "section": "N/A"}
    assert FIHRulesEngine._rerank_title(meta) == ""


def _answer_prompt(country_code):
    return prompts.get_rag_answer_prompt(
        detected_variant="outdoor", jurisdiction_label="International",
        country_code=country_code, context_text="CTX", standalone_query="Q")


def test_answer_prompt_without_country_has_no_local_hierarchy():
    prompt = _answer_prompt(None)
    assert "None" not in prompt
    assert "HIERARCHY RULE" not in prompt


def test_answer_prompt_with_country_explains_override():
    prompt = _answer_prompt("BEL")
    assert "'LOCAL' (BEL) rules" in prompt
    assert "this is the rule in BEL" in prompt
