"""Hàng đợi + worker chạy pipeline.

* Hàng đợi nằm TRONG SQLite (status='queued'), nên khởi động lại server không mất việc:
  tài liệu đang chạy dở được đưa về 'queued' và chạy tiếp (phần MinerU đã .done được bỏ qua).
* `main_slots` worker thread = số tài liệu chạy đồng thời; mỗi tài liệu lại có nhiều tiến trình MinerU
  (MineruRunner giới hạn tổng số tiến trình toàn máy).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from ..core.config import Settings
from ..models.document_repository import DocumentRepository
from ..models.entities import QUEUED, RUNNING_STATUSES
from .mineru_runner import MineruRunner
from .pipeline import Pipeline
from .storage import Storage

log = logging.getLogger("scheduler")


class Scheduler:
    def __init__(self, settings: Settings, repo: DocumentRepository, storage: Storage, pipeline: Pipeline,
                 runner: MineruRunner):
        self.s, self.repo, self.storage, self.pipeline, self.runner = settings, repo, storage, pipeline, runner
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()
        self._cancel: Dict[str, threading.Event] = {}      # doc_id -> cờ hủy (chỉ có khi đang chạy)
        self._pending_cancel: set = set()                  # hủy đến TRƯỚC khi worker kịp đăng ký cờ hủy
        self._force: set = set()
        self.last_decision = "Chưa có tài liệu nào chạy"

    # ------------------------------------------------------------------ vòng đời
    def start(self) -> None:
        n = self.repo.requeue_interrupted()
        if n:
            log.info("Đưa %d tài liệu đang chạy dở về hàng đợi", n)
        for i in range(self.s.main_slots):
            t = threading.Thread(target=self._worker, name=f"pipeline-{i + 1}", daemon=True)
            t.start()
            self._threads.append(t)
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            events = list(self._cancel.values())
        for ev in events:
            ev.set()
        for doc_id in list(self._cancel):
            self.runner.kill(doc_id)
        for t in self._threads:
            t.join(timeout=10)

    def notify(self) -> None:
        self._wake.set()

    def _worker(self) -> None:
        while not self._stop.is_set():
            doc = self.repo.claim_next()
            if doc is None:
                self._wake.wait(2.0)
                self._wake.clear()
                continue
            cancel = threading.Event()
            with self._lock:
                self._cancel[doc.id] = cancel
                if doc.id in self._pending_cancel:               # người dùng đã bấm Hủy ngay khi vừa được nhận việc
                    cancel.set()
                force = doc.id in self._force
                self._force.discard(doc.id)
            self.last_decision = f"Đang chạy {doc.filename}"
            try:
                self.pipeline.run(doc, cancel, force=force)
            except Exception:                                    # noqa: BLE001  (Pipeline.run đã tự bắt; đây là lưới an toàn)
                log.exception("Worker gặp lỗi ngoài dự kiến với %s", doc.id)
                self.repo.update(doc.id, status="failed", error_code="PIPELINE_ERROR",
                                 error_message="Lỗi nội bộ trong worker.", finished_at=time.time())
            finally:
                with self._lock:
                    self._cancel.pop(doc.id, None)
                    self._pending_cancel.discard(doc.id)
                self.last_decision = "Đang rảnh" if not self.repo.count_by_status(QUEUED) else "Còn tài liệu đang chờ"
                self._wake.set()                                  # nhận tiếp việc ngay

    # ------------------------------------------------------------------ lệnh từ controller
    def submit(self, doc_id: str, force: bool = False) -> bool:
        with self._lock:
            self._pending_cancel.discard(doc_id)
            if force:
                self._force.add(doc_id)
        ok = self.repo.enqueue(doc_id)
        if ok:
            self._wake.set()
        return ok

    def cancel(self, doc_id: str, wait: bool = False, timeout: float = 30.0) -> None:
        """Hủy: đang chờ -> hủy ngay; đang chạy -> bật cờ hủy + kill MinerU.
        wait=True: đợi tới khi worker thật sự rời tài liệu (cần trước khi xóa file)."""
        if self.repo.cancel_if_queued(doc_id):
            return
        with self._lock:
            ev = self._cancel.get(doc_id)
            if ev is None:
                doc = self.repo.get(doc_id)
                if doc is not None and doc.status in RUNNING_STATUSES:
                    self._pending_cancel.add(doc_id)             # worker vừa nhận việc nhưng chưa đăng ký cờ
        if ev is not None:
            ev.set()
            self.runner.kill(doc_id)
        if wait:
            deadline = time.time() + timeout
            while time.time() < deadline:
                doc = self.repo.get(doc_id)
                with self._lock:
                    busy = doc_id in self._cancel
                if not busy and (doc is None or doc.status not in RUNNING_STATUSES):
                    return
                time.sleep(0.2)

    # ------------------------------------------------------------------ thống kê
    def stats(self) -> dict:
        running_ids = []
        with self._lock:
            running_ids = list(self._cancel.keys())
        return {
            "running": running_ids,
            "main_slots": self.s.main_slots,
            "aux_mode": "off",
            "mineru_processes": self.runner.running_count(),
            "queued_tasks": self.repo.count_by_status(QUEUED),
            "last_decision": self.last_decision,
        }
