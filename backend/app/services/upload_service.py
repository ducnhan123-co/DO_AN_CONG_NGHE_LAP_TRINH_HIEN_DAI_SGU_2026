"""Nhận PDF: kiểm tra -> băm nội dung -> (tái sử dụng kết quả cũ | tạo tài liệu mới) -> xếp hàng.

doc_id = sha1(nội dung)[:10] — đúng cách đặt ID của rag_toan (compute_doc_id), nên cùng một file luôn ra cùng
thư mục documents/<id>/ và PDF giống hệt người khác đã chuyển thì dùng lại kết quả ngay (cache_hit).
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from fastapi import UploadFile

from ..core.config import Settings
from ..models.document_repository import DocumentRepository
from ..models.entities import DONE, Document, LibraryEntry
from .scheduler import Scheduler
from .storage import Storage

_CHUNK = 1 << 20


class UploadRejected(Exception):
    """File bị từ chối (hiển thị cho người dùng trong danh sách `rejected`)."""


@dataclass
class Staged:
    path: Path
    filename: str
    sha1: str
    sha256: str
    size: int
    pages: int


class UploadService:
    def __init__(self, settings: Settings, repo: DocumentRepository, storage: Storage, scheduler: Scheduler):
        self.s, self.repo, self.storage, self.scheduler = settings, repo, storage, scheduler
        self.lock = threading.Lock()                  # dùng chung với thao tác xóa để không xóa nhầm file vừa được dùng lại

    # ------------------------------------------------------------------ 1. nhận + kiểm tra
    @staticmethod
    def clean_filename(name: Optional[str]) -> str:
        base = Path((name or "").replace("\\", "/")).name
        base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
        return base[:200]

    async def stage(self, upload: UploadFile) -> Staged:
        filename = self.clean_filename(upload.filename)
        if not filename.lower().endswith(".pdf"):
            raise UploadRejected("không phải file PDF")
        limit = self.s.max_upload_mb * (1 << 20)
        tmp = self.s.input_dir / f".upload-{uuid.uuid4().hex}.part"
        h1, h256, size, head = hashlib.sha1(), hashlib.sha256(), 0, b""
        try:
            with open(tmp, "wb") as f:
                while True:
                    block = await upload.read(_CHUNK)
                    if not block:
                        break
                    size += len(block)
                    if size > limit:
                        raise UploadRejected(f"file lớn hơn {self.s.max_upload_mb} MB")
                    if len(head) < 1024:
                        head += block[: 1024 - len(head)]
                    h1.update(block)
                    h256.update(block)
                    f.write(block)
            if size == 0:
                raise UploadRejected("file rỗng")
            if b"%PDF-" not in head:
                raise UploadRejected("nội dung không phải PDF")
            pages = self._count_pages(tmp)
            return Staged(tmp, filename, h1.hexdigest()[:40], h256.hexdigest(), size, pages)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _count_pages(self, path: Path) -> int:
        from pypdf import PdfReader
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted and not reader.decrypt(""):
                raise UploadRejected("PDF có mật khẩu, không đọc được")
            n = len(reader.pages)
        except UploadRejected:
            raise
        except Exception:
            raise UploadRejected("PDF bị hỏng hoặc không đọc được") from None
        if n < 1:
            raise UploadRejected("PDF không có trang nào")
        if n > self.s.max_pages:
            raise UploadRejected(f"PDF {n} trang, vượt giới hạn {self.s.max_pages} trang")
        return n

    # ------------------------------------------------------------------ 2. đăng ký vào thư viện + xếp hàng
    def register(self, client_id: str, st: Staged) -> Tuple[Document, LibraryEntry]:
        with self.lock:
            doc_id = self._pick_id(st)
            existing = self.repo.get(doc_id)
            display = Path(st.filename).stem[:200] or doc_id
            requeue = False
            cache_hit = False

            if existing is None:
                os.replace(st.path, self.storage.input_pdf(doc_id))
                self.repo.insert(Document(id=doc_id, sha256=st.sha256, filename=st.filename, size_bytes=st.size,
                                          num_pages=st.pages, tier=self.s.mineru_tier))
                requeue = True
            else:
                st.path.unlink(missing_ok=True)                    # đã có PDF này rồi
                if not self.storage.input_pdf(doc_id).is_file():   # data/input bị xóa tay -> không còn gì để chạy lại
                    raise UploadRejected("dữ liệu cũ của file này đã mất, hãy xóa mục cũ rồi tải lại")
                if existing.status == DONE and self.storage.docx_path(doc_id).is_file():
                    cache_hit = True
                elif not existing.is_active:                       # failed / cancelled / done-nhưng-mất-file
                    requeue = True

            entry = self.repo.link(client_id, doc_id, display, st.filename, cache_hit)
            if requeue:
                self.scheduler.submit(doc_id)
        doc = self.repo.get(doc_id)
        return doc, entry

    def _pick_id(self, st: Staged) -> str:
        """sha1[:10]; nếu (cực hiếm) trùng id với file KHÁC nội dung thì nới dài id."""
        for n in (10, 14, 20, 32, 40):
            cand = st.sha1[:n]
            ex = self.repo.get(cand)
            if ex is None or ex.sha256 == st.sha256:
                return cand
        return st.sha256[:48]
