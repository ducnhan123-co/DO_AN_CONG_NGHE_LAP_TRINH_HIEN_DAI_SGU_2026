# Backend PDF → Word (MVC) nối `rag_toan` với `frontend`

```
projects/
├── rag_toan/     lõi - backend import trực tiếp src/*
├── frontend/     giao diện - gọi /api/...
└── backend/      thư mục này
```

## Chạy nhanh

```bash
cd backend
pip install -r requirements.txt -r requirements-mineru.txt   # + pandoc, tesseract ở mức hệ điều hành
python backend/run.py            # mở http://127.0.0.1:8000  (backend phục vụ luôn frontend, khớp frontend/config.js)
```

Dev không có model MinerU: `MINERU_CMD="python tests/fake_mineru_kit.py" python run.py`
Test: `pip install -r requirements-dev.txt && pytest -q tests`

> **Dùng 1 process duy nhất** (không `--workers N` của uvicorn): hàng đợi + worker nằm trong process.
> **`app.db` cũ**: nếu `data/app.db` là của backend phiên bản trước, server sẽ báo lỗi và yêu cầu đổi tên/xóa nó (schema khác).

## Kiến trúc MVC

| Lớp | Thư mục | Vai trò |
|---|---|---|
| **Model** | `app/models` | `database.py` (SQLite WAL), `entities.py` (Document, LibraryEntry), `document_repository.py` (mọi SQL) |
| **View** | `app/views` | biến Model → JSON đúng trường frontend đọc (`document_view.py`, `system_view.py`) |
| **Controller** | `app/controllers` | route `/api/...`, chỉ điều phối, không xử lý PDF |
| **Service** | `app/services` | `pipeline.py` (luồng main.py), `mineru_runner.py`, `scheduler.py` (hàng đợi), `upload_service.py`, `storage.py` (bố cục data/), `engine.py` (cầu nối rag_toan), `docx_validator.py`, `rag_service.py` |
| Core | `app/core` | cấu hình, lỗi, container, proxy log |

## Pipeline = `main.py`, chia bước để giao diện theo dõi được

| main.py | Backend | status (frontend) | % |
|---|---|---|---|
| `prepare_run_dir`, `plan_strips`, `build_strips_pdf` | `documents/<id>/`, như cũ | parsing | 2 |
| `run_mineru_parallel` | `MineruRunner` (Popen: **hủy được**, tiến độ/RAM từng phần) | parsing | 2–70 |
| ghép phần | `merge_parts` | merging | 70–75 |
| `fix_legacy_tex_bf`, `prepare_work_md` | như cũ → `work.md` | preparing | 75–82 |
| `md_to_docx`, cột/khung | như cũ → `docx_output/<id>.docx` (file tạm rồi đổi tên) | building | 82–92 |
| — | `validate_docx` (đếm Equation/ảnh/bảng) | validating | 92–97 |
| structured → chunks → validation | tùy chọn; chỉ chạy nếu các module tương ứng còn trong `rag_toan/src` | validating | 97–99 |
| LlamaIndex | tùy chọn `RAG_INDEX=1` | | |

Giữ nguyên mặc định của main.py: 2 tiến trình MinerU, stagger 20 s, profile `auto`, tier `advanced`, resume (phần `.done` được bỏ qua).

## Bố cục `data/`

```
data/
├── app.db
├── input/<id>.pdf
├── docx_output/<id>.docx
└── documents/<id>/        (id = sha1 nội dung[:10], như doc_id của rag_toan; không còn runs/)
    ├── logs/ (pipeline.log, mineru_part_k.log)
    ├── mineru/  mineru_parts/
    ├── work.md  structured_data.json  chunks.json  validation.json
    └── index/ (tùy chọn)
```

Giao diện sửa → dữ liệu đổi ngay: tải lên (tạo `input/` + `documents/<id>`), hủy (kill MinerU), thử lại (tiếp tục từ chỗ dở; `?force=true` chạy lại cả MinerU), đổi tên, **xóa (xóa thật file trong data/** khi không còn ai dùng tài liệu đó).
Mỗi trình duyệt (`X-Client-Id`) có thư viện riêng; PDF giống hệt đã xử lý thì dùng lại kết quả (`cache_hit`).

## Bố cục cột

Backend xử lý cột theo `rag_toan/main.py`: tài liệu có khung phân cột có thể dùng `plan_strips`; các tài liệu khác dùng `layout_of`/section-column hiện có để giữ bố cục gốc trong Word. Giao diện và API không còn chế độ tách từng cột PDF thành các dải riêng nhằm ép đầu ra thành một cột.

## API (khớp frontend)

`GET /api/health` · `GET /api/system/stats` · `GET|POST /api/documents` · `GET|PATCH|DELETE /api/documents/{id}` ·
`POST …/cancel` · `POST …/retry` · `GET …/docx` · `GET …/pdf` ·
thêm: `GET …/artifacts[/{name}]`, `GET …/log`, `POST …/search` (RAG). Tài liệu Swagger: `/api/docs`.

## Đóng gói và  triển khai nhanh

### Đóng gói
docker build -f backend/Dockerfile -t pdf2docx .
docker run -d -p 8000:8000 -v "$(pwd)/backend/data:/app/backend/data" --name pdf2docx pdf2docx

### dùng compose để triển khai
```bash
cp .env.example .env
docker compose up -d --build      # từ thư mục backend/
```
Image gồm Python + Pandoc + Tesseract + MinerU + model tải sẵn lúc build (người dùng đầu không phải đợi), `data/` mount ra ngoài. Frontend được phục vụ cùng cổng 8000 nên 1 URL là đủ.
Để máy nhẹ hơn: `MINERU_EXTRA_ARGS=--remote --api-key …` (dùng dịch vụ mineru.net, bỏ phần model nặng).

## Giới hạn đã biết

- **Chưa chạy với MinerU thật hoàn chỉnh**: sandbox không tải được model. Đã kiểm thử bằng `fake_mineru_kit` + Pandoc/rag_toan thật, và với `mineru-kit` thật tới bước khởi chạy/hủy. Tier `advanced` có thể cần model riêng → xem `mineru-kit models show`; bước tải model trong Dockerfile **chưa kiểm thử**.
- **Tiến độ MinerU là ước lượng theo thời gian** (mineru-kit không báo %), tự học giây/trang sau mỗi lần chạy; tối đa 95% tới khi xong.
- `GET …/docx` và `…/pdf` không cần `X-Client-Id` (vì dùng `<a href>`/`<iframe>`); ai biết `id` (10 hex) đều tải được. Frontend chưa có đăng nhập; khi mở Internet nên đặt sau xác thực (reverse proxy/SSO) hoặc thêm link ký (signed URL).
- RAG (`RAG_INDEX=1`, `/search`) và `--remote` **chưa kiểm thử** (thiếu torch/model/key). Chưa có bước LLM Qwen (frontend chưa có màn hỏi đáp).
- Chưa có dọn dẹp dữ liệu tự động theo thời gian; ổ đĩa tăng dần cho tới khi người dùng bấm Xóa.
- Server bị kill cứng (`kill -9`) có thể để lại tiến trình `mineru-kit` mồ côi; khởi động lại sẽ tự chạy tiếp tài liệu dở.