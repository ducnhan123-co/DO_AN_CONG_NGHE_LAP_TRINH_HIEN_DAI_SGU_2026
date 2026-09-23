# Ở thư mục gốc
## Sử dụng môi trường ảo nếu cần
.venv\Scripts\Activate.ps1

## Cài thư viện
pip install -r backend/requirements-backend.txt

## Test backend nếu muốn
python -m pytest backend/tests -q

## Chạy server
python -m uvicorn backend.app.main:app --port 8000 --reload-dir backend/app --reload-dir src --reload

## Chạy bằng Docker
docker compose up --build

# Cấu trúc
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
├── data/.gitkeep
├── requirements-backend.txt
└── .env.example

Quy tắc phụ thuộc:
- controllers/ chỉ gọi models/ và dùng views/schemas.py — không chứa logic nghiệp vụ.
- models/ không biết gì về HTTP (không import Request/Response).
- Chỉ models/pipeline_model.py được import src/ (pipeline gốc MinerU/DOCX/RAG).