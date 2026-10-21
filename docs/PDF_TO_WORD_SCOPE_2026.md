# Phạm vi đồ án SGU 2026 — PDF → Word

**Chỉ thực hiện:** chuyển PDF toán học sang Word, công thức Word Equation (OMML), bảng, ảnh, bố cục khó, scan mờ/nhòe. **Không thực hiện:** hỏi đáp, LlamaIndex/RAG, chatbot, embedding hay vector database.

## Luồng chính
PDF upload → kiểm tra → phân biệt PDF chữ/scan → MinerU + OCR/layout → Markdown/structured JSON → chuẩn hoá LaTeX/bảng/ảnh → Pandoc DOCX Equation → kiểm tra OOXML & so sánh render → tải DOCX.

## Giữ và phát triển
- `llm/src/run_mineru.py`: parser adapter, cache theo hash.
- `llm/src/build_docx.py`: normalization, tables, images, OMML và tạo DOCX.
- `llm/src/layout.py`: sửa bố cục cột, section, khổ trang theo bbox (đang có file **untracked** ở local).
- `pdf_to_word.py`: entrypoint **conversion-only**, tách khỏi RAG/chat.
- `tests/test_build_docx_fixes.py` và `tests/test_layout.py`: 14 passed / 5 warnings trên Mac ngày 15/10/2026, chỉ là unit/module tests.

## Legacy cần tháo dỡ sau khi API/UI mới vượt qua E2E
`llm/src/llama_rag.py`, `ask_rag.py`, `build_rag.py`, phần chunk/embedding không dùng, `backend/app/core/llm.py`, các chat controllers, chat frontend, preload model và `main.py` cũ. Không xoá nóng nếu còn import/caller: kiểm tra dependency và migration trước.

## Ưu tiên
| Mức | Việc | Bằng chứng nghiệm thu |
|---|---|---|
| P0 | API/frontend chỉ upload → job → download | Không phải bật Ollama; tải Word được |
| P0 | Xuất OMML, không tạo DOCX dở dang | XML có m:oMath, file Word mở được |
| P0 | Thử >=3 PDF thật và smoke E2E | Có PDF + DOCX + log + ảnh đối chiếu |
| P1 | Cột, bảng gộp ô và hình ảnh | Có render-diff và test giữ thứ tự |
| P1 | Ảnh mờ/nhòe/scan, fallback + cảnh báo | Có ground truth; CER/symbol error |
| P2 | Benchmark 10 loại PDF | Ghi rõ model version, phần cứng, số liệu |

## Chú ý
- Không tuyên bố nhận dạng chính xác 100% hoặc “mọi công thức”.
- `layout.py`, `build_docx.py` đang có thay đổi local chưa commit; **không reset --hard**, không ghi đè.
- Bản báo cáo Word cập nhật được cung cấp riêng trong cuộc trò chuyện.
- PyMuPDF: https://pymupdf.readthedocs.io/en/latest/
- MinerU: https://github.com/opendatalab/MinerU
- Pandoc: https://pandoc.org/MANUAL.html
- Office Math: https://learn.microsoft.com/en-us/office/math/
