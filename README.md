# Medical De-identification System

An AI-powered system that detects and redacts Protected Health Information (PHI) from medical documents — lab reports, clinical notes, discharge summaries — following the HIPAA Safe Harbor method (45 CFR §164.514(b)).

---

## Quick Start

### Prerequisites
- Docker & Docker Compose (v2+)
- A [Groq API key](https://console.groq.com/) — free, no credit card required

### 1. Configure environment
```bash
cp .env.example .env
# Edit .env and paste your Groq API key
```

### 2. Build and run
```bash
docker compose up --build
```

### 3. Open the app

| Service  | URL                        |
|----------|----------------------------|
| Frontend | http://localhost:3001      |
| API docs | http://localhost:8001/docs |

---

## Usage

1. Open **http://localhost:3001**
2. **Upload** a PDF, PNG, JPG, TIFF, or TXT medical document (≤ 20 MB)
3. Choose a **de-identification mode**:
   - **Synthetic Data** — PHI replaced with realistic fake names, shifted dates, and plausible addresses (preserves document feel for research/training)
   - **Placeholder Labels** — PHI replaced with tags like `[PATIENT_NAME]`, `[DATE]` (easier to audit)
4. Click **De-identify Document**
5. Review the side-by-side **Before / After** view with PHI highlights
6. Download the **Redaction Audit Report** — a text summary of every replacement
7. Switch to the **Dashboard** tab for aggregate statistics across all processed documents

---

## Implementation Design

### Model Choice — Llama 3.3 70B via Groq

The core AI engine uses Meta's **Llama 3.3 70B** open-source model served through the Groq API. It was chosen for the following reasons:

| Factor | Llama 3.3 70B (Groq) | SpaCy / Presidio |
|--------|----------------------|-----------------|
| Context understanding | Deep — understands "Ref. By: Dr. X" as a doctor name | Shallow — pattern/entity detection only |
| Multilingual support | Handles mixed scripts in lab reports | Requires per-language models |
| Synthetic replacement | Generates culturally consistent fake data | Requires separate Faker logic |
| Structured JSON output | Instructable via prompt | Requires post-processing |
| Cost | Free tier (14,400 req/day) | Free but lower accuracy |

The prompt instructs the model to return a strict JSON schema (`redacted_text` + `phi_entities[]`). A robust parser handles common LLM quirks — markdown fences, literal newlines inside string values — ensuring reliable machine-parseable output.

### OCR Pipeline

Two-layer extraction handles all document types:

```
PDF upload
    │
    ├─► PyMuPDF (fitz) ── text-based PDF? ──► extracted text ──► Llama 3.3
    │       │
    │       └── < 50 chars? (scanned PDF) ──► Tesseract OCR (2× resolution) ──► Llama 3.3
    │
Image upload (PNG/JPG/TIFF)
    └─► Tesseract OCR ──────────────────────────────────────────────────────► Llama 3.3
```

- **PyMuPDF** extracts text natively from digital PDFs (fast, preserves layout)
- **Tesseract 4** handles scanned/image PDFs and standalone images via OCR
- Each page is rendered at 2× resolution before OCR for better accuracy

### HIPAA PHI Categories Covered (Safe Harbor Method)

| # | Category | Example |
|---|----------|---------|
| 1 | PATIENT_NAME | "Yash M. Patel", "Mr. Mubin Sayed" |
| 2 | DOCTOR_NAME | "Dr. Hiren Shah", "Dr. Payal Shah" |
| 3 | STAFF_NAME | "MUBARAK KARAJGI" |
| 4 | DATE | "02 Dec 2024", "11/04/2025" |
| 5 | PHONE | "9876543210", "0123456789" |
| 6 | EMAIL | "lab@drlogy.com" |
| 7 | ADDRESS | "125, Shivam Bungalow, S G Road, Mumbai" |
| 8 | PATIENT_ID | PID: 555, Report ID: 725 |
| 9 | MEDICAL_RECORD | Sample collection barcode |
| 10 | LAB_CONTACT | Lab phone / website URLs |
| 11 | AGE | "45 years", "M/32" |
| 12 | OTHER | Any remaining identifiers |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Docker Compose                         │
│                                                          │
│  ┌──────────────────┐        ┌────────────────────────┐  │
│  │   Frontend       │        │   Backend              │  │
│  │   React + Vite   │◄──────►│   FastAPI (Python)     │  │
│  │   Nginx :80      │  /api  │   Uvicorn :8000        │  │
│  └──────────────────┘        │                        │  │
│                              │  ┌──────────────────┐  │  │
│                              │  │  OCR Engine       │  │  │
│                              │  │  PyMuPDF+Tessract │  │  │
│                              │  └────────┬─────────┘  │  │
│                              │           │             │  │
│                              │  ┌────────▼─────────┐  │  │
│                              │  │  Groq API         │  │  │
│                              │  │  Llama 3.3 70B    │  │  │
│                              │  └────────┬─────────┘  │  │
│                              │           │             │  │
│                              │  ┌────────▼─────────┐  │  │
│                              │  │  SQLite DB        │  │  │
│                              │  │  (audit trail)    │  │  │
│                              │  └──────────────────┘  │  │
│                              └────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/v1/health` | Health check |
| `POST` | `/api/v1/deidentify` | Upload & de-identify a document |
| `GET`  | `/api/v1/reports` | List audit records (paginated) |
| `GET`  | `/api/v1/reports/{id}` | Full details for a single record |
| `GET`  | `/api/v1/dashboard/stats` | Aggregate compliance statistics |

Interactive API docs: **http://localhost:8001/docs**

---

## Project Structure

```
.
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── pytest.ini
│   ├── config.py            # Pydantic settings, env-variable driven
│   ├── main.py              # FastAPI app, routes, middleware
│   ├── engine/
│   │   ├── ocr.py           # PyMuPDF + Tesseract extraction
│   │   ├── deidentifier.py  # Groq/Llama integration + prompt
│   │   └── report.py        # Audit report builder + risk scoring
│   ├── db/
│   │   ├── models.py        # SQLAlchemy ORM model
│   │   └── database.py      # SQLite connection + session factory
│   └── tests/
│       ├── conftest.py          # Shared fixtures (in-memory DB, test client)
│       ├── test_api.py          # API endpoint integration tests
│       ├── test_deidentifier.py # Deidentifier unit tests
│       ├── test_ocr.py          # OCR engine unit tests
│       ├── test_report.py       # Report builder unit tests
│       └── test_database.py     # Database CRUD integration tests
├── frontend/
│   ├── Dockerfile           # Multi-stage: Vite build → Nginx
│   ├── nginx.conf           # SPA routing + /api reverse proxy
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── src/
│       ├── App.jsx                   # Tab layout, state management
│       ├── api.js                    # Axios API client
│       └── components/
│           ├── UploadPanel.jsx       # Drag-and-drop upload + mode selector
│           ├── ComparisonView.jsx    # Side-by-side before/after with highlights
│           ├── RedactionReport.jsx   # PHI table + downloadable audit report
│           └── Dashboard.jsx         # Compliance dashboard with bar chart
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
sudo apt-get install -y tesseract-ocr   # required by OCR tests

# All 153 tests (unit + integration)
pytest tests/ -v

# Only unit tests (fast, no I/O)
pytest tests/ -m unit

# Only integration tests
pytest tests/ -m integration

# With coverage report
pytest tests/ --cov=. --cov-omit="tests/*" --cov-report=term-missing
```

| File | Marker | Tests | Covers |
|------|--------|-------|--------|
| `test_api.py` | integration | 33 | FastAPI endpoints, error mapping, DB persistence |
| `test_deidentifier.py` | unit | 34 | Groq/Llama prompt, Faker seeding, JSON parsing |
| `test_ocr.py` | unit | 24 | PyMuPDF extraction, Tesseract OCR, dispatch |
| `test_report.py` | unit | 30 | Risk scoring, report structure, lookup tables |
| `test_database.py` | integration | 18 | SQLAlchemy CRUD, schema, session lifecycle |

---

## Development (without Docker)

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install Tesseract (Ubuntu/Debian)
sudo apt-get install tesseract-ocr tesseract-ocr-eng

export GROQ_API_KEY=gsk_...
export DB_PATH=./data/deidentification.db
mkdir -p ./data

uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxies /api → localhost:8000)
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | **Yes** | — | Groq API key (get free at console.groq.com) |
| `DB_PATH` | No | `/app/data/deidentification.db` | SQLite database path |
| `MAX_FILE_SIZE_MB` | No | `20` | Maximum upload size in MB |
| `RATE_LIMIT_PER_MINUTE` | No | `20` | Per-IP rate limit on `/deidentify` |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model ID |
| `GROQ_MAX_TOKENS` | No | `8096` | Max tokens for model response |
| `CORS_ORIGINS` | No | `http://localhost:3001,...` | Comma-separated allowed origins |

See [`.env.example`](.env.example) for a template.
