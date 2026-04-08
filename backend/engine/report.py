"""
Redaction Report Generator.

Builds a structured audit report from de-identification results and
computes a privacy risk score based on the HIPAA sensitivity of each
PHI type detected.

All public functions include structured logging so report generation
activity is fully traceable in server logs.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

PHI_DESCRIPTIONS: dict[str, str] = {
    "PATIENT_NAME":   "Patient Name",
    "DOCTOR_NAME":    "Doctor / Physician Name",
    "STAFF_NAME":     "Lab Staff / Technician Name",
    "DATE":           "Date (test, registration, report)",
    "PHONE":          "Phone / Fax Number",
    "EMAIL":          "Email Address",
    "ADDRESS":        "Physical Address",
    "PATIENT_ID":     "Patient ID / Report ID",
    "MEDICAL_RECORD": "Medical Record Number",
    "LAB_CONTACT":    "Lab Contact Info (phone/email/URL)",
    "AGE":            "Patient Age",
    "OTHER":          "Other Identifier",
}

# Sensitivity weight per PHI type — used for risk scoring
RISK_WEIGHTS: dict[str, int] = {
    "PATIENT_NAME":   5,
    "PATIENT_ID":     4,
    "MEDICAL_RECORD": 4,
    "ADDRESS":        4,
    "PHONE":          3,
    "EMAIL":          3,
    "DOCTOR_NAME":    2,
    "STAFF_NAME":     2,
    "DATE":           2,
    "LAB_CONTACT":    2,
    "AGE":            1,
    "OTHER":          1,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    filename: str,
    phi_entities: list[dict],
    summary: dict[str, int],
    original_text: str,
    redacted_text: str,
    ocr_used: bool,
    processing_time_ms: int,
    mode: str,
) -> dict[str, Any]:
    """
    Build the full redaction audit report returned to the client and stored
    in the database.

    Args:
        filename:          Sanitised original filename.
        phi_entities:      List of {original, replacement, phi_type, context}.
        summary:           Aggregated counts per phi_type.
        original_text:     Full pre-redaction document text.
        redacted_text:     Full post-redaction document text.
        ocr_used:          Whether Tesseract OCR was invoked.
        processing_time_ms: Wall-clock ms for the Claude de-identification call.
        mode:              'synthetic' | 'placeholder'.

    Returns:
        Nested dict with audit, statistics, phi_entities, and text sections.

    Raises:
        ValueError: If required arguments are logically inconsistent.
    """
    if not filename:
        raise ValueError("filename must not be empty")

    phi_count = len(phi_entities)
    logger.info(
        "Generating audit report | file='%s' | phi_found=%d | mode=%s | ocr=%s | time=%d ms",
        filename, phi_count, mode, ocr_used, processing_time_ms,
    )

    try:
        risk_score = _calculate_risk_score(summary)
        risk_level = _risk_level(risk_score)
        logger.debug("Risk assessment | score=%d | level=%s", risk_score, risk_level)
    except Exception as exc:
        # Risk scoring is non-critical — log and fall back to zero
        logger.error("Risk score calculation failed: %s", exc, exc_info=True)
        risk_score, risk_level = 0, "UNKNOWN"

    try:
        by_category = {PHI_DESCRIPTIONS.get(k, k): v for k, v in summary.items()}
    except Exception as exc:
        logger.warning("Could not map PHI descriptions: %s", exc)
        by_category = dict(summary)

    report = {
        "audit": {
            "filename": filename,
            "processed_at": datetime.utcnow().isoformat() + "Z",
            "mode": mode,
            "ocr_used": ocr_used,
            "processing_time_ms": processing_time_ms,
        },
        "statistics": {
            "total_phi_found": phi_count,
            "by_category": by_category,
            "by_category_raw": summary,
            "risk_score": risk_score,
            "risk_level": risk_level,
        },
        "phi_entities": phi_entities,
        "text": {
            "original": original_text,
            "redacted": redacted_text,
            "char_count_original": len(original_text),
            "char_count_redacted": len(redacted_text),
        },
    }

    logger.info(
        "Audit report ready | file='%s' | risk=%s (%d/100) | PHI types=%s",
        filename, risk_level, risk_score, list(summary.keys()),
    )
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _calculate_risk_score(summary: dict[str, int]) -> int:
    """
    Compute a privacy risk score in the range 0–100.

    Each PHI type contributes (weight × count) to a raw score which is
    then scaled to 0–100 and capped.

    Args:
        summary: {phi_type: count} mapping.

    Returns:
        Integer in [0, 100].
    """
    if not summary:
        logger.debug("No PHI in summary — risk score is 0")
        return 0

    raw = sum(RISK_WEIGHTS.get(phi_type, 1) * count for phi_type, count in summary.items())
    score = min(100, int(raw * 3))
    logger.debug("Risk score raw=%d → normalised=%d", raw, score)
    return score


def _risk_level(score: int) -> str:
    """
    Map a numeric risk score to a human-readable level.

    Thresholds:
        < 20  → LOW
        < 50  → MEDIUM
        < 80  → HIGH
        ≥ 80  → CRITICAL
    """
    if score < 20:
        return "LOW"
    if score < 50:
        return "MEDIUM"
    if score < 80:
        return "HIGH"
    return "CRITICAL"
