"""
HIPAA De-identification API — FastAPI Backend
Version: v1
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import groq
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from werkzeug.utils import secure_filename

from config import get_settings
from db.database import get_db, init_db
from db.models import DeidentificationRecord
from engine.deidentifier import deidentify
from engine.ocr import extract_text
from engine.report import generate_report

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized. CORS origins: %s", settings.cors_origins_list)
    yield

app = FastAPI(
    title="HIPAA De-identification API",
    description="AI-powered medical document de-identification using Claude.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,     # Must be False when allow_origins is not ["*"]
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".txt"}

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response



@app.get("/api/v1/health", tags=["System"])
def health() -> dict:
    """Liveness check. Returns current timestamp and version."""
    return {
        "status": "ok",
        "version": app.version,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/v1/deidentify", tags=["De-identification"])
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def deidentify_document(
    request: Request,
    file: UploadFile = File(..., description="Medical document (PDF, image, or TXT)"),
    mode: str = Form(
        default="synthetic",
        description="'synthetic' for realistic fake data, 'placeholder' for [LABEL] tags",
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Upload a medical document and receive a fully de-identified version.

    - Extracts text via PyMuPDF (digital PDFs) or Tesseract OCR (scanned/image).
    - Sends text to Claude for HIPAA Safe Harbor de-identification.
    - Returns original text, de-identified text, PHI entity list, and audit metadata.
    """
    # --- Validate mode ---
    if mode not in ("synthetic", "placeholder"):
        raise HTTPException(status_code=400, detail="mode must be 'synthetic' or 'placeholder'")

    # --- Validate file ---
    raw_filename = file.filename or "upload.txt"
    filename = secure_filename(raw_filename) or "upload.txt"
    ext = _get_extension(filename)

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Maximum: {settings.max_file_size_mb} MB.",
        )

    # --- OCR / text extraction ---
    try:
        original_text, ocr_used = extract_text(file_bytes, filename)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not original_text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from the document. "
                   "Ensure the file is not blank or password-protected.",
        )

    # --- De-identification via Claude ---
    t0 = time.perf_counter()
    try:
        result = deidentify(original_text, mode=mode, seed_key=filename)

    except groq.RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="Groq API rate limit reached. Please retry in a few seconds.",
        )
    except groq.AuthenticationError:
        raise HTTPException(
            status_code=503,
            detail="Invalid Groq API key. Check your GROQ_API_KEY configuration.",
        )
    except groq.APIConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Could not reach the Groq API. Check your network connection.",
        )
    except groq.APIStatusError as exc:
        logger.error("Groq API error %s: %s", exc.status_code, exc.message)
        raise HTTPException(
            status_code=502,
            detail=f"Groq API error ({exc.status_code}). Please retry.",
        )
    except ValueError as exc:
        # JSON parse failure from deidentifier
        raise HTTPException(status_code=422, detail=str(exc))

    processing_time_ms = int((time.perf_counter() - t0) * 1000)

    phi_entities = result["phi_entities"]
    summary = result.get("summary", {})
    redacted_text = result["redacted_text"]

    # --- Build audit report ---
    report = generate_report(
        filename=filename,
        phi_entities=phi_entities,
        summary=summary,
        original_text=original_text,
        redacted_text=redacted_text,
        ocr_used=ocr_used,
        processing_time_ms=processing_time_ms,
        mode=mode,
    )

    # --- Persist to DB ---
    record_id = str(uuid.uuid4())
    record = DeidentificationRecord(
        id=record_id,
        filename=filename,
        original_text=original_text,
        redacted_text=redacted_text,
        phi_entities=phi_entities,
        phi_summary=summary,
        phi_count=len(phi_entities),
        ocr_used=ocr_used,
        processing_time_ms=processing_time_ms,
        mode=mode,
    )
    try:
        db.add(record)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to persist de-identification record id=%s", record_id)
        # Do not fail the request — return the result even if audit persistence failed
        report["audit"]["persistence_warning"] = (
            "Audit record could not be saved to the database."
        )

    return {"id": record_id, **report}


@app.get("/api/v1/reports", tags=["Audit"])
def list_reports(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return a paginated list of de-identification audit records."""
    total = db.query(DeidentificationRecord).count()
    records = (
        db.query(DeidentificationRecord)
        .order_by(DeidentificationRecord.created_at.desc())
        .offset(offset)
        .limit(min(limit, 100))   # hard cap per request
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": [_record_summary(r) for r in records],
    }


@app.get("/api/v1/reports/{record_id}", tags=["Audit"])
def get_report(record_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return full details (including original + redacted text) for a single record."""
    record = (
        db.query(DeidentificationRecord)
        .filter(DeidentificationRecord.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Record not found.")
    return _record_full(record)


@app.get("/api/v1/dashboard/stats", tags=["Dashboard"])
def dashboard_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Aggregate statistics across all processed documents.
    Used by the Compliance Dashboard.
    """
    records = (
        db.query(DeidentificationRecord)
        .with_entities(
            DeidentificationRecord.phi_count,
            DeidentificationRecord.phi_summary,
            DeidentificationRecord.ocr_used,
            DeidentificationRecord.processing_time_ms,
            DeidentificationRecord.filename,
        )
        .all()
    )

    if not records:
        return {
            "total_documents": 0,
            "total_phi_found": 0,
            "phi_by_category": {},
            "ocr_count": 0,
            "avg_processing_time_ms": 0,
            "recent_filenames": [],
        }

    total_phi = sum(r.phi_count for r in records)
    combined: dict[str, int] = {}
    for r in records:
        for phi_type, count in (r.phi_summary or {}).items():
            combined[phi_type] = combined.get(phi_type, 0) + count

    avg_time = int(sum(r.processing_time_ms for r in records) / len(records))

    return {
        "total_documents": len(records),
        "total_phi_found": total_phi,
        "phi_by_category": combined,
        "ocr_count": sum(1 for r in records if r.ocr_used),
        "avg_processing_time_ms": avg_time,
        "recent_filenames": [r.filename for r in records[:5]],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_extension(filename: str) -> str:
    parts = filename.rsplit(".", 1)
    return f".{parts[-1].lower()}" if len(parts) == 2 else ""


def _record_summary(r: DeidentificationRecord) -> dict:
    return {
        "id": r.id,
        "filename": r.filename,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "phi_count": r.phi_count,
        "phi_summary": r.phi_summary,
        "ocr_used": r.ocr_used,
        "processing_time_ms": r.processing_time_ms,
        "mode": r.mode,
    }


def _record_full(r: DeidentificationRecord) -> dict:
    return {
        **_record_summary(r),
        "original_text": r.original_text,
        "redacted_text": r.redacted_text,
        "phi_entities": r.phi_entities,
    }
