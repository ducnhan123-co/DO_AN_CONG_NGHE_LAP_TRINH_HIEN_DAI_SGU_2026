# Review nhánh `origin/Nghia` (đối chiếu ngày 2026-10-16)

**Kiểm bằng:** `git fetch --all`, `git log origin/main..origin/Nghia`, `git diff 851a3a2 origin/Nghia`,
merge thử trong worktree riêng (đã xoá, không đụng working tree).

## Nhánh này là gì
- Gốc là `851a3a2` (main cũ). Có **2 commit mới** so với main: `fb5e268` "sửa frontend" (8/10) và
  `fa1a84c` "backend cũ" (10/10). Main hiện đi trước 15 commit. Nhánh `Nghia` **local** còn cũ hơn nữa (25/9).
- Nội dung: pipeline 2 giai đoạn (đọc nhanh bằng pypdf → chat được sau vài chục giây, MinerU nâng cấp ngầm,
  hoán đổi chỉ mục), chat nhiều tài liệu (`doc_ids`), nhóm tài liệu (`collections`, schema V2), khoá
  `_mineru_lock/_embed_lock`, executor DOCX riêng, prompt tiếng Việt, timeout pandoc.

## Áp vào main được không
Merge thử: **xung đột ở 3 file** (`pipeline_model.py`, `index.html`, `reader.html`), 13 file còn lại tự gộp.
**Không merge nguyên nhánh**, vì:
1. Gần như toàn bộ là tính năng **chat/RAG**; phạm vi đồ án hiện tại (README) là **PDF → DOCX**, UI đã bỏ chat.
2. Đường "đọc nhanh" pypdf đọc lớp chữ thô: PDF font TCVN3 (vd. giáo trình Cơ học) ra rác, không qua
   `tcvn3_to_unicode` / `vi_textlayer`.
3. UI `index.html`/`reader.html` của main đã viết lại (chip trạng thái, SuperDoc, upload nhiều file).

## Đã lấy
- `PANDOC_TIMEOUT_S = 900` (build_docx): pandoc treo → báo lỗi thay vì kẹt thread DOCX vô hạn. Có test.
- Đã có sẵn ở main, không cần lấy: ghi DOCX nguyên tử (`output.building.docx` + `os.replace`), `config.js` cổng 8000,
  sửa `Citation` trước `MessageOut`.

## Nếu sau này cần chat nhiều tài liệu
Cherry-pick riêng: `library_db.SCHEMA_V2`, `library_model` (collections), `compat_controller.chat_stream(doc_ids)`.
Đừng đụng `pipeline_model.py` cùng lúc: tách PR, rồi chạy lại `tests/` và upload thử 1 PDF.
