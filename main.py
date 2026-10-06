# """Pipeline chuẩn: PDF -> MinerU -> DOCX Equation -> Chunk (fixed) -> LlamaIndex RAG -> (optional) Qwen.

# Chạy:
#   python main.py --pdf input/bai_giang.pdf --skip-llm
#   python main.py --pdf input/bai_giang.pdf              # có Qwen trả lời
#   python main.py --pdf input/bai_giang.pdf --force       # chạy lại MinerU dù đã có output

# MỚI so với bản gốc (fix 3 lỗi trong Weekly_Sprint_02.xlsx, task "Preprocessing"):
#   1) Mỗi PDF chạy trong run dir riêng `runs/<ten>_<doc_id>/` -> không lấy nhầm
#      output của PDF chạy trước đó khi chạy nhiều PDF liên tiếp.
#   2) Chunk dựng từ `structured_data.json` (đọc content_list.json của MinerU),
#      ảnh base64 bị lọc bỏ ngay khi chuẩn hoá, không còn lọt vào chunk text.
#   3) Chunk theo BLOCK (structured + chunking), công thức/table là đơn vị không
#      bị chia -> không còn công thức bị cắt đôi giữa 2 chunk.
#   Retrieval chuyển từ FAISS thủ công sang LlamaIndex, trả kèm score/source/page.
# """
# import argparse
# import json
# import shutil
# from pathlib import Path

# from src.build_docx import md_to_docx, prepare_work_md
# from src.chunking import build_chunks
# from src.config import (DOCX_DIR, EMBED_MODEL, INPUT_DIR, LLM_NAME, MAX_CHARS,
#                         MINERU_BACKEND, MINERU_TIER, OVERLAP, RUNS_DIR, TOP_K)
# from src.run_mineru import (find_content_list, find_mineru_outputs,
#                             prepare_run_dir, run_mineru)
# from src.structured import load_raw, normalize_blocks, save_structured
# from src.validate import validate_chunks


# def main():
#     ap = argparse.ArgumentParser()
#     ap.add_argument("--pdf", required=True, help="Đường dẫn PDF toán đầu vào")
#     ap.add_argument("--backend", default=MINERU_BACKEND,
#                     help="Giữ để tương thích cũ, không còn ảnh hưởng lệnh chạy thật")
#     ap.add_argument("--tier", default=MINERU_TIER,
#                     help="flash / basic / standard / advanced (mineru-kit parse)")
#     ap.add_argument("--skip-llm", action="store_true",
#                     help="Bỏ qua Qwen local (chỉ retrieval)")
#     ap.add_argument("--force", action="store_true",
#                     help="Chạy lại MinerU dù run dir đã có output")
#     args = ap.parse_args()

#     for p in [INPUT_DIR, DOCX_DIR, RUNS_DIR]:
#         p.mkdir(parents=True, exist_ok=True)

#     src_pdf = Path(args.pdf)
#     if not src_pdf.exists():
#         raise FileNotFoundError(f"Không thấy PDF: {src_pdf}")
#     pdf_path = INPUT_DIR / src_pdf.name
#     if src_pdf.resolve() != pdf_path.resolve():
#         shutil.copy2(src_pdf, pdf_path)
#     print("PDF:", pdf_path)

#     # 0. Run dir riêng cho PDF này (fix lỗi #1: lấy nhầm dữ liệu cũ)
#     doc_id, run_dir = prepare_run_dir(pdf_path, RUNS_DIR)
#     mineru_dir = run_dir / "mineru"
#     print(f"doc_id={doc_id} | run_dir={run_dir}")

#     # 1. MinerU (CLI mới mineru-kit parse, giống notebook)
#     run_mineru(pdf_path, mineru_dir, backend=args.backend, tier=args.tier,
#                force=args.force)
#     md_path, _json_files, _image_files = find_mineru_outputs(mineru_dir)
#     content_list_path = find_content_list(mineru_dir)
#     markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
#     print(markdown_text[:1500])

#     # 2. DOCX Equation thật (không đổi so với bản gốc)
#     work_md = DOCX_DIR / f"{pdf_path.stem}_for_docx.md"
#     prepare_work_md(markdown_text, md_path, work_md)
#     docx_path = DOCX_DIR / f"{pdf_path.stem}.docx"
#     md_to_docx(work_md, docx_path, md_path.parent)

#     # 3. Structured data + chunk theo BLOCK (fix lỗi #2 base64, #3 cắt đôi công thức)
#     raw = load_raw(content_list_path, md_path)
#     blocks = normalize_blocks(raw, source=pdf_path.name, doc_id=doc_id)
#     structured_path = save_structured(blocks, run_dir / "structured_data.json")

#     chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
#     chunks_path = run_dir / "chunks.json"
#     chunks_path.write_text(
#         json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
#     print(f"Blocks: {len(blocks)} | Chunks: {len(chunks)}")

#     report = validate_chunks(chunks, pdf_path.name, doc_id)
#     (run_dir / "validation.json").write_text(
#         json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
#     print("Validation:", {k: v for k, v in report.items() if k != "problems"})
#     for p in report["problems"][:20]:
#         print("  !", p)
#     if not report["ok"]:
#         print(f"[CẢNH BÁO] {len(report['problems'])} vấn đề, "
#               f"xem {run_dir / 'validation.json'}")

#     # 4. LlamaIndex (E5) — retrieval kèm score/source/page
#     from src.llama_rag import build_index, chunks_to_nodes, retrieve
#     nodes = chunks_to_nodes(chunks)
#     index = build_index(nodes, EMBED_MODEL, run_dir / "index")

#     demo_q = "Hãy giải thích một khái niệm trong tài liệu."
#     for i, r in enumerate(retrieve(index, demo_q, TOP_K), 1):
#         print(f"--- {i} | score={r['score']:.4f} | page={r['page']} | {r['section']} ---")
#         print(r["text"][:500])

#     # 5. Qwen optional
#     if not args.skip_llm:
#         from src.ask_rag import ask_rag, load_llm
#         tok, model = load_llm(LLM_NAME)
#         ans, srcs = ask_rag(
#             "Hãy giải thích một định nghĩa quan trọng trong tài liệu.",
#             tok, model, index, top_k=TOP_K)
#         print(ans)
#         print("\nSOURCES:")
#         for s in srcs:
#             print(f"- page={s['page']} | {s['section']} | score={s['score']:.4f}")

#     print("\n===== FINAL OUTPUT =====")
#     print("PDF          :", pdf_path)
#     print("doc_id       :", doc_id)
#     print("Markdown     :", md_path)
#     print("DOCX         :", docx_path)
#     print("Structured   :", structured_path)
#     print("Chunks       :", chunks_path)
#     print("Validation   :", run_dir / "validation.json")
#     print("Index        :", run_dir / "index")


# if __name__ == "__main__":
#     main()

"""Pipeline chuẩn: PDF -> MinerU -> DOCX Equation -> Chunk (fixed) -> LlamaIndex RAG -> (optional) Qwen.

Chạy:
  python main.py --pdf input/bai_giang.pdf --skip-llm
  python main.py --pdf input/bai_giang.pdf              # có Qwen trả lời
  python main.py --pdf input/bai_giang.pdf --force       # chạy lại MinerU dù đã có output

MỚI so với bản gốc (fix 3 lỗi trong Weekly_Sprint_02.xlsx, task "Preprocessing"):
  1) Mỗi PDF chạy trong run dir riêng `runs/<ten>_<doc_id>/` -> không lấy nhầm
     output của PDF chạy trước đó khi chạy nhiều PDF liên tiếp.
  2) Chunk dựng từ `structured_data.json` (đọc content_list.json của MinerU),
     ảnh base64 bị lọc bỏ ngay khi chuẩn hoá, không còn lọt vào chunk text.
  3) Chunk theo BLOCK (structured + chunking), công thức/table là đơn vị không
     bị chia -> không còn công thức bị cắt đôi giữa 2 chunk.
  Retrieval chuyển từ FAISS thủ công sang LlamaIndex, trả kèm score/source/page.
"""
import argparse
import json
import shutil
import threading
import traceback
from pathlib import Path

from llm.src.build_docx import fix_legacy_tex_bf, md_to_docx, prepare_work_md
from llm.src.chunking import build_chunks
from llm.src.config import (DOCX_DIR, EMBED_MODEL, INPUT_DIR, LLM_NAME, MAX_CHARS,
                        MINERU_BACKEND, MINERU_TIER, OVERLAP, RUNS_DIR, TOP_K)
from llm.src.run_mineru import (find_content_list, find_mineru_outputs,
                            prepare_run_dir, run_mineru)
from llm.src.structured import load_raw, normalize_blocks, save_structured
from llm.src.validate import validate_chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="Đường dẫn PDF toán đầu vào")
    ap.add_argument("--backend", default=MINERU_BACKEND,
                    help="Giữ để tương thích cũ, không còn ảnh hưởng lệnh chạy thật")
    ap.add_argument("--tier", default=MINERU_TIER,
                    help="flash / basic / standard / advanced (mineru-kit parse)")
    ap.add_argument("--skip-llm", action="store_true",
                    help="Bỏ qua Qwen local (chỉ retrieval)")
    ap.add_argument("--force", action="store_true",
                    help="Chạy lại MinerU dù run dir đã có output")
    ap.add_argument("--no-ask", action="store_true",
                    help="Không vào vòng hỏi đáp tương tác, chỉ build xong rồi thoát")
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

    # 1. MinerU (CLI mới mineru-kit parse, giống notebook)
    run_mineru(pdf_path, mineru_dir, backend=args.backend, tier=args.tier,
               force=args.force)
    md_path, _json_files, _image_files = find_mineru_outputs(mineru_dir)
    content_list_path = find_content_list(mineru_dir)
    markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
    # Fix `{ \bf X }` -> `\mathbf{X}`: pandoc/texmath không hiểu \bf, làm công
    # thức bị fallback về text thô thay vì thành Equation. Áp dụng 1 lần, dùng
    # chung cho cả DOCX lẫn RAG để nhất quán.
    markdown_text = fix_legacy_tex_bf(markdown_text)
    print(markdown_text[:1500])

    # 2. DOCX Equation thật -- CHẠY NỀN bằng thread, không chặn các bước sau.
    # DOCX (pandoc + định dạng Word) có thể mất vài phút với file dài, trong khi
    # RAG index (bước 3-4 bên dưới) build nhanh hơn nhiều -> cho build song song,
    # để có thể hỏi đáp ngay khi index xong, không phải đợi DOCX xuất xong.
    work_md = DOCX_DIR / f"{pdf_path.stem}_for_docx.md"
    docx_path = DOCX_DIR / f"{pdf_path.stem}.docx"
    docx_error = {}

    def build_docx_job():
        try:
            prepare_work_md(markdown_text, md_path, work_md)
            md_to_docx(work_md, docx_path, md_path.parent)
        except Exception:
            # thread không tự ném lỗi ra main thread -> phải tự bắt lại, in ra
            # khi join() ở cuối, để lỗi DOCX không bị im lặng trôi qua.
            docx_error["traceback"] = traceback.format_exc()

    docx_thread = threading.Thread(target=build_docx_job, name="docx-export")
    docx_thread.start()
    print("[DOCX] Đang xuất Word ở nền... (chạy song song, không cần đợi)")

    # 3. Structured data + chunk theo BLOCK (fix lỗi #2 base64, #3 cắt đôi công thức)
    raw = load_raw(content_list_path, md_path, md_text=markdown_text)
    blocks = normalize_blocks(raw, source=pdf_path.name, doc_id=doc_id)
    structured_path = save_structured(blocks, run_dir / "structured_data.json")

    chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
    chunks_path = run_dir / "chunks.json"
    chunks_path.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Blocks: {len(blocks)} | Chunks: {len(chunks)}")

    report = validate_chunks(chunks, pdf_path.name, doc_id)
    (run_dir / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Validation:", {k: v for k, v in report.items() if k != "problems"})
    for p in report["problems"][:20]:
        print("  !", p)
    if not report["ok"]:
        print(f"[CẢNH BÁO] {len(report['problems'])} vấn đề, "
              f"xem {run_dir / 'validation.json'}")

    # 4. LlamaIndex (E5) — retrieval kèm score/source/page. Lúc này DOCX có thể
    # vẫn đang build ở nền (xem docx_thread) -- index đã dùng được ngay, không
    # cần đợi DOCX.
    from llm.src.llama_rag import build_index, chunks_to_nodes, retrieve
    nodes = chunks_to_nodes(chunks)
    index = build_index(nodes, EMBED_MODEL, run_dir / "index")
    print(f"[RAG] Index sẵn sàng ({len(chunks)} chunks)."
          + (" DOCX vẫn đang xuất ở nền." if docx_thread.is_alive() else " DOCX đã xong."))

    # 4b. Qwen (tuỳ chọn) nạp 1 lần, dùng lại cho mọi câu hỏi trong vòng lặp
    tok = model = None
    if not args.skip_llm:
        from llm.src.ask_rag import load_llm
        tok, model = load_llm(LLM_NAME)

    # 5. Vòng lặp hỏi đáp -- hỏi được ngay cả khi DOCX vẫn đang chạy ở thread kia.
    if not args.no_ask:
        print("\n----- HỎI ĐÁP (Enter để thoát) -----")
        while True:
            try:
                q = input("Câu hỏi: ").strip()
            except EOFError:
                break
            if not q:
                break
            if tok is not None:
                from src.ask_rag import ask_rag
                ans, srcs = ask_rag(q, tok, model, index, top_k=TOP_K)
                print(ans)
                print("Nguồn:", "; ".join(
                    f"page={s['page']}|{s['section']}|score={s['score']:.3f}" for s in srcs))
            else:
                for i, r in enumerate(retrieve(index, q, TOP_K), 1):
                    print(f"--- {i} | score={r['score']:.4f} | page={r['page']} | {r['section']} ---")
                    print(r["text"][:500])

    # 6. Đợi DOCX xuất xong hẳn trước khi in tổng kết (nếu người dùng thoát hỏi
    # đáp sớm hơn lúc DOCX build xong).
    if docx_thread.is_alive():
        print("\n[DOCX] Đang chờ xuất Word xong...")
    docx_thread.join()
    if docx_error:
        print("\n[DOCX] LỖI khi xuất Word:")
        print(docx_error["traceback"])

    print("\n===== FINAL OUTPUT =====")
    print("PDF          :", pdf_path)
    print("doc_id       :", doc_id)
    print("Markdown     :", md_path)
    print("DOCX         :", docx_path, "(lỗi, xem log ở trên)" if docx_error else "")
    print("Structured   :", structured_path)
    print("Chunks       :", chunks_path)
    print("Validation   :", run_dir / "validation.json")
    print("Index        :", run_dir / "index")


if __name__ == "__main__":
    main()