"""
Unit tests — engine/deidentifier.py

Tests cover:
  - _synthetic_identity: determinism, field types, per-seed uniqueness, range checks
  - _extract_json_block: regex extraction from mixed text
  - _parse_response: JSON parsing, markdown stripping, error propagation
  - _validate: schema normalisation, edge cases
  - _build_summary: aggregation correctness
  - deidentify: early-exit on empty text, Claude invocation arguments,
                 exception propagation, result structure

All Anthropic API calls are mocked.

Markers: @pytest.mark.unit
"""

import json
import logging
from unittest.mock import MagicMock, call, patch

import pytest

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.unit


# ===========================================================================
# _synthetic_identity
# ===========================================================================

class TestSyntheticIdentity:

    def test_returns_all_required_keys(self):
        from engine.deidentifier import _synthetic_identity
        identity = _synthetic_identity("any_seed")
        required = {"patient_name", "doctor_name", "phone", "address", "email", "date_shift_days"}
        assert required.issubset(identity.keys()), f"Missing keys: {required - identity.keys()}"

    def test_is_deterministic_for_same_seed(self):
        from engine.deidentifier import _synthetic_identity
        a = _synthetic_identity("report_abc.pdf")
        b = _synthetic_identity("report_abc.pdf")
        assert a["patient_name"] == b["patient_name"]
        assert a["phone"] == b["phone"]
        assert a["date_shift_days"] == b["date_shift_days"]

    def test_differs_for_different_seeds(self):
        from engine.deidentifier import _synthetic_identity
        a = _synthetic_identity("patient_alpha.pdf")
        b = _synthetic_identity("patient_beta.pdf")
        # At least some fields should differ
        differences = sum(
            1 for key in ("patient_name", "phone", "email")
            if a[key] != b[key]
        )
        assert differences > 0, "All fields identical for different seeds — seed has no effect"

    def test_date_shift_within_valid_range(self):
        from engine.deidentifier import _synthetic_identity
        for seed in ("file_a", "file_b", "file_c", "file_d"):
            identity = _synthetic_identity(seed)
            shift = identity["date_shift_days"]
            assert 14 <= shift <= 60, f"date_shift_days={shift} out of range [14, 60]"

    def test_phone_is_numeric_string(self):
        from engine.deidentifier import _synthetic_identity
        identity = _synthetic_identity("test.pdf")
        assert identity["phone"].isdigit(), f"Phone should be digits, got: {identity['phone']}"

    def test_patient_name_is_non_empty_string(self):
        from engine.deidentifier import _synthetic_identity
        identity = _synthetic_identity("test.pdf")
        assert isinstance(identity["patient_name"], str)
        assert len(identity["patient_name"]) > 0

    def test_email_contains_at_symbol(self):
        from engine.deidentifier import _synthetic_identity
        identity = _synthetic_identity("test.pdf")
        assert "@" in identity["email"]


# ===========================================================================
# _extract_json_block
# ===========================================================================

class TestExtractJsonBlock:

    def test_finds_simple_json_object(self):
        from engine.deidentifier import _extract_json_block
        text = 'prefix {"key": "value"} suffix'
        result = _extract_json_block(text)
        assert result is not None
        assert '"key"' in result

    def test_finds_nested_json(self):
        from engine.deidentifier import _extract_json_block
        nested = '{"outer": {"inner": [1, 2, 3]}}'
        result = _extract_json_block(nested)
        assert result == nested

    def test_returns_none_when_no_json(self):
        from engine.deidentifier import _extract_json_block
        result = _extract_json_block("No JSON here at all.")
        assert result is None

    def test_returns_none_on_empty_string(self):
        from engine.deidentifier import _extract_json_block
        assert _extract_json_block("") is None


# ===========================================================================
# _parse_response
# ===========================================================================

class TestParseResponse:

    def _valid_payload(self, redacted="hello", entities=None):
        return json.dumps({
            "redacted_text": redacted,
            "phi_entities": entities or [],
        })

    def test_parses_clean_json(self):
        from engine.deidentifier import _parse_response
        result = _parse_response(self._valid_payload("clean text"))
        assert result["redacted_text"] == "clean text"
        assert result["phi_entities"] == []

    def test_strips_markdown_json_fence(self):
        from engine.deidentifier import _parse_response
        wrapped = f"```json\n{self._valid_payload('fenced')}\n```"
        result = _parse_response(wrapped)
        assert result["redacted_text"] == "fenced"

    def test_strips_plain_code_fence(self):
        from engine.deidentifier import _parse_response
        wrapped = f"```\n{self._valid_payload('plain fence')}\n```"
        result = _parse_response(wrapped)
        assert result["redacted_text"] == "plain fence"

    def test_extracts_json_from_surrounding_prose(self):
        from engine.deidentifier import _parse_response
        payload = self._valid_payload("extracted")
        prose_wrapped = f"Here is the result:\n{payload}\nEnd."
        result = _parse_response(prose_wrapped)
        assert result["redacted_text"] == "extracted"

    def test_raises_value_error_on_totally_invalid_response(self):
        from engine.deidentifier import _parse_response
        with pytest.raises(ValueError, match="unexpected response format"):
            _parse_response("This is not JSON at all and has no braces.")

    def test_raises_value_error_on_malformed_json(self):
        from engine.deidentifier import _parse_response
        with pytest.raises(ValueError):
            _parse_response("{broken json ][}")

    def test_phi_entities_are_normalised(self):
        from engine.deidentifier import _parse_response
        payload = json.dumps({
            "redacted_text": "de-id text",
            "phi_entities": [
                {"original": "John", "replacement": "James", "phi_type": "PATIENT_NAME", "context": "header"},
            ],
        })
        result = _parse_response(payload)
        assert len(result["phi_entities"]) == 1
        assert result["phi_entities"][0]["original"] == "John"


# ===========================================================================
# _validate
# ===========================================================================

class TestValidate:

    def test_returns_required_keys(self):
        from engine.deidentifier import _validate
        result = _validate({"redacted_text": "text", "phi_entities": []})
        assert "redacted_text" in result
        assert "phi_entities" in result

    def test_missing_redacted_text_defaults_to_empty(self):
        from engine.deidentifier import _validate
        result = _validate({"phi_entities": []})
        assert result["redacted_text"] == ""

    def test_missing_phi_entities_defaults_to_empty_list(self):
        from engine.deidentifier import _validate
        result = _validate({"redacted_text": "text"})
        assert result["phi_entities"] == []

    def test_non_list_phi_entities_becomes_empty_list(self):
        from engine.deidentifier import _validate
        result = _validate({"redacted_text": "text", "phi_entities": "oops"})
        assert result["phi_entities"] == []

    def test_skips_entity_without_original(self):
        from engine.deidentifier import _validate
        entities = [
            {"replacement": "James", "phi_type": "PATIENT_NAME", "context": "x"},  # no 'original'
            {"original": "John", "replacement": "James", "phi_type": "PATIENT_NAME", "context": "x"},
        ]
        result = _validate({"redacted_text": "t", "phi_entities": entities})
        assert len(result["phi_entities"]) == 1

    def test_phi_type_defaults_to_other(self):
        from engine.deidentifier import _validate
        entities = [{"original": "Jane", "replacement": "Sara"}]  # no phi_type
        result = _validate({"redacted_text": "t", "phi_entities": entities})
        assert result["phi_entities"][0]["phi_type"] == "OTHER"

    def test_raises_type_error_on_non_dict_input(self):
        from engine.deidentifier import _validate
        with pytest.raises(TypeError):
            _validate("this is a string not a dict")

    def test_all_entity_fields_coerced_to_str(self):
        from engine.deidentifier import _validate
        entities = [{"original": 123, "replacement": None, "phi_type": "DATE", "context": 456}]
        result = _validate({"redacted_text": "t", "phi_entities": entities})
        e = result["phi_entities"][0]
        assert all(isinstance(v, str) for v in e.values())


# ===========================================================================
# _build_summary
# ===========================================================================

class TestBuildSummary:

    def test_counts_single_type(self):
        from engine.deidentifier import _build_summary
        entities = [{"phi_type": "DATE"}, {"phi_type": "DATE"}]
        assert _build_summary(entities) == {"DATE": 2}

    def test_counts_multiple_types(self):
        from engine.deidentifier import _build_summary
        entities = [
            {"phi_type": "PATIENT_NAME"},
            {"phi_type": "DATE"},
            {"phi_type": "DATE"},
            {"phi_type": "PHONE"},
            {"phi_type": "PHONE"},
            {"phi_type": "PHONE"},
        ]
        summary = _build_summary(entities)
        assert summary == {"PATIENT_NAME": 1, "DATE": 2, "PHONE": 3}

    def test_empty_list_returns_empty_dict(self):
        from engine.deidentifier import _build_summary
        assert _build_summary([]) == {}

    def test_missing_phi_type_defaults_to_other(self):
        from engine.deidentifier import _build_summary
        entities = [{"original": "X"}]  # no phi_type key
        summary = _build_summary(entities)
        assert summary.get("OTHER", 0) == 1


# ===========================================================================
# deidentify (public function)
# ===========================================================================

class TestDeidentify:

    def test_returns_early_on_empty_text(self):
        from engine.deidentifier import deidentify
        result = deidentify("")
        assert result["redacted_text"] == ""
        assert result["phi_entities"] == []
        assert result["summary"] == {}

    def test_returns_early_on_whitespace_only_text(self):
        from engine.deidentifier import deidentify
        result = deidentify("   \n\t  ")
        assert result["redacted_text"] == ""

    @patch("groq.Groq")
    def test_calls_claude_with_correct_model(self, mock_groq_cls):
        """Verifies the model from config is passed to the API."""
        from engine.deidentifier import deidentify
        from config import get_settings

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"redacted_text":"ok","phi_entities":[]}'))]
        mock_client.chat.completions.create.return_value = mock_response

        deidentify("Patient: John Doe", mode="placeholder")

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == get_settings().groq_model

    @patch("groq.Groq")
    def test_synthetic_mode_includes_faker_hints_in_prompt(self, mock_groq_cls):
        """The prompt for synthetic mode must contain Faker-generated identity data."""
        from engine.deidentifier import deidentify

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"redacted_text":"x","phi_entities":[]}'))]
        mock_client.chat.completions.create.return_value = mock_response

        deidentify("Patient: John", mode="synthetic", seed_key="deterministic.pdf")

        _, kwargs = mock_client.chat.completions.create.call_args
        # system message is first, user content is second
        user_content = kwargs["messages"][1]["content"]
        assert "Patient name" in user_content  # synthetic prompt header

    @patch("groq.Groq")
    def test_placeholder_mode_does_not_include_faker_hints(self, mock_groq_cls):
        from engine.deidentifier import deidentify

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"redacted_text":"x","phi_entities":[]}'))]
        mock_client.chat.completions.create.return_value = mock_response

        deidentify("Patient: John", mode="placeholder")

        _, kwargs = mock_client.chat.completions.create.call_args
        user_content = kwargs["messages"][1]["content"]
        assert "[PATIENT_NAME]" in user_content  # placeholder prompt
        assert "Patient name  →" not in user_content  # no faker hints

    @patch("groq.Groq")
    def test_result_includes_summary(self, mock_groq_cls):
        from engine.deidentifier import deidentify

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps({
            "redacted_text": "de-identified",
            "phi_entities": [
                {"original": "John", "replacement": "James", "phi_type": "PATIENT_NAME", "context": "name"},
                {"original": "01/01/2020", "replacement": "15/01/2020", "phi_type": "DATE", "context": "date"},
            ],
        })))]
        mock_client.chat.completions.create.return_value = mock_response

        result = deidentify("Patient: John, Date: 01/01/2020")
        assert "summary" in result
        assert result["summary"]["PATIENT_NAME"] == 1
        assert result["summary"]["DATE"] == 1

    @patch("groq.Groq")
    def test_propagates_rate_limit_error(self, mock_groq_cls):
        import groq
        from engine.deidentifier import deidentify

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = groq.RateLimitError(
            message="rate limit", response=MagicMock(), body={}
        )
        with pytest.raises(groq.RateLimitError):
            deidentify("Some patient text")

    @patch("groq.Groq")
    def test_propagates_connection_error(self, mock_groq_cls):
        import groq
        from engine.deidentifier import deidentify

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = groq.APIConnectionError(request=MagicMock())
        with pytest.raises(groq.APIConnectionError):
            deidentify("Patient: Jane Smith")

    @patch("groq.Groq")
    def test_raises_value_error_on_bad_json(self, mock_groq_cls):
        from engine.deidentifier import deidentify

        mock_client = MagicMock()
        mock_groq_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Not JSON at all!!!"))]
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(ValueError, match="unexpected response format"):
            deidentify("Patient: John Doe")
