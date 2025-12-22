
import sys
import os
import json
import random
from typing import List, Dict

# Add parent dir to path to allow importing app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from database import PostgresVectorDB
from langchain_google_vertexai import VertexAI
from logger import get_logger

logger = get_logger(__name__)

def generate_qa_pairs(limit: int = 10, variant: str = "indoor") -> List[Dict]:
    """
    Fetches random chunks from the DB and uses an LLM to generate 
    QA pairs for them.
    """
    db = PostgresVectorDB()
    llm = VertexAI(
        model_name=config.LLM_MODEL,
        project=config.PROJECT_ID,
        location=config.REGION,
        temperature=0.4 # Slightly creative for question generation
    )

    logger.info(f"Fetching random chunks for variant '{variant}'...")
    
    # We need a method to get random chunks. 
    # Current DB class only has search. We will add a helper query here directly 
    # using the engine's pool for simplicity.
    with db.pool.connect() as conn:
        from sqlalchemy import text
        # Sample random rows
        # Note: TABLESAMPLE is fast but requires non-zero rows. 
        # Fallback to simple RANDOM() sort for small datasets.
        sql = text(rf"""
            SELECT content, metadata 
            FROM {config.TABLE_NAME} 
            WHERE variant = :variant 
            AND (
                -- Match headings like "9.12", "Rule 9.1", "Rule 10"
                -- Postgres regex for "Starts with Rule<space>Digit OR Digit.Digit"
                metadata->>'heading' ~* '^(Rule\s+[0-9]+|[0-9]+\.[0-9]+)'
            )
            ORDER BY RANDOM() 
            LIMIT :limit
        """)
        results = conn.execute(sql, {"variant": variant, "limit": limit}).fetchall()
    
    qa_dataset = []
    
    logger.info(f"Generating questions for {len(results)} chunks...")
    
    for row in results:
        content = row[0]
        metadata = row[1]
        
        # Heading context if available
        heading = metadata.get('heading', 'Rule')
        
        prompt = f"""
        You are an expert examiner for Field Hockey Rules.
        Your goal is to create a difficult question based on the text below.
        
        TEXT:
        {content}
        
        VARIANT: {variant}
        
        INSTRUCTIONS:
        1. Write a specific question that can be answered primarily using this text.
        2. **CRITICAL: You MUST explicitly mention "{variant}" in the question text** (e.g. "In {variant} hockey, what is...").
        3. Provide the correct answer based on the text.
        4. Output JSON format only: {{"question": "...", "answer": "..."}}
        
        JSON Output:
        """
        
        try:
            response = llm.invoke(prompt).strip()
            
            qa = parse_json_response(response)
            
            entry = {
                "question": qa.get("question"),
                "ground_truth": qa.get("answer"),
                "source_text": content,
                "context_guidance": f"Derived from {heading}",
                "variant": variant
            }
            qa_dataset.append(entry)
            print(f"Generated: {entry['question']}")
            
        except Exception as e:
            logger.error(f"Failed to generate QA for chunk: {e}")
            
    return qa_dataset

def parse_json_response(response_text: str) -> Dict:
    """Parses LLM JSON output, handling markdown code blocks."""
    cleaned = response_text.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)

import argparse

if __name__ == "__main__":
    # CLI entrypoint
    parser = argparse.ArgumentParser(description="Generate Golden Dataset from DB chunks.")
    parser.add_argument("--limit", type=int, default=10, help="Number of questions to generate")
    parser.add_argument("--variant", type=str, default="indoor", help="Ruleset variant (indoor, outdoor, hockey5s)")
    args = parser.parse_args()

    output_file = "evals/generated_dataset.json"
    
    logger.info(f"Starting dataset generation for variant '{args.variant}' (limit={args.limit})...")
    new_dataset = generate_qa_pairs(limit=args.limit, variant=args.variant)
    
    # Load existing if available to append
    existing_dataset = []
    if os.path.exists(output_file):
        try:
            with open(output_file, "r") as f:
                existing_dataset = json.load(f)
        except json.JSONDecodeError:
            pass # corrupted or empty file
            
    final_dataset = existing_dataset + new_dataset
    
    with open(output_file, "w") as f:
        json.dump(final_dataset, f, indent=2)
        
    logger.info(f"Added {len(new_dataset)} new pairs. Total: {len(final_dataset)} saved to {output_file}")
