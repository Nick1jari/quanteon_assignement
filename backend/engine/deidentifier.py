"""
De-identification Engine using Claude API.

Flow (Synthetic mode):
  1. Faker generates a seeded synthetic patient identity (reproducible per filename).
  2. Claude receives the document + synthetic identity hints in the prompt.
  3. Claude detects ALL PHI and replaces using the hinted values where applicable.
  4. Structured JSON is parsed and returned.

Flow (Placeholder mode):
  1. Claude detects ALL PHI and replaces with [TYPE_LABEL] placeholders.
  2. No Faker involvement.

HIPAA Safe Harbor — 18 identifiers are targeted.
"""

import hashlib
import json
import logging
import re
from typing import Any

import groq
from faker import Faker

from config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a HIPAA compliance expert specialising in medical document de-identification.
You follow the HIPAA Safe Harbor method (45 CFR §164.514(b)) precisely.

CRITICAL OUTPUT RULES — you must follow these exactly:
1. Return ONLY a single raw JSON object. No markdown, no code fences, no backticks, no extra text.
2. In the "redacted_text" value, represent newlines as the two-character sequence \\n (backslash + n), NOT as actual line breaks.
3. The entire response must be parseable by Python's json.loads() on the first attempt.
"""

_USER_PROMPT_SYNTHETIC = """\
De-identify the medical document below using HIPAA Safe Harbor.

Replace every PHI instance with REALISTIC SYNTHETIC data.
Use the pre-generated synthetic identity where applicable (for consistency and reproducibility):
  Patient name  → {patient_name}
  Doctor name   → {doctor_name}
  Phone numbers → {phone}
  Address       → {address}
  Email         → {email}
  Date shift    → add exactly {date_shift_days} days to every date (keep original format)
  MRN / IDs     → generate similar-length random alphanumeric strings

PHI categories to detect (cover all 18 HIPAA Safe Harbor identifiers):
  PATIENT_NAME, DOCTOR_NAME, STAFF_NAME, DATE, PHONE, EMAIL,
  ADDRESS, PATIENT_ID, MEDICAL_RECORD, LAB_CONTACT, AGE, OTHER

Rules:
- Replace EVERY occurrence of the same PHI consistently (same original → same replacement).
- Preserve ALL medical values, reference ranges, units, flags (High/Low), clinical terms EXACTLY.
- Maintain document structure and line breaks.

Return ONLY this JSON schema — no extra text:
{{
  "redacted_text": "<complete document with all PHI replaced>",
  "phi_entities": [
    {{
      "original": "<exact PHI string as it appears>",
      "replacement": "<replacement string>",
      "phi_type": "<PATIENT_NAME|DOCTOR_NAME|STAFF_NAME|DATE|PHONE|EMAIL|ADDRESS|PATIENT_ID|MEDICAL_RECORD|LAB_CONTACT|AGE|OTHER>",
      "context": "<one sentence: where/how this PHI appeared>"
    }}
  ]
}}

Few-shot example (excerpt):
  Input:  "Patient: Mary Johnson, DOB: 03/15/1978, Phone: 555-123-4567"
  Output: {{"redacted_text": "Patient: Sarah Kim, DOB: 04/14/1978, Phone: 555-987-6543",
            "phi_entities": [{{"original":"Mary Johnson","replacement":"Sarah Kim","phi_type":"PATIENT_NAME","context":"Patient header"}},
                             {{"original":"03/15/1978","replacement":"04/14/1978","phi_type":"DATE","context":"Date of birth"}},
                             {{"original":"555-123-4567","replacement":"555-987-6543","phi_type":"PHONE","context":"Patient phone"}}]}}

Medical document:
---
{text}
---"""

_USER_PROMPT_PLACEHOLDER = """\
De-identify the medical document below using HIPAA Safe Harbor.

Replace every PHI instance with a DESCRIPTIVE BRACKETED PLACEHOLDER, e.g.:
  [PATIENT_NAME], [DOCTOR_NAME], [DATE_OF_TEST], [PHONE_NUMBER], [ADDRESS], [PATIENT_ID], [EMAIL]

PHI categories (cover all 18 HIPAA Safe Harbor identifiers):
  PATIENT_NAME, DOCTOR_NAME, STAFF_NAME, DATE, PHONE, EMAIL,
  ADDRESS, PATIENT_ID, MEDICAL_RECORD, LAB_CONTACT, AGE, OTHER

Rules:
- Replace EVERY occurrence of the same PHI consistently.
- Preserve ALL medical values, reference ranges, units, flags (High/Low), clinical terms EXACTLY.
- Maintain document structure and line breaks.

Return ONLY this JSON schema — no extra text:
{{
  "redacted_text": "<complete document with all PHI replaced>",
  "phi_entities": [
    {{
      "original": "<exact PHI string>",
      "replacement": "<bracketed placeholder>",
      "phi_type": "<category>",
      "context": "<one sentence>"
    }}
  ]
}}

Medical document:
---
{text}
---"""


# ---------------------------------------------------------------------------
# Synthetic identity generation via Faker
# ---------------------------------------------------------------------------

def _synthetic_identity(seed_key: str) -> dict[str, Any]:
    """
    Generate a reproducible fake patient identity seeded by a document key.
    Using a deterministic seed ensures the same document always produces
    the same synthetic replacements across re-runs.
    """
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2**31)
    fake = Faker()
    Faker.seed(seed)
    fake.seed_instance(seed)

    return {
        "patient_name": fake.name(),
        "doctor_name": f"Dr. {fake.last_name()}, {fake.suffix() if fake.boolean() else 'MD'}",
        "phone": fake.numerify("##########"),   # 10-digit, no dashes (matches Indian format)
        "address": fake.address().replace("\n", ", "),
        "email": fake.ascii_safe_email(),
        "date_shift_days": fake.random_int(min=14, max=60),
    }


# ---------------------------------------------------------------------------
# Core public function
# ---------------------------------------------------------------------------

def deidentify(text: str, mode: str = "synthetic", seed_key: str = "default") -> dict[str, Any]:
    """
    Detect and replace PHI in *text* using Claude.

    Args:
        text:     Extracted document text.
        mode:     'synthetic' | 'placeholder'
        seed_key: Deterministic seed key for Faker (use the filename for reproducibility).

    Returns:
        {redacted_text, phi_entities, summary}

    Raises:
        groq.RateLimitError: API rate limit hit.
        groq.APIStatusError: Non-2xx response from Groq.
        groq.APIConnectionError: Network failure.
    """
    if not text or not text.strip():
        return {"redacted_text": "", "phi_entities": [], "summary": {}}

    settings = get_settings()
    client = groq.Groq(api_key=settings.groq_api_key)

    # Build prompt
    if mode == "synthetic":
        hints = _synthetic_identity(seed_key)
        user_content = _USER_PROMPT_SYNTHETIC.format(text=text, **hints)
    else:
        user_content = _USER_PROMPT_PLACEHOLDER.format(text=text)

    logger.info("Sending document (%d chars) to Groq/Llama [mode=%s]", len(text), mode)

    # Call Groq — let exceptions propagate so main.py can handle them meaningfully
    message = client.chat.completions.create(
        model=settings.groq_model,
        max_tokens=settings.groq_max_tokens,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    raw = message.choices[0].message.content
    result = _parse_response(raw)
    result["summary"] = _build_summary(result["phi_entities"])
    return result


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> dict[str, Any]:
    """
    Extract and validate JSON from the model's response.

    Handles common Llama/Groq quirks:
    - Response wrapped in triple backticks (```json ... ```)
    - Literal newlines inside JSON string values (invalid JSON)
    """
    # Step 1: strip markdown code fences aggressively
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

    # Step 2: build candidates to try in order
    candidates = [cleaned, _extract_json_block(cleaned)]

    for candidate in candidates:
        if not candidate:
            continue
        # Try as-is first
        try:
            return _validate(json.loads(candidate))
        except (json.JSONDecodeError, TypeError):
            pass
        # Try after fixing literal newlines inside string values
        fixed = _fix_literal_newlines(candidate)
        try:
            return _validate(json.loads(fixed))
        except (json.JSONDecodeError, TypeError):
            pass

    logger.error("Failed to parse model JSON response (first 500 chars):\n%s", raw[:500])
    raise ValueError(
        "The model returned an unexpected response format. "
        "The document may be too large or contain unusual formatting."
    )


def _fix_literal_newlines(text: str) -> str:
    """
    Replace literal newline characters inside JSON string values with \\n.

    Llama sometimes emits:
        {"redacted_text": "line1
        line2"}
    which is invalid JSON. This walks the text character by character and
    escapes bare newlines that appear inside string literals.
    """
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\':
            result.append(ch)
            escape_next = True
        elif ch == '"':
            in_string = not in_string
            result.append(ch)
        elif ch == '\n' and in_string:
            result.append('\\n')
        elif ch == '\r' and in_string:
            pass  # strip bare carriage returns inside strings
        else:
            result.append(ch)
    return ''.join(result)


def _extract_json_block(text: str) -> str | None:
    """Find the outermost JSON object in text."""
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group() if match else None


def _validate(data: dict) -> dict:
    """Normalise and validate required keys."""
    if not isinstance(data, dict):
        raise TypeError("Expected a JSON object")

    redacted = str(data.get("redacted_text", ""))
    entities = data.get("phi_entities", [])
    if not isinstance(entities, list):
        entities = []

    normalised = []
    for e in entities:
        if isinstance(e, dict) and e.get("original"):
            normalised.append(
                {
                    "original": str(e.get("original", "")),
                    "replacement": str(e.get("replacement", "")),
                    "phi_type": str(e.get("phi_type", "OTHER")),
                    "context": str(e.get("context", "")),
                }
            )

    return {"redacted_text": redacted, "phi_entities": normalised}


def _build_summary(entities: list[dict]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for e in entities:
        t = e.get("phi_type", "OTHER")
        summary[t] = summary.get(t, 0) + 1
    return summary
