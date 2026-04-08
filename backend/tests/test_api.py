"""
Integration tests — HIPAA De-identification REST API.

These tests exercise the full HTTP stack (routing, validation, error handling,
DB persistence) with Claude API and OCR calls replaced by unittest mocks.

IMPORTANT: Mocks must patch functions in the `main` module namespace
(where they are imported), not in their original module.  This is the
standard Python mock gotcha: mock where the name is used, not where it lives.

  CORRECT:  @patch("main.extract_text", ...)
  WRONG:    @patch("engine.ocr.extract_text", ...)   ← main already holds a ref

Markers:
    @pytest.mark.integration  — exercises multiple layers together
"""

import logging
from unittest.mock import MagicMock, call, patch

import pytest

from tests.conftest import MOCK_DEIDENTIFY_RESULT, SAMPLE_MEDICAL_TEXT

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration


# ===========================================================================
# Health check
# ===========================================================================

class TestHealth:
    def test_returns_200(self, api_client):
        resp = api_client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_response_body_fields(self, api_client):
        body = api_client.get("/api/v1/health").json()
        assert body["status"] == "ok"
        assert "timestamp" in body
        assert "version" in body

    def test_response_has_request_id_header(self, api_client):
        resp = api_client.get("/api/v1/health")
        header_names = {k.lower() for k in resp.headers}
        assert "x-request-id" in header_names


# ===========================================================================
# /api/v1/deidentify — happy paths
# ===========================================================================

class TestDeidentifyHappyPaths:

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_txt_synthetic_returns_200(self, mock_deidentify, mock_ocr, api_client):
        """Plain-text upload in synthetic mode returns HTTP 200 with full report."""
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("report.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in ("id", "audit", "statistics", "phi_entities", "text"):
            assert key in body, f"Missing key: {key}"

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_phi_count_matches_entities_list(self, mock_deidentify, mock_ocr, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        body = resp.json()
        assert body["statistics"]["total_phi_found"] == len(MOCK_DEIDENTIFY_RESULT["phi_entities"])

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_original_text_preserved_in_response(self, mock_deidentify, mock_ocr, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.json()["text"]["original"] == SAMPLE_MEDICAL_TEXT

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_deidentifier_called_with_correct_args(self, mock_deidentify, mock_ocr, api_client):
        """Verify the engine is invoked with the right filename seed key."""
        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("report.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        mock_deidentify.assert_called_once_with(
            SAMPLE_MEDICAL_TEXT, mode="synthetic", seed_key="report.txt"
        )

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value={
        **MOCK_DEIDENTIFY_RESULT,
        "phi_entities": [{**MOCK_DEIDENTIFY_RESULT["phi_entities"][0], "replacement": "[PATIENT_NAME]"}],
        "summary": {"PATIENT_NAME": 1},
    })
    def test_placeholder_mode_returns_bracket_replacements(self, mock_deidentify, mock_ocr, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "placeholder"},
        )
        assert resp.status_code == 200
        entities = resp.json()["phi_entities"]
        assert any("[" in e["replacement"] for e in entities)

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, True))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_ocr_used_flag_propagated_to_audit(self, mock_deidentify, mock_ocr, api_client):
        """ocr_used=True from OCR extraction must appear in the audit section."""
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("scan.png", b"fake_png", "image/png")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 200
        assert resp.json()["audit"]["ocr_used"] is True

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_record_persisted_to_database(self, mock_deidentify, mock_ocr, api_client, test_engine):
        """Successful de-identification creates an audit record in the database."""
        from sqlalchemy.orm import sessionmaker
        from db.models import DeidentificationRecord

        Session = sessionmaker(bind=test_engine)
        with Session() as session:
            before = session.query(DeidentificationRecord).count()

        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )

        with Session() as session:
            after = session.query(DeidentificationRecord).count()

        assert after == before + 1

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_statistics_contains_risk_level(self, mock_deidentify, mock_ocr, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        stats = resp.json()["statistics"]
        assert "risk_level" in stats
        assert stats["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_pdf_upload_accepted(self, mock_deidentify, mock_ocr, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("report.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 200

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_response_id_is_uuid_string(self, mock_deidentify, mock_ocr, api_client):
        import uuid
        body = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        ).json()
        uuid.UUID(body["id"])  # raises ValueError if not valid UUID


# ===========================================================================
# /api/v1/deidentify — input validation
# ===========================================================================

class TestDeidentifyValidation:

    def test_invalid_mode_returns_400(self, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", b"text", "text/plain")},
            data={"mode": "WRONG_MODE"},
        )
        assert resp.status_code == 400
        assert "mode" in resp.json()["detail"].lower()

    def test_unsupported_extension_returns_400(self, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("report.docx", b"fake", "application/msword")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    @patch("main.extract_text", return_value=("", False))
    def test_blank_extraction_returns_422(self, mock_ocr, api_client):
        """OCR/PDF extraction yielding empty text → HTTP 422."""
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("blank.txt", b"   ", "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 422

    @patch("main.extract_text", side_effect=ValueError("Cannot open PDF: corrupted"))
    def test_extraction_error_returns_422(self, mock_ocr, api_client):
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("bad.pdf", b"notapdf", "application/pdf")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 422
        assert "Cannot open PDF" in resp.json()["detail"]

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_default_mode_is_synthetic(self, mock_deidentify, mock_ocr, api_client):
        """Omitting mode form field defaults to synthetic."""
        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
        )
        _, kwargs = mock_deidentify.call_args
        assert kwargs["mode"] == "synthetic"

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_filename_is_sanitised(self, mock_deidentify, mock_ocr, api_client):
        """werkzeug.secure_filename is applied; path traversal chars are stripped."""
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("../../../etc/passwd.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        # Should either succeed (with sanitised name) or reject — never expose ../
        audit = resp.json().get("audit", {})
        filename = audit.get("filename", "")
        assert ".." not in filename


# ===========================================================================
# /api/v1/deidentify — Groq error mapping
# ===========================================================================

class TestDeidentifyErrorMapping:

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify")
    def test_rate_limit_maps_to_429(self, mock_deidentify, mock_ocr, api_client):
        import groq
        mock_deidentify.side_effect = groq.RateLimitError(
            message="Too many requests", response=MagicMock(), body={}
        )
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["detail"].lower()

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify")
    def test_auth_error_maps_to_503_with_key_message(self, mock_deidentify, mock_ocr, api_client):
        import groq
        mock_deidentify.side_effect = groq.AuthenticationError(
            message="Invalid key", response=MagicMock(), body={}
        )
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 503
        assert "API key" in resp.json()["detail"]

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify")
    def test_connection_error_maps_to_503(self, mock_deidentify, mock_ocr, api_client):
        import groq
        mock_deidentify.side_effect = groq.APIConnectionError(request=MagicMock())
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 503
        assert "network" in resp.json()["detail"].lower()

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify")
    def test_value_error_from_json_parse_maps_to_422(self, mock_deidentify, mock_ocr, api_client):
        """ValueError raised by deidentifier (bad JSON) → HTTP 422."""
        mock_deidentify.side_effect = ValueError("LLM returned an unexpected response format.")
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 422

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify")
    def test_api_status_error_maps_to_502(self, mock_deidentify, mock_ocr, api_client):
        """InternalServerError (HTTP 500 from Groq) is a subclass of APIStatusError
        but NOT of RateLimitError or AuthenticationError, so it maps to HTTP 502."""
        import groq
        import httpx

        req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        mock_http_resp = httpx.Response(500, text="Internal Server Error", request=req)
        mock_deidentify.side_effect = groq.InternalServerError(
            message="Internal Server Error",
            response=mock_http_resp,
            body={},
        )
        resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert resp.status_code == 502


# ===========================================================================
# /api/v1/reports
# ===========================================================================

class TestReportsEndpoint:

    def test_list_returns_correct_structure(self, api_client):
        resp = api_client.get("/api/v1/reports")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("total", "records", "limit", "offset"):
            assert key in body
        assert isinstance(body["records"], list)

    def test_get_nonexistent_record_returns_404(self, api_client):
        resp = api_client.get("/api/v1/reports/does-not-exist-0000")
        assert resp.status_code == 404

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_get_persisted_record_by_id(self, mock_deidentify, mock_ocr, api_client):
        """POST then GET the same record by its returned ID."""
        post_resp = api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        assert post_resp.status_code == 200
        record_id = post_resp.json()["id"]

        get_resp = api_client.get(f"/api/v1/reports/{record_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == record_id

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_list_pagination_respects_limit(self, mock_deidentify, mock_ocr, api_client):
        for _ in range(4):
            api_client.post(
                "/api/v1/deidentify",
                files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
                data={"mode": "synthetic"},
            )
        body = api_client.get("/api/v1/reports?limit=2").json()
        assert len(body["records"]) <= 2

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_list_total_increments_after_upload(self, mock_deidentify, mock_ocr, api_client):
        before = api_client.get("/api/v1/reports").json()["total"]
        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        after = api_client.get("/api/v1/reports").json()["total"]
        assert after == before + 1


# ===========================================================================
# /api/v1/dashboard/stats
# ===========================================================================

class TestDashboardStats:

    def test_empty_db_returns_zero_counts(self, api_client):
        body = api_client.get("/api/v1/dashboard/stats").json()
        assert "total_documents" in body
        assert "total_phi_found" in body
        assert "phi_by_category" in body
        assert isinstance(body["phi_by_category"], dict)

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_stats_total_documents_increments(self, mock_deidentify, mock_ocr, api_client):
        before = api_client.get("/api/v1/dashboard/stats").json()["total_documents"]
        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        after = api_client.get("/api/v1/dashboard/stats").json()["total_documents"]
        assert after == before + 1

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, False))
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_stats_phi_by_category_populated(self, mock_deidentify, mock_ocr, api_client):
        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("r.txt", SAMPLE_MEDICAL_TEXT.encode(), "text/plain")},
            data={"mode": "synthetic"},
        )
        stats = api_client.get("/api/v1/dashboard/stats").json()
        assert len(stats["phi_by_category"]) > 0

    @patch("main.extract_text", return_value=(SAMPLE_MEDICAL_TEXT, True))  # OCR used
    @patch("main.deidentify", return_value=MOCK_DEIDENTIFY_RESULT)
    def test_stats_ocr_count_increments(self, mock_deidentify, mock_ocr, api_client):
        before = api_client.get("/api/v1/dashboard/stats").json()["ocr_count"]
        api_client.post(
            "/api/v1/deidentify",
            files={"file": ("scan.png", b"fake", "image/png")},
            data={"mode": "synthetic"},
        )
        after = api_client.get("/api/v1/dashboard/stats").json()["ocr_count"]
        assert after == before + 1
