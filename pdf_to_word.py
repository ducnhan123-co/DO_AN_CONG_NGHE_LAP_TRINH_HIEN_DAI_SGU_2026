"""Chạy riêng chức năng PDF -> Word Equation, không tải RAG/chat/LLM."""
import argparse
import json
import logging
import zipfile
from pathlib import Path

def validate_pdf(p: Path):
    if not p.is_file() or p.suffix.lower() != ".pdf":
        raise ValueError("Đầu vào phải là một tệp PDF có thật")
    with p.open("rb") as f:
        if f.read(5) != b"%PDF-":
            raise ValueError("Sai PDF magic header")

def check_word(p: Path):
    with zipfile.ZipFile(p) as z:
        if z.testzip() is not None or "word/document.xml" not in z.namelist():
            raise RuntimeError("DOCX sinh ra không hợp lệ")
        x=z.read("word/document.xml")
        return {"bytes":p.stat().st_size,"omml_tags":x.count(b"<m:oMath"),
                "media_files":sum(n.startswith("word/media/") for n in z.namelist())}

def main():
    ap=argparse.ArgumentParser(description="PDF toán -> DOCX (không chat/RAG)")
    ap.add_argument("--pdf",required=True);ap.add_argument("--output")
    ap.add_argument("--work-dir",default="backend/data/pdf_word_runs")
    ap.add_argument("--tier",default="standard",choices=("flash","basic","standard","advanced"))
    ap.add_argument("--method",default="auto",choices=("auto","txt","ocr"))
    ap.add_argument("--force",action="store_true")
    ap.add_argument("--layout",action="store_true")
    a=ap.parse_args()
    from llm.src.run_mineru import prepare_run_dir,run_mineru,find_mineru_outputs,find_content_list
    from llm.src.build_docx import prepare_work_md,md_to_docx
    pdf=Path(a.pdf).expanduser().resolve();validate_pdf(pdf)
    doc_id,run=prepare_run_dir(pdf,Path(a.work_dir).resolve())
    parse_dir=run/"mineru"
    run_mineru(pdf,parse_dir,tier=a.tier,method=a.method,force=a.force,workers=0)
    markdown,_,_=find_mineru_outputs(parse_dir)
    work=run/"for_word.md"
    prepare_work_md(markdown.read_text(encoding="utf-8"),markdown,work)
    if a.layout:
        content=find_content_list(parse_dir)
        if content:
            from llm.src import layout
            blocks=json.loads(content.read_text(encoding="utf-8"))
            info=layout.analyze_layout(blocks,str(pdf))
            (run/"layout.json").write_text(json.dumps(info,ensure_ascii=False),encoding="utf-8")
            if info["multi_col"]:
                work.write_text(layout.insert_layout_markers(work.read_text(encoding="utf-8"),blocks,info),encoding="utf-8")
    out=Path(a.output).expanduser().resolve() if a.output else run/(pdf.stem+".docx")
    out.parent.mkdir(parents=True,exist_ok=True)
    md_to_docx(work,out,markdown.parent)
    result={"document_id":doc_id,"docx":str(out),"preflight":check_word(out),
            "note":"Cần đối chiếu công thức/bố cục thủ công; preflight không đo accuracy."}
    (run/"conversion_report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    try: main()
    except Exception as exc:
        logging.exception("Không thể chuyển PDF sang Word: %s",exc)
        raise SystemExit(1) from exc
