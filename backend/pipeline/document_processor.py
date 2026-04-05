import PyPDF2
import os
import logging
import sys
from typing import List, Dict, Any

# Add the pipeline directory to the path to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from ingestion import process_document
import json
import os

def load_schema(schema_path: str = None) -> dict:
    """
    Load the JSON schema for validation.
    """
    if schema_path is None:
        # Default to the schema file in the backend/schema directory relative to this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        schema_path = os.path.join(current_dir, "..", "schema", "policy.json")

    with open(schema_path, "r") as f:
        return json.load(f)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_text_from_file(file_path: str) -> str:
    """
    Extract text content from a file (PDF or TXT).
    """
    try:
        if file_path.lower().endswith('.pdf'):
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n"
                return text
        elif file_path.lower().endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            logger.warning(f"Unsupported file type: {file_path}")
            return ""
    except Exception as e:
        logger.error(f"Error extracting text from file {file_path}: {e}")
        return ""

def process_document_file(file_path: str) -> Dict[str, Any]:
    """
    Process a single document file through the ingestion pipeline.
    """
    logger.info(f"Processing document: {file_path}")

    # Extract text from file
    raw_text = extract_text_from_file(file_path)

    if not raw_text.strip():
        logger.warning(f"No text extracted from {file_path}")
        return None

    # For now, we'll create a basic extracted data structure
    # In a real implementation, this would use NLP to extract structured data
    extracted_data = {
        "drug_name": "Unknown",  # Would be extracted from text
        "drug_category": "Unknown",  # Would be extracted from text
        "access_status": "Preferred",  # Default, would be determined from text
        "covered_indications": ["Unknown"],  # Would be extracted from text
        "pa_requirements": "See document for details",  # Would be extracted from text
        "step_therapy_requirements": "See document for details",  # Would be extracted from text
        "site_of_care_restrictions": "See document for details",  # Would be extracted from text
        "dosing_limits": "See document for details",  # Would be extracted from text
        "effective_dates": "See document for details"  # Would be extracted from text
    }

    # Process through ingestion pipeline (with local schema loading)
    try:
        schema = load_schema()
        processed_data = process_document(raw_text, extracted_data)
    except Exception as e:
        logger.error(f"Error in ingestion pipeline: {e}")
        # If ingestion fails, return the extracted data anyway for now
        processed_data = extracted_data

    if processed_data:
        logger.info(f"Successfully processed document: {file_path}")
        return processed_data
    else:
        logger.warning(f"Document failed validation: {file_path}")
        return None

def load_and_process_all_documents(documents_dir: str = "./documents") -> List[Dict[str, Any]]:
    """
    Load and process all documents (PDF and TXT) in the specified directory.
    """
    processed_documents = []

    if not os.path.exists(documents_dir):
        logger.warning(f"Documents directory does not exist: {documents_dir}")
        return processed_documents

    # Support both PDF and TXT files
    files = [f for f in os.listdir(documents_dir)
             if f.lower().endswith('.pdf') or f.lower().endswith('.txt')]

    if not files:
        logger.info(f"No supported files found in {documents_dir}")
        return processed_documents

    logger.info(f"Found {len(files)} files to process")

    for file_name in files:
        file_path = os.path.join(documents_dir, file_name)
        processed_data = process_document_file(file_path)

        if processed_data:
            processed_documents.append(processed_data)

    logger.info(f"Successfully processed {len(processed_documents)} documents")
    return processed_documents

if __name__ == "__main__":
    # Test the document processor
    documents = load_and_process_all_documents()
    print(f"Processed {len(documents)} documents")
    for i, doc in enumerate(documents):
        print(f"Document {i+1}: {doc}")