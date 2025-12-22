from langchain_google_vertexai import VertexAI
import config
from logger import get_logger

logger = get_logger(__name__)

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
    
    prompt = f"""Summarize the following rule content in a single plain English sentence (max 15 words).
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
