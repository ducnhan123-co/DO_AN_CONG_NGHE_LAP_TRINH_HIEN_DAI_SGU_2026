## FE Render connecting to Kiet CLI on Mac

Static HTML cannot run a CLI by itself. Click Ket noi Mac and enter the
HTTPS Cloudflare Tunnel URL and demo username/password. The password stays in
sessionStorage and must NOT be committed. The existing Mac FastAPI upload/job
API launches kiet_cli.py in a subprocess; the same API delivers DOCX/audit.
There is NO additional Kiet API. See docs/MAC_TUNNEL_DEPLOY.md.

---

# MatchPDF — Frontend

Gửi BE: file này mô tả **FE cần BE cung cấp gì (tối thiểu)** để chạy đủ luồng *Upload PDF → Đọc PDF → Chat có trích dẫn trang → Tải DOCX*.

- Stack FE: HTML tĩnh + Tailwind/PDF.js/KaTeX qua CDN, không build. Chạy: `python3 -m http.server 8080` trong thư mục `frontend/`.
- Đã đối chiếu với: commit `07b9deb` (main), route của `backend/app/main.py` (main) và `origin/Nghia` (đọc source, **chưa chạy** nhánh Nghia).
- Cấu hình: `config.js` — `MATCHPDF_API_BASE` (BE, mặc định `:8001`), `MATCHPDF_LIB_BASE` (Library, mặc định `:8002`).

---

## 1. Hiện trạng: cái gì thật, cái gì còn mock

| Phần | Trạng thái |
|---|---|
| Upload, đọc PDF, chat stream, DOCX | **Đã gọi BE thật** (BE cũ trong `main`, cổng 8001). Cần BE mới giữ đúng contract ở §3. |
| Danh sách tài liệu, phiên chat, lịch sử tin nhắn, công thức, lịch sử DOCX | Gọi **Library API (8002)** — service riêng do FE làm, lưu SQLite. BE **không** phải làm (xem §5). |
| Chip gợi ý câu hỏi (`reader.html` ~L181–184) | **Hardcode** ("Chương 2 nói gì về mô hình RAG?"…) — chưa sinh từ tài liệu. |
| Lời chào `seed()` (~L572) | **Hardcode** mẫu trích dẫn `[2]`. |
| Chọn model (`#modelSel`, ~L169) | **Hardcode** 3 model Ollama (`qwen2.5:1.5b`, `qwen3:8b`, `qwen3:14b`). |
| Người dùng "Sinh viên SGU / sv@sgu.edu.vn" | **Hardcode**, chưa có đăng nhập. Định danh = `X-Client-Id` ngẫu nhiên trong localStorage. |
| Nút "Tách PDF", "Nhóm PDF" | Chỉ `toast('sắp có')`. |
| Mục lục PDF | Chỉ liệt kê "Trang 1..N", chưa có outline thật. |
| Khi BE tắt | Upload báo "Server chưa chạy"; badge "Chế độ demo". Không còn dữ liệu mẫu. |

## 2. Luồng xử lý (FE ↔ BE)

```
Upload (index.html)                 Reader (reader.html)
 POST /api/upload  ───────────────►  GET  /api/doc/{id}   (poll 2s khi indexing, 5s khi nền chạy)
   ◄─ {doc_id,num_pages,status}      GET  /api/file/{id}  (PDF gốc, PDF.js render)
 location → reader.html?doc_id=…     POST /api/warm       (1 lần/model khi status=ready)
                                     POST /api/chat_stream ─► SSE: {t}… {done,citations,elapsed_s}
                                     GET  /api/docx/{id}  (nút "Tải DOCX" sáng khi docx=ready)
```

1. **Upload** `multipart` field `f`. BE phải trả về **ngay** (không chờ OCR/embedding); việc nặng chạy nền.
2. FE mở reader tức thì, PDF đọc được ngay; chat bị khóa tới khi `status=ready` (FE poll `/api/doc/{id}`).
3. **Chat**: FE gửi `question` + `history` (≤6 tin, đã ghép công thức từ Library), nhận SSE; `[n]` trong câu trả lời → nút nhảy tới **trang n**.
4. **DOCX**: nút sáng khi `docx=ready`; tải qua `docx_url`.

## 3. API BE tối thiểu (contract FE đang dùng)

CORS: cho `GET, POST, DELETE` (+ `Content-Type`, và `Range` nếu BE tự phục vụ PDF) từ origin FE.

### P0 — thiếu là FE không chạy

| # | Method & path | Request | Response FE đọc | Ghi chú |
|---|---|---|---|---|
| 1 | `GET /api/health` | — | `{ok: bool, llm?: string}` | FE gọi mỗi 15s; **phải nhanh** (không chờ LLM). Hiện badge "AI thật · {llm}". |
| 2 | `POST /api/upload` | multipart `f` (PDF ≤50MB) | `{doc_id, name, num_pages, status, parser?, docx?, file_url?}` | 415 nếu không phải PDF, 413 nếu quá 50MB. Trả ngay, `status:"indexing"`. |
| 3 | `GET /api/doc/{doc_id}` | — | xem bảng dưới | 404 nếu không có. FE poll tới khi hết trạng thái "đang chạy". |
| 4 | `GET /api/file/{doc_id}` | — | PDF, `Content-Type: application/pdf`, `inline` | Phải đọc được **cả khi đang indexing**. Nên hỗ trợ `Range` (sách 700 trang). |
| 5 | `POST /api/chat_stream` | JSON: `{doc_id, question(≤2000), top_k(1–10), model, history:[{role,content}]≤12}` | SSE `text/event-stream` | 425 nếu chưa ready, 404 nếu không có doc. Định dạng SSE bên dưới. |
| 6 | `GET /api/docx/{doc_id}` | — | file `.docx` | **425** khi chưa xong (FE dựa vào mã này), 404 nếu không có. |

**Trường `GET /api/doc/{id}`** (FE dùng):

| Trường | Giá trị / ý nghĩa |
|---|---|
| `doc_id`, `name`, `num_pages` | bắt buộc |
| `status` | `indexing` \| `ready` \| `failed` (+ `error` string khi failed) |
| `num_chunks` | hiển thị trên meta |
| `parser` | `pypdf` \| `mineru_running` \| `mineru` \| `mineru_failed` (FE map ra nhãn; đổi giá trị thì báo FE) |
| `embed` | `building` \| `ready` \| `failed` (chat vẫn dùng được khi `building`) |
| `docx` | `building` \| `ready` \| `failed`; kèm `docx_url` khi `ready` |
| `file_url` | đường dẫn PDF gốc (dùng khi Library 8002 tắt) |

**SSE của `/api/chat_stream`** — mỗi sự kiện một dòng `data: <json>\n\n`:

```
data: {"t": "đoạn chữ"}                                  ← lặp nhiều lần
data: {"done": true, "citations": [12, 15], "elapsed_s": 3.4}   ← kết thúc; citations = SỐ TRANG
data: {"error": "thông báo"}                              ← lỗi giữa chừng
```

> **Quan trọng:** `citations` là **số trang (int)** vì FE gọi `gotoPage(n)`. Chuỗi `[n]` trong chữ trả lời cũng là số trang. Công thức trong chữ dùng `$…$` / `$$…$$` (KaTeX).

### P1 — nên có, FE đã chờ sẵn

| # | Method & path | Dùng để | Nếu thiếu |
|---|---|---|---|
| 7 | `DELETE /api/doc/{doc_id}` → 200/202/204 | Xóa PDF vật lý khi user xóa tài liệu (Library 8002 gọi) | UI báo "PDF trên server chưa xóa được"; file rác tồn đọng. |
| 8 | `POST /api/warm` `{model}` → `{ok:true,model}` | Nạp trước model Ollama | Chat đầu chậm (~1 phút). FE bỏ qua lỗi. |

### Không cần (đừng tốn công)
Danh sách tài liệu, đổi tên, phiên chat, lưu tin nhắn, lịch sử DOCX, nhật ký — đã có ở Library 8002.

## 4. Đối chiếu nhánh `origin/Nghia` (BE mới) — khoảng trống so với contract

Route nhánh Nghia (đọc từ source): `POST /documents` (202), `GET /documents/{id}`, `GET /jobs/{id}`, `POST /documents/{id}/chat` (SSE: `thinking/token/citations/done/error`), `GET /documents/{id}/export/docx`.

| FE cần | Nghia có? | Việc phải làm |
|---|---|---|
| `GET /api/health` | Không thấy | Thêm. |
| Upload → `doc_id`, `num_pages` | `document_id`, `job_id`; **chưa có `num_pages`** | Thêm `num_pages` (hoặc FE đọc từ PDF.js — báo để chọn). |
| Trạng thái | `status` + job `stage` (`mineru_parsing/building_docx/indexing/ready`) | Map sang `status/parser/docx/embed` ở §3, hoặc FE đổi sang poll `/jobs/{id}`. Thống nhất 1 cách. |
| `GET /api/file/{id}` (PDF gốc) | **Không** | Thêm (file nằm sẵn ở `backend/data/documents/{id}/input.pdf`). |
| Citation = **số trang** | `Citation{index, chunk_id, heading, score, snippet}` — **không có `page`** | **Thêm `page`** vào mỗi citation; không có thì không nhảy trang được. |
| `history` trong chat | `ChatRequest` không có | Thêm `history` (hoặc BE tự giữ hội thoại — khi đó báo FE bỏ phần ghép lịch sử). |
| `model` trong chat | Không | Thêm `model` (hoặc bỏ dropdown ở FE). |
| Định dạng SSE | Event có tên (`token`/`done`…) | Thống nhất: FE sửa parser sang event có tên, hoặc BE dùng `data:{t}` như §3. FE sẵn sàng đổi. |
| 425 khi chưa ready | Trả 409 | Thống nhất mã (FE đổi dễ). |
| `DELETE`, `warm` | Không | P1. |
| `doc_id` | UUID 32 hex (cũ: 10 hex) | Library 8002 nhận cả hai; không ảnh hưởng. |

**Câu hỏi mở cần BE trả lời:** (a) giữ tên route `/api/*` hay chuyển hẳn `/documents/*`? (FE chỉ sửa 2 file, ~8 chỗ gọi); (b) BE hay FE lưu lịch sử chat? (hiện FE/Library lưu, tránh lưu 2 nơi); (c) MinerU (`mineru-kit` không có trên máy dev, bản cài 2.7.6) — công thức chưa test thật.

## 5. Library API (cổng 8002) — FE tự làm, BE không phải viết

Tiền tố `/api/lib`, header `X-Client-Id`. `GET /health`, `GET /docs`, `PUT|PATCH|DELETE /docs/{id}`, `GET /docs/{id}/file`, `GET|POST /docs/{id}/sessions`, `PATCH|DELETE /sessions/{id}`, `GET|POST /sessions/{id}/messages`, `POST /docs/{id}/ingest`, `GET /docs/{id}/context`, `POST /docs/{id}/docx/snapshot`, `GET /docs/{id}/docx`, `GET /docx/{vid}/download`, `GET /docs/{id}/activity`. Nó đọc thẳng `runtime/documents/{id}.pdf|.docx` và `{id}_mineru/*_content_list.json` của BE (gom ở `library_api/sources.py`). **Nếu BE mới đổi chỗ lưu file** thì chỉ cần báo để sửa `sources.py`.

## 6. Cách tự kiểm lại (không tin README này)

```bash
# 1. Liệt kê mọi chỗ FE gọi BE (phải khớp bảng §3)
cd frontend && grep -noE "(API\.base|API_BASE)\+?'?/api/[a-z_/]+" index.html reader.html | sort -u
# 2. Route BE hiện tại
grep -nE '@app\.(get|post|delete)' ../backend/app/main.py
# 3. Route nhánh Nghia
git show origin/Nghia:backend/app/controllers/chat_controller.py | grep -n '@router'
# 4. Thử contract bằng tay
curl -s localhost:8001/api/health
curl -s -F f=@some.pdf localhost:8001/api/upload
curl -N -X POST localhost:8001/api/chat_stream -H 'Content-Type: application/json' \
  -d '{"doc_id":"<id>","question":"Tóm tắt","top_k":5,"model":"qwen3:8b","history":[]}'
```

## 7. Chưa kiểm chứng

- Chưa chạy BE nhánh Nghia cùng FE; mọi dòng ở §4 là từ đọc source.
- Chưa test PDF scan (OCR) và công thức MinerU thật (MinerU hỏng trên máy dev, xem `docs/NOTE_2026-10-01_library-service.md` §5).
- Chưa đo hiệu năng với BE mới.
