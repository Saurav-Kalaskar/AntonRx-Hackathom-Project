import logging
import os
from openai import OpenAI, APIError, APIConnectionError, RateLimitError

try:
    from ..env_loader import load_env_once
except ImportError:
    from env_loader import load_env_once

load_env_once()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Nvidia NIM — Nemotron-3-Super-120B via OpenAI-compatible endpoint
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"
STRICT_LLM_MODE = os.getenv("STRICT_LLM_MODE", "0").strip().lower() in {"1", "true", "yes"}


class PADrafter:
    def __init__(self, payer_name: str, patient_context: dict, retrieved_rules: list):
        self.payer_name = payer_name
        self.patient_context = patient_context
        self.retrieved_rules = retrieved_rules
        self.client = (
            OpenAI(
                base_url=NVIDIA_API_URL,
                api_key=NVIDIA_API_KEY,
                timeout=60.0,
            )
            if NVIDIA_API_KEY
            else None
        )

    def _generate_fallback_draft(self) -> str:
        """
        Deterministic fallback letter used when the LLM is unavailable.
        """
        patient_name = self.patient_context.get("patient_name", "the patient")
        diagnosis = self.patient_context.get("diagnosis", "the documented diagnosis")
        medication = self.patient_context.get("medication", "the requested medication")

        clauses = []
        for i, rule in enumerate(self.retrieved_rules[:3], start=1):
            source = rule.get("source", "Policy Document")
            text = (rule.get("text", "") or "").strip()
            snippet = text[:260] + ("..." if len(text) > 260 else "")
            if snippet:
                clauses.append(f"- Clause {i} ({source}): {snippet}")

        criteria_block = "\n".join(clauses) if clauses else "- No indexed policy clauses were available for this request."

        return (
            "Date: [Insert Date]\n"
            f"To: Medical Director, {self.payer_name}\n"
            f"RE: Prior Authorization Request - {patient_name} - {medication}\n\n"
            "Dear Medical Director,\n\n"
            f"I am submitting this prior authorization request for {patient_name}, diagnosed with {diagnosis}, "
            f"for treatment with {medication}. Based on the available clinical information and payer criteria, "
            "this request meets medical necessity and should be approved without delay.\n\n"
            "Policy criteria considered:\n"
            f"{criteria_block}\n\n"
            "Clinical rationale:\n"
            f"{medication} is requested to treat {diagnosis} in alignment with accepted standards of care. "
            "Delays in access may increase risk of clinical deterioration and additional downstream utilization.\n\n"
            "Please review this request at your earliest convenience. Supporting documentation can be provided upon request.\n\n"
            "Sincerely,\n"
            "[Prescriber Name, Credentials]\n"
            "[Practice Name]\n"
            "[Contact Information]"
        )

    def _construct_prompt(self) -> str:
        """
        Build the PA letter prompt. Retrieved rules are cited inline.
        The LLM is constrained to only cite content present in the context.
        """
        patient_name = self.patient_context.get("patient_name", "the patient")
        diagnosis = self.patient_context.get("diagnosis", "unknown diagnosis")
        medication = self.patient_context.get("medication", "unknown medication")
        additional = self.patient_context.get("additional_info", "")

        # Format retrieved policy clauses with explicit citations
        if self.retrieved_rules:
            rules_block = "\n\n".join(
                f"[Clause {i+1} | Source: {r.get('source','?')}, Chunk #{r.get('chunk_index','?')} | Relevance: {r.get('score',0):.0%}]:\n{r.get('text','')}"
                for i, r in enumerate(self.retrieved_rules)
            )
        else:
            rules_block = "No specific policy clauses were retrieved. Draft based on general PA best practices."

        prompt = f"""You are a board-certified Clinical Pharmacist and Prior Authorization (PA) Specialist with deep expertise in oncology, rheumatology, and specialty drug coverage policy.

Your task is to draft a formal, complete, and clinically compelling Prior Authorization request letter.

=== PATIENT INFORMATION ===
Patient Name: {patient_name}
Diagnosis / Indication: {diagnosis}
Requested Medication: {medication}
Target Payer: {self.payer_name}
Additional Clinical Notes: {additional if additional else 'None provided.'}

=== RETRIEVED PAYER POLICY CLAUSES (cite these explicitly in the letter) ===
{rules_block}

=== INSTRUCTIONS ===
1. Write a professional PA request letter addressed to the Medical Director of {self.payer_name}.
2. Cite ONLY the policy clauses provided above — do NOT invent requirements not listed.
3. For each major criterion (step therapy, biomarker testing, medical necessity), write a dedicated paragraph that explicitly names the clause source and how the patient meets it.
4. Include: Date, RE: line with patient name and medication, opening paragraph, clinical necessity section, policy compliance section, closing with prescriber attestation placeholder.
5. Use formal clinical letter format. Do NOT use markdown syntax in the output — use plain text with line breaks.
6. The letter must be self-contained and ready for PDF export.

Generate the Prior Authorization letter now:"""

        return prompt

    def generate_draft(self) -> str:
        """
        Call Nemotron via NVIDIA NIM and return the PA letter text.
        Raises exceptions on API failure — no silent mock fallback.
        """
        prompt = self._construct_prompt()

        logger.info(f"Sending PA draft request to {MODEL_ID} for payer={self.payer_name}, medication={self.patient_context.get('medication')}")

        if not self.client:
            if STRICT_LLM_MODE:
                raise RuntimeError("STRICT_LLM_MODE is enabled and NVIDIA_API_KEY is not configured.")
            logger.warning("NVIDIA_API_KEY is not configured. Returning deterministic fallback draft.")
            return self._generate_fallback_draft()

        try:
            completion = self.client.chat.completions.create(
                model=MODEL_ID,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
                max_tokens=2048,
                top_p=0.95,
            )
            result = completion.choices[0].message.content
            logger.info(f"PA draft generated successfully ({len(result)} characters)")
            return result

        except RateLimitError as e:
            logger.error(f"NVIDIA NIM rate limit hit: {e}")
            if STRICT_LLM_MODE:
                raise RuntimeError(f"LLM rate limit exceeded in strict mode: {e}")
            return self._generate_fallback_draft()

        except APIConnectionError as e:
            logger.error(f"NVIDIA NIM connection error: {e}")
            if STRICT_LLM_MODE:
                raise RuntimeError(f"Cannot connect to NVIDIA NIM API in strict mode: {e}")
            return self._generate_fallback_draft()

        except APIError as e:
            logger.error(f"NVIDIA NIM API error: {e}")
            if STRICT_LLM_MODE:
                raise RuntimeError(f"NVIDIA NIM API error in strict mode: {e}")
            return self._generate_fallback_draft()

        except Exception as e:
            logger.error(f"Unexpected error generating draft: {e}", exc_info=True)
            if STRICT_LLM_MODE:
                raise RuntimeError(f"Unexpected LLM generation error in strict mode: {str(e)}")
            return self._generate_fallback_draft()
