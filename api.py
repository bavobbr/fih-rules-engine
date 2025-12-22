from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import os
import uvicorn
import json
from datetime import datetime
from contextlib import asynccontextmanager

from rag_engine import FIHRulesEngine
from logger import get_logger

logger = get_logger(__name__)

# Global engine instance
engine: Optional[FIHRulesEngine] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the RAG engine on startup."""
    global engine
    try:
        logger.info("Initializing FIH Rules Engine...")
        engine = FIHRulesEngine()
        logger.info("Engine initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize engine: {e}", exc_info=True)
        # We don't raise here to allow the health check to return 503 instead of crashing
    yield
    # Cleanup if needed

app = FastAPI(
    title="FIH Rules API",
    description="REST API for querying the official FIH (International Hockey Federation) rules for Outdoor, Indoor, and Hockey5s using RAG.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration
# Create a list of allowed origins. In production, this should be specific.
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Security ---
API_KEY = os.getenv("API_KEY", "dev-secret-key")

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

# --- Data Models ---

class Message(BaseModel):
    role: str = Field(..., description="The role of the message sender (e.g., 'user', 'assistant')", example="user")
    content: str = Field(..., description="The content of the message", example="What are the rules for a penalty corner?")

class ChatRequest(BaseModel):
    query: str = Field(..., description="The user's question or query", example="What is a flick?")
    history: List[Message] = Field(default=[], description="The conversation history for context")

class SourceDoc(BaseModel):
    page_content: str = Field(..., description="The text content from the source document")
    metadata: Dict[str, Any] = Field(..., description="Metadata about the source document (e.g., source file, page number)")

class ChatResponse(BaseModel):
    answer: str = Field(..., description="The AI-generated answer to the query")
    standalone_query: str = Field(..., description="The query reformulated to be standalone based on history")
    variant: str = Field(..., description="The variant of the rules used (e.g., 'outdoor')")
    source_docs: List[SourceDoc] = Field(..., description="The source documents used to generate the answer")

class EvalsMetrics(BaseModel):
    custom_metrics: Dict[str, float] = Field(..., description="Custom metrics calculated during evaluation (e.g., accuracy, hit rate)")
    ragas_metrics: Dict[str, float] = Field(..., description="RAGAS-specific metrics (e.g., faithfulness, answer relevancy)")

class EvalsResponse(BaseModel):
    timestamp: str = Field(..., description="ISO 8601 timestamp of when the evaluation report was generated")
    metrics: EvalsMetrics = Field(..., description="The evaluation metrics")

# --- Endpoints ---

REPORT_PATH = "evals/report_latest.json"

@app.get("/health", tags=["System"], summary="Health Check", response_description="Service health status")
async def health_check():
    """
    Check if the API and the RAG engine are initialized and healthy.
    
    Returns a 200 status if healthy, or 503 if the engine is not initialized.
    """

@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)], tags=["Chat"], summary="AI Chat", response_description="AI generated answer with source citations")
async def chat(request: ChatRequest):
    """
    Process a chat request using the FIH Rules RAG engine.
    
    This endpoint takes a user query and optional conversation history, reformulates the query 
    into a standalone question, performs a vector search over the FIH rules, and generates 
    an answer using Gemini.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    try:
        # Convert Pydantic models to dicts/tuples expected by engine
        history_list = [(m.role, m.content) for m in request.history]
        
        result = engine.query(request.query, history=history_list)
        
        # Transform result for response
        # engine.query returns dict with keys: answer, standalone_query, variant, source_docs
        # source_docs are LangChain Documents, need to convert to Pydantic
        
        source_docs_data = [
            SourceDoc(page_content=doc.page_content, metadata=doc.metadata) 
            for doc in result["source_docs"]
        ]
        
        return ChatResponse(
            answer=result["answer"],
            standalone_query=result["standalone_query"],
            variant=result["variant"],
            source_docs=source_docs_data
        )
        
    except Exception as e:
        logger.error(f"Error processing chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/evals/latest", response_model=EvalsResponse, dependencies=[Depends(verify_api_key)], tags=["Evals"], summary="Get Latest Metrics", response_description="Latest evaluation report metrics")
async def get_latest_evals():
    """
    Retrieve the most recent evaluation metrics generated by the synthetic evaluation pipeline.
    
    The metrics include both custom calculations (accuracy, hit rate) and RAGAS scores 
    (faithfulness, relevancy, etc.).
    """
    if not os.path.exists(REPORT_PATH):
        raise HTTPException(status_code=404, detail="Evaluation report not found")
    
    try:
        with open(REPORT_PATH, "r") as f:
            report = json.load(f)
        
        # Get file modification time as timestamp
        mod_time = os.path.getmtime(REPORT_PATH)
        timestamp = datetime.fromtimestamp(mod_time).isoformat()
        
        return EvalsResponse(
            timestamp=timestamp,
            metrics=EvalsMetrics(
                custom_metrics=report.get("custom_metrics", {}),
                ragas_metrics=report.get("ragas_metrics", {})
            )
        )
    except Exception as e:
        logger.error(f"Error reading evaluation report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error reading evaluation report")


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
