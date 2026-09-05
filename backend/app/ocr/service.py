"""
OCR extraction service.

Section 13: "The OCR provider should be abstracted so Tesseract can later
be replaced with an enterprise OCR service such as Azure AI Document
Intelligence." `OCRProvider` is that abstraction boundary — callers (the
background task in tasks.py) depend only on `extract_text(content, file_type)
-> str`, never on Tesseract directly.

This is genuinely tested against the real `tesseract` binary (installed via
apt) — unlike the SharePoint integration, OCR has no external network
dependency, so we're not limited to mocks here.
"""
import io
from abc import ABC, abstractmethod

import pymupdf
import pytesseract
from PIL import Image

from app.core.config import get_settings

_settings = get_settings()
if _settings.TESSERACT_CMD:
    # See TESSERACT_CMD's docstring in core/config.py — needed on Windows
    # where PATH lookup for an already-running process isn't reliable.
    pytesseract.pytesseract.tesseract_cmd = _settings.TESSERACT_CMD


class OCRProvider(ABC):
    @abstractmethod
    async def extract_text(self, content: bytes, file_type: str) -> str:
        """Returns extracted text, or an empty string if nothing was found."""


class TesseractOCRProvider(OCRProvider):
    """
    Text-based PDFs get their text pulled directly (PyMuPDF) — much faster
    and more accurate than OCR when the PDF already has a text layer.
    Scanned PDFs and raw images go through actual Tesseract OCR.
    """

    async def extract_text(self, content: bytes, file_type: str) -> str:
        file_type = file_type.lower()
        if file_type == "pdf":
            return self._extract_from_pdf(content)
        if file_type in ("jpg", "jpeg", "png", "tiff"):
            return self._ocr_image_bytes(content)
        return ""

    def _extract_from_pdf(self, content: bytes) -> str:
        doc = pymupdf.open(stream=content, filetype="pdf")
        try:
            text_layer = "\n".join(page.get_text() for page in doc)
            if text_layer.strip():
                # Real, embedded text layer — no OCR needed at all.
                return text_layer.strip()

            # No text layer (scanned/image-only PDF) — rasterize each page
            # and OCR it. 200 DPI balances legibility against processing time
            # for typical scanned invoices/contracts (Section 12's example).
            parts = []
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                parts.append(self._ocr_image_bytes(img_bytes))
            return "\n".join(parts).strip()
        finally:
            doc.close()

    def _ocr_image_bytes(self, content: bytes) -> str:
        image = Image.open(io.BytesIO(content))
        return pytesseract.image_to_string(image).strip()


_default_provider = TesseractOCRProvider()


def get_ocr_provider() -> OCRProvider:
    return _default_provider
