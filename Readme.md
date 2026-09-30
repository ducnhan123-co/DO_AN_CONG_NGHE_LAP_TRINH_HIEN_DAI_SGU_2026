# SGU PDF RAG — bản tích hợp đầu tiên

PDF toán được xử lý theo một luồng duy nhất: upload → pypdf/OCR để chat ngay → MinerU nền cho công thức LaTex → hybrid Ollama embedding + TF-IDF RAG → Qwen local stream. Sơ đồ tham chiếu: [kiến trúc tổng thể](https://ducnhan123-co.github.io/DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026/diagrams/01-kien-truc-tong-the.html).

```text
frontend/     MatchPDF: upload, PDF reader và chat streaming
backend/      FastAPI: xác thực upload, CORS và API /api/*
llm/          MinerU, OCR, embedding/RAG và Ollama Qwen (`llm/matchpdf.py`)
main.py       CLI chạy toàn bộ pipeline cho một PDF
docs/         tài liệu và sơ đồ đã công bố
```

Mỗi PDF có run directory theo hash nội dung nên không lấy nhầm output cũ. Dữ liệu upload, model cache, chỉ mục và DOCX sinh ra nằm ngoài Git.

## Chạy local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
ollama serve  # nếu Ollama app chưa chạy
uvicorn backend.app.main:app --reload --port 8001
python3 -m http.server 8080 --directory frontend
```

Mở `http://127.0.0.1:8080`. Cần có các model `qwen3:8b` và `qwen3-embedding:0.6b`; API `/api/health` phải trả về `"ok": true`. Với PDF scan, `llm/ocr.py` fallback qua Tesseract (`vie+eng`); MinerU chạy nền nên chat được ngay bằng bản đọc nhanh.

## Deploy

Push `main` kích hoạt `.github/workflows/deploy-pages.yml` để deploy `frontend/` lên GitHub Pages. Backend và Ollama phải chạy ở một host Python riêng; trước khi deploy frontend, đặt `frontend/config.js` thành URL HTTPS của host đó và thêm domain GitHub Pages vào `CORS_ORIGINS`. GitHub Pages không thể gọi Ollama đang chạy trên máy cá nhân của người xem.

Chi tiết CLI và mô hình: `HUONG_DAN_CHAY_CHI_TIET.md`.
