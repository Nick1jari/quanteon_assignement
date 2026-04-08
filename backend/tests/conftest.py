"""
Shared pytest fixtures for the HIPAA De-identification test suite.

Database strategy:
  - Uses an in-memory SQLite engine with StaticPool so ALL sessions within a
    test run share the same underlying connection.  Without StaticPool, each
    new session opens a new connection, and in-memory SQLite creates an empty
    database per connection — tables would vanish between session creates.

Usage:
    pytest tests/ -v                  # run all tests
    pytest tests/ -m unit             # only unit tests
    pytest tests/ -m integration      # only integration tests
    pytest tests/ -k "test_ocr"       # run tests matching pattern
"""

import os
import sys

import pytest
from sqlalchemy import create_engine, text as _text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Env vars MUST be set before any app module is imported ────────────────────
os.environ["GROQ_API_KEY"]           = "gsk_test-placeholder"
os.environ["DB_PATH"]                = ":memory:"
os.environ["LOG_LEVEL"]             = "WARNING"   # silence noise during tests
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"     # effectively disable rate limiting

# Ensure the backend root is on sys.path for direct module imports in tests
_backend_root = os.path.dirname(os.path.dirname(__file__))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

# ── Imports after env is ready ────────────────────────────────────────────────
from db.database import get_db   # noqa: E402
from db.models import Base       # noqa: E402
from main import app             # noqa: E402


# ---------------------------------------------------------------------------
# In-memory SQLite engine — session-scoped, shared via StaticPool
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_engine():
    """
    Create a session-scoped in-memory SQLite engine that shares a single
    underlying connection across all sessions (StaticPool).

    This is necessary because SQLite in-memory databases are per-connection:
    without StaticPool, each new Session() would see an empty database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,          # ← all sessions share the same connection
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_engine):
    """
    Provide a per-test SQLAlchemy session.

    Changes are flushed (so they are queryable within the test) but rolled
    back on teardown to keep tests isolated from each other.
    """
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def api_client(test_engine):
    """
    FastAPI TestClient whose database dependency is overridden with the
    in-memory test engine.

    Sessions created for API requests commit normally (so audit records are
    visible to subsequent queries in the same test).  After each test, all
    rows in deidentification_records are deleted to maintain isolation.
    """
    from fastapi.testclient import TestClient

    Session = sessionmaker(bind=test_engine)

    def _override_get_db():
        db = Session()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    # Teardown: clear records so tests don't bleed into each other
    app.dependency_overrides.clear()
    with test_engine.connect() as conn:
        conn.execute(_text("DELETE FROM deidentification_records"))
        conn.commit()


# ---------------------------------------------------------------------------
# Reusable test data
# ---------------------------------------------------------------------------

SAMPLE_MEDICAL_TEXT = (
    "Patient: Mr. John Doe\n"
    "DOB: 15/03/1982\n"
    "Phone: 9876543210\n"
    "Address: 12, MG Road, Mumbai - 400001\n"
    "Report ID: RPT-2025-001\n"
    "Referred by: Dr. Priya Sharma\n"
    "Report Date: 10/04/2025\n"
    "\n"
    "Hemoglobin: 13.5 g/dL  (reference: 12-17 g/dL)  NORMAL\n"
    "Total WBC:  9000 /cumm  (reference: 4000-11000)  NORMAL\n"
    "Platelet:   320000 /cumm\n"
)

MOCK_PHI_ENTITIES = [
    {"original": "John Doe",        "replacement": "James Smith",    "phi_type": "PATIENT_NAME", "context": "Patient name in header"},
    {"original": "15/03/1982",      "replacement": "29/03/1982",     "phi_type": "DATE",         "context": "Date of birth"},
    {"original": "9876543210",      "replacement": "8765432109",     "phi_type": "PHONE",        "context": "Patient phone number"},
    {"original": "12, MG Road, Mumbai - 400001", "replacement": "45, Park Street, Delhi - 110001", "phi_type": "ADDRESS", "context": "Patient address"},
    {"original": "RPT-2025-001",    "replacement": "RPT-7843-XZ9",  "phi_type": "PATIENT_ID",   "context": "Report identifier"},
    {"original": "Dr. Priya Sharma","replacement": "Dr. Thomas Lee", "phi_type": "DOCTOR_NAME",  "context": "Referring physician"},
    {"original": "10/04/2025",      "replacement": "24/04/2025",     "phi_type": "DATE",         "context": "Report date"},
]

MOCK_DEIDENTIFY_RESULT = {
    "redacted_text": (
        "Patient: Mr. James Smith\n"
        "DOB: 29/03/1982\n"
        "Phone: 8765432109\n"
        "Address: 45, Park Street, Delhi - 110001\n"
        "Report ID: RPT-7843-XZ9\n"
        "Referred by: Dr. Thomas Lee\n"
        "Report Date: 24/04/2025\n"
        "\n"
        "Hemoglobin: 13.5 g/dL  (reference: 12-17 g/dL)  NORMAL\n"
        "Total WBC:  9000 /cumm  (reference: 4000-11000)  NORMAL\n"
        "Platelet:   320000 /cumm\n"
    ),
    "phi_entities": MOCK_PHI_ENTITIES,
    "summary": {
        "PATIENT_NAME": 1, "DATE": 2, "PHONE": 1,
        "ADDRESS": 1, "PATIENT_ID": 1, "DOCTOR_NAME": 1,
    },
}
