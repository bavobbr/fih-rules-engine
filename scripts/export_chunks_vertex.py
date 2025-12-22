"""Export chunks using the Vertex AI Smart Loader (Gemini Structure Analysis)."""
import sys
import os

# Add root to path so we can import loaders
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import loaders
import json
import config

# Config
INPUT_PDF = "docs/fih-rules-of-hockey-June23-update.pdf"
OUTPUT_FILE = "debug_output/vertex_chunks_export.txt"

def export_chunks():
    print(f"--- Exporting Chunks from {INPUT_PDF} using Vertex AI Loader ---")
    print("Strategy: Gemini will analyze structure and Document AI will parse only 'body'/'definitions'.")
    
    # 1. Initialize Loader
    # We explicitly instantiate the Vertex loader to bypass config if needed, 
    # but let's stick to the pattern of setting the strategy if we use the factory,
    # or just import directly.
    from loaders.vertex_ai_loader import VertexAILoader
    loader = VertexAILoader()
    
    # 2. Run Ingestion 
    # Note: No target_pages argument needed, the LLM decides.
    print("Running VertexAILoader...")
    try:
        chunks = loader.load_and_chunk(INPUT_PDF, variant="outdoor")
    except Exception as e:
        print(f"❌ Error during loading: {e}")
        return
    
    print(f"✅ Generated {len(chunks)} chunks.")
    
    # 3. Write to File
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"Source: {INPUT_PDF}\n")
        f.write(f"Loader: VertexAILoader (Gemini + DocAI Batch)\n")
        f.write(f"Total Chunks: {len(chunks)}\n")
        f.write("="*50 + "\n\n")
        
        for i, doc in enumerate(chunks):
            f.write(f"--- Chunk {i} ---\n")
            
            # Format Metadata nicely
            metadata_str = json.dumps(doc.metadata, indent=4)
            f.write(f"METADATA:\n{metadata_str}\n\n")
            
            f.write(f"CONTENT:\n{doc.page_content}\n")
            f.write("\n" + "="*50 + "\n\n")
            
    print(f"✅ Exported details to {OUTPUT_FILE}")

if __name__ == "__main__":
    if not os.path.exists(INPUT_PDF):
        print(f"❌ Input file not found: {INPUT_PDF}")
        sys.exit(1)
        
    export_chunks()
