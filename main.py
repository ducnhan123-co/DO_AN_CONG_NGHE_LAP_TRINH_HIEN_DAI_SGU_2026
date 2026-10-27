# Cách 3
"""Pipeline PDF toán -> DOCX (Equation thật), có kiểm tra chất lượng.

Luồng: PDF -> (tách dải cột / che rãnh gáy nếu cần) -> MinerU -> sửa lỗi OCR/công thức
       -> Pandoc -> DOCX -> audit.

Chạy:
  python main.py --pdf input/bai_giang.pdf
  python main.py --pdf input/bai_giang.pdf --force       # chạy lại MinerU dù đã có output
  python main.py --pdf input/bai_giang.pdf --vi-correct                    # thêm dấu (vietnam.py) rồi sửa chính tả (vi_correct.py)
  python main.py --pdf input/bai_giang.pdf --vi-correct --no-vi-diacritic  # chỉ sửa chính tả
"""
import argparse
import json
import shutil
from pathlib import Path

from src.audit import print_audit, run_audit
from src.build_docx import fix_legacy_tex_bf, md_to_docx, prepare_work_md
from src.column_split import (apply_band_layout, build_strips_pdf, content_list_to_docx_md,
                              plan_strips, save_plan)
from src.columns import (apply_section_columns, drop_ocr_details,
                         insert_column_breaks, layout_of)
from src.config import DOCX_DIR, INPUT_DIR, MINERU_BACKEND, MINERU_TIER, RUNS_DIR
from src.frame_layout import apply_frame_layout, detect_frame_layout
from src.image_size import apply_pdf_image_sizes
from src.math_repair import repair_markdown
from src.parallel_mineru import run_mineru_parallel
from src.run_mineru import (find_content_list, find_mineru_outputs,
                            prepare_run_dir, run_mineru)
from src.scan_clean import clean_scan_pdf, is_image_pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="Đường dẫn PDF toán đầu vào")
    ap.add_argument("--backend", default=MINERU_BACKEND,
                    help="Giữ để tương thích cũ, không còn ảnh hưởng lệnh chạy thật")
    ap.add_argument("--tier", default=MINERU_TIER,
                    help="flash / basic / standard / advanced (mineru-kit parse)")
    ap.add_argument("--force", action="store_true",
                    help="Chạy lại MinerU dù run dir đã có output")
    ap.add_argument("--workers", type=int, default=2,
                    help="Số tiến trình MinerU chạy song song (mặc định 2). "
                         "Đặt 1 để chạy tuần tự như cũ.")
    ap.add_argument("--stagger", type=float, default=20.0,
                    help="Giây chờ giữa lúc khởi động các tiến trình MinerU (mặc định 20)")
    ap.add_argument("--no-columns", action="store_true",
                    help="Không giữ bố cục nhiều cột trong DOCX")
    ap.add_argument("--no-frame", action="store_true",
                    help="Không dựng khung/viền/tiêu đề mục cho PDF dạng tờ khung nhiều cột")
    ap.add_argument("--no-scan-clean", action="store_true",
                    help="Không che dải trang bên cạnh ở PDF scan")
    ap.add_argument("--no-image-size", action="store_true",
                    help="Không đặt ảnh theo kích thước gốc trong PDF (để Pandoc tự chọn)")
    ap.add_argument("--image-scale", type=float, default=1.0,
                    help="Thu/phóng đồng loạt kích thước ảnh so với PDF (1.0 = đúng như PDF)")
    ap.add_argument("--no-repair", action="store_true",
                    help="Không sửa lỗi OCR/công thức trên Markdown (math_repair)")
    ap.add_argument("--no-split", action="store_true",
                    help="Không tách PDF nhiều cột thành từng dải cột trước khi đưa vào MinerU")
    ap.add_argument("--ocr-lang", default="eng",
                    help="Ngôn ngữ tesseract để dò cột, vd 'vie+eng' (cần cài gói ngôn ngữ)")
    ap.add_argument("--col-font-pt", type=float, default=8.0,
                    help="Cỡ chữ nền (pt) khi DOCX nhiều cột; 0 = giữ nguyên")
    ap.add_argument("--no-vi-diacritic", action="store_true",
                    help="Khi dùng --vi-correct: bỏ bước THÊM DẤU (vietnam.py), chỉ sửa chính tả từng chữ")
    ap.add_argument("--vi-correct", action="store_true",
                    help="Thêm dấu (nrl-ai, src/vietnam.py) rồi sửa chính tả (bmd1905, src/vi_correct.py) "
                         "tiếng Việt. Mặc định tắt để không tải model nếu chưa cần.")
    args = ap.parse_args()

    for p in [INPUT_DIR, DOCX_DIR, RUNS_DIR]:
        p.mkdir(parents=True, exist_ok=True)

    src_pdf = Path(args.pdf)
    if not src_pdf.exists():
        raise FileNotFoundError(f"Không thấy PDF: {src_pdf}")
    pdf_path = INPUT_DIR / src_pdf.name
    if src_pdf.resolve() != pdf_path.resolve():
        shutil.copy2(src_pdf, pdf_path)
    print("PDF:", pdf_path)

    # 0. Run dir riêng cho PDF này (fix lỗi #1: lấy nhầm dữ liệu cũ)
    doc_id, run_dir = prepare_run_dir(pdf_path, RUNS_DIR)
    mineru_dir = run_dir / "mineru"
    print(f"doc_id={doc_id} | run_dir={run_dir}")

    # 0b. PDF dạng "tờ khung nhiều cột": tách thành các dải cột (dò từ đường kẻ/khoảng trắng của chính PDF)
    #     để MinerU đọc từng cột như tài liệu 1 cột -> đúng thứ tự đọc, không bị gộp thành 1 bảng khổng lồ.
    #     PDF thường -> plan=None, mọi thứ chạy y như cũ.
    plan = None if (args.no_split or args.no_columns) else plan_strips(pdf_path)
    mineru_pdf = pdf_path
    if plan:
        mineru_pdf = build_strips_pdf(pdf_path, run_dir / f"{pdf_path.stem}__strips.pdf", plan)
        save_plan(plan, run_dir / "strips_plan.json")
        print(f"[split] {len(plan['strips'])} dải cột từ {plan['pages']} trang -> MinerU đọc {mineru_pdf.name}")

    # 0c. PDF scan/chụp sách: che dải trang bên cạnh lộ sau rãnh gáy trước khi OCR (xem src/scan_clean.py)
    if mineru_pdf == pdf_path and not args.no_scan_clean and is_image_pdf(pdf_path):
        cleaned = run_dir / f"{pdf_path.stem}__clean.pdf"
        if not cleaned.exists() or args.force:
            _, st = clean_scan_pdf(pdf_path, cleaned, report_path=run_dir / "scan_clean.json")
            print(f"[scan_clean] che rãnh gáy {st['pages_masked']}/{st['pages']} trang")
        mineru_pdf = cleaned

    # 1. MinerU (CLI mới mineru-kit parse, giống notebook)
    if args.workers > 1:
        # Chia PDF thành N dải trang liên tiếp (từ trang 1), chạy N tiến trình cùng lúc
        run_mineru_parallel(mineru_pdf, mineru_dir, workers=args.workers,
                            tier=args.tier, force=args.force, stagger=args.stagger)
    else:
        run_mineru(mineru_pdf, mineru_dir, backend=args.backend, tier=args.tier,
                   force=args.force)
    md_path, _json_files, _image_files = find_mineru_outputs(mineru_dir)
    content_list_path = find_content_list(mineru_dir)
    if plan and not content_list_path:
        print("[split] MinerU không trả content_list.json -> bỏ chế độ tách dải, dùng Markdown như cũ.")
        plan = None
    markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
    # Fix `{ \bf X }` -> `\mathbf{X}`: pandoc/texmath không hiểu \bf, làm công
    # thức bị fallback về text thô thay vì thành Equation. Áp dụng 1 lần, dùng
    markdown_text = fix_legacy_tex_bf(markdown_text)
    print(markdown_text[:1500])

    # 2. DOCX Equation thật (không đổi so với bản gốc)
    # Nhiều cột (leaflet, cheat-sheet...): Pandoc chỉ ra 1 cột nên phải dò cột + chèn ngắt cột.
    # PDF 1 cột -> layout=None, mọi thứ chạy y như cũ.
    strips_raw = None
    if plan:       # đã có thứ tự cột chính xác -> không cần OCR dò cột
        layout = None
        strips_raw = json.loads(Path(content_list_path).read_text(encoding="utf-8"))
        docx_md = content_list_to_docx_md(strips_raw, plan)
    else:
        layout = None if args.no_columns else layout_of(pdf_path, lang=args.ocr_lang)
        docx_md = markdown_text
        if layout:
            docx_md = insert_column_breaks(drop_ocr_details(markdown_text), layout)
    # Advanced của MinerU sinh <details>...</details> sau mỗi ảnh (mô tả tự động, bảng điểm, chữ OCR rời
    # trong hình). Luôn bỏ khỏi DOCX; ảnh gốc vẫn giữ nên không mất thông tin.
    docx_md = drop_ocr_details(docx_md)
    if not args.no_repair:
        docx_md, fix_rep = repair_markdown(docx_md)
        print("[repair] DOCX:", {k: (v if isinstance(v, int) else len(v)) for k, v in fix_rep.items()})
        (run_dir / "repair_report.json").write_text(
            json.dumps(fix_rep, ensure_ascii=False, indent=2), encoding="utf-8")
    # Sửa dấu / chính tả tiếng Việt (gọi SAU repair_markdown). Chỉ nạp model khi bật cờ.
    if args.vi_correct:
        # Bước 1: THÊM DẤU theo ngữ cảnh (src/vietnam.py, nrl-ai vit5, có chấm điểm kiểm chứng từng chữ)
        if not args.no_vi_diacritic:
            from src.vietnam import correct_markdown as add_diacritics
            dia_report_path = run_dir / "vi_diacritic_report.txt"
            docx_md, dia_rep = add_diacritics(docx_md, report_path=str(dia_report_path))
            print("[vi-diacritic]", dia_rep)
        # Bước 2: SỬA CHÍNH TẢ từng chữ (src/vi_correct.py, bmd1905)
        from src.vi_correct import correct_markdown as fix_spelling
        vi_report_path = run_dir / "vi_correct_report.txt"
        docx_md, vi_rep = fix_spelling(
            docx_md, report_path=str(vi_report_path), spelling=True, add_diacritics=False)
        print("[vi-correct]", vi_rep)
    frame = None if (args.no_frame or args.no_columns) else detect_frame_layout(pdf_path)
    # Ảnh: đặt đúng kích thước như trong PDF (MinerU cắt hình ở 200 dpi). Bỏ qua với tài liệu nhiều cột /
    # tờ khung vì columns.py và frame_layout.py tự co ảnh theo cột.
    if not args.no_image_size and not (plan or layout or frame):
        docx_md, n_img = apply_pdf_image_sizes(docx_md, md_path.parent, scale=args.image_scale)
        print(f"[image] đặt kích thước gốc PDF cho {n_img} ảnh")
    work_md = DOCX_DIR / f"{pdf_path.stem}_for_docx.md"
    prepare_work_md(docx_md, md_path, work_md)
    docx_path = DOCX_DIR / f"{pdf_path.stem}.docx"
    md_to_docx(work_md, docx_path, md_path.parent)
    if layout:
        apply_section_columns(docx_path, layout["n_cols"], layout["page_pt"],
                              body_pt=args.col_font_pt or None)
    # PDF dạng "tờ khung nhiều cột" (cheat sheet...): dựng lại viền trang, kẻ cột, banner + tiêu đề mục.
    # Tự nhận từ hình học PDF; PDF thường -> frame=None, không đổi gì.
    if plan:
        apply_section_columns(docx_path, plan["ncols"], tuple(plan["page_pt"]), body_pt=args.col_font_pt or None)
        apply_band_layout(docx_path, plan, heads=(frame or {}).get("headings", []))
    elif frame:
        if not layout:   # columns.py không dò ra cột (do có đường kẻ) -> vẫn thu nhỏ chữ/ảnh như chế độ nhiều cột
            apply_section_columns(docx_path, frame["cols"], (frame["page_w_pt"], frame["page_h_pt"]),
                                  body_pt=args.col_font_pt or None)
        apply_frame_layout(docx_path, frame)

    # Kiểm tra tự động: trang MinerU bỏ khối, nhảy số bài/ý, công thức rớt thành text trong DOCX
    print_audit(run_audit(run_dir, docx_md, docx_path))

    print("\n===== FINAL OUTPUT =====")
    print("PDF          :", pdf_path)
    print("doc_id       :", doc_id)
    print("Markdown     :", md_path)
    print("DOCX         :", docx_path)
    print("Audit        :", run_dir / "audit.json")
    print("Repair       :", run_dir / "repair_report.json")
    if args.vi_correct:
        if not args.no_vi_diacritic:
            print("VI diacritic :", run_dir / "vi_diacritic_report.txt")
        print("VI correct   :", run_dir / "vi_correct_report.txt")


if __name__ == "__main__":
    main()