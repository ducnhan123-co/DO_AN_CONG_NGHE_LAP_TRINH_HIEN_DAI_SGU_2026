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
from pathlib import Path

from llm.build_docx import md_to_docx, prepare_work_md
from llm.chunking import build_chunks
from llm.latex_norm import fix_vni, normalize_math_in_text
from llm.config import (EMBED_MODEL, INPUT_DIR, LLM_NAME, MAX_CHARS,
                        MINERU_BACKEND, MINERU_TIER, OVERLAP, RUNS_DIR, TOP_K)
from llm.run_mineru import (find_content_list, find_mineru_outputs,
                            prepare_run_dir, run_mineru)
from llm.structured import load_raw, normalize_blocks, save_structured
from llm.validate import validate_chunks


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
    args = ap.parse_args()

    for p in [INPUT_DIR, RUNS_DIR]:
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
    # Sửa VNI ("Neáu" -> "Nếu") + chuẩn hoá công thức ({\\bf x}, \\displaylimits) để Pandoc
    # ra Equation thật thay vì chữ LaTeX thô trong DOCX.
    markdown_text = normalize_math_in_text(fix_vni(
        md_path.read_text(encoding="utf-8", errors="ignore")))
    print(markdown_text[:1500])

    # 2. DOCX Equation thật (không đổi so với bản gốc)
    docx_dir = run_dir / "docx"
    docx_dir.mkdir(exist_ok=True)
    work_md = docx_dir / "source_for_docx.md"
    prepare_work_md(markdown_text, md_path, work_md)
    docx_path = docx_dir / f"{pdf_path.stem}.docx"
    md_to_docx(work_md, docx_path, md_path.parent)

    # 3. Structured data + chunk theo BLOCK (fix lỗi #2 base64, #3 cắt đôi công thức)
    raw = load_raw(content_list_path, md_path)
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

    # 4. LlamaIndex (E5) — retrieval kèm score/source/page
    from llm.llama_rag import build_index, chunks_to_nodes, retrieve
    nodes = chunks_to_nodes(chunks)
    index = build_index(nodes, EMBED_MODEL, run_dir / "index")

    demo_q = "Hãy giải thích một khái niệm trong tài liệu."
    for i, r in enumerate(retrieve(index, demo_q, TOP_K), 1):
        print(f"--- {i} | score={r['score']:.4f} | page={r['page']} | {r['section']} ---")
        print(r["text"][:500])

    # 5. Qwen optional
    if not args.skip_llm:
        from llm.ask_rag import ask_rag, load_llm
        tok, model = load_llm(LLM_NAME)
        ans, srcs = ask_rag(
            "Hãy giải thích một định nghĩa quan trọng trong tài liệu.",
            tok, model, index, top_k=TOP_K)
        print(ans)
        print("\nSOURCES:")
        for s in srcs:
            print(f"- page={s['page']} | {s['section']} | score={s['score']:.4f}")

    print("\n===== FINAL OUTPUT =====")
    print("PDF          :", pdf_path)
    print("doc_id       :", doc_id)
    print("Markdown     :", md_path)
    print("DOCX         :", docx_path)
    print("Structured   :", structured_path)
    print("Chunks       :", chunks_path)
    print("Validation   :", run_dir / "validation.json")
    print("Index        :", run_dir / "index")


if __name__ == "__main__":
    main()
