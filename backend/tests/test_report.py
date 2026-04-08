"""
Unit tests — engine/report.py

Tests cover:
  - generate_report: output structure, audit fields, statistics fields,
                     character counts, empty-PHI edge case, invalid input guard
  - _calculate_risk_score: zero baseline, scaling with count, cap at 100,
                            unknown type fallback weight
  - _risk_level: all four boundary thresholds
  - PHI_DESCRIPTIONS / RISK_WEIGHTS completeness and consistency

Markers: @pytest.mark.unit
"""

import logging
from datetime import datetime

import pytest

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_ENTITIES = [
    {"original": "John Doe",    "replacement": "James Smith",  "phi_type": "PATIENT_NAME", "context": "name"},
    {"original": "01/01/1980",  "replacement": "15/01/1980",   "phi_type": "DATE",          "context": "dob"},
    {"original": "9876543210",  "replacement": "8765432109",   "phi_type": "PHONE",         "context": "phone"},
]

SAMPLE_SUMMARY = {"PATIENT_NAME": 1, "DATE": 1, "PHONE": 1}

SAMPLE_ORIGINAL  = "Patient: John Doe\nDOB: 01/01/1980\nPhone: 9876543210"
SAMPLE_REDACTED  = "Patient: James Smith\nDOB: 15/01/1980\nPhone: 8765432109"


# ===========================================================================
# generate_report
# ===========================================================================

class TestGenerateReport:

    def _call(self, **overrides):
        """Helper that calls generate_report with defaults and optional overrides."""
        from engine.report import generate_report
        defaults = dict(
            filename="lab_report.pdf",
            phi_entities=SAMPLE_ENTITIES,
            summary=SAMPLE_SUMMARY,
            original_text=SAMPLE_ORIGINAL,
            redacted_text=SAMPLE_REDACTED,
            ocr_used=False,
            processing_time_ms=1200,
            mode="synthetic",
        )
        defaults.update(overrides)
        return generate_report(**defaults)

    # ── Top-level keys ───────────────────────────────────────────────────────

    def test_has_audit_section(self):
        assert "audit" in self._call()

    def test_has_statistics_section(self):
        assert "statistics" in self._call()

    def test_has_phi_entities_section(self):
        assert "phi_entities" in self._call()

    def test_has_text_section(self):
        assert "text" in self._call()

    # ── Audit section ────────────────────────────────────────────────────────

    def test_audit_filename(self):
        report = self._call(filename="report.pdf")
        assert report["audit"]["filename"] == "report.pdf"

    def test_audit_mode(self):
        for mode in ("synthetic", "placeholder"):
            assert self._call(mode=mode)["audit"]["mode"] == mode

    def test_audit_ocr_used_false(self):
        assert self._call(ocr_used=False)["audit"]["ocr_used"] is False

    def test_audit_ocr_used_true(self):
        assert self._call(ocr_used=True)["audit"]["ocr_used"] is True

    def test_audit_processing_time(self):
        assert self._call(processing_time_ms=999)["audit"]["processing_time_ms"] == 999

    def test_audit_processed_at_is_iso_format(self):
        ts = self._call()["audit"]["processed_at"]
        # Should not raise
        datetime.fromisoformat(ts.rstrip("Z"))

    # ── Statistics section ───────────────────────────────────────────────────

    def test_statistics_total_phi_found(self):
        report = self._call(phi_entities=SAMPLE_ENTITIES)
        assert report["statistics"]["total_phi_found"] == len(SAMPLE_ENTITIES)

    def test_statistics_by_category_raw_matches_summary(self):
        report = self._call(summary=SAMPLE_SUMMARY)
        assert report["statistics"]["by_category_raw"] == SAMPLE_SUMMARY

    def test_statistics_by_category_uses_human_labels(self):
        report = self._call()
        by_cat = report["statistics"]["by_category"]
        # Should have human-readable keys, not raw type codes
        assert "PATIENT_NAME" not in by_cat
        assert any("Patient" in k for k in by_cat)

    def test_statistics_risk_score_is_integer(self):
        score = self._call()["statistics"]["risk_score"]
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_statistics_risk_level_valid(self):
        level = self._call()["statistics"]["risk_level"]
        assert level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    # ── Text section ─────────────────────────────────────────────────────────

    def test_text_original_preserved(self):
        report = self._call(original_text=SAMPLE_ORIGINAL)
        assert report["text"]["original"] == SAMPLE_ORIGINAL

    def test_text_redacted_preserved(self):
        report = self._call(redacted_text=SAMPLE_REDACTED)
        assert report["text"]["redacted"] == SAMPLE_REDACTED

    def test_text_char_counts_correct(self):
        report = self._call(original_text="ABCDE", redacted_text="XY")
        assert report["text"]["char_count_original"] == 5
        assert report["text"]["char_count_redacted"] == 2

    # ── Edge cases ───────────────────────────────────────────────────────────

    def test_empty_phi_entities(self):
        report = self._call(phi_entities=[], summary={})
        assert report["statistics"]["total_phi_found"] == 0
        assert report["statistics"]["risk_score"] == 0
        assert report["statistics"]["risk_level"] == "LOW"

    def test_raises_on_empty_filename(self):
        from engine.report import generate_report
        with pytest.raises(ValueError, match="filename"):
            generate_report(
                filename="",
                phi_entities=[],
                summary={},
                original_text="text",
                redacted_text="text",
                ocr_used=False,
                processing_time_ms=0,
                mode="synthetic",
            )


# ===========================================================================
# _calculate_risk_score
# ===========================================================================

class TestCalculateRiskScore:

    def test_empty_summary_returns_zero(self):
        from engine.report import _calculate_risk_score
        assert _calculate_risk_score({}) == 0

    def test_none_zero_returns_zero(self):
        from engine.report import _calculate_risk_score
        assert _calculate_risk_score({}) == 0

    def test_single_patient_name_returns_nonzero(self):
        from engine.report import _calculate_risk_score
        score = _calculate_risk_score({"PATIENT_NAME": 1})
        assert score > 0

    def test_score_increases_with_count(self):
        from engine.report import _calculate_risk_score
        low  = _calculate_risk_score({"PATIENT_NAME": 1})
        high = _calculate_risk_score({"PATIENT_NAME": 10})
        assert high > low

    def test_heavier_phi_types_score_higher(self):
        """PATIENT_NAME (weight=5) should score higher than AGE (weight=1) for same count."""
        from engine.report import _calculate_risk_score
        name_score = _calculate_risk_score({"PATIENT_NAME": 1})
        age_score  = _calculate_risk_score({"AGE": 1})
        assert name_score > age_score

    def test_score_capped_at_100(self):
        from engine.report import _calculate_risk_score
        massive = {"PATIENT_NAME": 1000, "ADDRESS": 1000, "PHONE": 1000}
        assert _calculate_risk_score(massive) == 100

    def test_unknown_phi_type_uses_weight_one(self):
        """PHI types not in RISK_WEIGHTS get fallback weight of 1."""
        from engine.report import _calculate_risk_score
        score = _calculate_risk_score({"CUSTOM_TYPE_XYZ": 5})
        expected = min(100, int(1 * 5 * 3))
        assert score == expected

    def test_combined_types_sum_correctly(self):
        from engine.report import _calculate_risk_score, RISK_WEIGHTS
        summary = {"PATIENT_NAME": 2, "DATE": 3}
        raw = RISK_WEIGHTS["PATIENT_NAME"] * 2 + RISK_WEIGHTS["DATE"] * 3
        expected = min(100, int(raw * 3))
        assert _calculate_risk_score(summary) == expected


# ===========================================================================
# _risk_level
# ===========================================================================

class TestRiskLevel:

    def test_score_0_is_low(self):
        from engine.report import _risk_level
        assert _risk_level(0) == "LOW"

    def test_score_19_is_low(self):
        from engine.report import _risk_level
        assert _risk_level(19) == "LOW"

    def test_score_20_is_medium(self):
        from engine.report import _risk_level
        assert _risk_level(20) == "MEDIUM"

    def test_score_49_is_medium(self):
        from engine.report import _risk_level
        assert _risk_level(49) == "MEDIUM"

    def test_score_50_is_high(self):
        from engine.report import _risk_level
        assert _risk_level(50) == "HIGH"

    def test_score_79_is_high(self):
        from engine.report import _risk_level
        assert _risk_level(79) == "HIGH"

    def test_score_80_is_critical(self):
        from engine.report import _risk_level
        assert _risk_level(80) == "CRITICAL"

    def test_score_100_is_critical(self):
        from engine.report import _risk_level
        assert _risk_level(100) == "CRITICAL"


# ===========================================================================
# PHI_DESCRIPTIONS & RISK_WEIGHTS consistency
# ===========================================================================

class TestLookupTables:

    def test_risk_weights_keys_subset_of_phi_descriptions(self):
        """Every type in RISK_WEIGHTS should also be in PHI_DESCRIPTIONS."""
        from engine.report import PHI_DESCRIPTIONS, RISK_WEIGHTS
        for phi_type in RISK_WEIGHTS:
            assert phi_type in PHI_DESCRIPTIONS, (
                f"'{phi_type}' in RISK_WEIGHTS but missing from PHI_DESCRIPTIONS"
            )

    def test_all_weights_are_positive(self):
        from engine.report import RISK_WEIGHTS
        for phi_type, weight in RISK_WEIGHTS.items():
            assert weight > 0, f"Weight for '{phi_type}' must be positive, got {weight}"

    def test_phi_descriptions_all_non_empty(self):
        from engine.report import PHI_DESCRIPTIONS
        for phi_type, description in PHI_DESCRIPTIONS.items():
            assert description.strip(), f"Description for '{phi_type}' is empty"
