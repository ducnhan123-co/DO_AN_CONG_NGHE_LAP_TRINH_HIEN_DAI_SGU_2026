# BE mới + các fix + hướng tối ưu (note ngày 2026-10-07)

Nhánh: `fix/nghia-multifile-ui` (từ `origin/Nghia` + fix). Server chạy 1 cổng duy nhất
`http://127.0.0.1:8000`, UI `http://127.0.0.1:8080`. Không cần mở cổng 8002 nữa.

## 1. BE mới gồm gì

| Thành phần | Đang dùng | Gọi kiểu gì |
|---|---|---|
| MinerU | `mineru` 2.7.6 legacy CLI, backend `pipeline` (`llm/src/run_mineru.py`) | `subprocess`: `mineru -p <pdf> -o <dir> -b pipeline -m <txt\|ocr\|auto> -l latin -d cpu -f true -t true` |
| text/scan detect | `has_extractable_text()` (pypdf, 3 trang đầu) | PDF chữ → `-m txt` (bỏ OCR); scan → `-m ocr` |
| Embedding | `intfloat/multilingual-e5-base` + LlamaIndex FAISS theo từng doc (`llm/src/llama_rag.py`) | `build_index(nodes, EMBED_MODEL, rag_dir)` |
| LLM chat | `none` (mặc định `.env`) → trả đoạn trích; có sẵn `qwen_local` (Qwen2.5-3B) / `ollama` (`backend/app/core/llm.py`) | `chat_model.stream_events()` |
| DB | SQLite WAL: `app.db` (documents/jobs/messages) + `library.db` (docs/sessions/formulas/docx_versions/activity) | SQLAlchemy + sqlite thuần |
| Pipeline nền | `ThreadPoolExecutor(max_workers=1)`: `mineru_parsing(10)` → `building_docx(30, thread riêng)` → `indexing(55)` → `ready(100)` | `POST /documents` (field `file`) → 202 → poll `GET /jobs/{id}` |
| API gộp 1 cổng | `backend/app/main.py` + `controllers/` (document/job/chat/export/compat/library), prefix `/api` | tương thích cũ: `/api/upload` (field `f`), `/api/doc/{id}`, `/api/file/{id}`, `/api/docx/{id}`; thư viện: `/api/doc`, `/api/doc/{id}/sessions`, `/api/session/{sid}/messages`, `/api/doc/{id}/ingest|context|docx|activity` |
| Frontend multi-file | `index.html` staged tối đa 10 file → `reader.html?doc_id=A&doc_id=B`; `reader.html` thanh tab trượt + panel DOCX list + Tải toàn bộ | 1 file giữ nguyên luồng cũ |

Chưa có: `upgrade_mineru` 2-stage flash→standard (store cũ có, BE mới chỉ chạy MinerU 1 lần);
`mineru-kit` 4.x (máy chưa có, xem mục 3).

## 2. Đã fix gì (toàn bộ trong nhánh này)

| # | Lỗi | File | Sửa |
|---|---|---|---|
| 1 | `Citation` định nghĩa sau `MessageOut` → BE không start (`NameError`) | `backend/app/views/schemas.py` | đưa `class Citation` lên trước `MessageOut` |
| 2 | `config.js` LIB trỏ 8002 (chết) | `frontend/config.js` | `MATCHPDF_LIB_BASE` → `8000` |
| 3 | `reader.html` dùng `/docs/…`, `/sessions/…` (số nhiều) → 404 hết | `frontend/reader.html` | đổi sang `/doc/…`, `/session/…` (15 chỗ), `LIB.blob('/doc/'+vid+'/download')` |
| 4 | `<div id="docxPanel" …></div>` tự đóng → nội dung panel rơi ra ngoài, bấm Tải DOCX không hiện gì | `frontend/reader.html` | gộp nội dung vào trong div |
| 5 | thiếu `$`, `dispName()`, `docxFile()` → multi-file crash `ReferenceError` | `frontend/reader.html` | thêm helpers + `scrollTabs()` + `savePage()` (nhớ trang qua localStorage) |
| 6 | `libSync(j, id)` tự ghi đè `id=API.docId` → đồng bộ nhầm file | `frontend/reader.html` | `libSync(j, docId)` dùng đúng id từng file |
| 7 | thanh tab chỉ `overflow-x-auto`, không nút/kéo rõ ràng | `frontend/reader.html` | thêm nút ◀ ▶ + kéo chuột + tự cuộn tới tab active + scrollbar visible |
| 8 | MinerU luôn OCR kể cả PDF chữ (~16s/trang) | `llm/src/run_mineru.py`, `llm/src/config.py`, `backend/app/models/pipeline_model.py` | tự phát hiện PDF chữ → `-m txt`; `-l latin`; `-d cpu`; giữ `-f/-t true` cho toán; worker 3→1 |

Kiểm chứng: upload `onepage.pdf` (1 trang chữ) → `indexing` → `ready` + DOCX `ready` trong ~85s,
log `PDF chữ -> MinerU method=txt`. `node --check` JS index/reader OK. `pytest backend/tests`
vẫn fail 2 test cũ (viết cho store BE cũ, không liên quan fix này).

## 3. Làm gì để nhanh hơn nữa

| Việc | Kỳ vọng | Ghi chú |
|---|---|---|
| Cài MinerU 4.x: `python -m pip install -U "mineru>=4.0,<5"` (cần Python <3.15, máy 3.13 OK) rồi `mineru-kit models download --tier standard` | flash nhanh gấp 3–5x bản standard | code `_run_kit()` đã tự dùng kit khi thấy binary; phải verify lại output (`--format zip`, `structured_content.json`) vì CLI 4.x khác 2.x; KHÔNG cài đè lúc server chạy — model tải hàng GB |
| Dựng lại 2-stage `upgrade_mineru`: flash preview → chat ngay, standard nền | chat dùng được sau ~1–2 phút/file dài | BE mới hiện chưa có, phải code thêm |
| Chạy MinerU server persistent thay vì spawn process mỗi file | tiết kiệm ~12s nạp model/file | 4.x có `mineru-kit webui`/server; 2.x không có |
| Giảm `TOP_K`, `MAX_CHARS` khi test tốc độ | index nhanh hơn | đổi trong `llm/src/config.py` + `.env TOP_K` |

## 4. Làm gì để chính xác hơn

| Việc | Vì sao |
|---|---|
| Giữ `formula=true`, `table=true` với PDF toán (đang giữ) | tắt là mất công thức Equation trong DOCX/RAG |
| Giữ tier `standard` cho bản cuối (đang giữ), chỉ dùng `flash` preview | `basic/flash` dùng model nhỏ, công thức kém hơn |
| Giữ `-l latin` (đang giữ) | mặc định CLI là `ch`, sai cho tiếng Việt |
| Kiểm tra `validation.json` sau mỗi file (`runs`/doc_dir) | phát hiện chunk mất công thức/table |
| Bật LLM (`LLM_BACKEND=ollama`, model `qwen2.5:7b`) khi cần trả lời sinh thay vì trích đoạn | hiện `none` chỉ trích xuất, không suy luận |
| Nạp công thức vào FTS (`POST /doc/{id}/ingest` đã tự gọi khi parser=mineru) | chat kèm LaTeX liên quan, đã có trong `libSync` |
