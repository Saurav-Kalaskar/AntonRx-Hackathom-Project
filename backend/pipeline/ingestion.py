import json
import logging
import re
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Heuristic patterns for exclusions
EXCLUSION_PATTERNS = [
    r"\bmedicare\b",
    r"\bmedicaid\b",
    r"\bstandard\s+pharmacy\s+benefit\b"
]

def load_schema(schema_path: str = "backend/schema/policy.json") -> Dict[str, Any]:
    with open(schema_path, "r") as f:
        return json.load(f)

def is_excluded(text: str) -> bool:
    """
    Apply heuristic exclusion filtering.
    Silently drop all data pertaining to Medicare, Medicaid, and standard pharmacy benefits.
    """
    text_lower = text.lower()
    for pattern in EXCLUSION_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False

def validate_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    """
    Basic validator enforcing the fields and types specified in the schema.
    In production, use jsonschema or Pydantic.
    """
    required_fields = schema.get("required", [])
    for field in required_fields:
        if field not in data:
            logger.warning(f"Validation failed: Missing required field '{field}'")
            return False
            
    # Example logic: ensure access_status is correct
    if data.get("access_status") not in ["Preferred", "Non-Preferred"]:
         logger.warning("Validation failed: Invalid access_status")
         return False
         
    return True

def push_to_dlq(data: Dict[str, Any], raw_text: str):
    """
    Dead-Letter Queue insertion for schema validation failures.
    """
    logger.info("Record pushed to Dead-Letter Queue (DLQ).")
    # DLQ implementation (e.g., SQS, DynamoDB, or local file)
    with open("backend/pipeline/dlq.jsonl", "a") as f:
        json.dump({"raw": raw_text, "extracted": data}, f)
        f.write("\n")

def process_document(raw_text: str, extracted_data: Dict[str, Any]):
    """
    Process an ingested document:
    1. Check if excluded.
    2. Validate against strict schema.
    3. Output to persistent storage or DLQ.
    """
    if is_excluded(raw_text):
        logger.info("Document excluded based on heuristic (Medicare/Medicaid/Pharmacy Benefit).")
        return None
        
    schema = load_schema()
    
    if validate_schema(extracted_data, schema):
        logger.info("Document successfully validated. Ready for Vector DB ingestion.")
        return extracted_data
    else:
        push_to_dlq(extracted_data, raw_text)
        return None

if __name__ == "__main__":
    # Test execution
    test_text = "This policy covers Keytruda for Oncology. No medicare patients."
    test_data = {
        "drug_name": "Keytruda",
        "access_status": "Preferred"
    }
    process_document(test_text, test_data)
