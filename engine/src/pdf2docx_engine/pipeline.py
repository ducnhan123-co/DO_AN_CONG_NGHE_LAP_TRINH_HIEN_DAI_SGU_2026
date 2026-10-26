"""Pipeline PDF toán -> DOCX (Equation thật), có kiểm tra chất lượng.

Luồng: PDF -> (tách dải cột / che rãnh gáy nếu cần) -> MinerU -> sửa lỗi OCR/công thức
       -> Pandoc -> DOCX -> audit.

Chạy:
  python -m pdf2docx_engine.pipeline --pdf bai_giang.pdf
  python -m pdf2docx_engine.pipeline --pdf bai_giang.pdf --out storage/runs/x --force
"""
import argparse
import json
from pathlib import Path

from .audit import print_audit, run_audit
from .config import DOCX_DIR, MINERU_TIER, MINERU_TIERS, STORAGE_DIR
from .docx.build_docx import fix_legacy_tex_bf, md_to_docx, prepare_work_md
from .docx.columns import apply_section_columns, drop_ocr_details, insert_column_breaks, layout_of
from .docx.frame_layout import apply_frame_layout, detect_frame_layout
from .docx.image_size import apply_pdf_image_sizes
from .math.math_repair import repair_markdown
from .pdf.column_split import apply_band_layout, build_strips_pdf, content_list_to_docx_md, plan_strips, save_plan
from .pdf.scan_clean import clean_scan_pdf, is_image_pdf
from .recognition.parallel_mineru import run_mineru_parallel
from .recognition.run_mineru import find_content_list, find_mineru_outputs, prepare_run_dir, run_mineru


def convert(pdf_path: Path, out_dir: Path, docx_dir: Path = DOCX_DIR, *, tier: str = MINERU_TIER, workers: int = 2,
            stagger: float = 20.0, force: bool = False, columns: bool = True, frame: bool = True,
            scan_clean: bool = True, image_size: bool = True, image_scale: float = 1.0,
            repair: bool = True, split: bool = True, ocr_lang: str = "eng",
            col_font_pt: float = 8.0) -> dict:
    """Chuyển 1 PDF thành DOCX: file trung gian ở out_dir, DOCX + Markdown dựng DOCX ở docx_dir (như kiet)."""
    pdf_path, out_dir, docx_dir = Path(pdf_path), Path(out_dir), Path(docx_dir)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Không thấy PDF: {pdf_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_dir.mkdir(parents=True, exist_ok=True)
    mineru_dir = out_dir / "mineru"
    print("PDF:", pdf_path, "| out:", out_dir)

    # PDF dạng "tờ khung nhiều cột": tách thành các dải cột để MinerU đọc từng cột như tài liệu 1 cột.
    # PDF thường -> plan=None.
    plan = plan_strips(pdf_path) if (split and columns) else None
    mineru_pdf = pdf_path
    if plan:
        mineru_pdf = build_strips_pdf(pdf_path, out_dir / f"{pdf_path.stem}__strips.pdf", plan)
        save_plan(plan, out_dir / "strips_plan.json")
        print(f"[split] {len(plan['strips'])} dải cột từ {plan['pages']} trang -> MinerU đọc {mineru_pdf.name}")

    # PDF scan/chụp sách: che dải trang bên cạnh lộ sau rãnh gáy trước khi OCR
    if mineru_pdf == pdf_path and scan_clean and is_image_pdf(pdf_path):
        cleaned = out_dir / f"{pdf_path.stem}__clean.pdf"
        if not cleaned.exists() or force:
            _, st = clean_scan_pdf(pdf_path, cleaned, report_path=out_dir / "scan_clean.json")
            print(f"[scan_clean] che rãnh gáy {st['pages_masked']}/{st['pages']} trang")
        mineru_pdf = cleaned

    # 1. MinerU
    if workers > 1:
        run_mineru_parallel(mineru_pdf, mineru_dir, workers=workers, tier=tier, force=force, stagger=stagger)
    else:
        run_mineru(mineru_pdf, mineru_dir, tier=tier, force=force)
    md_path, _json_files, _image_files = find_mineru_outputs(mineru_dir)
    content_list_path = find_content_list(mineru_dir)
    if plan and not content_list_path:
        print("[split] MinerU không trả content_list.json -> bỏ chế độ tách dải, dùng Markdown như cũ.")
        plan = None
    # `{ \bf X }` -> `\mathbf{X}`: pandoc/texmath không hiểu \bf, công thức sẽ rơi về text thô
    markdown_text = fix_legacy_tex_bf(md_path.read_text(encoding="utf-8", errors="ignore"))

    # 2. Markdown cho DOCX. Nhiều cột: Pandoc chỉ ra 1 cột nên phải dò cột + chèn ngắt cột.
    if plan:       # đã có thứ tự cột chính xác -> không cần OCR dò cột
        layout = None
        strips_raw = json.loads(Path(content_list_path).read_text(encoding="utf-8"))
        docx_md = content_list_to_docx_md(strips_raw, plan)
    else:
        layout = layout_of(pdf_path, lang=ocr_lang) if columns else None
        docx_md = markdown_text
        if layout:
            docx_md = insert_column_breaks(drop_ocr_details(markdown_text), layout)
    # MinerU advanced sinh <details>...</details> sau mỗi ảnh -> luôn bỏ, ảnh gốc vẫn giữ.
    docx_md = drop_ocr_details(docx_md)
    if repair:
        docx_md, fix_rep = repair_markdown(docx_md)
        print("[repair]", {k: (v if isinstance(v, int) else len(v)) for k, v in fix_rep.items()})
        (out_dir / "repair_report.json").write_text(
            json.dumps(fix_rep, ensure_ascii=False, indent=2), encoding="utf-8")
    frame_info = detect_frame_layout(pdf_path) if (frame and columns) else None
    # Ảnh đúng kích thước PDF; tài liệu nhiều cột / tờ khung tự co ảnh theo cột nên bỏ qua.
    if image_size and not (plan or layout or frame_info):
        docx_md, n_img = apply_pdf_image_sizes(docx_md, md_path.parent, scale=image_scale)
        print(f"[image] đặt kích thước gốc PDF cho {n_img} ảnh")

    # 3. DOCX qua Pandoc + dựng lại bố cục
    work_md = docx_dir / f"{pdf_path.stem}_for_docx.md"
    prepare_work_md(docx_md, md_path, work_md)
    docx_path = docx_dir / f"{pdf_path.stem}.docx"
    md_to_docx(work_md, docx_path, md_path.parent)
    body_pt = col_font_pt or None
    if layout:
        apply_section_columns(docx_path, layout["n_cols"], layout["page_pt"], body_pt=body_pt)
    if plan:
        apply_section_columns(docx_path, plan["ncols"], tuple(plan["page_pt"]), body_pt=body_pt)
        apply_band_layout(docx_path, plan, heads=(frame_info or {}).get("headings", []))
    elif frame_info:
        if not layout:   # columns.py không dò ra cột (do có đường kẻ) -> vẫn thu nhỏ chữ/ảnh
            apply_section_columns(docx_path, frame_info["cols"],
                                  (frame_info["page_w_pt"], frame_info["page_h_pt"]), body_pt=body_pt)
        apply_frame_layout(docx_path, frame_info)

    # 4. Audit: trang MinerU bỏ khối, nhảy số bài/ý, công thức rớt thành text trong DOCX
    audit = run_audit(out_dir, docx_md, docx_path)
    print_audit(audit)
    return {"docx": docx_path, "markdown": md_path, "audit": audit}


def main(argv=None):
    ap = argparse.ArgumentParser(description="PDF toán -> DOCX (Equation thật)")
    ap.add_argument("--pdf", required=True, type=Path, help="PDF đầu vào")
    ap.add_argument("--out", type=Path, help="Thư mục kết quả (mặc định storage/runs/<ten>_<doc_id>)")
    ap.add_argument("--docx-dir", type=Path, default=DOCX_DIR, help="Thư mục ghi DOCX (mặc định storage/docx_output)")
    ap.add_argument("--tier", default=MINERU_TIER, choices=MINERU_TIERS, help="Tier của mineru-kit parse")
    ap.add_argument("--force", action="store_true", help="Chạy lại MinerU dù đã có output")
    ap.add_argument("--workers", type=int, default=2, help="Số tiến trình MinerU song song (1 = tuần tự)")
    ap.add_argument("--stagger", type=float, default=20.0, help="Giây chờ giữa lúc khởi động các tiến trình")
    ap.add_argument("--no-columns", action="store_true", help="Không giữ bố cục nhiều cột")
    ap.add_argument("--no-frame", action="store_true", help="Không dựng khung/viền/tiêu đề mục")
    ap.add_argument("--no-scan-clean", action="store_true", help="Không che rãnh gáy ở PDF scan")
    ap.add_argument("--no-image-size", action="store_true", help="Không đặt ảnh theo kích thước gốc PDF")
    ap.add_argument("--image-scale", type=float, default=1.0, help="Thu/phóng ảnh so với PDF")
    ap.add_argument("--no-repair", action="store_true", help="Không sửa lỗi OCR/công thức (math_repair)")
    ap.add_argument("--no-split", action="store_true", help="Không tách PDF nhiều cột thành dải cột")
    ap.add_argument("--ocr-lang", default="eng", help="Ngôn ngữ tesseract để dò cột, vd 'vie+eng'")
    ap.add_argument("--col-font-pt", type=float, default=8.0, help="Cỡ chữ (pt) khi nhiều cột; 0 = giữ nguyên")
    a = ap.parse_args(argv)

    out = a.out or prepare_run_dir(a.pdf, STORAGE_DIR / "runs")[1]
    res = convert(a.pdf, out, a.docx_dir, tier=a.tier, workers=a.workers, stagger=a.stagger, force=a.force,
                  columns=not a.no_columns, frame=not a.no_frame, scan_clean=not a.no_scan_clean,
                  image_size=not a.no_image_size, image_scale=a.image_scale, repair=not a.no_repair,
                  split=not a.no_split, ocr_lang=a.ocr_lang, col_font_pt=a.col_font_pt)
    print("\n===== FINAL OUTPUT =====")
    print("DOCX  :", res["docx"])
    print("Audit :", Path(out) / "audit.json")


if __name__ == "__main__":
    main()
