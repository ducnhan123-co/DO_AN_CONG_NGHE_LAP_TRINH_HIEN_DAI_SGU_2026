# Backend: PDF Toán → MinerU → DOCX + RAG Chat

Backend FastAPI cho ứng dụng chat với tài liệu PDF toán: upload → MinerU → DOCX → RAG hỏi đáp có trích dẫn. Tổ chức theo mô hình MVC.

## Mục lục

1. [Kiến trúc](#1-kiến-trúc)
2. [API contract](#2-api-contract)
3. [Cách chạy](#3-cách-chạy)

---

## 1. Kiến trúc

### 1.1. Cấu trúc thư mục

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                     # khởi tạo FastAPI, lifespan, gắn router
│   │
│   ├── controllers/                # ==== CONTROLLER ====
│   │   ├── __init__.py             # gom router, khai báo /health
│   │   ├── document_controller.py  # POST /documents, GET /documents/{id}
│   │   ├── job_controller.py       # GET /jobs/{id}
│   │   ├── chat_controller.py      # POST /documents/{id}/chat (JSON + SSE)
│   │   └── export_controller.py    # GET /documents/{id}/export/docx
│   │
│   ├── models/                     # ==== MODEL ====
│   │   ├── __init__.py
│   │   ├── database.py             # engine, session, bảng Document/Job/Message
│   │   ├── document_model.py       # nghiệp vụ upload, trạng thái tài liệu/job
│   │   ├── chat_model.py           # nghiệp vụ chat: prompt, gọi LLM, lưu hội thoại
│   │   └── pipeline_model.py       # worker nền: gọi src/ (MinerU→DOCX→FAISS)
│   │
│   ├── views/                      # ==== VIEW ====
│   │   ├── __init__.py
│   │   └── schemas.py              # toàn bộ Pydantic request/response + SSE
│   │
│   └── core/
│       ├── __init__.py
│       ├── config.py                # đọc .env
│       ├── errors.py                # AppError + exception handler chuẩn
│       └── llm.py                   # none / qwen_local / ollama
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── test_api.py
│
├── data/.gitkeep                   # PDF, DOCX, SQLite, FAISS (không commit nội dung)
├── requirements-backend.txt
└── .env.example
```

Quy tắc phụ thuộc:
- `controllers/` chỉ gọi `models/` và dùng `views/schemas.py` để validate/định dạng — không chứa logic nghiệp vụ.
- `models/` không import `Request`/`Response` của FastAPI.
- Chỉ `models/pipeline_model.py` được import `src/` (pipeline gốc MinerU/DOCX/RAG).
- `views/schemas.py` chỉ mô tả dữ liệu, không gọi DB hay service.

### 1.2. Sơ đồ hoạt động tổng thể

Client gửi request tới Controller. Controller dùng View để validate/định dạng dữ liệu, gọi Model để xử lý nghiệp vụ. Model đọc/ghi dữ liệu ở ba nơi lưu trữ: SQLite (trạng thái tài liệu và job) (có thể đổi), thư mục `data/documents` (file PDF, DOCX) và chỉ mục FAISS (theo từng tài liệu).

```
                              +------------+
                              |   Client   |
                              +-----+------+
                                    |
                                    v
      +-----------------------+           schemas            +-------------------+
      |      Controllers      |<---------------------------> |       Views       |
      | (nhận request, gọi    |                              | (định dạng JSON,  |
      |  Model)               |                              |  SSE)             |
      +-----------+-----------+                              +-------------------+
                  |
                  v
      +-------------------------------------------------------+
      |                       Models                          |
      |   document_model, chat_model, pipeline_model          |
      +---------+------------------+------------------+-------+
                |                  |                  |
                v                  v                  v
        +--------------+  +-----------------+  +---------------+
        |    SQLite    |  |  data/documents |  |  FAISS index  |
        | documents,   |  |    pdf, docx    |  | theo từng     |
        | jobs         |  |                 |  | doc_id        |
        +--------------+  +-----------------+  +---------------+
```

### 1.3. Trạng thái xử lý tài liệu

```
[queued] --> [mineru_parsing] --> [building_docx] --> [indexing] --> [ready]
    |               |                    |                |
    +---------------+--------------------+----------------+
                                |
                                v
                           [failed]

(Bất kỳ bước nào cũng có thể rẽ sang "failed" nếu xử lý lỗi)
```

| `stage` (job) / `status` (document) | `progress` | Ý nghĩa |
|-------------------------------------|------------|-------------------------------------------------------|
| `queued`                            | 0          | Đã nhận file, chờ tới lượt (chỉ chạy 1 job cùng lúc)  |
| `mineru_parsing`                    | 5          | MinerU đang đọc PDF thành Markdown                    |
| `building_docx`                     | 40         | Đang tạo DOCX với công thức Equation                  |
| `indexing`                          | 65         | Đang chia đoạn, embedding, lập chỉ mục FAISS          |
| `ready`                             | 100        | Hoàn tất, có thể chat và tải DOCX                     |
| `failed`                            | giữ nguyên | Lỗi. Xem trường `error`, `stage` cho biết bước bị lỗi |

Khi server khởi động lại, mọi job đang `queued`/`running` bị đánh dấu `failed` (`SERVER_RESTARTED`) — người dùng cần upload lại.

### 1.4. Luồng upload tài liệu và xử lý nền

Request upload trả về ngay lập tức (202), việc xử lý PDF chạy trong luồng nền riêng (`ThreadPoolExecutor(max_workers=1)`), không chặn response.

```
Client
  |
  |  POST /documents (file PDF)
  v
document_controller.upload_document()
  |
  |  create_document(db, upload)
  v
document_model.create_document()
  |    input:  UploadFile
  |    output: (Document, Job) + lưu input.pdf
  |
  |  submit_pipeline(doc_id, job_id)
  v
pipeline_model.submit_pipeline()
  |
  |-----------------------------------> 202 {document_id, job_id} ----> Client
  |
  |  (chạy song song, KHÔNG chặn response)
  v
pipeline_model.run_pipeline()   [thread nền, 1 job/lần]
  |
  |-- run_mineru(pdf_path, mineru_dir)
  |       input:  PDF
  |       output: Markdown + ảnh
  |
  |-- prepare_work_md() + md_to_docx()
  |       input:  Markdown
  |       output: output.docx
  |
  |-- split_markdown_sections() + make_chunks() + build_index()
  |       input:  Markdown
  |       output: FAISS index + chunks
  |
  v
cập nhật Job.status = succeeded, Document.status = ready
```

### 1.5. Luồng chat với tài liệu (streaming, có "thinking")

Tài liệu phải ở trạng thái `ready`. Các sự kiện `thinking` là nhật ký tiến trình (phân tích câu hỏi, truy xuất, sinh câu trả lời) — không phải chain-of-thought thô của mô hình.

```
Client
  |
  |  POST /documents/{id}/chat {question, stream:true}
  v
chat_controller.chat()
  |
  |  ensure_ready(db, doc_id)
  v
chat_model.ensure_ready()
  |    output: Document, hoặc lỗi 404/409 nếu chưa "ready" --> dừng, trả lỗi cho Client
  |
  |  stream_events(doc_id, question, top_k)
  v
chat_model.stream_events()
  |
  |----> event "thinking": "Đang phân tích câu hỏi..."          ----> Client
  |
  |-- search(doc_id, question, top_k)
  |       input:  câu hỏi
  |       output: hits [{chunk_id, heading, score, text}, ...]
  |
  |----> event "thinking": "Tìm thấy N đoạn liên quan..."       ----> Client
  |
  |-- llm.stream(system_prompt, context + question)
  |       input:  prompt (ngữ cảnh + câu hỏi)
  |       output: từng token câu trả lời
  |
  |----> event "token" (lặp lại nhiều lần)                      ----> Client
  |----> event "citations" {items: [...]}                       ----> Client
  |
  |-- _save_messages()  ghi câu hỏi + câu trả lời vào bảng Message
  |
  |----> event "done" {answer, citations, thinking}             ----> Client
```

### 1.6. Bảng tra cứu hàm theo file

| Hàm                 | File                                 | Input                             | Output                                 |
|---------------------|--------------------------------------|-----------------------------------|----------------------------------------|
| `upload_document()` | `controllers/document_controller.py` | `UploadFile` (PDF)                | `202 DocumentCreated`                  |
| `create_document()` | `models/document_model.py`           | `db`, `UploadFile`                | `(Document, Job)` + lưu `input.pdf`    |
| `submit_pipeline()` | `models/pipeline_model.py`           | `document_id`, `job_id`           | chạy `run_pipeline()` nền              |
| `run_pipeline()`    | `models/pipeline_model.py`           | `document_id`, `job_id`         | `output.docx` + FAISS index, cập nhật DB |
| `get_job()`         | `controllers/job_controller.py`      | `job_id`                          | `JobOut`                               |
| `job_out()`         | `models/document_model.py`           | `db`, `job_id`                    | `JobOut {status, stage, progress}`     |
| `chat()`            | `controllers/chat_controller.py`     | `{question, top_k, stream}`       | JSON hoặc SSE                          |
| `ensure_ready()`    | `models/chat_model.py`               | `document_id`                     | `Document` hoặc lỗi 404/409            |
| `stream_events()`   | `models/chat_model.py`               | `document_id`, câu hỏi            | chuỗi `thinking/token/citations/done`  |
| `search()`          | `models/pipeline_model.py`           | `document_id`, câu hỏi, `top_k`   | list đoạn liên quan (có `score`)       |
| `llm.stream()`      | `core/llm.py`                        | system prompt, câu hỏi + ngữ cảnh | từng đoạn text                         |
| `export_docx()`     | `controllers/export_controller.py`   | `document_id`                     | file `.docx`                           |
| `get_docx()`        | `models/document_model.py`           | `db`, `document_id`               | đường dẫn file + tên tải xuống         |

### 1.7. Quyết định thiết kế

- **Job nền bằng `ThreadPoolExecutor(max_workers=1)`** + bảng `jobs`. MinerU rất nặng, chỉ chạy 1 job một lúc. Không cần Redis/Celery.
- **FAISS lưu theo từng tài liệu** (`data/documents/{id}/rag/`), nạp lười và cache trong bộ nhớ.
- **SQLite chế độ WAL** cho phép đọc trạng thái khi worker đang ghi. Đổi sang PostgreSQL chỉ cần đổi `DATABASE_URL`.
- **LLM đứng sau interface `LLMBackend`** (`none`, `qwen_local`, `ollama`) — đổi mô hình không ảnh hưởng API.
- **Lỗi thống nhất** `{error:{code,message,details}}` cho mọi endpoint.

### 1.8. Giới hạn hiện tại

- Chưa có xác thực/phân quyền — ai biết `document_id` cũng truy cập được.
- Lịch sử chat được lưu nhưng chưa đưa vào prompt của câu hỏi tiếp theo.
- Chưa có API liệt kê/xóa tài liệu.
- Job không hủy được, không tự chạy lại sau khi server restart.

---

## 2. API contract

- Base URL (dev): `http://localhost:8000`
- Swagger UI: `/docs` · ReDoc: `/redoc` · Schema: `/openapi.json`
- Không có tiền tố phiên bản (`v1`...). Dữ liệu vào/ra là JSON, trừ upload (`multipart/form-data`), chat stream (SSE) và export (file DOCX).

### 2.1. Luồng sử dụng

```
POST /documents ──► 202 {document_id, job_id}
        │
        ▼
GET /jobs/{job_id}   (poll 2–5 giây/lần) ──► status: succeeded
        │
        ▼
POST /documents/{id}/chat   ──► {answer, citations, thinking}
GET  /documents/{id}/export/docx ──► file .docx
```

### 2.2. Định dạng lỗi chung

#### ví dụ
```json
{ "error": { "code": "DOCUMENT_NOT_READY", "message": "…", "details": { "status": "indexing" } } }
```

| HTTP      | `code`                                             | Khi nào                                                               |
|-----------|----------------------------------------------------|-----------------------------------------------------------------------|
| 400       | `EMPTY_FILE`                                       | File upload rỗng                                                      |
| 404       | `DOCUMENT_NOT_FOUND`                               | Sai `document_id`                                                     |
| 404       | `JOB_NOT_FOUND`                                    | Sai `job_id`                                                          |
| 404 / 405 | `NOT_FOUND` / `METHOD_NOT_ALLOWED`                 | Sai đường dẫn / sai method                                            |
| 409       | `DOCUMENT_NOT_READY`                               | Chat hoặc export khi chưa `ready` (`details.status` là bước hiện tại) |
| 409       | `DOCUMENT_FAILED`                                  | Tài liệu xử lý thất bại                                               |
| 413       | `FILE_TOO_LARGE`                                   | Vượt `MAX_UPLOAD_MB` (mặc định 50)                                    |
| 415       | `INVALID_FILE_TYPE`                                | Không phải PDF hợp lệ                                                 |
| 422       | `VALIDATION_ERROR`                                 | Thiếu file, câu hỏi rỗng hoặc quá 2000 ký tự...                       |
| 500       | `INTERNAL_ERROR`, `CHAT_FAILED`, `INDEX_NOT_FOUND` | Lỗi hệ thống                                                          |
| 503       | `LLM_UNAVAILABLE`                                  | Không nạp hoặc không gọi được mô hình ngôn ngữ                        |

Mã lỗi pipeline thất bại (job/document): `PIPELINE_FAILED`, `EMPTY_MARKDOWN`, `DOCX_NOT_CREATED`, `NO_CHUNKS`, `SERVER_RESTARTED`.

### 2.3. `GET /health`

#### ví dụ 
```bash
curl http://localhost:8000/health
```
```json
{ "status": "ok", "database": "ok", "llm_backend": "none" }
```

### 2.4. `POST /documents` — upload PDF

`multipart/form-data`, trường `file` (PDF, tối đa `MAX_UPLOAD_MB`). Trả **202** ngay, xử lý chạy nền. Header `Location` trỏ tới job.

#### ví dụ 
```bash
curl -F "file=@input/bai_giang.pdf;type=application/pdf" http://localhost:8000/documents
```
```json
{
  "document_id": "3f2a9c1e5b7d4e0f9a1b2c3d4e5f6a7b",
  "job_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  "filename": "bai_giang.pdf",
  "status": "queued",
  "job_url": "/jobs/a1b2c3d4e5f60718293a4b5c6d7e8f90"
}
```
Lỗi: 400, 413, 415, 422.

### 2.5. `GET /documents/{document_id}`

#### ví dụ 
```bash
curl http://localhost:8000/documents/<document_id>
```
```json
{
  "id": "3f2a9c1e5b7d4e0f9a1b2c3d4e5f6a7b",
  "filename": "bai_giang.pdf",
  "status": "ready",
  "error": null,
  "num_sections": 12,
  "num_chunks": 87,
  "latest_job_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  "docx_available": true,
  "created_at": "2026-09-21T03:10:11.120000Z",
  "updated_at": "2026-09-21T03:14:52.900000Z"
}
```
Lỗi: 404.

### 2.6. `GET /jobs/{job_id}`

#### ví dụ 
```bash
curl http://localhost:8000/jobs/<job_id>
```
```json
{
  "id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  "document_id": "3f2a9c1e5b7d4e0f9a1b2c3d4e5f6a7b",
  "status": "running",
  "stage": "building_docx",
  "progress": 40,
  "error": null,
  "created_at": "2026-09-21T03:10:11.130000Z",
  "started_at": "2026-09-21T03:10:12.000000Z",
  "finished_at": null
}
```
Khi thất bại: `"status":"failed"`, `"stage"` giữ bước bị lỗi, `"error":{"code":"PIPELINE_FAILED","message":"…"}`. Lỗi: 404.

### 2.7. `POST /documents/{document_id}/chat`

#### ví dụ 
Body:

| Trường        | Kiểu                 | Mặc định    | Ghi chú                                                      |
|---------------|----------------------|-------------|--------------------------------------------------------------|
| `question`    | string, 1–2000 ký tự | (bắt buộc)  | Tự cắt khoảng trắng đầu/cuối                                 |
| `top_k`       | integer 1–20         | `TOP_K` (5) | Số đoạn truy xuất                                            |
| `stream`      | boolean              | `false`     | `true` (hoặc header `Accept: text/event-stream`) để nhận SSE |

Tài liệu phải ở trạng thái `ready`, nếu không trả 409.

**Chế độ JSON (mặc định):**

#### ví dụ 
```bash
curl -X POST http://localhost:8000/documents/<document_id>/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Định nghĩa đạo hàm là gì?"}'
```
```json
{
  "message_id": "9c8b7a6d5e4f30211203948576a1b2c3",
  "document_id": "3f2a9c1e5b7d4e0f9a1b2c3d4e5f6a7b",
  "answer": "Đạo hàm của f tại x0 là giới hạn của tỉ số … [1]",
  "citations": [
    { "index": 1, "chunk_id": 12, "heading": "Định nghĩa 1.2", "score": 0.8132,
      "snippet": "Đạo hàm của hàm số f tại x0 là giới hạn của tỉ số…" }
  ],
  "thinking": [
    { "step": "analyze",   "text": "Đang phân tích câu hỏi..." },
    { "step": "retrieve",  "text": "Đang tìm 5 đoạn liên quan trong tài liệu..." },
    { "step": "retrieved", "text": "Tìm thấy 5 đoạn liên quan: Định nghĩa 1.2, Ví dụ 1.3" },
    { "step": "generate",  "text": "Đang soạn câu trả lời bằng Ollama (qwen2.5:7b)..." }
  ]
}
```

**Chế độ stream (SSE):**

#### ví dụ 
```bash
curl -N -X POST http://localhost:8000/documents/<document_id>/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Định nghĩa đạo hàm là gì?","stream":true}'
```
```
event: thinking
data: {"step": "analyze", "text": "Đang phân tích câu hỏi..."}

event: token
data: {"text": "Đạo hàm của "}

event: citations
data: {"items": [{"index": 1, "chunk_id": 12, "heading": "Định nghĩa 1.2", "score": 0.8132, "snippet": "…"}]}

event: done
data: {"message_id": "…", "document_id": "…", "answer": "…", "citations": [...], "thinking": [...]}
```

| Sự kiện     | Dữ liệu                                                                    |
|-------------|----------------------------------------------------------------------------|
| `thinking`  | `{step, text}` với `step` ∈ `analyze`, `retrieve`, `retrieved`, `generate` |
| `token`     | `{text}`, từng đoạn câu trả lời, nối lại thành `answer`                    |
| `citations` | `{items: [Citation]}`                                                      |
| `done`      | Đối tượng giống response JSON, luôn là sự kiện cuối khi thành công         |
| `error`     | `{code, message}`, sự kiện cuối khi thất bại                               |

**Lưu ý cho frontend:** `EventSource` của trình duyệt chỉ hỗ trợ `GET`, endpoint này là `POST` — dùng `fetch` + đọc `response.body.getReader()`, hoặc thư viện `@microsoft/fetch-event-source`.

Lỗi trước khi bắt đầu stream (404, 409, 422) trả HTTP thường. Lỗi giữa chừng (`LLM_UNAVAILABLE`...) báo qua sự kiện `error`.

### 2.8. `GET /documents/{document_id}/export/docx`

```bash
curl -OJ http://localhost:8000/documents/<document_id>/export/docx
```
Trả file `.docx` (`Content-Disposition` là `<tên PDF>.docx`). Lỗi: 404, 409.

### 2.9. Cấu hình (`backend/.env`)

| Biến                         | Mặc định                               | Ý nghĩa                                               |
|------------------------------|----------------------------------------|-------------------------------------------------------|
| `DATABASE_URL`               | SQLite trong `backend/data/`           | Chuỗi kết nối SQLAlchemy                              |
| `DATA_DIR`                   | `backend/data`                         | Nơi lưu PDF, DOCX, index                              |
| `MAX_UPLOAD_MB`              | 50                                     | Giới hạn upload                                       |
| `TOP_K`                      | 5                                      | Số đoạn truy xuất mặc định                            |
| `LLM_BACKEND`                | `none`                                 | `none`, `qwen_local` hoặc `ollama`                    |
| `LLM_NAME`                   | rỗng                                   | Tên mô hình Qwen local, rỗng thì dùng `src/config.py` |
| `PRELOAD_LLM`                | false                                  | Nạp LLM khi khởi động                                 |
| `OLLAMA_URL`, `OLLAMA_MODEL` | `http://localhost:11434`, `qwen2.5:7b` | Cấu hình Ollama                                       |
| `CORS_ORIGINS`               | `["*"]`                                | Danh sách origin cho frontend                         |

---

## 3. Cách chạy

### 3.1. Yêu cầu môi trường

- Python **3.11 hoặc 3.12** (không dùng 3.13/3.14 — `torch`, `faiss-cpu` chưa có bản build sẵn)
- Pandoc đã cài trên máy (nếu không dùng Docker) — cần cho bước tạo DOCX: https://pandoc.org/installing.html
- (Tùy chọn) Docker Desktop

### 3.2. Cài đặt (không dùng Docker)

```bash
git clone <URL_repo>
cd DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026

python -m venv .venv
```

Kích hoạt venv — **Windows PowerShell:**
```powershell
.\.venv\Scripts\Activate.ps1
# Nếu báo lỗi "running scripts is disabled":
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```
**macOS / Linux:**
```bash
source .venv/bin/activate
```

Cài thư viện (bao gồm cả `requirements.txt` gốc nhờ `-r ../requirements.txt`):
```bash
pip install -r backend/requirements-backend.txt
```

Tạo file cấu hình:
```bash
# Windows
copy backend\.env.example backend\.env
# macOS/Linux
cp backend/.env.example backend/.env
```
Mặc định chạy được ngay với `LLM_BACKEND=none` (chat trả về đoạn trích, chưa cần GPU).

### 3.3. Chạy test (không cần MinerU/GPU)

```bash
python -m pytest backend/tests -q
```

### 3.4. Chạy server

```bash
python -m uvicorn backend.app.main:app --port 8000 --reload-dir backend/app --reload-dir src --reload
```

Mở **http://localhost:8000/docs** (Swagger UI).

> **Không dùng `--reload` trơn** (không kèm `--reload-dir`). Thư mục `backend/data/` thay đổi liên tục lúc xử lý PDF, sẽ làm server tự khởi động lại giữa chừng và làm hỏng job đang chạy.

### 3.5. Chạy bằng Docker (không cần cài Python/Pandoc)

```bash
docker compose up --build
```

API chạy ở `http://localhost:8000`. Dữ liệu lưu ở `backend/data/` trên máy host (đã mount volume), không mất khi tắt container.

Dùng Ollama kèm theo:
```bash
docker compose --profile ollama up
docker compose exec ollama ollama pull qwen2.5:7b
# đặt LLM_BACKEND=ollama trong backend/.env hoặc biến môi trường
```

### 3.6. Kiểm thử toàn luồng với PDF

```powershell
.\scripts\smoke_test.ps1 -Pdf input\ten_file.pdf
```
```bash
scripts/smoke_test.sh input/ten_file.pdf
```

Script upload PDF, theo dõi job đến khi xong, thử chat (JSON + SSE), và tải DOCX.

### 3.7. Lỗi thường gặp

| Lỗi                                             | Nguyên nhân                                       | Cách sửa                          |
|-------------------------------------------------|---------------------------------------------------|-----------------------------------|
| `pip install` lỗi biên dịch `torch`/`faiss-cpu` | Dùng Python 3.13+                                 | Cài lại bằng Python 3.11/3.12     |
| `ImportError: cannot import name ...`           | File thiếu dòng cuối khi copy                     | Đối chiếu lại nội dung file       |
| `ModuleNotFoundError: backend`                  | Chưa `cd` vào thư mục gốc dự án        | Chạy lệnh từ thư mục có `backend/` và `src/` |
| Server tự restart giữa lúc xử lý PDF            | Dùng `--reload` không kèm `--reload-dir`          | Dùng đúng lệnh ở mục 3.4          |
| `curl.exe` không nhận diện trên PowerShell      | PowerShell alias `curl` thành `Invoke-WebRequest` | Gõ `curl.exe` thay vì `curl`      |