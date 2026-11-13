import os
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
        """Reads a PDF, Word (.docx) or text file and returns sequential chunks."""

        # Determine file type from the original name (admin uploads arrive as extension-less temp files)
        extension = os.path.splitext(original_filename or file_path)[1].lower()

        text_content = ""
        if extension == ".pdf":
            from pypdf import PdfReader
            try:
                reader = PdfReader(file_path)
                for page in reader.pages:
                    text_content += page.extract_text() + "\n"
            except Exception as e:
                raise ValueError(f"Failed to read PDF {file_path}: {e}")
        elif extension == ".docx":
            try:
                text_content = self._read_docx(file_path)
            except Exception as e:
                raise ValueError(f"Failed to read Word file {file_path}: {e}")
        elif extension == ".txt":
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = f.read()
            except Exception as e:
                 raise ValueError(f"Failed to read text file {file_path}: {e}")
        else:
            raise ValueError(f"Unsupported file type '{extension}'. Use .pdf, .docx or .txt.")

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
                doc.metadata["source_file"] = original_filename
            final_docs.append(doc)

        return final_docs

    @staticmethod
    def _read_docx(file_path: str) -> str:
        """Extract body paragraphs and tables in document order. Table rows become 'cell | cell'."""
        import docx  # admin-only dependency (requirements-dev.txt)
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(file_path)
        lines = []
        for element in document.element.body.iterchildren():
            if element.tag.endswith("}p"):
                text = Paragraph(element, document).text.strip()
                if text:
                    lines.append(text)
            elif element.tag.endswith("}tbl"):
                for row in Table(element, document).rows:
                    cells = []
                    for cell in row.cells:
                        text = cell.text.strip()
                        # Merged cells repeat their text in every spanned column
                        if text and (not cells or cells[-1] != text):
                            cells.append(text)
                    if cells:
                        lines.append(" | ".join(cells))
        return "\n".join(lines)
