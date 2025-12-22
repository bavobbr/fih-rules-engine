from typing import List
from pypdf import PdfReader
from langchain_core.documents import Document
from loaders.base import BaseLoader
import os

class SimpleLocalLoader(BaseLoader):
    """Simple loader that processes PDFs locally using PyPDF."""
    
    def load_and_chunk(self, file_path: str, variant: str, original_filename: str = None) -> List[Document]:
        filename = original_filename or os.path.basename(file_path)
        print(f"--- [SimpleLocalLoader] Processing: {filename} ---")
        
        reader = PdfReader(file_path)
        docs = []
        
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text.strip():
                # Create a chunk per page for simplicity
                docs.append(Document(
                    page_content=text,
                    metadata={
                        "source_file": filename,
                        "page": i + 1,
                        "variant": variant
                    }
                ))
        
        print(f"--- [SimpleLocalLoader] Created {len(docs)} page-based chunks. ---")
        return docs
