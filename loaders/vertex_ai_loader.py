import io
import json
import uuid
from typing import List, Dict, Any
from google.cloud import storage, documentai
from google import genai
from google.genai import types
from langchain_core.documents import Document
from pypdf import PdfWriter, PdfReader

from loaders.base import BaseLoader
from loaders.document_ai_common import DocumentAILayoutMixin
from loaders.utils import summarize_text
import config

class VertexAILoader(BaseLoader, DocumentAILayoutMixin):
    """
    Intelligent Loader that uses Vertex AI (Gemini) to analyze document structure
    and filter relevant pages before processing them with Document AI.
    """
    
    def __init__(self, bucket_name: str = None):
        self.bucket_name = bucket_name or config.GCS_BUCKET_NAME
        self.client = storage.Client()
        
        # Initialize Google Gen AI Client (Vertex AI mode)
        self.genai_client = genai.Client(
            vertexai=True, 
            project=config.PROJECT_ID, 
            location=config.REGION,
            http_options=types.HttpOptions(api_version="v1")
        )
        # self.docai_loader is not needed as we implement custom batch logic here


    def load_and_chunk(self, file_path: str, variant: str, original_filename: str = None) -> List[Document]:
        """
        1. Analyze PDF Structure with Gemini.
        2. Filter for 'body' or 'definitions' pages.
        3. Split PDF to keep only relevant pages.
        4. process filtered PDF via Document AI (Batch).
        """
        original_filename = original_filename or file_path.split("/")[-1]
        print(f"--- [VertexAILoader] Processing: {original_filename} ---")
        
        # 1. Structure Analysis
        print(f"--- [VertexAILoader] Analyzing structure with Gemini... ---")
        structure_map = self._analyze_structure(file_path)
        
        # 2. Identify Relevant Pages
        valid_ranges = [
            s for s in structure_map.get("sections", [])
            if s.get("content_type") in ["body", "definitions", "specifications"]
        ]
        
        if not valid_ranges:
            print("--- [VertexAILoader] Warning: No 'body' or 'definitions' found. Processing entire doc? No, falling back to 'body' assumption for all.")
            # Fallback strategy? For now, let's just error or process everything if fails.
            # But let's assume Gemini works.
            
        print(f"--- [VertexAILoader] Identified {len(valid_ranges)} relevant sections. ---")

        # 3. Create Filtered PDF (In-Memory)
        filtered_pdf_bytes, page_mapping = self._create_filtered_pdf(file_path, valid_ranges)
        
        if not filtered_pdf_bytes:
             print("--- [VertexAILoader] No pages selected. Returning empty. ---")
             return []

        # 4. Upload & Process (Delegating to DocAI Batch)
        # We need to upload this bytes object to GCS temporarily
        temp_filename = f"temp_vertex_filtered_{uuid.uuid4()}.pdf"
        temp_gcs_uri = self._upload_bytes_to_gcs(filtered_pdf_bytes, temp_filename)
        
        print(f"--- [VertexAILoader] Uploaded filtered PDF to {temp_gcs_uri} ---")
        
        try:
            # We reuse the batch loader's core logic but we need to intercept the output 
            # to fix page numbers using `page_mapping`.
            # Since DocumentAIBatchLoader.load_and_chunk takes a file path, we might need 
            # a lower-level method or just subclass behavior. 
            # ACTUALLY: We can just use the internal helper if we expose it, 
            # or just replicate `process_batch` logic here to keep it clean.
            # Let's call the helper `_process_batch` if we can refactor `DocumentAIBatchLoader` 
            # to be more composed. 
            # 
            # For now, let's implement the batch call directly here to avoid tight coupling 
            # with private methods of another class, but reusing the Mixin.
            
            raw_documents = self._process_batch_with_retry(temp_gcs_uri)
            
            # 5. Chunking & Remapping
            # Create a page configuration map for the chunker
            page_config = {}
            # We need to map filtered page indices to their content types
            # filtered_page_index 0 -> page_mapping[0] (original page)
            # find which section in valid_ranges contains original page
            for i, original_page in enumerate(page_mapping):
                filtered_page_num = i + 1
                content_type = "body" # Default
                for s in valid_ranges:
                     if s["start_page"] <= original_page <= s["end_page"]:
                          content_type = s["content_type"]
                          break
                page_config[filtered_page_num] = {"content_type": content_type}

            chunks = self._layout_chunking(raw_documents, variant, page_config=page_config)
            
            # Remap Pages
            for chunk in chunks:
                filtered_page_index = chunk.metadata.get("page", 0) - 1 # 0-indexed in list
                
                # Safety check
                if 0 <= filtered_page_index < len(page_mapping):
                     original_page_num = page_mapping[filtered_page_index]
                     chunk.metadata["page"] = original_page_num
                     chunk.metadata["source"] = f"{original_filename} (Vertex AI Filtered)"
                else:
                    # Keep as is if out of bounds (shouldn't happen)
                    pass

            # Summarization Step (parity with DocumentAIBatchLoader)
            print(f"--- [VertexAILoader] Summarizing {len(chunks)} chunks... ---")
            for chunk in chunks:
                chunk.metadata["summary"] = summarize_text(chunk.page_content)
                if "source_file" not in chunk.metadata:
                     chunk.metadata["source_file"] = original_filename

            return chunks
            
        finally:
            # Cleanup
            self._delete_gcs_blob(temp_filename)

    def _analyze_structure(self, file_path: str) -> Dict[str, Any]:
        """Call Gemini 1.5 Pro to map the PDF."""
        model_name = config.LLM_MODEL
        
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
            
        # Define Schema using new Types
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "sections": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "section_name": {"type": "STRING"},
                            "start_page": {"type": "INTEGER"},
                            "end_page": {"type": "INTEGER"},
                            "content_type": {
                                "type": "STRING", 
                                "enum": ["intro", "toc", "definitions", "body", "specifications", "outro"]
                            }
                        },
                        "required": ["section_name", "start_page", "end_page", "content_type"]
                    }
                }
            },
            "required": ["sections"]
        }
        
        prompt = """
        Analyze the document structure of the attached FIH Rules of Hockey PDF. 
        Map every page to a section. 
        Identify the main body (where the actual playing rules start) as 'body'.
        Identify the definitions section as 'definitions'.
        Everything else (Preface, Contents, Advertising, End notes) should be 'intro' or 'outro'.
        """
        
        try:
            response = self.genai_client.models.generate_content(
                model=model_name,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                            types.Part.from_text(text=prompt)
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema
                )
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"--- [VertexAILoader] Gemini Analysis Failed: {e} ---")
            return {"sections": [{"start_page": 1, "end_page": 999, "content_type": "body"}]}

    def _create_filtered_pdf(self, file_path: str, sections: List[Dict]) -> (bytes, List[int]):
        """
        Splits PDF and returns (bytes, list_of_original_page_numbers).
        """
        reader = PdfReader(file_path)
        writer = PdfWriter()
        page_mapping = [] # Index i in new PDF -> Original Page Number
        
        total_pages = len(reader.pages)
        
        # Collect all pages to keep
        pages_to_keep = set()
        for section in sections:
            start = section.get("start_page", 1)
            end = section.get("end_page", 1)
            # Handle potential 1-based indexing from LLM
            # Usually users say "Page 1 to 5".
            # PDFReader is 0-indexed.
            
            for p in range(start, end + 1):
                if 1 <= p <= total_pages:
                    pages_to_keep.add(p)
        
        sorted_pages = sorted(list(pages_to_keep))
        
        for p_num in sorted_pages:
            writer.add_page(reader.pages[p_num - 1])
            page_mapping.append(p_num)
            
        output_stream = io.BytesIO()
        writer.write(output_stream)
        return output_stream.getvalue(), page_mapping

    def _upload_bytes_to_gcs(self, data: bytes, destination_blob_name: str) -> str:
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_string(data, content_type="application/pdf")
        return f"gs://{self.bucket_name}/{destination_blob_name}"

    def _delete_gcs_blob(self, blob_name: str):
        try:
            bucket = self.client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            blob.delete()
        except Exception as e:
            print(f"Warning: Failed to delete temp blob {blob_name}: {e}")

    def _process_batch_with_retry(self, gcs_uri: str) -> List[documentai.Document]:
        """
        Reuses DocumentAIBatchLoader logic to run the actual job.
        We instantiate it internally.
        """
        # We need to bypass the 'upload' part of the BatchLoader and just call the process method.
        # But `process_new_file` in BatchLoader expects a LOCAL file content to upload.
        # We already have it in GCS.
        # We need to call `batch_process_documents` directly on the processor.
        
        # Let's borrow the logic from `DocumentAIBatchLoader._batch_process_request`
        # Or better, we can modify `DocumentAIBatchLoader` to accept a GCS URI directly?
        # No, let's just implement the client call here to be self-contained for this feature.
        
        opts = {"api_endpoint": f"{config.DOCAI_LOCATION}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(client_options=opts)
        
        # Input Config
        gcs_doc = documentai.GcsDocument(gcs_uri=gcs_uri, mime_type="application/pdf")
        gcs_documents = documentai.GcsDocuments(documents=[gcs_doc])
        input_config = documentai.BatchDocumentsInputConfig(gcs_documents=gcs_documents)
        
        # Output Config
        # We need a temp output folder
        output_prefix = f"vertex_loader_output/{uuid.uuid4()}"
        output_uri = f"gs://{self.bucket_name}/{output_prefix}"
        
        output_config = documentai.DocumentOutputConfig(
            gcs_output_config={"gcs_uri": output_uri}
        )
        
        name = client.processor_path(config.PROJECT_ID, config.DOCAI_LOCATION, config.DOCAI_PROCESSOR_ID)
        
        request = documentai.BatchProcessRequest(
            name=name,
            input_documents=input_config,
            document_output_config=output_config,
        )
        
        print("--- [VertexAILoader] Starting Batch Operation... ---")
        operation = client.batch_process_documents(request=request)
        operation.result(timeout=300) # Wait
        print("--- [VertexAILoader] Batch Operation Complete. Fetching results... ---")
        
        # Fetch Results
        return self._fetch_shards_from_gcs(output_prefix)

    def _fetch_shards_from_gcs(self, prefix: str) -> List[documentai.Document]:
        shards = []
        blobs = list(self.client.list_blobs(self.bucket_name, prefix=prefix))
        
        # Filter for JSON
        json_blobs = [b for b in blobs if b.name.endswith(".json")]
        
        for blob in json_blobs:
            content = blob.download_as_bytes()
            shards.append(documentai.Document.from_json(content, ignore_unknown_fields=True))
            
        # Cleanup output
        for blob in blobs:
            try:
                 blob.delete()
            except: pass
            
        # Sort shards by page number just in case
        # (Though `_layout_chunking` handles list of shards, sort order helps)
        return shards
