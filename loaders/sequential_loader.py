from typing import List, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loaders.base import BaseLoader
from loaders.utils import clean_text

class SequentialLoader(BaseLoader):
    """
    Simple loader that chunks text sequentially by character count.
    Used for unstructured local rule appendices where document structure is weak.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_and_chunk(self, file_path: str, variant: str, original_filename: str = None) -> List[Document]:
        """Reads a text/PDF file and returns sequential chunks."""
        
        # Determine file type and extract text
        text_content = ""
        is_pdf = file_path.lower().endswith(".pdf")
        if original_filename and original_filename.lower().endswith(".pdf"):
            is_pdf = True

        if is_pdf:
            from pypdf import PdfReader
            try:
                reader = PdfReader(file_path)
                for page in reader.pages:
                    text_content += page.extract_text() + "\n"
            except Exception as e:
                raise ValueError(f"Failed to read PDF {file_path}: {e}")
        else:
            # Assume plain text for now
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = f.read()
            except Exception as e:
                 raise ValueError(f"Failed to read text file {file_path}: {e}")

        if not text_content:
            return []

        # Clean basic noise
        text_content = clean_text(text_content)

        # Split
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
        
        chunks = splitter.create_documents([text_content])

        # Post-process: Add 'variant' only (rag_engine adds the rest)
        # We don't have rich structure here, so no 'rule' or 'chapter' metadata usually.
        final_docs = []
        for doc in chunks:
            doc.metadata["variant"] = variant
            if original_filename:
                doc.metadata["source"] = original_filename
            final_docs.append(doc)
            
        return final_docs
