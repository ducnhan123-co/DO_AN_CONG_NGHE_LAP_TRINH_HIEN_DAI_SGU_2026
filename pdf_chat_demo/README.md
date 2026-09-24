# PDF Chat demo — đọc PDF gốc + chat với model local (MinerU + Ollama)

- `index.html`: thư viện, upload PDF → tự mở trang đọc.
- `reader.html`: bên trái PDF gốc (PDF.js, bôi đen/copy được), bên phải chat; công thức vẽ bằng KaTeX, bấm `[số trang]` để nhảy trang.
- `server.py`: FastAPI (cổng 8001). Upload → pypdf/OCR (chat được ngay) → MinerU 4.x chạy nền thay bằng text có LaTeX chuẩn → retrieval hybrid (qwen3-embedding + TF-IDF) → Ollama qwen3 trả lời kèm trang, có lịch sử hội thoại.
- `latex_norm.py`: chép từ `src_update_fixed_new/src/latex_norm.py` (chuẩn hoá LaTeX của MinerU).

## Chạy

```bash
pip install -r requirements.txt           # + tesseract (brew) nếu cần OCR PDF scan
ollama pull qwen3:8b && ollama pull qwen3-embedding:0.6b   # qwen3:14b / qwen2.5:1.5b tuỳ chọn
python3 server.py                         # API http://127.0.0.1:8001
python3 -m http.server 8080               # mở http://localhost:8080/index.html
```

MinerU 4.x nên cài venv riêng (kéo torch), rồi trỏ tới nó:
`MINERU_BIN=/path/to/.venv/bin/mineru-kit python3 server.py`. Không có MinerU thì vẫn chạy bằng pypdf.

## Benchmark nhỏ (LSTM.pdf 10 trang đầu, qwen3:8b, 4 câu hỏi công thức có đáp án)

| | pypdf | MinerU (standard) |
|---|---|---|
| Thời gian trích 10 trang | ~0s | ~30s (chạy nền) |
| Công thức KaTeX vẽ được (trích xuất) | không có LaTeX | 29/29 display, 88/88 inline |
| Trang chứa đáp án xếp hạng 1 | 2/4 | 4/4 |
| Trả lời đúng + trích dẫn đúng trang | 4/4 | 4/4 |
| Công thức trong câu trả lời KaTeX vẽ được | 0/2 | 6/6 |

Mẫu nhỏ (1 bài, 4 câu); KaTeX parse được ≠ công thức đúng ngữ nghĩa (MinerU vẫn nhầm vài ký hiệu inline, vd `n`→`\pi`).
