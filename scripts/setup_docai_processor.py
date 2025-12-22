"""Provision a Document AI OCR Processor (Idempotent)."""
from google.cloud import documentai
from google.api_core.client_options import ClientOptions
import os

PROJECT_ID = "langchain-poc-479114"
LOCATION = "us"  # Document AI locations are 'us' or 'eu'

def get_or_create_processor():
    # You must set the api_endpoint if you use a location other than 'us'.
    opts = ClientOptions(api_endpoint=f"{LOCATION}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)

    parent = client.common_location_path(PROJECT_ID, LOCATION)
    print(f"Listing processors in {parent}...")

    # 1. List existing
    processors = client.list_processors(parent=parent)
    ocr_processor = None
    
    for p in processors:
        if p.type_ == "OCR_PROCESSOR" and p.state == documentai.Processor.State.ENABLED:
            ocr_processor = p
            break
            
    if ocr_processor:
        print(f"Found existing processor: {ocr_processor.name}")
        return ocr_processor.name

    # 2. Create if not found
    print("No enabled OCR processor found. Creating one...")
    processor = documentai.Processor(
        display_name="fih-rag-ocr",
        type_="OCR_PROCESSOR"
    )
    
    try:
        created_processor = client.create_processor(
            parent=parent,
            processor=processor
        )
        print(f"Created processor: {created_processor.name}")
        return created_processor.name
    except Exception as e:
        print(f"Failed to create processor: {e}")
        return None

if __name__ == "__main__":
    name = get_or_create_processor()
    if name:
        # name format: projects/PROJECT_ID/locations/LOCATION/processors/PROCESSOR_ID
        print(f"FULL_PROCESSOR_NAME={name}")
        processor_id = name.split("/")[-1]
        print(f"PROCESSOR_ID={processor_id}")
