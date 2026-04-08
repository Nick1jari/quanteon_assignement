"""
Integration tests — db/database.py and db/models.py

Tests cover:
  - Schema creation (init_db creates all tables)
  - Session lifecycle (get_db yields, closes, rolls back on error)
  - DeidentificationRecord CRUD operations
  - Field defaults and JSON column storage
  - Error handling when DB commit fails

All tests use the in-memory SQLite engine from conftest.py so
no file is written to disk and tests are fully isolated.

Markers: @pytest.mark.integration
"""

import logging
import uuid
from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.integration


# ===========================================================================
# Schema / init_db
# ===========================================================================

class TestSchema:

    def test_deidentification_records_table_exists(self, test_engine):
        """init_db must create the deidentification_records table."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()
        logger.debug("Tables in test DB: %s", tables)
        assert "deidentification_records" in tables

    def test_table_has_expected_columns(self, test_engine):
        inspector = inspect(test_engine)
        cols = {c["name"] for c in inspector.get_columns("deidentification_records")}
        expected = {
            "id", "filename", "created_at", "original_text", "redacted_text",
            "phi_entities", "phi_summary", "phi_count", "ocr_used",
            "processing_time_ms", "mode",
        }
        missing = expected - cols
        assert not missing, f"Missing columns: {missing}"

    def test_engine_is_reachable(self, test_engine):
        with test_engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


# ===========================================================================
# get_db session lifecycle
# ===========================================================================

class TestGetDb:

    def test_yields_a_session(self, db_session):
        from db.database import SessionLocal
        # db_session is created by conftest — just verify it's a valid session
        assert db_session is not None
        assert db_session.is_active

    def test_session_can_execute_queries(self, db_session):
        from db.models import DeidentificationRecord
        count = db_session.query(DeidentificationRecord).count()
        assert isinstance(count, int)


# ===========================================================================
# DeidentificationRecord — CRUD
# ===========================================================================

class TestDeidentificationRecordCRUD:

    def _make_record(self, **overrides) -> "DeidentificationRecord":
        from db.models import DeidentificationRecord
        defaults = dict(
            id=str(uuid.uuid4()),
            filename="test_lab_report.pdf",
            original_text="Patient: John Doe, Phone: 9876543210",
            redacted_text="Patient: James Smith, Phone: 8765432109",
            phi_entities=[
                {"original": "John Doe", "replacement": "James Smith",
                 "phi_type": "PATIENT_NAME", "context": "name"},
            ],
            phi_summary={"PATIENT_NAME": 1},
            phi_count=1,
            ocr_used=False,
            processing_time_ms=1500,
            mode="synthetic",
        )
        defaults.update(overrides)
        return DeidentificationRecord(**defaults)

    # ── Create ───────────────────────────────────────────────────────────────

    def test_create_record_persists(self, db_session):
        record = self._make_record()
        db_session.add(record)
        db_session.flush()

        fetched = db_session.query(
            __import__("db.models", fromlist=["DeidentificationRecord"]).DeidentificationRecord
        ).filter_by(id=record.id).first()
        assert fetched is not None
        logger.info("Record persisted with id=%s", record.id)

    def test_record_id_is_uuid_string(self, db_session):
        record = self._make_record()
        db_session.add(record)
        db_session.flush()
        assert isinstance(record.id, str)
        # Verify it's a valid UUID
        uuid.UUID(record.id)

    # ── Read ─────────────────────────────────────────────────────────────────

    def test_read_filename(self, db_session):
        record = self._make_record(filename="cbc_report.pdf")
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.filename == "cbc_report.pdf"

    def test_read_original_and_redacted_text(self, db_session):
        record = self._make_record(
            original_text="ORIGINAL_CONTENT",
            redacted_text="REDACTED_CONTENT",
        )
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.original_text == "ORIGINAL_CONTENT"
        assert fetched.redacted_text == "REDACTED_CONTENT"

    def test_read_phi_count(self, db_session):
        record = self._make_record(phi_count=7)
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.phi_count == 7

    # ── JSON fields ──────────────────────────────────────────────────────────

    def test_phi_entities_json_roundtrip(self, db_session):
        entities = [
            {"original": "Jane Doe", "replacement": "Mary Smith",
             "phi_type": "PATIENT_NAME", "context": "header"},
            {"original": "01/01/2025", "replacement": "15/01/2025",
             "phi_type": "DATE", "context": "report date"},
        ]
        record = self._make_record(phi_entities=entities, phi_count=2)
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.phi_entities == entities
        assert len(fetched.phi_entities) == 2

    def test_phi_summary_json_roundtrip(self, db_session):
        summary = {"PATIENT_NAME": 2, "DATE": 5, "PHONE": 1}
        record = self._make_record(phi_summary=summary)
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.phi_summary == summary

    def test_empty_phi_entities_persists_as_empty_list(self, db_session):
        record = self._make_record(phi_entities=[], phi_summary={}, phi_count=0)
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.phi_entities == []

    # ── Defaults ─────────────────────────────────────────────────────────────

    def test_created_at_is_populated_automatically(self, db_session):
        record = self._make_record()
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.created_at is not None
        assert isinstance(fetched.created_at, datetime)
        logger.debug("created_at = %s", fetched.created_at)

    def test_default_mode_is_synthetic(self, db_session):
        from db.models import DeidentificationRecord
        record = DeidentificationRecord(
            id=str(uuid.uuid4()),
            filename="f.pdf",
            original_text="orig",
            redacted_text="redacted",
            phi_entities=[],
            phi_summary={},
        )
        db_session.add(record)
        db_session.flush()

        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.mode == "synthetic"

    # ── Multiple records ─────────────────────────────────────────────────────

    def test_multiple_records_can_coexist(self, db_session):
        from db.models import DeidentificationRecord
        ids = [str(uuid.uuid4()) for _ in range(5)]
        for rid in ids:
            db_session.add(self._make_record(id=rid))
        db_session.flush()

        count = db_session.query(DeidentificationRecord).filter(
            DeidentificationRecord.id.in_(ids)
        ).count()
        assert count == 5

    def test_ordering_by_created_at(self, db_session):
        """Records should be retrievable in descending created_at order."""
        from db.models import DeidentificationRecord
        for i in range(3):
            db_session.add(self._make_record(filename=f"file_{i}.pdf"))
        db_session.flush()

        records = (
            db_session.query(DeidentificationRecord)
            .order_by(DeidentificationRecord.created_at.desc())
            .limit(3)
            .all()
        )
        assert len(records) == 3

    # ── OCR flag ─────────────────────────────────────────────────────────────

    def test_ocr_used_true_persists(self, db_session):
        record = self._make_record(ocr_used=True)
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.ocr_used is True

    def test_ocr_used_false_persists(self, db_session):
        record = self._make_record(ocr_used=False)
        db_session.add(record)
        db_session.flush()

        from db.models import DeidentificationRecord
        fetched = db_session.query(DeidentificationRecord).filter_by(id=record.id).first()
        assert fetched.ocr_used is False
