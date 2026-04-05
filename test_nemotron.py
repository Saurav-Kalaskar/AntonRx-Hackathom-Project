import json
from backend.generator.drafter import PADrafter

def test_nemotron():
    drafter = PADrafter(
        payer_name="Aetna",
        patient_context={"patient_name": "Jane Doe", "diagnosis": "NSCLC", "pd_l1": "Positive"},
        retrieved_rules=[
            {"text": "Keytruda is covered for NSCLC if PD-L1 is positive and patient has failed platinum-based chemotherapy.", "source": "Aetna Medical Policy 123"}
        ]
    )
    
    print("Sending request to Nvidia API via PADrafter...")
    try:
        output = drafter.generate_draft()
        print("SUCCESS! Output from Nemotron:")
        print(output)
    except Exception as e:
        print(f"FAILED: {str(e)}")
        if hasattr(e, 'response') and e.response:
            print(e.response.text)

if __name__ == "__main__":
    test_nemotron()
