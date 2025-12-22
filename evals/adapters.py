
from abc import ABC, abstractmethod
from typing import Dict, List, Any
import sys
import os

# Add parent dir to path to allow importing app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_engine import FIHRulesEngine

class BotAdapter(ABC):
    """Abstract interface for any bot implementation (RAG, Agent, etc.)"""
    
    @abstractmethod
    def query(self, question: str) -> Dict[str, Any]:
        """
        Must return a dict with at least:
        {
            "answer": str,
            "source_docs": List[Document] (Optional, for Hit Rate)
        }
        """
        pass

class RAGBotAdapter(BotAdapter):
    """Adapter for the official FIHRulesEngine."""
    
    def __init__(self):
        self.engine = FIHRulesEngine()
        
    def query(self, question: str) -> Dict[str, Any]:
        # The engine expects history arg, even if empty
        return self.engine.query(question, history=[])

class MockBotAdapter(BotAdapter):
    """A dumb bot for testing the evaluator itself."""
    
    def query(self, question: str) -> Dict[str, Any]:
        return {
            "answer": "I don't know, but I strictly follow the rules.",
            "source_docs": []
        }
