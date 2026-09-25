# Cấu trúc dự án — PDF Toán → Word (Equation thật) → RAG

Pipeline: **PDF → MinerU (OCR) → Markdown → DOCX (công thức thật) + Structured data → Chunk → LlamaIndex (RAG) → (tuỳ chọn) Qwen trả lời**.

## Cây thư mục

```
rag_toan/
├── main.py                  # Điểm chạy chính, nối toàn bộ pipeline lại
├── requirements.txt         # Danh sách thư viện cần cài
├── Readme.md                 # Giới thiệu ngắn
├── HUONG_DAN_CHAY_CHI_TIET.md# Hướng dẫn chạy từng bước chi tiết
│
├── input/                   # PDF gốc bỏ vào đây để xử lý
│   └── *.pdf
│
├── docx_output/             # Kết quả DOCX cuối cùng (đã có công thức + số trang)
│   ├── *.docx
│   └── *_for_docx.md        # Markdown trung gian, đã gắn path ảnh, dùng để Pandoc render DOCX
│
├── runs/                    # Dữ liệu trung gian, MỖI PDF một thư mục riêng (theo doc_id)
│   └── <ten_file>_<doc_id>/
│       ├── mineru/           # Output thô của MinerU: Markdown + JSON + ảnh
│       ├── structured_data.json  # Toàn bộ nội dung đã chuẩn hoá theo block (heading/text/formula/table/...)
│       ├── chunks.json       # Các đoạn (chunk) đã cắt để đưa vào RAG
│       ├── validation.json   # Báo cáo kiểm tra chất lượng chunk (DoD)
│       └── index/            # Vector index (LlamaIndex) để tìm kiếm ngữ nghĩa
│
├── src/                      # Toàn bộ logic xử lý, chia theo từng bước
│   ├── config.py              # Cấu hình chung: đường dẫn, tên model embedding/LLM, tham số chunk
│   ├── run_mineru.py          # Bước 1: chạy MinerU để OCR PDF -> Markdown/JSON/ảnh, quản lý run dir riêng từng PDF
│   ├── build_docx.py          # Bước 2: Markdown -> DOCX qua Pandoc (giữ công thức OMML thật), tự đánh số trang
│   ├── structured.py          # Bước 3: gom nội dung MinerU thành các "block" chuẩn (có page, section, loại nội dung)
│   ├── chunking.py            # Bước 4: cắt block thành chunk cho RAG, không cắt đôi công thức/bảng
│   ├── validate.py            # Bước 5: kiểm tra chunk có lỗi không (base64 lọt vào, công thức lệch dấu $, thiếu page...)
│   ├── llama_rag.py           # Bước 6: build vector index (LlamaIndex + E5) và truy vấn (retrieval)
│   ├── ask_rag.py             # Bước 7 (tuỳ chọn): dùng Qwen2.5-3B trả lời câu hỏi dựa trên các chunk truy hồi được
│   └── __init__.py
│
└── tests/
    └── test_chunking.py       # Test cho logic cắt chunk
```

## Từng phần làm được gì

| File / thư mục | Chức năng |
|---|---|
| `main.py` | Chạy toàn bộ pipeline từ 1 lệnh: nhận PDF đầu vào, gọi lần lượt MinerU → DOCX → structured data → chunk → index → (tuỳ chọn) hỏi Qwen. In ra đường dẫn tất cả file kết quả ở cuối. |
| `src/config.py` | Nơi đổi cấu hình: model embedding (`multilingual-e5-base`), model LLM (`Qwen2.5-3B-Instruct`), số ký tự tối đa/overlap khi chunk, các thư mục input/output. |
| `src/run_mineru.py` | Chạy MinerU để đọc PDF (kể cả PDF scan/ảnh) ra Markdown + JSON có toạ độ, công thức, bảng. Mỗi PDF có `doc_id` riêng (hash theo nội dung file) để không lẫn dữ liệu giữa các lần chạy khác nhau. |
| `src/build_docx.py` | Chuyển Markdown sang file Word thật (`.docx`) bằng Pandoc, công thức toán hiển thị dạng Equation có thể sửa được trong Word (không phải ảnh). Tự động chèn số trang vào chân trang mỗi file. |
| `src/structured.py` | Đọc dữ liệu thô MinerU, chuẩn hoá thành danh sách "block" (mỗi đoạn văn/công thức/bảng/heading là 1 block, có số trang, mục lục, loại nội dung), lọc bỏ ảnh base64 rác. |
| `src/chunking.py` | Gộp các block thành từng "chunk" vừa đủ dài để đưa vào mô hình embedding, đảm bảo công thức/bảng không bị cắt làm đôi giữa 2 chunk. |
| `src/validate.py` | Rà lại toàn bộ chunk: có sót ảnh base64 không, công thức có bị lệch dấu `$`/`$$` không, có thiếu số trang/nguồn không — xuất báo cáo `validation.json`. |
| `src/llama_rag.py` | Biến các chunk thành vector (embedding E5), lưu vào chỉ mục LlamaIndex; cho phép tìm các đoạn liên quan nhất tới 1 câu hỏi, kèm điểm số, trang, mục. |
| `src/ask_rag.py` | Dùng LLM Qwen2.5-3B (chạy local, không cần API trả phí) để trả lời câu hỏi dựa trên các đoạn tìm được ở trên (RAG). Có thể bỏ qua bước này bằng cờ `--skip-llm`. |
| `input/` | Nơi để các file PDF cần xử lý. |
| `docx_output/` | File Word thành phẩm — đây là thứ người dùng cuối cần: có công thức thật + số trang. |
| `runs/<ten>_<doc_id>/` | Toàn bộ dữ liệu trung gian và index tìm kiếm cho từng PDF, tách riêng để chạy nhiều file không đè lên nhau. |

## Cách chạy

```bash
# Chỉ cần DOCX + chỉ mục tìm kiếm, không cần LLM trả lời
python main.py --pdf input/bai_giang.pdf --skip-llm

# Chạy đầy đủ, có Qwen trả lời câu hỏi mẫu
python main.py --pdf input/bai_giang.pdf

# Ép chạy lại MinerU dù đã có kết quả cũ trong runs/
python main.py --pdf input/bai_giang.pdf --force
```

Kết quả cuối: file Word trong `docx_output/` (có công thức + số trang), và chỉ mục RAG trong `runs/<ten>_<doc_id>/index/` để hỏi đáp trên nội dung PDF.
