
import pytest
import json
from evals.generate_dataset import parse_json_response

def test_parse_json_clean():
    """Test parsing clean JSON."""
    raw = '{"question": "Q?", "answer": "A."}'
    result = parse_json_response(raw)
    assert result["question"] == "Q?"
    assert result["answer"] == "A."

def test_parse_json_markdown_block():
    """Test parsing JSON wrapped in markdown."""
    raw = '```json\n{"question": "Q?", "answer": "A."}\n```'
    result = parse_json_response(raw)
    assert result["question"] == "Q?"

def test_parse_json_markdown_no_lang():
    """Test parsing JSON wrapped in ``` without language."""
    raw = '```\n{"question": "Q?", "answer": "A."}\n```'
    result = parse_json_response(raw)
    assert result["question"] == "Q?"

def test_parse_json_invalid():
    """Test that invalid JSON raises JSONDecodeError."""
    raw = 'Wait, here is the json: {foo}'
    with pytest.raises(json.JSONDecodeError):
        parse_json_response(raw)
