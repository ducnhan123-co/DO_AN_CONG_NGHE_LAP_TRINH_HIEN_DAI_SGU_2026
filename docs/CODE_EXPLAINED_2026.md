# Giải thích code PDF → Word (bản 2026)

Tài liệu này trích code thật trong repo và giải thích cách pipeline hoạt động. Mọi số liệu
"đã kiểm chứng" đều ghi kèm lệnh và môi trường; phần chưa chạy thật được ghi rõ là chưa kiểm chứng.

## 0. Môi trường kiểm chứng

- macOS (darwin), Python 3.13.14, Pandoc 3.11.
- Ngày chạy: 2026-10-23.
- Đã chạy: `python3 -m pytest tests/test_metrics.py tests/test_build_docx_fixes.py -q`
  → 22 passed (gồm 8 test metrics và 14 test build_docx, trong đó có test mới cho bảng-công thức
  và công thức display không có ảnh MinerU).
- Chưa chạy end-to-end trên toàn bộ 40 tài liệu mẫu trong một lần; các kết luận về độ chính xác
  nội dung vẫn cần ground truth.

## 1. Luồng tổng quát

Entrypoint chuyển đổi riêng (không chat/RAG) là `pdf_to_word.py`:

```python
run_mineru(pdf, parse_dir, tier=a.tier, method=a.method, force=a.force, workers=0)
markdown, _, _ = find_mineru_outputs(parse_dir)
work = run / "for_word.md"
prepare_work_md(markdown.read_text(encoding="utf-8"), markdown, work)
out = Path(a.output) if a.output else run / (pdf.stem + ".docx")
md_to_docx(work, out, markdown.parent)
```

Thứ tự thực tế:

```text
PDF
  → MinerU (layout + OCR + công thức)
  → Markdown gốc + *_content_list.json + ảnh cắt
  → prepare_work_md()      # chuẩn hóa, vá lỗi, quyết định ảnh thay thế
  → Pandoc                  # Markdown → DOCX, TeX → OMML Equation
  → hậu xử lý python-docx   # font, bố cục, justify, số trang, đáp số
  → DOCX
```

`prepare_work_md()` là nơi tập trung gần như toàn bộ quyết định "sửa được thì sửa, không sửa được
thì dùng ảnh gốc". Code hiện tại (rút gọn thứ tự, `llm/src/build_docx.py:840`):

```python
markdown_text = swap_degenerate_math_for_images(markdown_text, md_path, work_md)
markdown_text = fix_symbol_pua(markdown_text)
markdown_text = recover_first_page_header(markdown_text, md_path)
markdown_text = swap_garbled_tables_for_images(markdown_text, md_path)
markdown_text = html_tables_to_pipe(markdown_text)
markdown_text = fix_answer_key_tables(markdown_text)
markdown_text = fix_legacy_tex_bf(markdown_text)
# ghi math_images.json: map LaTeX → ảnh, và danh sách force (bảng-công thức)
markdown_text = fix_texmath_compat(markdown_text)
markdown_text = tag_left_math_blocks(markdown_text)
markdown_text = fix_broken_double_prime(markdown_text)
markdown_text = fix_legacy_vietnamese_mojibake(markdown_text)
markdown_text = fix_missing_right_in_chained_systems(markdown_text)
problems = find_unbalanced_left_right(markdown_text)
```

Điểm quan trọng: `math_images.json` được ghi **trước** các bước sửa công thức cuối cùng, vì khóa
được tính bằng `_final_math_key()` — tức là khóa theo bản LaTeX sau khi đã qua đúng các bước sửa
mà Pandoc sẽ thấy, không phải bản gốc.

## 2. Chuẩn hóa công thức trước khi vào Pandoc

Pandoc dùng `texmath`, không hiểu một số cú pháp MinerU xuất ra. Khi không hiểu, Pandoc không làm
DOCX hỏng; nó để nguyên TeX thô trong tài liệu. Vì vậy các hàm dưới đây chỉ nhằm tăng tỉ lệ
công thức thành Equation thật.

### 2.1 `\bf` kiểu cũ

`llm/src/build_docx.py:22`:

```python
def fix_legacy_tex_bf(markdown_text: str) -> str:
    prev = None
    while prev != markdown_text:
        prev = markdown_text
        markdown_text = re.sub(
            r"\{\s*\\bf\s+([^{}]+?)\s*\}", r"\\mathbf{\1}", markdown_text)
    return markdown_text
```

Ví dụ `{ \bf x }` → `\mathbf{x}`. Hàm lặp đến khi không đổi để xử lý trường hợp lồng nhau.

### 2.2 Dấu đạo hàm cấp 2 bị đọc thành ngoặc kép

`llm/src/build_docx.py:36`:

```python
markdown_text = re.sub(
    r'\^\s*\{\s*["“”]\s*\}', r"^ {\\prime \\prime}", markdown_text)
```

MinerU đôi khi đọc `″` thành `"`, nên `f''_{x^2}` thành `f _ {x^2} ^ {"}`. Nếu để nguyên, texmath
không parse được và công thức rớt về text thô, mất luôn dấu đạo hàm.

### 2.3 Ký tự font Symbol (private use area)

`llm/src/build_docx.py:420`–`435`:

```python
_SYMBOL_SPECIAL = {0xA2: "′", 0xA3: "≤", 0xA5: "∞", 0xB1: "±", 0xB3: "≥", 0xB4: "×",
                   0xB8: "÷", 0xB9: "≠", 0xAE: "→", 0xDE: "⇒", 0xDB: "⇔", 0xB0: "°"}

def fix_symbol_pua(markdown_text: str) -> str:
    return re.sub("[\uF020-\uF0FF]", _symbol_char, markdown_text)
```

PDF cũ dùng font Symbol; ký tự nằm ở `U+F0xx`. Nếu không đổi, DOCX hiện ô vuông.

### 2.4 Tương thích texmath

`llm/src/build_docx.py:483`:

```python
def fix_texmath_compat_one(tex: str) -> str:
    t = fix_font_declarations(tex)
    t = re.sub(r"\\begin\{array\}\s*\{([^}]*)\}",
               lambda m: "\\begin{array}{" + re.sub(r"\s+", "", m.group(1)) + "}", t)
    t = re.sub(r"\\hline\b", " ", t)
    nb = len(re.findall(r"\\begin\{array\}", t))
    ne = len(re.findall(r"\\end\{array\}", t))
    while ne > nb:
        k = t.rfind("\\end{array}")
        t = t[:k] + t[k + len("\\end{array}"):]
        ne -= 1
    if nb > ne:
        t = t + " \\end{array}" * (nb - ne)
    t = _unwrap_command(t, "boxed")
    t = t.replace("\\displaylimits", "")
    ...
```

Các lỗi được xử lý: khoảng trắng trong khai báo cột `{l l}` → `{ll}`, `\hline`, `\boxed{}`,
`\displaylimits`, `\tt`, `\bf{x}`, accent không có ngoặc (`\dot \mathbf{Y}`), `\text{...}` chứa
accent, và `\right` dư ở cuối. Đây là hàm chạy trên **từng span** math, không chạy trên toàn file.

### 2.5 Hệ phương trình chuỗi bị thiếu `\right.`

`llm/src/build_docx.py:117`:

```python
def _fix_chained_systems_in_one_formula(formula: str) -> str:
    if formula.count("\\left") == formula.count("\\right"):
        return formula
    ...
    for m in _CHAIN_TOKEN_RE.finditer(formula):
        ...
        else:  # gặp \end{array} rồi tới mũi tên
            out.append(m.group("endarr"))
            if balance > 0:
                out.append(r" \right.")
                balance -= 1
                changed = True
            out.append(m.group("sep"))
            out.append(m.group("arrow"))
    ...
    if changed and fixed.count("\\left") == fixed.count("\\right"):
        return fixed
    return formula
```

Hàm chỉ nhận kết quả nếu sau khi sửa số `\left` và `\right` thực sự cân bằng. Nếu không, giữ
nguyên bản gốc và để `find_unbalanced_left_right()` báo cho người dùng, tránh sửa sai.

### 2.6 Công thức còn lệch `\left/\right`

`llm/src/build_docx.py:188`:

```python
def find_unbalanced_left_right(markdown_text: str) -> list:
    problems = []
    for m in FORMULA_RE.finditer(markdown_text):
        formula = m.group(0)
        n_left = len(re.findall(r"\\left(?![a-zA-Z])", formula))
        n_right = len(re.findall(r"\\right(?![a-zA-Z])", formula))
        if n_left != n_right:
            problems.append({"formula": formula, "n_left": n_left,
                             "n_right": n_right, "pos": m.start()})
    return problems
```

Hàm này **chỉ báo**, không tự sửa. Lý do: đúng số lượng không đảm bảo đúng vị trí; sửa mù dễ làm
hỏng công thức đang đúng.

## 3. Công thức hỏng → ảnh gốc

### 3.1 Bản đồ LaTeX → ảnh

`llm/src/build_docx.py:652`:

```python
def build_math_image_map(markdown_text, md_path, work_md=None):
    items = _content_items(md_path)
    if not items:
        return {"map": {}, "force": [], "bbox": {}}
    pdf = _find_input_pdf(md_path)
    crop_dir = (work_md.parent if work_md else md_path.parent) / "crops"
    out, force, bbox_map = {}, [], {}
    for it in items:
        if it.get("type") != "equation" or not isinstance(it.get("text"), str):
            continue
        body = it["text"].strip()
        if body.startswith("$$") and body.endswith("$$"):
            body = body[2:-2]
        key = _final_math_key(_norm_tex(body))
        table_like = looks_like_table_formula(body)
        page, bbox = it.get("page_idx"), it.get("bbox")
        if pdf.exists() and isinstance(page, int) and bbox:
            bbox_map[key] = {"pdf": str(pdf), "page": page, "bbox": bbox}
        img = None
        rel = it.get("img_path")
        if rel:
            candidate = (md_path.parent / rel).resolve()
            if candidate.exists():
                img = str(candidate)
        if img is None and table_like and key in bbox_map:
            png = crop_dir / f"table_formula_{len(out) + 1}.png"
            info = bbox_map[key]
            if _crop_pdf_region(info["pdf"], info["page"], info["bbox"], png):
                img = str(png)
        if img:
            out[key] = img
        if table_like:
            force.append(key)
    return {"map": out, "force": sorted(set(force)), "bbox": bbox_map}
```

Ba thứ được lưu:

1. `map`: LaTeX → ảnh MinerU cắt sẵn (`equation.img_path`).
2. `force`: khóa bị nghi là bảng-công thức; thay bằng ảnh kể cả khi Pandoc không báo lỗi.
3. `bbox`: `{pdf, page, bbox}` cho mọi equation có tọa độ. Đây là đường lui khi Pandoc không
   dịch được một công thức display mà MinerU không cắt ảnh riêng.

Với bảng-công thức, ảnh được cắt ngay trong `build_math_image_map` để `force` có ảnh dùng. Với
công thức display khác, ảnh chỉ được cắt khi Pandoc thực sự báo lỗi, tránh tạo hàng trăm file
ảnh không cần thiết.

### 3.2 Khi nào thay bằng ảnh

`llm/src/build_docx.py:1146`:

```python
def _swap_failed_math_for_images(work_md: Path, pandoc_stderr: str) -> int:
    data = json.loads((work_md.with_name("math_images.json")).read_text(encoding="utf-8"))
    img_map = data.get("map", {})
    bbox_map = data.get("bbox", {})
    force = set(data.get("force", []))
    failed = {_norm_tex(x) for x in re.findall(
        r"Could not convert TeX math(.*?), rendering as TeX:", pandoc_stderr, re.S)} | force
    ...
    def _sub(m):
        nonlocal n
        key = _norm_tex(m.group(1))
        if key not in failed:
            return m.group(0)
        if key in img_map:
            n += 1
            return f"\n![]({img_map[key]})\n"
        info = bbox_map.get(key)
        if info:
            png = work_md.parent / "crops" / f"failed_math_{n + 1}.png"
            if _crop_pdf_region(info["pdf"], info["page"], info["bbox"], png):
                n += 1
                return f"\n![]({png})\n"
        return m.group(0)
```

Thứ tự ưu tiên:

1. Ảnh MinerU có sẵn (`img_map`).
2. Ảnh cắt từ `bbox` của PDF (`bbox_map`).
3. Với inline math không có ảnh riêng: cắt cả đoạn văn từ PDF theo `block_regions.json`
   (`llm/src/build_docx.py:1167`).

Lưu ý: `force` được hợp vào `failed`, nên bảng-công thức bị thay ảnh ngay cả khi Pandoc vẫn dịch
được nhưng nội dung sẽ sai.

## 4. Bảng

### 4.1 HTML table → pipe table

MinerU xuất bảng dạng `<table>`. Nếu để nguyên, Pandoc coi là HTML thô và bỏ cấu trúc; DOCX có
`w:tbl = 0`, các ô rơi thành đoạn rời. `html_tables_to_pipe()` (`llm/src/build_docx.py:728`) đổi
sang pipe table, `colspan` thành ô trống, và đổi `|` trong math thành `\vert` để không phá cột.

### 4.2 Bảng hỏng → ảnh gốc của bảng

`looks_like_garbled_table()` (`llm/src/build_docx.py:697`) phát hiện:

- các hàng lệch số cột (tính cả `colspan`);
- bảng hẹp (≤ 4 cột) mà ≥ 25% ô trống.

`swap_garbled_tables_for_images()` (`llm/src/build_docx.py:812`) thay `table_body` bằng
`img_path` của chính bảng đó. Đây là đường lui cho bảng chân trị/biến thiên nhỏ bị OCR mất ô.

### 4.3 Bảng bị nhận thành công thức

Đây là trường hợp mới được bổ sung. Hàm nhận diện `looks_like_table_formula()`
(`llm/src/build_docx.py:606`):

```python
def looks_like_table_formula(body: str) -> bool:
    if _TABLE_AS_FRAC_RE.search(body):
        return True
    if "\\begin{tabular}" in body or "\\hline" in body:
        return True
    specs = _TABLE_ARRAY_RE.findall(body)
    if any("|" in (spec or "") for _, spec in specs):
        return True
    rows = [row for row in _ROW_SPLIT_RE.split(body) if row.strip()]
    if len(rows) < 2:
        return False
    max_cols = max(len(_CELL_SPLIT_RE.split(row)) for row in rows)
    if max_cols >= 4:
        return True
    if max_cols >= 3 and len(rows) >= 3 and not _MATRIX_WRAP_RE.search(body):
        return True
    if max_cols >= 2 and len(_TEXT_CELL_RE.findall(body)) >= 3:
        return True
    return False
```

Các dấu hiệu: `tabular`, `\hline`, cột có `|`, array ≥ 4 cột, array ≥ 3×3 không bọc trong
`\left[...\right]`, hoặc nhiều ô `\text{...}`. Ma trận có ngoặc và hệ phương trình `cases` được
giữ nguyên.

Luồng xử lý:

```text
equation text
  → looks_like_table_formula() == True
  → build_math_image_map(): lấy img_path, hoặc cắt bbox từ PDF
  → ghi khóa vào "force"
  → _swap_failed_math_for_images(): thay $$...$$ bằng ![](crop.png)
  → DOCX có ảnh gốc thay vì công thức rác
```

Đã kiểm chứng bằng test `test_table_formula_without_mineru_image_is_cropped_from_pdf`:
tạo PDF bằng PyMuPDF, content_list chỉ có `text` + `bbox` (không có `img_path`), chạy
`prepare_work_md` + `md_to_docx`; kết quả DOCX có `word/media/*.png` và không còn
`\begin{array}` trong `document.xml`.

## 5. Pandoc và hậu xử lý DOCX

`_md_to_docx_inplace()` (`llm/src/build_docx.py:1212`):

- Tạo file tạm `.building.docx` rồi `os.replace` một lần. Lý do: backend coi file đích tồn tại là
  job xong; nếu ghi trực tiếp, client có thể tải file 0 byte hoặc file đang dựng.
- Chỉ thêm `--toc` khi tài liệu ≥ 40.000 ký tự và ≥ 8 heading; tiêu đề TOC là "Mục lục".
- `--resource-path` trỏ tới thư mục Markdown để Pandoc tìm ảnh.
- Nếu Pandoc báo lỗi công thức, gọi `_swap_failed_math_for_images` rồi chạy lại Pandoc.
- Sau Pandoc: `set_font`, `layout`/`columns`, `justify_paragraphs`, `apply_math_alignment`,
  `format_answer_key_paragraphs`, `add_page_numbers`.

## 6. Độ đo CER, WER, PER

Module mới: `llm/src/metrics.py`.

### 6.1 Định nghĩa

```text
CER = (S + D + I) / N      # ký tự
WER = (S + D + I) / N      # từ, tách theo khoảng trắng
PER = số trang có ít nhất một lỗi / tổng số trang
```

- `S`, `D`, `I`: thay thế, xóa, chèn.
- `N`: độ dài bản tham chiếu (ký tự hoặc từ).
- `PER` ở đây là **Page Error Rate**. Nếu nhóm dùng PER theo nghĩa khác (ví dụ Paragraph Error
  Rate), chỉ cần đổi đơn vị trang trong `evaluate_pages()`; định nghĩa phải ghi rõ trong báo cáo.
- CER/WER toàn bộ là micro-average: tổng lỗi / tổng độ dài, không phải trung bình cộng các trang.
  Cách này tránh trang ngắn chi phối kết quả.
- PER nghiêm (ngưỡng 0): chỉ cần một ký tự sai là trang đó bị tính lỗi. Vì vậy kết quả còn có
  `page_exact_match_rate` và CER từng trang.

### 6.2 Chuẩn hóa

`normalize_text()` (`llm/src/metrics.py:50`) làm các việc sau, theo đúng thứ tự:

1. Tùy chọn bỏ vùng math `$...$`, `$$...$$`, `\(...\)`, `\[...\]`.
2. Bỏ ký tự vô hình: ZWSP, ZWJ, BOM, soft hyphen, control hướng.
3. Unicode NFC. Với tiếng Việt, đây là bước bắt buộc: dấu tổ hợp và dấu dựng sẵn khác dãy điểm mã
   nhưng cùng nội dung hiển thị.
4. Tùy chọn lowercase.
5. Gộp khoảng trắng và strip.

Không chuẩn hóa thì CER bị cộng lỗi cho khác biệt mã hóa, không phải lỗi nhận dạng.

### 6.3 Cách đếm lỗi

`edit_counts()` (`llm/src/metrics.py:224`) dùng Levenshtein. Với chuỗi nhỏ (mặc định
≤ 20 triệu ô DP), kết quả chính xác và trả `exact=True`. Với chuỗi lớn hơn, module căn theo dòng
và trả `exact=False`; muốn số chính xác tuyệt đối, chia đầu vào thành từng trang rồi gọi
`evaluate_pages()`.

### 6.4 CLI

```bash
python3 -m llm.src.metrics \
  --ref ground_truth/ \
  --hyp output/ \
  --strip-math \
  --json metrics.json
```

- `--ref` và `--hyp` có thể là file hoặc thư mục.
- Ghép file theo stem: `bai1.txt` ↔ `bai1.md` / `bai1.docx`.
- Đọc được `.txt`, `.md`, `.docx` (DOCX lấy paragraph + cell; không lấy OMML).
- Tách trang bằng form feed `\f` nếu cả hai phía đều có; nếu không, coi toàn file là một trang.
- `--strip-math`: đo riêng văn bản, không trộn lỗi công thức vào CER.

### 6.5 Điều kiện để có số liệu

Không có ground truth độc lập thì không thể tính CER/WER/PER có ý nghĩa. Không được lấy chính
kết quả OCR làm ground truth. Quy trình tối thiểu:

1. Chọn 20–30 trang theo tầng: PDF text, scan 300 dpi, scan mờ, có công thức, có bảng, song ngữ.
2. Người chép lại nội dung từ ảnh gốc, không copy từ DOCX/Markdown đầu ra.
3. Lưu mỗi trang một file `.txt`, dùng `\f` nếu muốn nhiều trang trong một file.
4. Chạy CLI, lưu `metrics.json`, ghi rõ phiên bản MinerU/Pandoc/Python và ngưỡng chuẩn hóa.

Vì chưa có bộ ground truth trong repo, hiện chưa có số CER/WER/PER của đồ án. Module chỉ là công cụ
để đo khi có dữ liệu; không tự tạo ra kết quả.

## 7. Tự kiểm chứng

```bash
python3 -m pytest tests/test_metrics.py tests/test_build_docx_fixes.py -q
python3 -m llm.src.metrics --help
python3 pdf_to_word.py --pdf input/test3.pdf --output /tmp/test3.docx
```

Kiểm tra DOCX:

```bash
python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("/tmp/test3.docx")
xml = z.read("word/document.xml").decode("utf-8")
print("OMML:", xml.count("<m:oMath"))
print("media:", [n for n in z.namelist() if n.startswith("word/media/")])
print("TeX thô còn:", "\\begin{array}" in xml or "\\frac" in xml)
PY
```

`preflight` trong `pdf_to_word.py` chỉ kiểm tra file DOCX hợp lệ, có OMML và media; nó **không**
chứng minh nội dung đúng. Đừng dùng `omml_tags` làm độ chính xác.

## 8. Giới hạn

- Chưa có ground truth → chưa có CER/WER/PER thực tế.
- `looks_like_table_formula()` là heuristic. Ma trận 4 cột không bọc ngoặc có thể bị thay bằng ảnh;
  khi đó nội dung vẫn đúng hình thức nhưng mất khả năng sửa Equation.
- Ảnh cắt từ PDF phụ thuộc `bbox` của MinerU. Nếu `bbox` sai, ảnh cũng sai; cần mở DOCX đối chiếu.
- WER tách theo khoảng trắng nên với tiếng Việt thực chất là mức âm tiết, không phải mức từ.
- Chưa đo độ trễ, RAM, hay chất lượng bảng bằng TEDS. Các chỉ tiêu đó cần benchmark riêng.
