
import pytest
from unittest.mock import patch, MagicMock
from evals.evaluate import BotEvaluator
import config

@pytest.fixture
def evaluator():
    """Returns a BotEvaluator instance with mocked dependencies."""
    mock_adapter = MagicMock()
    with patch('evals.evaluate.VertexAI'), \
         patch('evals.evaluate.VertexAIEmbeddings'):
        return BotEvaluator(mock_adapter)

def test_check_citation_basic(evaluator):
    """Test basic citation matching."""
    guidance = "Derived from 9.12"
    answer = "According to Rule 9.12, play stops."
    assert evaluator._check_citation(answer, guidance) is True

def test_check_citation_parentheses(evaluator):
    """Test matching inside parentheses."""
    guidance = "Derived from 9.12"
    answer = "Play stops (9.12)."
    assert evaluator._check_citation(answer, guidance) is True

def test_check_citation_missing(evaluator):
    """Test missing citation."""
    guidance = "Derived from 9.12"
    answer = "Play stops according to the rules."
    assert evaluator._check_citation(answer, guidance) is False

def test_check_citation_wrong_rule(evaluator):
    """Test referencing the wrong rule."""
    guidance = "Derived from 9.12"
    answer = "According to Rule 9.13, play stops."
    assert evaluator._check_citation(answer, guidance) is False

def test_check_citation_no_guidance(evaluator):
    """Test None guidance returns None (skipped)."""
    assert evaluator._check_citation("Answer", None) is None
    assert evaluator._check_citation("Answer", "") is None

def test_check_citation_partial_match(evaluator):
    """Test precise matching (e.g. 1.2 shouldn't match 1.23).
    CURRENT IMPLEMENTATION uses 'in', so 1.2 matches 1.23.
    This test verifies current behavior, even if suboptimal.
    """
    guidance = "Derived from 1.2"
    answer = "Rule 1.23 applies."
    # The current logic: rule_number = "1.2". "1.2" in "Rule 1.23" is True.
    # This documents specific (potentially unwanted) behavior.
    assert evaluator._check_citation(answer, guidance) is True 
