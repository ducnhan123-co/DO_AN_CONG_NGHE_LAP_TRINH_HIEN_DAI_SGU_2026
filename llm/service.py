"""HTTP-facing use cases built on the fixed MinerU/LlamaIndex pipeline."""
import json
from pathlib import Path

from .build_docx import md_to_docx, prepare_work_md
from .chunking import build_chunks
from .config import EMBED_MODEL, LLM_NAME, MAX_CHARS, MINERU_TIER, OVERLAP, TOP_K
from .latex_norm import fix_vni, normalize_math_in_text
from .llama_rag import build_index, chunks_to_nodes, load_index, retrieve
from .ocr import extract_pages
from .run_mineru import find_content_list, find_mineru_outputs, prepare_run_dir, run_mineru
from .structured import load_raw, normalize_blocks, save_structured
from .validate import validate_chunks


def process_pdf(pdf_path: Path, workspace: Path) -> dict:
    """Process one PDF in an isolated run directory and persist its RAG index."""
    document_id, run_dir = prepare_run_dir(pdf_path, workspace / "runs")
    mineru_dir = run_dir / "mineru"
    try:
        run_mineru(pdf_path, mineru_dir, tier=MINERU_TIER)
        markdown_path, _, _ = find_mineru_outputs(mineru_dir)
        content_list_path = find_content_list(mineru_dir)
        markdown = normalize_math_in_text(fix_vni(
            markdown_path.read_text(encoding="utf-8", errors="ignore")
        ))
        parser = "mineru"
    except (FileNotFoundError, RuntimeError):
        markdown_path = run_dir / "ocr.md"
        markdown = "\n\n".join(extract_pages(pdf_path))
        markdown_path.write_text(markdown, encoding="utf-8")
        content_list_path = None
        parser = "ocr"

    docx_dir = run_dir / "docx"
    docx_dir.mkdir(exist_ok=True)
    work_md = prepare_work_md(markdown, markdown_path, docx_dir / "source_for_docx.md")
    docx_path = md_to_docx(work_md, docx_dir / f"{pdf_path.stem}.docx", markdown_path.parent)

    blocks = normalize_blocks(load_raw(content_list_path, markdown_path), pdf_path.name, document_id)
    structured_path = save_structured(blocks, run_dir / "structured_data.json")
    chunks = build_chunks(blocks, MAX_CHARS, OVERLAP)
    report = validate_chunks(chunks, pdf_path.name, document_id)
    (run_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    if not report["ok"]:
        raise ValueError("Dữ liệu RAG không đạt kiểm tra: " + "; ".join(report["problems"][:3]))
    chunks_path = run_dir / "chunks.json"
    chunks_path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    index_dir = run_dir / "index"
    build_index(chunks_to_nodes(chunks), EMBED_MODEL, index_dir)
    result = {
        "document_id": document_id,
        "run_dir": str(run_dir),
        "markdown_path": str(markdown_path),
        "docx_path": str(docx_path),
        "structured_path": str(structured_path),
        "index_dir": str(index_dir),
        "chunk_count": len(chunks),
        "parser": parser,
    }
    (workspace / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def answer_question(workspace: Path, question: str, use_local_llm: bool = False) -> dict:
    """Return cited E5 results; Qwen generation remains explicit and lazy."""
    result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
    index = load_index(Path(result["index_dir"]), EMBED_MODEL)
    sources = retrieve(index, question, TOP_K)
    if use_local_llm:
        from .ask_rag import ask_rag, load_llm

        tokenizer, model = load_llm(LLM_NAME)
        answer, sources = ask_rag(question, tokenizer, model, index, TOP_K)
    else:
        answer = "Đã tìm thấy các đoạn liên quan. Bật ENABLE_LOCAL_LLM=1 để Qwen tổng hợp câu trả lời."
    return {"answer": answer, "sources": sources}
