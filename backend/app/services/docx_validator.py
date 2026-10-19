"""Bước "Kiểm tra file Word": DOCX phải mở được, và đếm số công thức đã thành Equation thật.

Đếm công thức trong Markdown chỉ là ước lượng (regex), nên chênh lệch nhỏ chỉ thành cảnh báo chứ không làm hỏng tài liệu.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Dict, Optional

from lxml import etree

from ..core.errors import PipelineError

_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
_INLINE = re.compile(r"(?<![\\$])\$(?!\$)([^$\n]+?)(?<!\\)\$(?!\$)")
_OMATH = re.compile(rb"<m:oMath(?![A-Za-z])")
_TBL = re.compile(rb"<w:tbl>")


def count_formulas_md(md: str) -> int:
    n_display = len(_DISPLAY.findall(md))
    rest = _DISPLAY.sub(" ", md)
    return n_display + len(_INLINE.findall(rest))


def validate_docx(docx_path: Path, work_md: Optional[Path]) -> Dict:
    if not docx_path.is_file() or docx_path.stat().st_size == 0:
        raise PipelineError("DOCX_INVALID", "File Word không tồn tại hoặc rỗng.")
    try:
        with zipfile.ZipFile(docx_path) as z:
            bad = z.testzip()
            if bad:
                raise PipelineError("DOCX_INVALID", f"File Word bị hỏng ở phần {bad}.")
            names = set(z.namelist())
            if "word/document.xml" not in names:
                raise PipelineError("DOCX_INVALID", "File Word thiếu word/document.xml.")
            xml = z.read("word/document.xml")
            etree.fromstring(xml)                      # XML phải đọc được
            images = sum(1 for n in names if n.startswith("word/media/"))
    except zipfile.BadZipFile as ex:
        raise PipelineError("DOCX_INVALID", "File Word không phải gói .docx hợp lệ.") from ex
    except etree.XMLSyntaxError as ex:
        raise PipelineError("DOCX_INVALID", f"word/document.xml lỗi cú pháp: {ex}") from ex

    equations = len(_OMATH.findall(xml))
    tables = len(_TBL.findall(xml))
    formulas_md = 0
    if work_md and work_md.is_file():
        formulas_md = count_formulas_md(work_md.read_text(encoding="utf-8", errors="ignore"))

    note: Dict = {"equations_docx": equations, "formulas_md": formulas_md, "images": images, "tables": tables}
    if formulas_md and equations < 0.9 * formulas_md:
        note["warning"] = (f"Chỉ {equations}/{formulas_md} công thức thành Equation; phần còn lại có thể "
                           f"đang là chữ thô (xem logs/pipeline.log, mục lệch \\left/\\right).")
    return note
