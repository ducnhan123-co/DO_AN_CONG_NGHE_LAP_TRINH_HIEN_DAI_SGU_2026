"""Chạy pipeline từ dòng lệnh, giống rag_toan/main.py nhưng kết quả nằm trong backend/data (và app.db):

    python -m backend.app.cli input/LSTM.pdf [input/khac.pdf ...]

Nhiều file được xử lý lần lượt theo đúng hàng đợi của server.
"""
import argparse
import sys
import time
from pathlib import Path

from fastapi import UploadFile
from starlette.datastructures import Headers

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.models import document_model as dm
from backend.app.models.database import SessionLocal, TERMINAL, init_db
from backend.app.models.pipeline import Pipeline, set_pipeline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PDF toán -> DOCX (MinerU + Pandoc), lưu vào backend/data")
    ap.add_argument("pdf", nargs="+", help="Đường dẫn file PDF")
    ap.add_argument("--force", action="store_true", help="Bỏ qua cache sha256")
    args = ap.parse_args(argv)
    s = get_settings()
    from backend.app.main import setup_logging
    setup_logging("WARNING")
    init_db()
    pipeline = Pipeline(s)
    set_pipeline(pipeline)
    pipeline.start()
    ids = []
    with SessionLocal() as db:
        for p in args.pdf:
            path = Path(p)
            if not path.exists():
                print(f"Không thấy PDF: {path}", file=sys.stderr)
                continue
            try:
                with open(path, "rb") as f:
                    up = UploadFile(file=f, filename=path.name, headers=Headers({"content-type": "application/pdf"}))
                    doc, job = dm.create_document(db, up, "", args.force)
            except AppError as exc:
                print(f"{path.name}: {exc.code} - {exc.message}", file=sys.stderr)
                continue
            ids.append(doc.id)
            print(f"{path.name}: doc_id={doc.id} | {doc.num_pages} trang | {doc.status}" + (" (dùng lại DOCX cũ)" if doc.cache_hit else ""))
    last = {}
    try:
        while ids:
            with SessionLocal() as db:
                outs = [dm.document_out(db, dm.get_document(db, i)) for i in ids]
            for o in outs:
                line = f"{o.name[:40]:<40} {o.status:<10} {o.progress:5.1f}%"
                if last.get(o.id) != line:
                    last[o.id] = line
                    print(line)
            if all(o.status in TERMINAL for o in outs):
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Dừng theo yêu cầu.")
    finally:
        pipeline.stop()
        set_pipeline(None)
    code = 0
    with SessionLocal() as db:
        for i in ids:
            d = dm.document_out(db, dm.get_document(db, i), detail=True)
            print(f"\n== {d.name} -> {d.status} ({d.elapsed_s}s) ==")
            for st in d.stages:
                extra = f" slot={st.slot}" if st.slot else ""
                print(f"  {st.stage:<9}{'#' + str(st.shard_index) if st.shard_index else '':<4} {st.status:<9} {st.duration_s or 0:>7.1f}s{extra}")
            if d.status == "done":
                print("  DOCX:", s.docx_path(d.id))
            else:
                code = 1
                print("  Lỗi:", d.error.code if d.error else "", d.error.message if d.error else "")
    return code


if __name__ == "__main__":
    sys.exit(main())
