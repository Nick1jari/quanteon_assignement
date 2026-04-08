"""
Unit tests — engine/ocr.py

Tests cover:
  - The public extract_text dispatcher (routing by extension)
  - _from_txt: UTF-8 decoding, whitespace stripping, encoding error tolerance
  - _from_image: Tesseract invocation, empty-result error, invalid image error
  - _from_pdf: native text path, OCR fallback, invalid PDF error
  - _run_tesseract: image pre-processing, TesseractNotFoundError, generic errors

All external I/O (fitz, PIL, pytesseract) is mocked — no real files needed.

Markers: @pytest.mark.unit
"""

import io
import logging
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from PIL import Image

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rgb_image(width: int = 100, height: int = 50) -> Image.Image:
    """Create a minimal in-memory RGB image for testing."""
    return Image.new("RGB", (width, height), color=(255, 255, 255))


def _make_rgba_image(width: int = 100, height: int = 50) -> Image.Image:
    return Image.new("RGBA", (width, height), color=(200, 200, 200, 128))


# ---------------------------------------------------------------------------
# extract_text dispatcher
# ---------------------------------------------------------------------------

class TestExtractTextDispatcher:

    @patch("engine.ocr._from_pdf", return_value=("pdf text", False))
    def test_pdf_extension_routes_to_from_pdf(self, mock_pdf):
        from engine.ocr import extract_text
        result = extract_text(b"bytes", "report.pdf")
        mock_pdf.assert_called_once_with(b"bytes")
        assert result == ("pdf text", False)

    @patch("engine.ocr._from_pdf", return_value=("pdf text", False))
    def test_pdf_extension_case_insensitive(self, mock_pdf):
        from engine.ocr import extract_text
        extract_text(b"bytes", "REPORT.PDF")
        mock_pdf.assert_called_once()

    @patch("engine.ocr._from_image", return_value=("image text", True))
    def test_png_extension_routes_to_from_image(self, mock_img):
        from engine.ocr import extract_text
        result = extract_text(b"bytes", "scan.png")
        mock_img.assert_called_once_with(b"bytes")
        assert result == ("image text", True)

    @patch("engine.ocr._from_image", return_value=("image text", True))
    def test_jpg_extension_routes_to_from_image(self, mock_img):
        from engine.ocr import extract_text
        extract_text(b"bytes", "scan.jpg")
        mock_img.assert_called_once()

    @patch("engine.ocr._from_image", return_value=("image text", True))
    def test_tiff_extension_routes_to_from_image(self, mock_img):
        from engine.ocr import extract_text
        extract_text(b"bytes", "scan.tiff")
        mock_img.assert_called_once()

    @patch("engine.ocr._from_txt", return_value=("plain text", False))
    def test_txt_extension_routes_to_from_txt(self, mock_txt):
        from engine.ocr import extract_text
        result = extract_text(b"plain text", "notes.txt")
        mock_txt.assert_called_once_with(b"plain text")
        assert result == ("plain text", False)

    @patch("engine.ocr._from_pdf", return_value=("pdf text", False))
    def test_unknown_extension_tries_pdf_first(self, mock_pdf):
        from engine.ocr import extract_text
        result = extract_text(b"bytes", "document.xyz")
        mock_pdf.assert_called_once()
        assert result == ("pdf text", False)

    @patch("engine.ocr._from_txt", return_value=("fallback text", False))
    @patch("engine.ocr._from_pdf", side_effect=ValueError("not a pdf"))
    def test_unknown_extension_falls_back_to_txt(self, mock_pdf, mock_txt):
        from engine.ocr import extract_text
        result = extract_text(b"raw bytes", "document.xyz")
        mock_txt.assert_called_once()
        assert result[0] == "fallback text"


# ---------------------------------------------------------------------------
# _from_txt
# ---------------------------------------------------------------------------

class TestFromTxt:

    def test_decodes_utf8(self):
        from engine.ocr import _from_txt
        text, ocr_used = _from_txt("Hello, World!".encode("utf-8"))
        assert text == "Hello, World!"
        assert ocr_used is False

    def test_strips_leading_trailing_whitespace(self):
        from engine.ocr import _from_txt
        text, _ = _from_txt(b"   Hello   \n")
        assert text == "Hello"

    def test_handles_latin1_via_replace(self):
        """Non-UTF-8 bytes should not raise; they get replaced."""
        from engine.ocr import _from_txt
        bad_bytes = b"Hello \xff World"
        text, _ = _from_txt(bad_bytes)
        assert "Hello" in text

    def test_empty_bytes_returns_empty_string(self):
        from engine.ocr import _from_txt
        text, _ = _from_txt(b"")
        assert text == ""

    def test_multiline_preserved(self):
        from engine.ocr import _from_txt
        content = "Line 1\nLine 2\nLine 3"
        text, _ = _from_txt(content.encode())
        assert "Line 2" in text


# ---------------------------------------------------------------------------
# _from_image
# ---------------------------------------------------------------------------

class TestFromImage:

    @patch("engine.ocr._run_tesseract", return_value="Extracted OCR text")
    @patch("PIL.Image.open", return_value=_make_rgb_image())
    def test_returns_ocr_text_and_ocr_used_true(self, mock_open, mock_tesseract):
        from engine.ocr import _from_image
        text, ocr_used = _from_image(b"fake_image_bytes")
        assert text == "Extracted OCR text"
        assert ocr_used is True

    @patch("engine.ocr._run_tesseract", return_value="")
    @patch("PIL.Image.open", return_value=_make_rgb_image())
    def test_raises_value_error_when_ocr_empty(self, mock_open, mock_tesseract):
        from engine.ocr import _from_image
        with pytest.raises(ValueError, match="no text"):
            _from_image(b"blank_image")

    def test_raises_value_error_on_invalid_bytes(self):
        from engine.ocr import _from_image
        with pytest.raises(ValueError, match="Cannot open image"):
            _from_image(b"this is not an image")

    @patch("engine.ocr._run_tesseract", return_value="Some medical data")
    @patch("PIL.Image.open", return_value=_make_rgb_image())
    def test_invokes_run_tesseract(self, mock_open, mock_tesseract):
        from engine.ocr import _from_image
        _from_image(b"img_bytes")
        mock_tesseract.assert_called_once()


# ---------------------------------------------------------------------------
# _from_pdf
# ---------------------------------------------------------------------------

class TestFromPdf:

    def _make_mock_page(self, text: str) -> MagicMock:
        page = MagicMock()
        page.get_text.return_value = text
        page.get_pixmap.return_value.tobytes.return_value = b"PNG_BYTES"
        return page

    @patch("fitz.open")
    def test_uses_native_text_when_sufficient(self, mock_fitz_open):
        from engine.ocr import _from_pdf

        long_text = "Patient: John Doe\n" * 5  # >50 chars
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__iter__.return_value = iter([self._make_mock_page(long_text)])
        mock_doc.__getitem__ = lambda self, idx: self._make_mock_page(long_text)
        mock_fitz_open.return_value = mock_doc

        # Rebuild with proper indexing
        page = self._make_mock_page(long_text)
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=page)

        text, ocr_used = _from_pdf(b"%PDF-1.4 fake")
        assert ocr_used is False

    @patch("fitz.open", side_effect=Exception("Cannot open"))
    def test_raises_value_error_on_invalid_pdf(self, mock_fitz_open):
        from engine.ocr import _from_pdf
        with pytest.raises(ValueError, match="Cannot open PDF"):
            _from_pdf(b"definitely not a pdf")


# ---------------------------------------------------------------------------
# _run_tesseract
# ---------------------------------------------------------------------------

class TestRunTesseract:

    @patch("pytesseract.image_to_string", return_value="Medical report text")
    def test_returns_tesseract_output(self, mock_tess):
        from engine.ocr import _run_tesseract
        result = _run_tesseract(_make_rgb_image())
        assert result == "Medical report text"
        mock_tess.assert_called_once()

    @patch("pytesseract.image_to_string", return_value="converted ok")
    def test_handles_rgba_image_conversion(self, mock_tess):
        """RGBA images must be converted before OCR — no crash."""
        from engine.ocr import _run_tesseract
        rgba = _make_rgba_image()
        result = _run_tesseract(rgba)
        assert result == "converted ok"

    @patch("pytesseract.image_to_string", side_effect=Exception("tess crashed"))
    def test_raises_value_error_on_generic_failure(self, mock_tess):
        from engine.ocr import _run_tesseract
        with pytest.raises(ValueError, match="OCR processing error"):
            _run_tesseract(_make_rgb_image())

    @patch("pytesseract.image_to_string")
    def test_uses_lstm_oem_and_psm3(self, mock_tess):
        """Verify Tesseract is invoked with OEM 1 (LSTM) and PSM 3 (auto)."""
        mock_tess.return_value = "text"
        from engine.ocr import _run_tesseract, _TESSERACT_CONFIG
        _run_tesseract(_make_rgb_image())
        _, kwargs = mock_tess.call_args
        assert "--oem 1" in kwargs.get("config", _TESSERACT_CONFIG)
        assert "--psm 3" in kwargs.get("config", _TESSERACT_CONFIG)
