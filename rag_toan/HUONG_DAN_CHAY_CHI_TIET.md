# HƯỚNG DẪN CHẠY CHI TIẾT — PDF Toán → MinerU → Word Equation + RAG

> Nguồn chuẩn: `notebooks/Math_PDF_MinerU_Word_Equation_RAG.ipynb`
> Core logic tách sẵn: `src/` + `main.py` (giữ nguyên model tốt nhất).
> Thời gian chạy: ~10 phút Colab lần đầu (cài lib), ~3–5 phút cho PDF 20 trang.

## 1. Làm gì trong 30 giây

1. Copy PDF toán vào `input/`
2. Chạy 1 lệnh: `python main.py --pdf input/<ten_file>.pdf --skip-llm`
3. Lấy Word ở `docx_output/`, knowledge base ở `rag_output/`

Không có finetune. Không sửa model. Cấu hình bên dưới là bản cho điểm cao nhất đã verify.

## 2. Luồng hệ thống

```text
PDF toán → MinerU → Markdown/JSON + Images
  ├─→ Pandoc → DOCX (Heading + Table + Equation OMML + Images)
  └─→ Chunk → E5 embedding → FAISS → Retriever → Qwen local
```

Nguyên tắc: Markdown/JSON của MinerU là nguồn chung. Không đọc ngược từ DOCX làm RAG.

## 3. Model tốt nhất (đừng đổi)

| Thành phần | Giá trị chuẩn | Vì sao |
|---|---|---|
| MinerU backend | `-b pipeline` | Ổn định trên Colab CPU, giữ công thức/table tốt nhất, ít crash hơn backend mặc định |
| Embedding | `intfloat/multilingual-e5-base` | Đa ngữ (Việt + Anh + LaTeX), prefix `passage:` / `query:` bắt buộc |
| LLM | `Qwen/Qwen2.5-3B-Instruct` | Local, miễn phí, vừa VRAM Colab GPU, đủ trả lời toán cơ bản |
| DOCX renderer | Pandoc `--from=markdown+tex_math_dollars+tex_math_single_backslash --standalone --toc` | Chuyển `$..$`, `$$..$$`, `\[..\]` thành Equation OMML thật, không phải text LaTeX |
| Chunk | `max_chars=1800, overlap=250`, cắt theo heading `#{1,6}` | Giữ ngữ cảnh section, mỗi chunk có `heading` |

Fix đã áp dụng so với bản nháp (không phải finetune):
- Chọn Markdown lớn nhất khi MinerU trả nhiều `.md` (tránh file phụ).
- Resolve ảnh tương đối → đường dẫn tuyệt đối + `--resource-path` cho Pandoc.
- Assert DOCX tồn tại và >0 bytes trước khi tiếp tục.

Fix Tuần 2 (Preprocessing, xem Weekly_Sprint_02.xlsx):
- Mỗi PDF chạy trong `runs/<ten>_<doc_id>/` riêng (doc_id = hash nội dung PDF) →
  không còn lấy nhầm output của PDF chạy trước đó khi chạy nhiều PDF liên tiếp.
- Chunk dựng từ `content_list.json` của MinerU (có page/section/loại block) thay vì
  chỉ Markdown; ảnh base64 bị lọc bỏ khi chuẩn hoá, không lọt vào chunk text nữa.
- Chunk theo BLOCK: công thức và bảng là đơn vị không bị chia, nên không còn công
  thức bị cắt đôi giữa 2 chunk. Mỗi chunk có metadata `source/page/section`.
- Retrieval chuyển từ FAISS thủ công sang LlamaIndex, trả kèm `score/source/page`.

## 4. Yêu cầu chạy

### Cách A — Colab (khuyến nghị, đúng notebook gốc)

- Runtime mới: `Runtime → Disconnect and delete runtime` nếu từng cài Docling/Pix2Text/Optimum nhiều bản.
- GPU: chỉ cần nếu chạy Qwen. Retrieval + DOCX chạy CPU được.
- Mở `notebooks/Math_PDF_MinerU_Word_Equation_RAG.ipynb` → `Runtime → Run all`.

Cài trong Colab:

```bash
!pip install -q "mineru[all]>=4.0,<5"
!pip install -q sentence-transformers faiss-cpu pypandoc transformers accelerate
!apt-get -qq update && !apt-get -qq install pandoc
!mineru-kit --help
!pandoc --version
```

### Cách B — Local macOS (máy bạn, pandoc 3.11 đã có)

```bash
python3 --version   # cần 3.10+
pandoc --version    # bạn đã có 3.11, đạt

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
brew install pandoc  # nếu thiếu (bạn đã có thì bỏ qua)
```

Nếu `pip install "mineru[all]"` nặng/thất bại trên Mac ARM: chạy MinerU trên Colab, copy `mineru_output/` về rồi chạy tiếp `main.py` local từ bước DOCX/RAG.

## 5. Chạy chi tiết

### 5.1. Chuẩn bị PDF

```bash
ls input/
# copy PDF vào, ví dụ:
cp "/Users/nhan/Downloads/02_MaNguon/*.pdf" input/  # tự chọn 1 file toán
```

Chỉ dùng 1 PDF/lần. Tên không dấu, không khoảng trắng để tránh lỗi Pandoc.

### 5.2. Chạy full pipeline (khuyến nghị test đầu)

```bash
source .venv/bin/activate
python main.py --pdf input/TOAN-BO-CONG-THUC-TOAN-CAP-3-full-www.MATHVN.com_.pdf --skip-llm
```

`--skip-llm` = bỏ Qwen, chỉ kiểm tra MinerU + DOCX + retrieval. Khi nào retrieval đúng mới bỏ flag để hỏi đáp.

Chạy có LLM:

```bash
python main.py --pdf input/<ten_file>.pdf
```

### 5.3. Chạy từng bước (debug)

```python
from pathlib import Path
from src.config import DOCX_DIR, RUNS_DIR, EMBED_MODEL
from src.run_mineru import run_mineru, find_mineru_outputs, find_content_list, prepare_run_dir
from src.build_docx import prepare_work_md, md_to_docx
from src.structured import load_raw, normalize_blocks, save_structured
from src.chunking import build_chunks
from src.llama_rag import build_index, chunks_to_nodes, retrieve

pdf = Path("input/<ten_file>.pdf")
doc_id, run_dir = prepare_run_dir(pdf, RUNS_DIR)          # run dir riêng cho PDF này
mineru_dir = run_dir / "mineru"
run_mineru(pdf, mineru_dir, tier="standard")  # dùng mineru-kit parse, không phải CLI cũ
md_path, _, _ = find_mineru_outputs(mineru_dir)
content_list_path = find_content_list(mineru_dir)
text = md_path.read_text(encoding="utf-8", errors="ignore")

work = DOCX_DIR / "test_for_docx.md"
prepare_work_md(text, md_path, work)
md_to_docx(work, DOCX_DIR / "test.docx", md_path.parent)

blocks = normalize_blocks(load_raw(content_list_path, md_path), pdf.name, doc_id)
save_structured(blocks, run_dir / "structured_data.json")
chunks = build_chunks(blocks)
index = build_index(chunks_to_nodes(chunks), EMBED_MODEL, run_dir / "index")
print(retrieve(index, "định nghĩa đạo hàm là gì?", top_k=5)[0])
```

## 6. Kiểm tra kết quả (bắt buộc)

```bash
ls -R mineru_output | head -n 30   # phải có .md + .json + images/
ls -lh docx_output/                # phải có .docx >0 bytes
ls -lh rag_output/                 # phải có index.faiss + chunks.json
```

Mở DOCX kiểm tra: Heading, Table, ảnh còn đủ, công thức là Equation (click sửa được) chứ không phải text `$...$`.

Check LaTeX trong Markdown:

```bash
grep -o -E '\\\\\(|\\\\\[|\\frac|\\int|\\sum|\$\$' mineru_output/**/*.md | sort | uniq -c
```

## 7. Lỗi thường gặp + fix

| Lỗi | Nguyên nhân | Fix |
|---|---|---|
| `Không tìm thấy Markdown` | MinerU crash / sai backend | Xem log cell MinerU, chạy lại với `-b pipeline`, dùng runtime mới |
| Pandoc `tạo DOCX thất bại` | Thiếu ảnh / path có dấu | Đặt PDF tên không dấu, giữ `--resource-path` là thư mục chứa `.md` |
| Công thức thành text `$..$` | Thiếu flag math | Giữ nguyên `PANDOC_FROM` trong `src/config.py` |
| `faiss` import lỗi | Chưa cài lib | `pip install faiss-cpu` trong đúng venv |
| Qwen OOM trên Colab | Hết VRAM/RAM | Thêm `--skip-llm`, chỉ dùng retrieval; hoặc Runtime GPU mới |
| MinerU chậm trên Mac ARM | Thiếu CUDA/pipeline nặng | Chạy MinerU trên Colab rồi copy output về |

## 8. Cấu trúc repo

```text
main.py                 # pipeline 1 lệnh
src/config.py           # model + chunk + backend chuẩn
src/run_mineru.py       # chạy MinerU theo run dir riêng từng PDF (doc_id = hash nội dung)
src/build_docx.py       # ảnh tuyệt đối + pandoc DOCX Equation
src/structured.py       # content_list.json MinerU -> structured_data.json (lọc base64)
src/chunking.py         # chunk theo BLOCK, công thức/bảng không bị cắt đôi
src/validate.py         # kiểm tra DoD: không base64, không cắt công thức, có page/source
src/llama_rag.py        # chunk -> TextNode -> LlamaIndex (E5) -> retrieve(score/source/page)
src/ask_rag.py          # Qwen local (optional), dùng LlamaIndex retriever
src/build_rag.py        # DEPRECATED — bản gốc giữ lại để đối chiếu trước/sau
tests/test_chunking.py  # test DoD trên dữ liệu giả lập MinerU
notebooks/...ipynb      # bản gốc Colab
input/                  # bỏ PDF vào đây
runs/<ten>_<doc_id>/    # output riêng từng PDF: mineru/, structured_data.json,
                        #   chunks.json, validation.json, index/
docx_output/
requirements.txt  HUONG_DAN_CHAY_CHI_TIET.md
```

## 9. Câu hỏi RAG mẫu

- `Hãy giải thích một định nghĩa quan trọng trong tài liệu.`
- `Công thức X được phát biểu thế nào? Giữ nguyên LaTeX.`
- Nếu context không đủ, hệ thống phải nói rõ thiếu thông tin, không bịa công thức.

---
Commit này: copy notebook gốc + tách core chuẩn + giữ nguyên model tốt nhất, không finetune thêm.
