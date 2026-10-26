"""Controller: /api/documents/* — nhận request, gọi service/model, trả bằng view. Không chứa logic xử lý PDF."""
from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ..core.container import Container, get_client_id, get_container
from ..core.errors import AppError, error_body
from ..models.entities import ACTIVE_STATUSES, CANCELLED, FAILED, DONE
from ..services.storage import ARTIFACT_NAMES, Storage
from ..services.upload_service import UploadRejected
from ..views.document_view import render_document, render_list

router = APIRouter(prefix="/api/documents", tags=["documents"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class RenameBody(BaseModel):
    display_name: str


class SearchBody(BaseModel):
    query: str
    top_k: Optional[int] = None


def _entry_or_404(c: Container, client_id: str, doc_id: str):
    if not Storage.valid_id(doc_id):
        raise AppError(404, "NOT_FOUND", "Tài liệu không tồn tại.")
    pair = c.repo.get_entry(client_id, doc_id)
    if pair is None:
        raise AppError(404, "NOT_FOUND", "Tài liệu không tồn tại hoặc đã bị xóa.")
    return pair


def _render(c: Container, doc, entry) -> dict:
    return render_document(doc, entry, c.storage.docx_path(doc.id).is_file())


# ---------------------------------------------------------------------- danh sách / upload
@router.get("")
def list_documents(limit: int = Query(200, ge=1, le=500), client_id: str = Depends(get_client_id),
                   c: Container = Depends(get_container)):
    pairs = c.repo.list_entries(client_id, limit)
    return render_list(pairs, lambda i: c.storage.docx_path(i).is_file())


@router.post("", status_code=202)
async def upload_documents(files: List[UploadFile] = File(...),
                           client_id: str = Depends(get_client_id), c: Container = Depends(get_container)):
    items, rejected = [], []
    for i, f in enumerate(files):
        name = c.uploads.clean_filename(f.filename) or "(không tên)"
        if i >= c.settings.max_files_per_request:
            rejected.append({"filename": name, "message": f"vượt quá {c.settings.max_files_per_request} file mỗi lần tải"})
            continue
        try:
            staged = await c.uploads.stage(f)
            doc, entry = c.uploads.register(client_id, staged)
            items.append(_render(c, doc, entry))
        except UploadRejected as ex:
            rejected.append({"filename": name, "message": str(ex)})
    if not items:
        msg = "; ".join(f"{r['filename']}: {r['message']}" for r in rejected) or "Không có file nào được nhận."
        return JSONResponse(error_body("UPLOAD_REJECTED", msg), status_code=400)
    return {"items": items, "rejected": rejected}


# ---------------------------------------------------------------------- 1 tài liệu
@router.get("/{doc_id}")
def get_document(doc_id: str, client_id: str = Depends(get_client_id), c: Container = Depends(get_container)):
    doc, entry = _entry_or_404(c, client_id, doc_id)
    return _render(c, doc, entry)


@router.patch("/{doc_id}")
def rename_document(doc_id: str, body: RenameBody, client_id: str = Depends(get_client_id),
                    c: Container = Depends(get_container)):
    _entry_or_404(c, client_id, doc_id)
    name = re.sub(r"[\x00-\x1f\x7f]", "", body.display_name).strip()
    if not name or len(name) > 200:
        raise AppError(400, "INVALID_NAME", "Tên hiển thị phải dài từ 1 đến 200 ký tự.")
    c.repo.rename(client_id, doc_id, name)
    return _render(c, *_entry_or_404(c, client_id, doc_id))


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, client_id: str = Depends(get_client_id), c: Container = Depends(get_container)):
    """Gỡ khỏi thư viện của người gọi. Dữ liệu trong data/ chỉ bị xóa khi KHÔNG còn ai dùng tài liệu này."""
    _entry_or_404(c, client_id, doc_id)
    with c.uploads.lock:
        remaining = c.repo.unlink(client_id, doc_id)
    if remaining == 0:
        c.scheduler.cancel(doc_id, wait=True)               # dừng MinerU/worker trước khi xóa file
        with c.uploads.lock:
            if c.repo.count_links(doc_id) == 0:             # lỡ có người vừa tải đúng file này lên thì giữ lại
                c.storage.remove_all(doc_id)
                c.repo.delete(doc_id)
    return Response(status_code=204)


@router.post("/{doc_id}/cancel")
def cancel_document(doc_id: str, client_id: str = Depends(get_client_id), c: Container = Depends(get_container)):
    doc, _ = _entry_or_404(c, client_id, doc_id)
    if doc.status not in ACTIVE_STATUSES:
        raise AppError(409, "NOT_ACTIVE", "Tài liệu không đang được xử lý.")
    c.scheduler.cancel(doc_id, wait=True, timeout=15)
    return _render(c, *_entry_or_404(c, client_id, doc_id))


@router.post("/{doc_id}/retry")
def retry_document(doc_id: str, force: bool = Query(False), client_id: str = Depends(get_client_id),
                   c: Container = Depends(get_container)):
    """Chạy lại tài liệu lỗi/đã hủy. Mặc định tiếp tục từ chỗ dở (bỏ qua phần MinerU đã xong);
    ?force=true chạy lại cả MinerU (như --force của main.py)."""
    doc, _ = _entry_or_404(c, client_id, doc_id)
    if doc.status not in (FAILED, CANCELLED) and not (force and doc.status == DONE):
        raise AppError(409, "NOT_RETRYABLE", "Chỉ chạy lại được tài liệu bị lỗi hoặc đã hủy.")
    if not c.storage.input_pdf(doc_id).is_file():
        raise AppError(409, "INPUT_MISSING", "Mất file PDF gốc, hãy xóa rồi tải lại.")
    c.scheduler.submit(doc_id, force=force)
    return _render(c, *_entry_or_404(c, client_id, doc_id))


# ---------------------------------------------------------------------- tải file
# 2 endpoint này được dùng bằng <a href> / <iframe src> nên trình duyệt KHÔNG gửi được X-Client-Id:
# quyền truy cập dựa vào việc biết doc_id (xem README, mục Bảo mật).
@router.get("/{doc_id}/docx")
def download_docx(doc_id: str, c: Container = Depends(get_container)):
    doc = c.repo.get(doc_id) if Storage.valid_id(doc_id) else None
    if doc is None:
        raise AppError(404, "NOT_FOUND", "Tài liệu không tồn tại.")
    path = c.storage.docx_path(doc_id)
    if doc.status != DONE or not path.is_file():
        raise AppError(409, "DOCX_NOT_READY", "File Word chưa sẵn sàng.")
    stem = re.sub(r'[\\/:*?"<>|]', "_", doc.filename.rsplit(".", 1)[0]) or doc_id
    return FileResponse(path, media_type=DOCX_MIME, filename=f"{stem}.docx")


@router.get("/{doc_id}/pdf")
def view_pdf(doc_id: str, c: Container = Depends(get_container)):
    doc = c.repo.get(doc_id) if Storage.valid_id(doc_id) else None
    path = c.storage.input_pdf(doc_id) if doc else None
    if doc is None or not path.is_file():
        raise AppError(404, "NOT_FOUND", "Không có PDF gốc cho tài liệu này.")
    return FileResponse(path, media_type="application/pdf", filename=doc.filename, content_disposition_type="inline")


# ---------------------------------------------------------------------- dữ liệu trung gian / log / RAG
@router.get("/{doc_id}/artifacts")
def list_artifacts(doc_id: str, client_id: str = Depends(get_client_id), c: Container = Depends(get_container)):
    _entry_or_404(c, client_id, doc_id)
    return {"items": [{"name": n, "size": p.stat().st_size}
                      for n in ARTIFACT_NAMES if (p := c.storage.artifact(doc_id, n))]}


@router.get("/{doc_id}/artifacts/{name}")
def get_artifact(doc_id: str, name: str, client_id: str = Depends(get_client_id),
                 c: Container = Depends(get_container)):
    _entry_or_404(c, client_id, doc_id)
    p = c.storage.artifact(doc_id, name)
    if p is None:
        raise AppError(404, "NOT_FOUND", "Chưa có file này.")
    return FileResponse(p, media_type="application/json" if name.endswith(".json") else "text/markdown",
                        filename=name)


@router.get("/{doc_id}/log")
def get_log(doc_id: str, tail_kb: int = Query(64, ge=1, le=1024), client_id: str = Depends(get_client_id),
            c: Container = Depends(get_container)):
    """Phần cuối của logs/pipeline.log — để người vận hành xem vì sao một tài liệu lỗi."""
    _entry_or_404(c, client_id, doc_id)
    p = c.storage.pipeline_log(doc_id)
    if not p.is_file():
        return PlainTextResponse("")
    size = p.stat().st_size
    with open(p, "rb") as f:
        f.seek(max(0, size - tail_kb * 1024))
        return PlainTextResponse(f.read().decode("utf-8", errors="replace"))


@router.post("/{doc_id}/search")
def search_document(doc_id: str, body: SearchBody, client_id: str = Depends(get_client_id),
                    c: Container = Depends(get_container)):
    """Truy xuất đoạn liên quan trong tài liệu (cần RAG_INDEX=1). Trả score/page/section như retrieve() của rag_toan."""
    doc, _ = _entry_or_404(c, client_id, doc_id)
    if doc.status != DONE:
        raise AppError(409, "NOT_READY", "Tài liệu chưa xử lý xong.")
    q = body.query.strip()
    if not q:
        raise AppError(400, "EMPTY_QUERY", "Câu hỏi đang trống.")
    return {"query": q, "results": c.rag.search(doc_id, q, body.top_k)}
