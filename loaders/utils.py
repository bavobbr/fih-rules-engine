from langchain_google_vertexai import VertexAI
import config
from logger import get_logger
import re

logger = get_logger(__name__)

def clean_text(text: str) -> str:
    """Cleans text by removing excessive whitespace and null bytes."""
    if not text:
        return ""
    # Remove null bytes
    text = text.replace("\x00", "")
    # Normalize unicode
    # text = unicodedata.normalize("NFKC", text)
    # Replace multiple newlines with single newline (optional, but good for embedding)
    # Actually for chunking we might want to keep paragraph breaks.
    # Just collapse multiple spaces to one
    # text = re.sub(r'\s+', ' ', text).strip() # This is too aggressive if we want to keep structure.
    
    # Simple cleanup:
    return text.strip()

def summarize_text(text: str) -> str:
    """Summarizes text into a short, human-readable label (max 15 words)."""
    if not text or not text.strip():
        return ""
        
    llm = VertexAI(
        model_name=config.LLM_MODEL,
        project=config.PROJECT_ID,
        location=config.REGION,
        temperature=0
    )
    
    prompt = f"""Summarize the following field hockey rule content in a single plain English sentence (max 15 words).
    This will be used as a human-readable label for a specific rule chunk.
    Do not use "This rule states..." or "The content..." just describe the topic directly.
    
    CONTENT:
    {text}
    
    Recall: Max 15 words.
    """
    
    try:
        summary = llm.invoke(prompt).strip()
        # Cleanup quotes if LLM adds them
        return summary.replace('"', '').replace("'", "")
    except Exception as e:
        logger.warning(f"Summarization failed: {e}")
        return "Summary unavailable"
