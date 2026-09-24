# PDF Chat demo — đọc PDF gốc + chat với model local (MinerU + Ollama)

- `index.html`: thư viện, upload PDF → tự mở trang đọc.
- `reader.html`: bên trái PDF gốc (PDF.js, bôi đen/copy được), bên phải chat; công thức vẽ bằng KaTeX, bấm `[số trang]` để nhảy trang.
- `server.py`: FastAPI (cổng 8001). Upload → pypdf/OCR (chat được ngay) → MinerU 4.x chạy nền thay bằng text có LaTeX chuẩn → retrieval hybrid (qwen3-embedding + TF-IDF) → Ollama qwen3 trả lời kèm trang, có lịch sử hội thoại.
- `li_rag.py`: bộ tìm đoạn bằng LlamaIndex (tuỳ chọn, bật bằng `RAG_ENGINE`).
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

## Tuỳ chọn LlamaIndex (`RAG_ENGINE`)

```bash
python3 server.py                          # mặc định: custom (qwen3-embedding + TF-IDF)
RAG_ENGINE=li_e5 python3 server.py         # LlamaIndex VectorStoreIndex + multilingual-e5-base (giống đồ án)
RAG_ENGINE=li_fusion_e5 python3 server.py  # E5 + BM25 (QueryFusionRetriever)
```

Chỉ thay BỘ TÌM ĐOẠN; phần hỏi "trang N", đếm công thức, lịch sử hội thoại, MinerU giữ nguyên.

### Benchmark tìm đoạn (LSTM 10 trang, MinerU, 23 chunk, 16 câu hỏi tiếng Việt — `bench/qset.py`)
Trúng = chunk trả về chứa đúng câu gốc của đáp án.

| Bộ tìm đoạn | Hit@1 | Hit@3 | Hit@5 | MRR | ms/truy vấn | Tạo index |
|---|---|---|---|---|---|---|
| custom (qwen3-emb + TF-IDF) — mặc định | 12/16 | 14/16 | 15/16 | 0.81 | ~89 | 2.4s |
| li_qwen (LlamaIndex, qwen3-emb) | 7/16 | 14/16 | 14/16 | 0.64 | ~89 | 1.6s |
| li_fusion (qwen3-emb + BM25) | 9/16 | 14/16 | 16/16 | 0.74 | ~89 | 1.6s |
| **li_e5 (LlamaIndex + E5, như đồ án)** | **13/16** | **16/16** | **16/16** | **0.90** | **~9–22** | 0.7s (+~10s nạp model lần đầu) |
| li_fusion_e5 (E5 + BM25) | 12/16 | 16/16 | 16/16 | 0.86 | ~8 | 0.8s |
| custom nhưng dùng E5 | 12/16 | 15/16 | 16/16 | 0.86 | ~8 | — |

Chạy 2 lần: thứ hạng giống hệt (retrieval ổn định, tất định).

### End-to-end (qwen3:8b, 16 câu, chấm tay các câu lệch)
- custom: 14 đúng, 1 đúng một phần, 1 sai (không tìm ra đoạn chứa công thức tín hiệu lỗi unit ẩn).
- li_e5: 15 đúng, 1 đúng một phần. Tổng thời gian LLM ~ như nhau (121s vs 125s / 16 câu) — tốc độ do LLM quyết định, không do framework.
- RAM server: ~35 MB (custom) → ~380 MB (li_e5, nạp torch + E5).

**Kết luận:** thứ tạo khác biệt là MODEL EMBEDDING (E5-base > qwen3-embedding 0.6B ở đây), không phải bản thân LlamaIndex (li_qwen còn kém custom). Mẫu nhỏ (1 tài liệu tiếng Anh, 16 câu): chênh 1 câu nằm trong sai số; cần thêm PDF tiếng Việt để kết luận chắc.
