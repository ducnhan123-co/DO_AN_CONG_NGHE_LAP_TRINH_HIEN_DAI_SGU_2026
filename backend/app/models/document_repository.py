"""Repository: mọi truy vấn SQL nằm ở đây; controller/service không viết SQL."""
from __future__ import annotations

import json
import time
from typing import List, Optional, Tuple

from .database import DOCUMENT_COLUMNS, Database
from .entities import (ACTIVE_STATUSES, PARSING, QUEUED, RUNNING_STATUSES, Document, LibraryEntry)

_JSON_FIELDS = ("shards", "stages")


class DocumentRepository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ documents
    def get(self, doc_id: str) -> Optional[Document]:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return Document.from_row(row) if row else None

    def insert(self, doc: Document) -> None:
        now = time.time()
        doc.created_at = doc.created_at or now
        doc.updated_at = now
        data = {k: getattr(doc, k) for k in DOCUMENT_COLUMNS}
        for f in _JSON_FIELDS:
            data[f] = json.dumps(data[f], ensure_ascii=False)
        if data["rag_ok"] is not None:
            data["rag_ok"] = int(data["rag_ok"])
        cols = ", ".join(data)
        marks = ", ".join(":" + k for k in data)
        with self.db.connect() as c:
            c.execute(f"INSERT INTO documents ({cols}) VALUES ({marks})", data)

    def update(self, doc_id: str, **fields) -> None:
        """Cập nhật một số cột; shards/stages tự chuyển sang JSON."""
        if not fields:
            return
        bad = set(fields) - DOCUMENT_COLUMNS
        if bad:
            raise ValueError(f"Cột không tồn tại: {bad}")
        fields["updated_at"] = time.time()
        for f in _JSON_FIELDS:
            if f in fields:
                fields[f] = json.dumps(fields[f], ensure_ascii=False)
        if fields.get("rag_ok") is not None:
            fields["rag_ok"] = int(fields["rag_ok"])
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        fields["_id"] = doc_id
        with self.db.connect() as c:
            c.execute(f"UPDATE documents SET {sets} WHERE id = :_id", fields)

    def delete(self, doc_id: str) -> None:
        with self.db.connect() as c:
            c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))

    def all_ids(self) -> List[str]:
        with self.db.connect() as c:
            return [r["id"] for r in c.execute("SELECT id FROM documents")]

    # ------------------------------------------------------------------ hàng đợi
    def enqueue(self, doc_id: str) -> bool:
        """Đưa vào hàng đợi (chỉ khi chưa active). Trả True nếu đã xếp hàng."""
        now = time.time()
        with self.db.connect() as c:
            cur = c.execute(
                "UPDATE documents SET status = ?, progress = 0, error_code = NULL, error_message = NULL, "
                "queued_at = ?, finished_at = NULL, updated_at = ? "
                "WHERE id = ? AND status NOT IN (%s)" % ",".join("?" * len(ACTIVE_STATUSES)),
                (QUEUED, now, now, doc_id, *ACTIVE_STATUSES))
            return cur.rowcount > 0

    def claim_next(self) -> Optional[Document]:
        """Worker nhận tài liệu xếp hàng lâu nhất (nguyên tử: hai worker không nhận trùng nhau)."""
        now = time.time()
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT id FROM documents WHERE status = ? ORDER BY queued_at ASC, created_at ASC LIMIT 1",
                (QUEUED,)).fetchone()
            if not row:
                return None
            c.execute("UPDATE documents SET status = ?, started_at = ?, finished_at = NULL, updated_at = ? "
                      "WHERE id = ?", (PARSING, now, now, row["id"]))
            full = c.execute("SELECT * FROM documents WHERE id = ?", (row["id"],)).fetchone()
        return Document.from_row(full)

    def cancel_if_queued(self, doc_id: str) -> bool:
        """Hủy tài liệu còn đang chờ (chưa worker nào nhận). True nếu hủy được."""
        now = time.time()
        with self.db.connect() as c:
            cur = c.execute(
                "UPDATE documents SET status = 'cancelled', finished_at = ?, updated_at = ? "
                "WHERE id = ? AND status = ?", (now, now, doc_id, QUEUED))
            return cur.rowcount > 0

    def requeue_interrupted(self) -> int:
        """Khởi động lại server: tài liệu đang chạy dở được đưa về hàng đợi (shard đã .done sẽ được bỏ qua)."""
        now = time.time()
        with self.db.connect() as c:
            cur = c.execute(
                "UPDATE documents SET status = ?, queued_at = ?, updated_at = ? WHERE status IN (%s)"
                % ",".join("?" * len(RUNNING_STATUSES)), (QUEUED, now, now, *RUNNING_STATUSES))
            return cur.rowcount

    def count_by_status(self, *statuses: str) -> int:
        with self.db.connect() as c:
            r = c.execute("SELECT COUNT(*) AS n FROM documents WHERE status IN (%s)" % ",".join("?" * len(statuses)),
                          statuses).fetchone()
        return int(r["n"])

    # ------------------------------------------------------------------ library
    def link(self, client_id: str, doc_id: str, display_name: str, filename: str,
             cache_hit: bool) -> LibraryEntry:
        """Thêm tài liệu vào thư viện của client (nếu đã có thì giữ nguyên tên người dùng đã đặt)."""
        now = time.time()
        with self.db.connect() as c:
            c.execute("INSERT OR IGNORE INTO library (client_id, doc_id, display_name, filename, cache_hit, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?)", (client_id, doc_id, display_name, filename, int(cache_hit), now))
            row = c.execute("SELECT * FROM library WHERE client_id = ? AND doc_id = ?", (client_id, doc_id)).fetchone()
        return LibraryEntry.from_row(row)

    def get_entry(self, client_id: str, doc_id: str) -> Optional[Tuple[Document, LibraryEntry]]:
        with self.db.connect() as c:
            row = c.execute(
                "SELECT d.*, l.display_name AS l_display_name, l.filename AS l_filename, "
                "l.cache_hit AS l_cache_hit, l.created_at AS l_created_at, l.client_id AS l_client_id "
                "FROM library l JOIN documents d ON d.id = l.doc_id WHERE l.client_id = ? AND l.doc_id = ?",
                (client_id, doc_id)).fetchone()
        return self._pair(row) if row else None

    def list_entries(self, client_id: str, limit: int = 200) -> List[Tuple[Document, LibraryEntry]]:
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT d.*, l.display_name AS l_display_name, l.filename AS l_filename, "
                "l.cache_hit AS l_cache_hit, l.created_at AS l_created_at, l.client_id AS l_client_id "
                "FROM library l JOIN documents d ON d.id = l.doc_id WHERE l.client_id = ? "
                "ORDER BY l.created_at DESC LIMIT ?", (client_id, limit)).fetchall()
        return [self._pair(r) for r in rows]

    def rename(self, client_id: str, doc_id: str, display_name: str) -> bool:
        with self.db.connect() as c:
            cur = c.execute("UPDATE library SET display_name = ? WHERE client_id = ? AND doc_id = ?",
                            (display_name, client_id, doc_id))
            return cur.rowcount > 0

    def unlink(self, client_id: str, doc_id: str) -> int:
        """Gỡ khỏi thư viện của client; trả về số client còn dùng tài liệu này."""
        with self.db.connect() as c:
            c.execute("DELETE FROM library WHERE client_id = ? AND doc_id = ?", (client_id, doc_id))
            r = c.execute("SELECT COUNT(*) AS n FROM library WHERE doc_id = ?", (doc_id,)).fetchone()
        return int(r["n"])

    def count_links(self, doc_id: str) -> int:
        with self.db.connect() as c:
            r = c.execute("SELECT COUNT(*) AS n FROM library WHERE doc_id = ?", (doc_id,)).fetchone()
        return int(r["n"])

    def display_name_for(self, doc_id: str) -> Optional[str]:
        with self.db.connect() as c:
            r = c.execute("SELECT display_name FROM library WHERE doc_id = ? ORDER BY created_at ASC LIMIT 1",
                          (doc_id,)).fetchone()
        return r["display_name"] if r else None

    @staticmethod
    def _pair(row) -> Tuple[Document, LibraryEntry]:
        doc = Document.from_row(row)
        entry = LibraryEntry(client_id=row["l_client_id"], doc_id=row["id"], display_name=row["l_display_name"],
                             filename=row["l_filename"], cache_hit=bool(row["l_cache_hit"]),
                             created_at=row["l_created_at"])
        return doc, entry

    # ------------------------------------------------------------------ meta
    def meta_get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.db.connect() as c:
            r = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else default

    def meta_set(self, key: str, value: str) -> None:
        with self.db.connect() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
