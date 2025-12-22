from .base import BaseLoader
from .vertex_ai_loader import VertexAILoader
from .local_loader import SimpleLocalLoader
import logging
import os

logger = logging.getLogger(__name__)

def get_document_ai_loader():
    """Factory: Returns the VertexAILoader by default.
    
    Falls back to SimpleLocalLoader if USE_LOCAL_LOADER=true (for dev/debugging).
    """
    if os.getenv("USE_LOCAL_LOADER", "").lower() == "true":
        logger.info(" [Factory] returning Simple Local Loader (PyPDF Fallback)")
        return SimpleLocalLoader()
        
    logger.info(" [Factory] returning Vertex AI Loader (Gemini Structure + DocAI Batch)")
    return VertexAILoader()

__all__ = ["BaseLoader", "VertexAILoader", "SimpleLocalLoader", "get_document_ai_loader"]
