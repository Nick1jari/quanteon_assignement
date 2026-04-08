"""
OCR Module — Text extraction from PDFs and images.

Extraction strategy:
  1. PyMuPDF (fitz) — native text extraction for digital PDFs (fast, accurate).
  2. Tesseract LSTM (OEM 1, PSM 3) — fallback for scanned / image-only PDFs,
     standalone images (PNG/JPG/TIFF), and handwritten text.

Tesseract settings:
  --oem 1  : LSTM neural-net engine only (better accuracy than legacy OEM 0/3).
  --psm 3  : Fully automatic page segmentation (handles multi-column lab reports,
             tables, and mixed-layout documents better than PSM 6).
"""

import io
import logging

import shutil

import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

# Minimum extracted characters to consider native PDF text extraction successful.
_MIN_TEXT_THRESHOLD = 50

# Tesseract config: LSTM engine + auto page segmentation
_TESSERACT_CONFIG = "--oem 1 --psm 3"


def _tesseract_available() -> bool:
    """Return True if the tesseract binary is reachable on PATH."""
    return shutil.which("tesseract") is not None


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def extract_text(file_bytes: bytes, filename: str) -> tuple[str, bool]:
    """
    Extract text from an uploaded file.

    Returns:
        (text, ocr_used) where ocr_used=True means Tesseract was invoked.

    Raises:
        ValueError: If extraction fails entirely.
    """
    name = filename.lower()

    if name.endswith(".pdf"):
        return _from_pdf(file_bytes)
    elif name.endswith((".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")):
        return _from_image(file_bytes)
    elif name.endswith(".txt"):
        return _from_txt(file_bytes)
    else:
        # Unknown extension — try PDF first, fall back to plain text
        try:
            return _from_pdf(file_bytes)
        except Exception:
            return _from_txt(file_bytes)


# ---------------------------------------------------------------------------
# Extraction strategies
# ---------------------------------------------------------------------------

def _from_pdf(file_bytes: bytes) -> tuple[str, bool]:
    """Extract text from a PDF. Falls back to OCR for scanned pages."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {exc}") from exc

    pages_text: list[str] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        native = page.get_text("text").strip()
        pages_text.append(native)

    full_text = "\n".join(pages_text).strip()

    if len(full_text) >= _MIN_TEXT_THRESHOLD:
        doc.close()
        logger.info("PDF text extracted natively (%d chars)", len(full_text))
        return full_text, False

    # Scanned PDF — check Tesseract is available before attempting OCR
    if not _tesseract_available():
        doc.close()
        raise ValueError(
            "This PDF appears to be scanned or image-based and requires OCR, "
            "but Tesseract is not installed in the current environment. "
            "Please upload a text-based PDF or a plain TXT file instead."
        )

    logger.info("Native PDF text insufficient (%d chars); switching to OCR", len(full_text))
    ocr_pages: list[str] = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        # 2× resolution for better OCR fidelity
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        ocr_pages.append(_run_tesseract(img))

    doc.close()
    return "\n".join(ocr_pages).strip(), True


def _from_image(file_bytes: bytes) -> tuple[str, bool]:
    """Extract text from a standalone image file using Tesseract."""
    if not _tesseract_available():
        raise ValueError(
            "Image text extraction requires Tesseract OCR, which is not installed "
            "in the current environment. Please upload a text-based PDF or TXT file instead."
        )
    try:
        image = Image.open(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Cannot open image: {exc}") from exc

    text = _run_tesseract(image)
    if not text.strip():
        raise ValueError("Tesseract returned no text from the image. "
                         "Ensure the image is legible and not blank.")
    return text, True


def _from_txt(file_bytes: bytes) -> tuple[str, bool]:
    """Decode a plain-text file."""
    try:
        return file_bytes.decode("utf-8", errors="replace").strip(), False
    except Exception as exc:
        raise ValueError(f"Cannot decode text file: {exc}") from exc


# ---------------------------------------------------------------------------
# Tesseract wrapper with image pre-processing
# ---------------------------------------------------------------------------

def _run_tesseract(image: Image.Image) -> str:
    """
    Pre-process the image for better OCR accuracy (especially for handwriting),
    then run Tesseract with optimised settings.

    Pre-processing steps:
      1. Convert to greyscale — removes colour noise.
      2. Auto-contrast — improves dark/light differentiation.
      3. Sharpen — helps with blurry scans.
    """
    # Convert to RGB first (handles RGBA, CMYK, etc.)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    # Greyscale → auto-contrast → sharpen
    grey = ImageOps.grayscale(image)
    contrasted = ImageOps.autocontrast(grey, cutoff=2)
    sharpened = contrasted.filter(ImageFilter.SHARPEN)

    try:
        return pytesseract.image_to_string(sharpened, config=_TESSERACT_CONFIG)
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR is not installed or not in PATH. "
            "Install it with: apt-get install tesseract-ocr"
        ) from exc
    except Exception as exc:
        logger.exception("Tesseract OCR failed")
        raise ValueError(f"OCR processing error: {exc}") from exc
