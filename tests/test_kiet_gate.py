"""Cổng lỗi của tools/kiet_docx.py: chỉ bảng NHỎ hỏng mới kích hoạt fix; bảng lớn hợp lệ và tài liệu sạch thì giữ Kiet thuần."""
import importlib.util
import sys
from pathlib import Path

from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("kiet_docx", ROOT / "tools" / "kiet_docx.py")
kiet_docx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kiet_docx)

TEXT = "chữ " * 200                                                  # đủ dài để không bị coi là scan ít chữ
SMALL_BAD = "<table><tr><td>P</td><td></td></tr><tr><td>T</td><td>F</td><td>x</td></tr></table>"   # hàng lệch số cột
BIG_BAD = "<table>" + SMALL_BAD[7:-8] + "<tr><td>" + "dài " * 1500 + "</td></tr></table>"


def _pdf(tmp_path):
    p = tmp_path / "a.pdf"
    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.write(p)
    return p


def test_small_garbled_table_triggers(tmp_path):
    assert kiet_docx.detect_errors(TEXT + SMALL_BAD, _pdf(tmp_path)) == ["bảng hỏng"]


def test_big_layout_table_and_clean_doc_do_not(tmp_path):
    assert kiet_docx.detect_errors(TEXT + BIG_BAD, _pdf(tmp_path)) == []
    assert kiet_docx.detect_errors(TEXT, _pdf(tmp_path)) == []
