import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Phải đặt biến môi trường TRƯỚC khi import app.
_tmp = tempfile.mkdtemp(prefix="mathchat_test_")
os.environ["DATA_DIR"] = _tmp
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["AI_PIPELINE_ENABLED"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.models import pipeline_model  # noqa: E402
from backend.app.models.database import Base, Document, SessionLocal, engine  # noqa: E402

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture(autouse=True)
def _clean_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    pipeline_model.clear_cache()
    yield


@pytest.fixture
def client(monkeypatch):
    # Không chạy pipeline thật (MinerU/FAISS) trong test API.
    monkeypatch.setattr(pipeline_model, "submit_pipeline", lambda document_id, job_id: None)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def pdf_bytes() -> bytes:
    return PDF_BYTES


@pytest.fixture
def make_doc():
    def _make(status: str = "ready", docx: bool = False, filename: str = "bai_giang.pdf") -> str:
        with SessionLocal() as db:
            doc = Document(filename=filename, status=status)
            db.add(doc)
            db.commit()
            doc_id = doc.id
        d = get_settings().doc_dir(doc_id)
        d.mkdir(parents=True, exist_ok=True)
        if docx:
            (d / "output.docx").write_bytes(b"PK\x03\x04fake-docx")
        return doc_id
    return _make