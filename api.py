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

API_DESCRIPTION = """
Ask questions about the field hockey rules and get an answer grounded in the official FIH rulebooks
(Outdoor, Indoor, Hockey5s), optionally combined with a country's national rules.

## Authentication
`POST /chat` and `GET /evals/latest` require the header `x-api-key: <key>`. A missing header returns
`422`, a wrong key `403`. The other endpoints are public.

## Typical client flow
1. `GET /jurisdictions` once, to fill a country picker. Offer "International" (no country) as the default.
2. `POST /chat` per user message. Send the earlier turns in `history` and the picked country code in `country`.
3. Render `answer` as **Markdown**. Optionally show `source_docs` as expandable sources.

## Answer format
`answer` is Markdown with three labelled sections, each label on its own line:

```
**Direct Answer**
A green card suspension lasts 2 minutes of playing time.

**Key Rules**
- **Rule 14.1**: A green card is a warning with a 2-minute suspension. *(fih-rules-of-hockey-2026-final.pdf, p. 45)*

**Reasoning**
The user asks for the duration of a green card suspension. ...
```

- **Key Rules** bullets start with a bold rule number when known, end with an italic *(file, p. page)* citation,
  and end with `(local rule)` when the rule comes from the selected country's national rules.
  The section is left out when no specific rule applies.
- Off-topic questions, greetings and questions the rules do not cover return **one plain sentence**
  without any section labels.
- The answer is written in the language of the question, and so are the section labels for Dutch and French:

| `language` | Labels | Local rule marker |
|---|---|---|
| `en` (and any other language) | Direct Answer / Key Rules / Reasoning | (local rule) |
| `nl` | Antwoord / Belangrijkste regels / Redenering | (lokale regel) |
| `fr` | Réponse / Règles clés / Raisonnement | (règle locale) |

  The detected language is returned in `language`.

## Hockey variant
The variant (outdoor, indoor or hockey5s) is detected from the question and the history; there is no request
field for it. Mention the variant in the question ("In indoor hockey, ...") to steer it. The detected variant is
returned in `variant`.

## Timing and errors
- A typical answer takes 3-6 seconds. After a period without traffic, the first request can take up to
  ~30 seconds extra (Cloud Run cold start). Use a client timeout of at least 60 seconds.
- `503` means the engine is still starting: retry after a few seconds. `500` is an internal error: show a
  generic "try again" message. Both return `{"detail": "..."}`.
"""

app = FastAPI(
    title="FIH Rules API",
    description=API_DESCRIPTION,
    version="1.2.0",
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
    role: str = Field(..., description="Who sent the message: 'user' or 'assistant'.", examples=["user"])
    content: str = Field(
        ...,
        description="The message text. For 'assistant' messages, send the `answer` you received back unchanged.",
        examples=["How long is a green card suspension?"]
    )

class ChatRequest(BaseModel):
    query: str = Field(..., description="The user's new question.", examples=["And a yellow card?"])
    history: List[Message] = Field(
        default=[],
        description=(
            "Earlier turns of this conversation, oldest first, without the current `query`. "
            "Used to understand follow-ups like 'and a yellow card?'; only the last 4 messages are used. "
            "Send an empty list to start a new conversation."
        ),
        examples=[[
            {"role": "user", "content": "How long is a green card suspension?"},
            {"role": "assistant", "content": "**Direct Answer**\nA green card suspension lasts 2 minutes of playing time."}
        ]]
    )
    country: Optional[str] = Field(
        default=None,
        description=(
            "3-letter country code from `GET /jurisdictions` (e.g. 'BEL') to include that country's national rules, "
            "which override the official rules where they differ. Omit or send null for the international rules only. "
            "An unknown code behaves like no country."
        ),
        examples=["BEL"]
    )

class SourceDoc(BaseModel):
    page_content: str = Field(..., description="The rule text that was given to the model.")
    metadata: Dict[str, Any] = Field(
        ...,
        description=(
            "Where the text comes from. Keys present depend on the source; treat all as optional:\n"
            "- `source_file` (string): document file name\n"
            "- `type` (string): 'official' (FIH rulebook) or 'local' (national rules)\n"
            "- `country` (string): country code, only for local rules\n"
            "- `variant` (string): 'outdoor', 'indoor' or 'hockey5s'\n"
            "- `page` (integer): page number, official rulebooks only\n"
            "- `rule`, `chapter`, `section` (string): position in the official rulebook; "
            "placeholder values like 'N/A' or 'General' mean unknown\n"
            "- `summary` (string): short human-readable label, official rulebooks only\n"
            "Other keys are internal and may change."
        ),
        examples=[{
            "source_file": "fih-rules-of-hockey-2026-final.pdf", "type": "official", "variant": "outdoor",
            "page": 45, "rule": "14.1", "chapter": "PLAYING THE GAME", "section": "14 Personal penalties",
            "summary": "Green, yellow and red card suspensions and their durations."
        }]
    )

class ChatResponse(BaseModel):
    answer: str = Field(
        ...,
        description=(
            "The answer as Markdown: '**Direct Answer**', '**Key Rules**' and '**Reasoning**' sections "
            "(labels translated for Dutch and French), or one plain sentence for off-topic questions. "
            "See the API description for details."
        )
    )
    standalone_query: str = Field(
        ...,
        description="The question rewritten to stand on its own using the history (useful for debugging; no need to show it)."
    )
    variant: str = Field(..., description="Detected hockey variant: 'outdoor', 'indoor' or 'hockey5s'.")
    language: str = Field(
        "en",
        description="ISO 639-1 code of the language the question was asked in, and the answer is written in (e.g. 'en', 'nl', 'fr').",
        examples=["nl"]
    )
    source_docs: List[SourceDoc] = Field(
        ...,
        description="The rule snippets the answer is based on, most relevant first (at most 10). Empty if nothing relevant was found."
    )

class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Human-readable error message.", examples=["Engine not ready"])

class HealthResponse(BaseModel):
    status: str = Field(..., description="'ok' when the engine is ready.", examples=["ok"])

# Error responses shared by the endpoints that need the engine
ENGINE_ERRORS = {
    500: {"model": ErrorResponse, "description": "Internal error. Show a generic 'try again' message."},
    503: {"model": ErrorResponse, "description": "The engine is still starting. Retry after a few seconds."},
}
AUTH_ERRORS = {
    403: {"model": ErrorResponse, "description": "Wrong `x-api-key` header."},
}

class EvalsMetrics(BaseModel):
    custom_metrics: Dict[str, float] = Field(..., description="Custom metrics calculated during evaluation (e.g., accuracy, hit rate)")
    ragas_metrics: Dict[str, float] = Field(..., description="RAGAS-specific metrics (e.g., faithfulness, answer relevancy)")

class EvalsResponse(BaseModel):
    timestamp: str = Field(..., description="ISO 8601 timestamp of when the evaluation report was generated")
    metrics: EvalsMetrics = Field(..., description="The evaluation metrics")

def get_engine():
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    return engine

# --- Endpoints ---

REPORT_PATH = "evals/report_latest.json"

@app.get(
    "/health", response_model=HealthResponse, tags=["System"], summary="Health Check",
    response_description="Service health status",
    responses={503: ENGINE_ERRORS[503]}
)
async def health_check():
    """
    Check if the API and the RAG engine are initialized and healthy.

    Returns a 200 status if healthy, or 503 if the engine is not initialized.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    return HealthResponse(status="ok")

@app.post(
    "/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)], tags=["Chat"],
    summary="Ask a rules question", response_description="Markdown answer with the rule snippets it is based on",
    responses={**AUTH_ERRORS, **ENGINE_ERRORS}
)
async def chat(request: ChatRequest):
    """
    Answer a field hockey rules question.

    The question is combined with the history to resolve follow-ups, the hockey variant is detected,
    the official rules (plus the national rules of `country`, if given) are searched, and an answer is
    written from the best-matching rules only. See the API description for the `answer` format.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    try:
        # Convert Pydantic models to dicts/tuples expected by engine
        history_list = [(m.role, m.content) for m in request.history]
        
        # Pass country code to engine
        result = engine.query(request.query, history=history_list, country_code=request.country)
        
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
            language=result.get("language", "en"),
            source_docs=source_docs_data
        )
        
    except Exception as e:
        logger.error(f"Error processing chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

class Jurisdiction(BaseModel):
    code: str = Field(..., description="ISO 3-letter country code (e.g. 'BEL')")
    name: str = Field(..., description="Full country name (e.g. 'Belgium')")

@app.get(
    "/jurisdictions", response_model=List[Jurisdiction], tags=["System"], summary="List Available Jurisdictions",
    response_description="List of countries with local rules ingested, sorted by name",
    responses=ENGINE_ERRORS
)
async def get_jurisdictions():
    """
    List all jurisdictions (countries) that have local rules currently ingested in the knowledge base.
    
    Returns a list of objects containing the country code and full name. Use `code` as the `country`
    field of `POST /chat`. "International" (official rules only) is not in the list: offer it as the
    default choice yourself.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    try:
        results = engine.list_jurisdictions()
        return [Jurisdiction(code=item["code"], name=item["name"]) for item in results]
    except Exception as e:
        logger.error(f"Error fetching jurisdictions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch jurisdictions")

class DocumentStat(BaseModel):
    source_file: str = Field(..., description="The name of the source document (PDF, Word or text file)")
    variant: str = Field(..., description="The ruleset variant (e.g., 'outdoor')")
    country: str = Field(..., description="The country code or 'Official' for global rules")
    chunk_count: int = Field(..., description="Number of text chunks generated from this file")

@app.get(
    "/knowledge-base", response_model=List[DocumentStat], tags=["System"], summary="List Knowledge Base Documents",
    response_description="List of all ingested source documents",
    responses=ENGINE_ERRORS
)
async def get_knowledge_base():
    """
    List all source documents currently ingested in the knowledge base.
    
    For each document, returns the filename, variant, applicable country (or 'Official'), 
    and the number of chunks.
    """
    if engine is None:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    try:
        # engine.db is accessible directly
        stats = engine.db.get_source_stats()
        return [
            DocumentStat(
                source_file=item["source_file"],
                variant=item["variant"],
                country=item["country"],
                chunk_count=item["chunk_count"]
            )
            for item in stats
        ]
    except Exception as e:
        logger.error(f"Error fetching knowledge base stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch knowledge base stats")

@app.get(
    "/evals/latest", response_model=EvalsResponse, dependencies=[Depends(verify_api_key)], tags=["Evals"],
    summary="Get Latest Metrics", response_description="Latest evaluation report metrics",
    responses={**AUTH_ERRORS, 404: {"model": ErrorResponse, "description": "No evaluation report available."}, 500: ENGINE_ERRORS[500]}
)
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
