import os
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("APP_DATA_DIR", ROOT / "backend" / "data" / "documents"))
BE_BASE = os.getenv("BE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DOC_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def pdf_path(doc_id: str) -> Path:
    return DATA_DIR / doc_id / "input.pdf"


def docx_path(doc_id: str) -> Path:
    return DATA_DIR / doc_id / "output.docx"


def content_list_path(doc_id: str) -> Path | None:
    found = list((DATA_DIR / doc_id / "mineru").rglob("*_content_list.json"))
    return max(found, key=lambda p: p.stat().st_size) if found else None


def delete_pdf(doc_id: str) -> str:
    """'deleted' | 'unsupported' (BE chưa có endpoint xóa) | 'error'."""
    try:
        response = requests.delete(f"{BE_BASE}/api/doc/{doc_id}", timeout=5)
    except requests.RequestException:
        return "error"
    if response.status_code in (200, 202, 204):
        return "deleted"
    return "unsupported" if response.status_code in (404, 405) else "error"