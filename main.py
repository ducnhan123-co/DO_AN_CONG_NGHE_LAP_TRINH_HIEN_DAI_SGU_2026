"""Pipeline chuẩn: PDF -> MinerU -> DOCX Equation -> FAISS RAG -> (optional) Qwen.

Chạy:
  python main.py --pdf input/bai_giang.pdf
  python main.py --pdf input/bai_giang.pdf --skip-llm
"""
import argparse
import shutil
from pathlib import Path

from src.config import (DOCX_DIR, EMBED_MODEL, INPUT_DIR, LLM_NAME, MAX_CHARS,
                        MINERU_BACKEND, MINERU_DIR, OVERLAP, RAG_DIR, TOP_K)
from src.run_mineru import find_mineru_outputs, run_mineru
from src.build_docx import md_to_docx, prepare_work_md
from src.build_rag import build_index, make_chunks, retrieve, split_markdown_sections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, help="Đường dẫn PDF toán đầu vào")
    ap.add_argument("--backend", default=MINERU_BACKEND)
    ap.add_argument("--skip-llm", action="store_true",
                    help="Bỏ qua Qwen local (chỉ retrieval)")
    args = ap.parse_args()

    for p in [INPUT_DIR, MINERU_DIR, DOCX_DIR, RAG_DIR]:
        p.mkdir(parents=True, exist_ok=True)

    src = Path(args.pdf)
    if not src.exists():
        raise FileNotFoundError(f"Không thấy PDF: {src}")
    pdf_path = INPUT_DIR / src.name
    if src.resolve() != pdf_path.resolve():
        shutil.copy2(src, pdf_path)
    print("PDF:", pdf_path)

    # 1. MinerU
    run_mineru(pdf_path, MINERU_DIR, backend=args.backend)
    md_path, _, _ = find_mineru_outputs(MINERU_DIR)
    markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
    print(markdown_text[:2000])

    # 2. DOCX Equation thật
    work_md = DOCX_DIR / f"{pdf_path.stem}_for_docx.md"
    prepare_work_md(markdown_text, md_path, work_md)
    docx_path = DOCX_DIR / f"{pdf_path.stem}.docx"
    md_to_docx(work_md, docx_path, md_path.parent)

    # 3. RAG
    sections = split_markdown_sections(markdown_text)
    chunks = make_chunks(sections, max_chars=MAX_CHARS, overlap=OVERLAP)
    print("Sections:", len(sections), "| Chunks:", len(chunks))
    index, embedder, index_path, chunks_path = build_index(
        chunks, EMBED_MODEL, RAG_DIR)

    demo_q = "Hãy giải thích một khái niệm trong tài liệu."
    for i, r in enumerate(retrieve(demo_q, embedder, index, chunks, TOP_K), 1):
        print(f"--- {i} | score={r['score']:.4f} | {r['heading']} ---")
        print(r["text"][:500])

    # 4. Qwen optional
    if not args.skip_llm:
        from src.ask_rag import ask_rag, load_llm
        tok, model = load_llm(LLM_NAME)
        ans, srcs = ask_rag("Hãy giải thích một định nghĩa quan trọng "
                            "trong tài liệu.", tok, model, embedder,
                            index, chunks)
        print(ans)
        print("\nSOURCES:")
        for s in srcs:
            print(f"- {s['heading']} | score={s['score']:.4f}")

    print("\n===== FINAL OUTPUT =====")
    print("PDF      :", pdf_path)
    print("Markdown :", md_path)
    print("DOCX     :", docx_path)
    print("FAISS    :", index_path)
    print("Chunks   :", chunks_path)


if __name__ == "__main__":
    main()
