"""
Database connection setup.

Uses SQLite via SQLAlchemy.  The DB path is configured through the
DB_PATH environment variable (default: /app/data/deidentification.db).

All public functions include structured logging and raise on hard failures
so callers can surface meaningful error messages.
"""
import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from .models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine setup
# ---------------------------------------------------------------------------

DB_PATH = os.getenv("DB_PATH", "/app/data/deidentification.db")

# :memory: is a special SQLite URI — no directory to create
if DB_PATH != ":memory:":
    _db_dir = os.path.dirname(DB_PATH)
    if _db_dir:
        try:
            os.makedirs(_db_dir, exist_ok=True)
            logger.debug("DB directory ensured: %s", _db_dir)
        except OSError as exc:
            logger.critical("Cannot create DB directory '%s': %s", _db_dir, exc)
            raise

DATABASE_URL = "sqlite:///:memory:" if DB_PATH == ":memory:" else f"sqlite:///{DB_PATH}"

try:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        # Pool settings suitable for SQLite in multi-worker context
        pool_pre_ping=True,
    )
    logger.debug("SQLAlchemy engine created: %s", DATABASE_URL)
except SQLAlchemyError as exc:
    logger.critical("Failed to create database engine: %s", exc, exc_info=True)
    raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def init_db() -> None:
    """
    Create all tables defined in models.py if they do not exist.
    Called once at application startup.

    Raises:
        SQLAlchemyError: If the database is unreachable or schema creation fails.
    """
    try:
        Base.metadata.create_all(bind=engine)
        # Verify connectivity with a lightweight query
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database initialized and connectivity verified: %s", DB_PATH)
    except OperationalError as exc:
        logger.critical(
            "Cannot connect to or initialize database at '%s': %s",
            DB_PATH, exc, exc_info=True,
        )
        raise
    except SQLAlchemyError as exc:
        logger.critical("Database schema creation failed: %s", exc, exc_info=True)
        raise


def get_db():
    """
    FastAPI dependency that yields a scoped SQLAlchemy session.

    The session is always closed in the finally block.
    Any SQLAlchemy errors during the request are logged before re-raising
    so they appear in the server logs with full context.
    """
    db = SessionLocal()
    logger.debug("DB session opened (id=%d)", id(db))
    try:
        yield db
    except SQLAlchemyError as exc:
        logger.error(
            "SQLAlchemy error during request — rolling back session (id=%d): %s",
            id(db), exc, exc_info=True,
        )
        db.rollback()
        raise
    finally:
        logger.debug("DB session closed (id=%d)", id(db))
        db.close()
