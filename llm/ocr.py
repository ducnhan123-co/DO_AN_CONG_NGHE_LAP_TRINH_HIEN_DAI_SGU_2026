"""Fallback OCR for scanned PDFs when MinerU is unavailable."""
import subprocess
import tempfile
from pathlib import Path


def extract_pages(pdf_path: Path, language: str = "vie+eng") -> list[str]:
    """Use embedded text first, then Tesseract only for a scanned PDF."""
    from pypdf import PdfReader

    pages = [(page.extract_text() or "").strip() for page in PdfReader(str(pdf_path)).pages]
    if sum(map(len, pages)) >= 50 * max(1, len(pages)):
        return pages

    import fitz

    text = []
    document = fitz.open(str(pdf_path))
    try:
        for page in document:
            with tempfile.NamedTemporaryFile(suffix=".png") as image:
                page.get_pixmap(dpi=180).save(image.name)
                result = subprocess.run(
                    ["tesseract", image.name, "stdout", "-l", language],
                    capture_output=True, text=True, timeout=240, check=True,
                )
                text.append(result.stdout.strip())
    finally:
        document.close()
    return text
