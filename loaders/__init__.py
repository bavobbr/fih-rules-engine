from .base import BaseLoader
from .vertex_ai_loader import VertexAILoader
import logging

logger = logging.getLogger(__name__)

def get_document_ai_loader():
    """Factory: Returns the VertexAILoader."""
    logger.info(" [Factory] returning Vertex AI Loader (Gemini Structure + DocAI Batch)")
    return VertexAILoader()

__all__ = ["BaseLoader", "VertexAILoader", "get_document_ai_loader"]
