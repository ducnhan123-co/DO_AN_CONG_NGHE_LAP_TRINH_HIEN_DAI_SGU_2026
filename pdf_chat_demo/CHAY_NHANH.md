# Chạy nhanh PDF Chat demo (server + UI)

Thư mục: `pdf_chat_demo/` trong repo đồ án (bản gốc trên máy: `~/Documents/01_CongViec/Projects/pdf_ui_sgu_demo`)

## 1. Bật (mở 2 tab terminal)

```bash
cd pdf_chat_demo

# Tab 1 — API (cổng 8001), chọn 1 trong 2:
RAG_ENGINE=li_e5 python3 server.py     # LlamaIndex + E5 (khuyến nghị, giống đồ án)
python3 server.py                      # bản cũ: qwen3-embedding + TF-IDF

# Tab 2 — giao diện (cổng 8080)
python3 -m http.server 8080
```

Mở trình duyệt: http://localhost:8080/index.html → "Tải lên PDF" → tự mở trang đọc + chat.
Sửa HTML xong thì bấm **Cmd+Shift+R** để tải lại.

Yêu cầu: Ollama đang chạy (`ollama serve` hoặc app Ollama), có sẵn model:
```bash
ollama pull qwen3:8b && ollama pull qwen3-embedding:0.6b   # qwen3:14b, qwen2.5:1.5b tuỳ chọn
```

## 2. Kiểm tra đang chạy chưa

```bash
curl -s 127.0.0.1:8001/api/health      # "ok": true, "rag_engine": ...
lsof -iTCP:8001 -iTCP:8080 -sTCP:LISTEN -nP
```

## 3. Tắt / chạy lại server (sau khi sửa server.py)

```bash
kill $(lsof -tiTCP:8001 -sTCP:LISTEN)                      # tắt API
RAG_ENGINE=li_e5 nohup python3 -u server.py > server.log 2>&1 &   # chạy nền, log ra server.log
tail -f server.log                                           # xem log (MinerU chạy xong sẽ in [MinerU] ...)
kill $(lsof -tiTCP:8080 -sTCP:LISTEN)                      # tắt UI nếu cần
```

## 4. Tuỳ chọn

| Biến môi trường | Ý nghĩa |
|---|---|
| `RAG_ENGINE=custom` (mặc định) / `li_e5` / `li_fusion_e5` / `li_qwen` / `li_fusion` | bộ tìm đoạn (xem `li_rag.py`) |
| `MINERU_BIN=/path/.venv/bin/mineru-kit` | chỗ cài MinerU 4.x; mặc định `~/Documents/00_Inbox/src_update_fixed/.venv/bin/mineru-kit`. Không có thì chỉ dùng pypdf |

## 5. Lưu ý

- Upload xong chat được ngay (pypdf); dòng dưới tên file hiện "⏳ MinerU đang phân tích công thức…", ~30–45s/10 trang sau đổi thành "✓ công thức LaTeX (MinerU)".
- Tài liệu lưu ở `data/<doc_id>.pdf` + `.json` → restart server không mất. File upload trước khi có MinerU thì upload lại để có công thức chuẩn.
- `li_e5`: lần hỏi đầu chậm thêm ~10s (nạp E5), RAM server ~380 MB.
- Model 14B chậm (~30–50s/câu dài); 8B ~5–10s.
