"""Fixture dùng chung: dữ liệu tạm, PDF mẫu, cấu hình trỏ tới mineru-kit giả."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="pdf2docx_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["MINERU_CMD"] = f'"{sys.executable}" "{Path(__file__).parent / "fake_mineru_kit.py"}"'
os.environ["MINERU_TIMEOUT_MIN_S"] = "60"
os.environ["MINERU_STAGGER_S"] = "0"            # test không chờ 20s giữa 2 lần khởi động (có test riêng cho so le)
os.environ["FAKE_MINERU_DELAY_PER_PAGE"] = "0.01"


def make_pdf(path: Path, pages: int, label: str = "Trang") -> Path:
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path))
    for i in range(1, pages + 1):
        for j in range(4):
            c.drawString(50, 800 - j * 20, f"{label} {i} dong {j}: dao ham la gioi han cua ti so gia so tren so gia doi so.")
        c.showPage()
    c.save()
    return path


@pytest.fixture(scope="session", autouse=True)
def _engine_present():
    """Backend dùng src/build_docx.py của thư mục dự án rag_toan NẰM NGANG backend/ và frontend/."""
    from backend.app.engine import rag_toan
    info = rag_toan.engine_info()
    assert info["found"], "Không thấy thư mục dự án rag_toan cạnh backend/ (cần có src/build_docx.py) - xem README"


@pytest.fixture(scope="session")
def pdf_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("pdfs")


@pytest.fixture(scope="session")
def pdf_factory(pdf_dir):
    def _make(name: str, pages: int, label: str = "Trang") -> Path:
        return make_pdf(pdf_dir / name, pages, label)
    return _make
