# SGU PDF RAG — bản tích hợp đầu tiên

PDF toán được xử lý theo một luồng duy nhất: MinerU 4 → chuẩn hoá VNI/LaTex → structured blocks → chunk không cắt công thức → E5/LlamaIndex RAG → Qwen tùy chọn. Sơ đồ tham chiếu: [kiến trúc tổng thể](https://ducnhan123-co.github.io/DO_AN_CONG_NGHE_LAP_TRINH_HIEN_DAI_SGU_2026/diagrams/01-kien-truc-tong-the.html).

```text
frontend/     giao diện tĩnh; chỉ gọi REST API
backend/      FastAPI: upload, trạng thái job, hỏi đáp; không chứa model logic
llm/          MinerU, OCR fallback, chuẩn hoá, structured/chunk/RAG/Qwen
main.py       CLI chạy toàn bộ pipeline cho một PDF
docs/         tài liệu và sơ đồ đã công bố
```

Mỗi PDF có run directory theo hash nội dung nên không lấy nhầm output cũ. Dữ liệu upload, model cache, chỉ mục và DOCX sinh ra nằm ngoài Git.

## Chạy local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
python main.py --pdf input/<file>.pdf --skip-llm

# Hoặc chạy web: mở hai terminal
uvicorn backend.app.main:app --reload --port 8000
python3 -m http.server 5173 --directory frontend
```

Mở `http://127.0.0.1:5173`. Bật `ENABLE_LOCAL_LLM=1` trước khi chạy API nếu máy có đủ RAM/VRAM cho Qwen. Với PDF scan, `llm/ocr.py` fallback qua Tesseract (`vie+eng`); MinerU vẫn là parser chuẩn.

## Deploy

Push `main` kích hoạt `.github/workflows/deploy-pages.yml` để deploy `frontend/` lên GitHub Pages. Backend phải chạy ở một host Python/Docker riêng; trước khi deploy frontend, đặt `frontend/config.js` thành URL API HTTPS và thêm domain đó vào `CORS_ORIGINS` của backend. Không đưa `CORS_ORIGINS=*` hoặc dữ liệu PDF lên production.

Chi tiết CLI và mô hình: `HUONG_DAN_CHAY_CHI_TIET.md`.
