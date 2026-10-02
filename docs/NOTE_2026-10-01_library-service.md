# Ghi chú công việc — 2026-10-01

Môi trường đã chạy thử: macOS (Darwin 25.4, arm64), Python 3.13, SQLite 3.50.4 (FTS5 bật), Chromium qua Playwright, Ollama local (qwen2.5:1.5b / qwen3:8b).

## 1. Sửa lỗi upload PDF (đã push trong commit `8a4473e`)
| Lỗi | Nguyên nhân gốc (đã tái hiện) | Cách sửa |
|---|---|---|
| Chọn/thả PDF không có phản ứng | `index.html`: `input.value=''` làm rỗng `FileList` trước khi `await serverOnline()` xong → danh sách file rỗng | Chụp `[...files]` ngay đầu hàm `handleFiles` |
| Chuyển sang trang chat thì trang chết | `reader.html` gọi `renderRecents()` trước khi khai báo `const API` (TDZ) | Dời lời gọi xuống sau khai báo |
| Upload treo vài chục giây (scan: vài phút) | `/api/upload` chạy OCR + embedding đồng bộ | Trả về ngay (`status: indexing`); index → DOCX nhanh → MinerU chạy nền; chat trả 425 khi chưa sẵn sàng |

## 2. Library Service mới (SQLite, cổng 8002) — commit này
- Package `library_api/` (`main.py`, `db.py`, `formulas.py`, `sources.py`); chỉ dùng `sqlite3` + FastAPI có sẵn, **không thêm dependency**; DB `runtime/library.db` (WAL, FTS5), bản chụp DOCX ở `runtime/library/docx/`.
- **Không sửa `backend/` và `llm/`** (BE đang chờ cập nhật từ nhánh `Nghia`). Chỗ phụ thuộc BE gom vào `library_api/sources.py`.
- Danh tính ẩn danh theo trình duyệt: `client_id` ngẫu nhiên (localStorage) gửi qua header `X-Client-Id`. Không phải xác thực.
- Tính năng: danh sách tài liệu (đổi tên/xóa), phiên chat + tin nhắn lưu server, công thức + ngữ cảnh (FTS5), trí nhớ ≤5 tin, lịch sử DOCX (phiên bản theo hash, tải lại bản cũ), nhật ký hoạt động.
- Frontend: `frontend/lib.js` (client dùng chung); `index.html` (thư viện từ server, menu ⋯ đổi tên/xóa, nhập danh sách cũ một lần); `reader.html` (tài liệu gần đây + phiên từ server, menu ⋯ xóa phiên/tài liệu, nút **Lịch sử**, ghép công thức + 4–5 tin vào `history` gửi BE).
- Trả lời câu "bấm lại DOCX có xử lý lại không": **không**, lấy bản hiện có ngay. Bản mới chỉ được chụp khi file DOCX của BE đổi nội dung (khác SHA-256).
- Khi 8002 tắt: chat qua BE vẫn chạy, chỉ báo không lưu được.

## 3. Lỗi UI sửa kèm
- **Khung PDF xám trống khi đổi tài liệu**: pdf.js 3.11.174 ném `TypeError ... 'destroy'` (`AnnotationEditorUIManager.destroy`) khi `setDocument` lần 2 trên cùng viewer → 0 trang. Sửa: dựng viewer mới cho mỗi tài liệu và `destroy()` tài liệu cũ.
- **Mục lục mất chữ ở trang đang chọn** khi hover (`hover:bg-white` đè chữ trắng) → dùng lớp `.is-active` với `!important`.
- **Đổi sang tài liệu cũ không nạp lại chat** → nạp phiên/tin nhắn từ server.
- `index.html` gọi `toast()` nhưng chưa định nghĩa → đã định nghĩa.

## 3b. Lỗi mở tài liệu cũ / sang tài liệu gần đây bị chậm, lag (sửa sau commit `e69ee56`)
**Nguyên nhân gốc (đã đo, môi trường như trên):** `MatchPdfStore._index` nhúng **toàn bộ chunk trong một request** `/api/embed` (timeout 60 s) và chạy đồng bộ trong `load()` — mà `load()` được gọi bởi `/api/doc`, `/api/file`, `/api/chat_stream` ngay lần đầu chạm tài liệu sau mỗi lần restart BE.
| Tài liệu | chunk | embed một lần |
|---|---|---|
| 100 trang | 106 | 18,8 s |
| 481 trang | 864 | **ReadTimeout sau 60 s** → rơi về TF-IDF |
| 706 trang (Calculus) | 1594 | **ReadTimeout sau 60 s** → rơi về TF-IDF |
Nên mở lại sách dày phải chờ ≥60 s rồi vẫn không có embedding.

**Yếu tố phụ ở FE (đã sửa):** `openDoc` không có chốt chạy lặp → bấm nhiều lần sinh nhiều lời chào "Đã mở…" (thấy trong ảnh) và nhiều lần tải PDF ghi đè nhau; mỗi lần mở lại gọi `/api/warm` (nạp model 8B) trùng lúc với embedding; mục lục 706 nút bị quét lại toàn bộ ở mỗi lần đổi trang; `/api/health` của BE (chờ Ollama tới 3 s) nằm trên đường mở trang.

**Cách sửa:**
- `llm/matchpdf.py` (chỉ file này; `backend/` không đụng): embed **theo lô 32** chunk (`EMBED_BATCH`), chạy ở **luồng nền** sau khi dựng TF-IDF; lưu cache `runtime/documents/{id}.emb.npz` (khóa theo SHA-1 nội dung chunk + tên model) nên restart không phải embed lại; `info()` có thêm `embed: building|ready|failed`. Chat dùng TF-IDF cho tới khi embedding xong. Nhánh `Nghia`/`kiet` không có `llm/matchpdf.py`.
- Library API: thêm `GET /api/lib/docs/{id}/file` (đọc PDF từ đĩa, hỗ trợ Range) để mở PDF không phải chờ BE.
- `reader.html`: chốt `openToken/opening` (chống mở lặp, bỏ kết quả cũ); tài liệu đã có trong thư viện thì hiện PDF + chat ngay, trạng thái chỉ mục của BE nạp nền; `/api/warm` chỉ gọi một lần mỗi model khi tài liệu sẵn sàng; mục lục chỉ đổi lớp ở một nút; hiển thị "đang lập chỉ mục ngữ nghĩa".

**Kết quả đo sau sửa:** `/api/doc` trên BE vừa restart: 0,02 s (100 trang) / 0,12 s (481) / 0,35 s (706) — trước đó ≥60 s. Trình duyệt, tài liệu 706 trang: PDF hiện sau 0,99 s (mở lần đầu), 0,17–0,28 s (chuyển tài liệu), 0,25 s (reload); bấm 3 mục liên tiếp chỉ còn 1 lời chào; chat trong lúc embedding đang chạy: token đầu sau 1,3 s. Con số "trước" ở trên là đo từng bước phía BE, **chưa** đo end-to-end qua trình duyệt trước khi sửa.

## 4. Cách đã kiểm chứng
- `python3 -m pytest tests -q` → 15 passed (9 Library API, 2 upload nền, 4 embedding nền/cache).
- `python3 tests/e2e_library.py` → `E2E OK` (Chromium thật + BE 8001 + FE 8080 + Library 8002 + Ollama): upload → chat → reload còn chat → đổi tài liệu cũ còn chat + PDF hiển thị → hộp Lịch sử có v1 → xóa phiên → đổi tên/xóa tài liệu → chặn 8002 mà chat vẫn chạy.
- Ghép công thức vào `history`: kiểm bằng cách giả lập phản hồi `/context` và đọc body gửi sang BE (1 ghi chú + tin gần nhất, ≤6 phần tử, khớp `history[-6:]` của `_prompt`).

## 5. Chưa kiểm chứng / giới hạn đã biết
- **MinerU hỏng trên máy**: 25/25 tài liệu `mineru_failed`; log `No such file or directory: 'mineru-kit'`; máy cài MinerU 2.7.6 (chỉ có `mineru -p -o`), code/`requirements.txt` đòi `mineru>=4.0,<5`. Vì vậy **chưa có công thức thật trong DB**; phần ingest chỉ test bằng `content_list` mẫu. Cần owner BE sửa rồi thử lại trên PDF toán thật.
- Chất lượng câu trả lời khi nhét ngữ cảnh qua `history` chưa đo (cần MinerU chạy được).
- **Xóa tài liệu chưa xóa được PDF vật lý trên BE** (BE hiện chỉ có GET/POST). UI báo rõ "PDF trên server chưa xóa được"; file vẫn nằm trong `runtime/documents/` cho tới khi BE có `DELETE /api/doc/{id}`.
- PDF scan cần OCR (Tesseract) chưa chạy thật; kéo-thả file chưa thử bằng tay (dùng chung hàm đã sửa).
- Restart BE giữa lúc xử lý nền thì tài liệu đó mất (index nằm trong RAM) — người dùng upload lại.
- `client_id` chỉ là định danh ẩn danh: ai biết id là xem được dữ liệu của id đó.

## 6. Việc cho owner BE / khi merge nhánh `Nghia`
1. Nhánh `origin/Nghia` là backend viết lại (MVC, API `/documents`, `/jobs`, `/documents/{id}/chat`, SQLite + FAISS riêng). Khi merge: viết lại `library_api/sources.py`, đổi chỗ FE gọi BE, quyết định lưu tin nhắn ở một nơi để không trùng.
2. Sửa lệnh MinerU (`mineru-kit` vs CLI 2.7.6) và thêm `DELETE /api/doc/{id}`.
3. Lưu embedding để restart không phải embed lại toàn bộ chunk (`load()` hiện gọi `_index` mỗi lần).
