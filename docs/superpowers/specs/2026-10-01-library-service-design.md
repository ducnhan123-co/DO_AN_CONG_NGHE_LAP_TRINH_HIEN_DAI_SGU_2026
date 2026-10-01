# Library Service (SQLite) — thiết kế

Ngày: 2026-10-01 · Trạng thái: **đã duyệt và đã triển khai (2026-10-01)** · Phạm vi: phần FE/thư viện của dự án MatchPDF

## 1. Mục tiêu
Bổ sung lưu trữ bền vững để tải lại trang vẫn còn tài liệu, phiên chat, công thức và lịch sử DOCX:

1. Danh sách tài liệu theo người dùng (ẩn danh theo trình duyệt), đổi tên, xóa.
2. Phiên chat + tin nhắn lưu trên server; đổi tài liệu / reload không mất chat.
3. Lưu công thức toán + ngữ cảnh (MinerU) để đưa vào prompt; trí nhớ 3–5 tin gần nhất.
4. Lịch sử các bản DOCX (xem, tải lại bản cũ) + nhật ký hoạt động.
5. Xóa phiên, xóa tài liệu (kèm PDF khi BE hỗ trợ).
6. Sửa lỗi UI kèm theo (mục 7).

**Không làm (non-goals):** đăng nhập thật; Redis; sửa bất cứ file nào trong `backend/`, `llm/`; lưu embedding/chunk RAG (thuộc BE); nút "xuất DOCX lại" (cần BE); sửa MinerU.

## 2. Ràng buộc đã chốt với chủ repo
- Danh tính: **ẩn danh theo trình duyệt** (`client_id` ngẫu nhiên, header `X-Client-Id`). Không phải xác thực.
- **Service FastAPI thứ hai, cổng 8002**, package `library_api/`, DB `runtime/library.db`.
- **Không đụng BE.** `backend/` hiện cũ; BE mới ở nhánh `origin/Nghia` (API khác, tự có SQLite + FAISS). Mọi chỗ phụ thuộc BE gom vào `library_api/sources.py` để sau chỉ sửa một file.
- Tích hợp AI: **FE ghép ngữ cảnh**, gửi qua trường `history` mà BE hiện có (BE `_prompt` chỉ dùng `history[-6:]`, mỗi tin cắt 3000 ký tự).
- MinerU hiện hỏng trên máy (`mineru-kit` không có; cài 2.7.6) → mảng công thức làm trước, test bằng `content_list` mẫu; dữ liệu thật vào khi owner BE sửa MinerU.

## 3. Kiến trúc
```
FE :8080 ──► BE :8001 (giữ nguyên: upload, chat_stream, RAG, MinerU, DOCX)
   └──────► Library API :8002 ── SQLite runtime/library.db (WAL, FTS5)
                               ├─ sources.py: ĐỌC runtime/documents/*, gọi DELETE sang BE
                               └─ runtime/library/docx/{doc_id}/v{N}.docx (bản chụp DOCX)
```
Chỉ dùng `sqlite3` của stdlib + FastAPI/uvicorn đã cài; **không thêm dependency**. Kiểm tra trên máy: SQLite 3.50.4, FTS5 bật, JSON1 có.

`sources.py` (điểm duy nhất biết bố cục BE): `docx_path(doc_id)`, `content_list_path(doc_id)`, `delete_pdf(doc_id) -> deleted|unsupported|error`. `doc_id` là chuỗi mờ, validate `[A-Za-z0-9_-]{1,64}` (không gắn regex 10-hex của BE hiện tại).

## 4. Dữ liệu
Migration bằng `PRAGMA user_version`. Mọi bảng có `client_id`; mọi route kiểm `documents.client_id == header`.

| Bảng | Cột |
|---|---|
| `documents` | `doc_id`, `client_id`, `name`, `display_name`, `num_pages`, `parser`, `created_at`, `last_opened_at`, `deleted_at`; PK (`client_id`,`doc_id`) |
| `sessions` | `id` PK, `client_id`, `doc_id`, `title`, `created_at`, `updated_at` |
| `messages` | `id` PK, `session_id` FK ON DELETE CASCADE, `role`, `content`, `citations` (JSON), `model`, `elapsed_s`, `created_at` |
| `formulas` | `id` PK, `client_id`, `doc_id`, `page`, `section`, `latex`, `ctx_before`, `ctx_after` |
| `formulas_fts` | FTS5 trên `latex` + `ctx_before` + `ctx_after`, rowid = `formulas.id` |
| `docx_versions` | `id` PK, `client_id`, `doc_id`, `version`, `source` (`fast`/`mineru`), `sha256`, `size`, `path`, `created_at`; UNIQUE(`doc_id`,`sha256`) |
| `activity_log` | `id` PK, `client_id`, `doc_id`, `kind`, `detail`, `created_at` |

Bật `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`.

## 5. API (`/api/lib`, header `X-Client-Id` 8–64 ký tự `[A-Za-z0-9_-]` bắt buộc, thiếu/sai → 400)
| Method + đường dẫn | Việc |
|---|---|
| `GET /docs` | Tài liệu chưa xóa, mới mở gần nhất trước |
| `PUT /docs/{doc_id}` `{name,num_pages,parser}` | Đăng ký/cập nhật khi upload hoặc mở (upsert, cập nhật `last_opened_at`) |
| `PATCH /docs/{doc_id}` `{display_name}` | Đổi tên |
| `DELETE /docs/{doc_id}` | Đặt `deleted_at`, xóa phiên/tin nhắn/công thức/DOCX snapshot, gọi `sources.delete_pdf`. Trả `{pdf: deleted\|unsupported\|error}` |
| `GET\|POST /docs/{doc_id}/sessions` | Liệt kê / tạo phiên |
| `PATCH\|DELETE /sessions/{sid}` | Đổi tiêu đề / xóa phiên (cascade tin nhắn) |
| `GET /sessions/{sid}/messages` | Tin nhắn theo thời gian |
| `POST /sessions/{sid}/messages` | Thêm 1–2 tin (hỏi + đáp) sau mỗi lượt chat |
| `GET /docs/{doc_id}/context?q=&session_id=` | `{recent:[≤5 tin], formulas:[≤3]}`; công thức xếp theo `bm25` của FTS5, câu hỏi được tách thành token an toàn rồi nối OR, rỗng thì không truy vấn |
| `POST /docs/{doc_id}/ingest` | Đọc `content_list` qua `sources`, nạp `equation` + đoạn kề + `section`; ghi đè theo doc (idempotent); trả số công thức |
| `POST /docs/{doc_id}/docx/snapshot` `{source}` | Băm file DOCX của BE; hash mới → chụp thành `v{N+1}`; trùng hash → trả bản hiện có, không tạo mới |
| `GET /docs/{doc_id}/docx` · `GET /docx/{id}/download` | Danh sách phiên bản · tải bản bất kỳ |
| `GET /docs/{doc_id}/activity` | Nhật ký (upload/docx/ingest/xóa) |

Hành vi DOCX: bấm "Tải DOCX" lấy bản mới nhất ngay (không xử lý lại). Chỉ có phiên bản mới khi file DOCX của BE thật sự đổi nội dung.

## 6. Frontend
- Thêm `frontend/lib.js` dùng chung: sinh/đọc `client_id`, wrapper `fetch` tới 8002 (có timeout, không ném lỗi ra ngoài: trả `null` khi 8002 tắt).
- `index.html`: thư viện đọc từ `GET /docs`; thẻ có menu ⋯ (Đổi tên, Xóa tài liệu + PDF); nhập một lần `matchpdf_recents2` cũ khi mở lần đầu.
- `reader.html`: "Tài liệu gần đây" và "Phiên chat" đọc từ server; mở/đổi tài liệu → nạp phiên mới nhất + tin nhắn; sau mỗi lượt chat `POST messages`; menu ⋯ phiên (Xóa phiên) và tài liệu; nút 🕘 **Lịch sử** cạnh "Tải DOCX" (danh sách phiên bản + nhật ký, nút tải lại).
- Ghép prompt: trước `chat_stream`, gọi `context` rồi gửi `history = [ghi chú "[Công thức liên quan] …" nếu có] + ≤4–5 tin gần nhất` (tối đa 6 phần tử để khớp `history[-6:]` của BE).
- Kích hoạt: `PUT docs` khi mở; `ingest` khi BE báo `parser=mineru`; `docx/snapshot` khi BE báo `docx=ready`.
- Suy giảm: 8002 tắt → chat qua BE vẫn chạy, hiện "chưa kết nối thư viện — chat không được lưu", không lỗi trang.
- Bỏ `localStorage` cho recents/sessions (giữ `client_id` và tùy chọn giao diện).

## 7. Lỗi UI kèm theo
1. Mục lục: dòng trang đang active bị `hover:bg-white` đè chữ trắng → mất chữ.
2. Đổi sang tài liệu cũ không nạp lại chat (`initSessions(false)`); khắc phục bằng nạp từ server (mục 6).
3. Khung PDF xám trống (ảnh bạn gửi): **chưa rõ nguyên nhân** → tái hiện bằng trình duyệt trước khi sửa; không sửa theo phỏng đoán.
4. Thẻ thư viện hiển thị tên file gốc lộn xộn → dùng `display_name`, cho đổi tên.

## 8. Xử lý lỗi & biên
- DB bận: `busy_timeout`; lỗi ghi trả 503 với thông điệp rõ.
- `client_id` sai/thiếu → 400; doc/phiên không thuộc client → 404 (không lộ tồn tại).
- `delete_pdf` trả `unsupported` khi BE chưa có endpoint xóa → UI báo "đã xóa khỏi thư viện; PDF trên server chưa xóa được (BE chưa hỗ trợ)". **PDF vật lý vẫn còn trên đĩa BE cho đến khi BE hỗ trợ xóa.**
- Ingest khi chưa có `content_list` → trả `{formulas:0}`, không lỗi.
- Giới hạn: nội dung tin ≤ 20 000 ký tự, tiêu đề ≤ 120, tối đa 500 công thức mỗi lần `ingest`; `context` trả không quá 3 công thức và 5 tin.

## 9. Kiểm thử
- `pytest` + `TestClient` với DB tạm: CRUD tài liệu/phiên/tin; cô lập theo `client_id`; cascade xóa; `ingest` bằng `content_list` mẫu tự dựng (kể cả idempotent); `context` (FTS5, token đặc biệt, rỗng); `docx/snapshot` không trùng hash; `delete_pdf` các trạng thái.
- E2E Playwright: upload → chat → reload → chat còn; đổi tài liệu cũ → chat hiện lại; xóa phiên; xóa tài liệu; tắt 8002 → chat vẫn chạy.
- Tự kiểm lại: `sqlite3 runtime/library.db ".schema"` và `curl` các endpoint.

## 10. Rủi ro & việc để sau
- Backend của Nghĩa có Document/Job/Message riêng và API khác (`/documents`, `/documents/{id}/chat`). Khi merge cần: viết lại `sources.py`, đổi chỗ FE gọi BE, quyết định lưu tin nhắn ở đâu để không trùng.
- Công thức chỉ có khi MinerU chạy được (chưa kiểm chứng trên PDF thật).
- Chất lượng khi nhét ngữ cảnh qua `history` chưa đo; đo bằng vài câu hỏi công thức thật sau khi MinerU chạy.
- Đề xuất cho owner BE: lưu embedding để restart không embed lại; thêm `DELETE /api/doc/{id}`.
