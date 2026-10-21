"""PDF -> DOCX đúng logic nhánh Kiet (bước 0-2 của kiet_ref/../main.py, giữ nguyên tham số mặc định của Kiet).

Dùng code gốc của Kiet trong kiet_ref/src (không sửa). Chạy bằng python của env có `mineru-kit` 4.x
(~/.venvs/mineru4) để có đủ mineru-kit + pytesseract.

  python tools/kiet_docx.py --pdf input.pdf --out output.docx [--name <tên_run>]
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIET = ROOT / "kiet_ref"
MAX_GARBLED_TABLE_CHARS = 3000
sys.path.insert(0, str(KIET))          # `src` = kiet_ref/src (không đụng llm.src của main)

from src.build_docx import fix_legacy_tex_bf, md_to_docx, prepare_work_md  # noqa: E402
from src.columns import (apply_section_columns, drop_ocr_details,  # noqa: E402
                         insert_column_breaks, layout_of)
from src.config import DOCX_DIR, INPUT_DIR, MINERU_TIER, RUNS_DIR  # noqa: E402
from src.parallel_mineru import run_mineru_parallel  # noqa: E402
from src.run_mineru import find_mineru_outputs, prepare_run_dir  # noqa: E402


def detect_errors(md: str, pdf_path: Path) -> list:
    """Dấu hiệu lỗi mà Kiet thuần không xử lý được (chỉ kích hoạt fix của main khi có). Cố ý KHÔNG có
    "công thức dài": PDF mẫu 43799 có công thức dài hợp lệ và phải giữ y chang bản Kiet."""
    sys.path.append(str(ROOT))
    from pypdf import PdfReader
    from llm.src.build_docx import looks_like_garbled_table
    from llm.src.run_mineru import has_extractable_text, pdf_is_legacy_vn
    errs = []
    if pdf_is_legacy_vn(pdf_path):
        errs.append("font TCVN3")
    # bảng nhỏ (chân trị/biến thiên). Bảng cả trang (cheat-sheet dựng bằng 1 bảng lớn) KHÔNG phải bảng hỏng:
    # cắt thành ảnh sẽ mất cả nghìn từ chữ sửa được (đo trên formula-sheet: 10646 -> 3805 từ).
    if any(len(t) < MAX_GARBLED_TABLE_CHARS and looks_like_garbled_table(t)
           for t in re.findall(r"<table.*?</table>", md, flags=re.S)):
        errs.append("bảng hỏng")
    words = len(re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)", " ", md).split())
    if not has_extractable_text(pdf_path) and words < 40 * len(PdfReader(str(pdf_path)).pages):
        errs.append("scan ít chữ")
    return errs


def build_with_fixes(pdf_path: Path, run_dir: Path, out: Path, col_font_pt: float) -> None:
    """Đường có fix của main: MinerU tier advanced (Kiet) nhưng xuất kèm toạ độ khối -> TCVN3, ảnh cắt cho
    bảng/khối hỏng, OCR bù trang scan... (llm/src) rồi dựng DOCX bằng llm/src/build_docx."""
    from llm.src.build_docx import md_to_docx as fix_docx, prepare_work_md as fix_prepare
    from llm.src.config import MINERU_DEVICE, MINERU_LANG
    from llm.src.run_mineru import find_mineru_outputs as fix_find, has_extractable_text, run_mineru as fix_run
    fix_dir = run_dir / "fix"
    mdir = fix_dir / "mineru"
    fix_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, fix_dir / "input.pdf")        # _find_input_pdf tìm input.pdf cạnh run
    fix_run(fix_dir / "input.pdf", mdir, tier="advanced", method="txt" if has_extractable_text(pdf_path) else "ocr",
            lang=MINERU_LANG, device=MINERU_DEVICE, workers=0)
    md_path, _, _ = fix_find(mdir)
    from llm.src.build_docx import fix_legacy_tex_bf as fix_bf
    work_md = fix_dir / "work_for_docx.md"
    fix_prepare(fix_bf(md_path.read_text(encoding="utf-8", errors="ignore")), md_path, work_md)
    fix_docx(work_md, out, md_path.parent)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True, help="Đường dẫn .docx kết quả")
    ap.add_argument("--name", default=None, help="Tên file trong kiet_ref/input (mặc định: tên PDF)")
    ap.add_argument("--tier", default=MINERU_TIER)      # Kiet: advanced
    ap.add_argument("--workers", type=int, default=2)   # Kiet: 2 tiến trình song song
    ap.add_argument("--stagger", type=float, default=20.0)
    ap.add_argument("--ocr-lang", default="eng")
    ap.add_argument("--col-font-pt", type=float, default=8.0)
    ap.add_argument("--no-columns", action="store_true")
    ap.add_argument("--col-breaks", action="store_true",
                    help="Chèn ngắt cột bằng OCR (cần pytesseract). Mặc định TẮT: khớp DOCX mẫu của Kiet "
                         "(đo trên 43799-maths-for-computer-sci: 3 cột liên tục, 0 ngắt cột)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-fix", action="store_true", help="Tắt cổng lỗi: luôn dùng Kiet thuần")
    a = ap.parse_args()

    for p in (INPUT_DIR, DOCX_DIR, RUNS_DIR):
        p.mkdir(parents=True, exist_ok=True)
    src_pdf = Path(a.pdf)
    pdf_path = INPUT_DIR / (a.name or src_pdf.name)
    if src_pdf.resolve() != pdf_path.resolve():
        shutil.copy2(src_pdf, pdf_path)

    _doc_id, run_dir = prepare_run_dir(pdf_path, RUNS_DIR)
    mineru_dir = run_dir / "mineru"
    run_mineru_parallel(pdf_path, mineru_dir, workers=a.workers, tier=a.tier,
                        force=a.force, stagger=a.stagger)
    md_path, _, _ = find_mineru_outputs(mineru_dir)
    markdown_text = fix_legacy_tex_bf(md_path.read_text(encoding="utf-8", errors="ignore"))

    if not a.col_breaks:     # y như máy Kiet không có pytesseract: layout_of() rơi về "chia cột liên tục"
        import src.columns as _cols

        def _no_ocr(*_a, **_k):
            raise ImportError("ngắt cột OCR tắt (dùng --col-breaks để bật)")
        _cols._ocr = _no_ocr
    errs = [] if a.no_fix else detect_errors(markdown_text, pdf_path)
    if errs:
        print(f"[KIET+FIX] phát hiện: {', '.join(errs)} -> dùng đường có fix của main")
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        build_with_fixes(pdf_path, run_dir, out, a.col_font_pt)
        print("KIET_DOCX_OK", out, "(+fix)")
        return
    layout = None if a.no_columns else layout_of(pdf_path, lang=a.ocr_lang)
    docx_md = insert_column_breaks(drop_ocr_details(markdown_text), layout) if layout else markdown_text
    work_md = DOCX_DIR / f"{pdf_path.stem}_for_docx.md"
    prepare_work_md(docx_md, md_path, work_md)
    docx_path = DOCX_DIR / f"{pdf_path.stem}.docx"
    md_to_docx(work_md, docx_path, md_path.parent)
    if layout:
        apply_section_columns(docx_path, layout["n_cols"], layout["page_pt"], body_pt=a.col_font_pt or None)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(docx_path, out)
    print("KIET_DOCX_OK", out)


if __name__ == "__main__":
    main()
