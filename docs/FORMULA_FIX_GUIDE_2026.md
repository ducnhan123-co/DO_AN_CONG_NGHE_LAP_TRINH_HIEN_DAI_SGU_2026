# Hướng xử lý công thức sai khi PDF → Word

Tài liệu này là bảng tra khi mở DOCX thấy công thức sai, công thức rớt thành chữ LaTeX thô, hoặc
một bảng bị biến thành công thức. Mỗi mục ghi: triệu chứng → nguyên nhân → code đang xử lý → chỗ
cần sửa → cách kiểm chứng.

## 0. Nguyên tắc

1. **Sửa được bằng cấu trúc thì sửa** (delimiter, lệnh texmath, `\right` thiếu).
2. **Không sửa được an toàn thì dùng ảnh gốc** — ảnh đúng nội dung quan trọng hơn Equation sai.
3. **Không bao giờ lấy kết quả OCR làm ground truth** để tính CER/WER.
4. Mọi thay đổi phải kiểm bằng DOCX thật, không chỉ bằng log "đã sửa".

## 1. Bảng tra nhanh

| Triệu chứng trong DOCX | Nguyên nhân thường gặp | Code xử lý | Chỗ dùng |
|---|---|---|---|
| Còn nguyên `$...$` hoặc `\frac{...}` thay vì Equation | Pandoc/texmath không parse được | `fix_texmath_compat`, `fix_legacy_tex_bf`, `fix_broken_double_prime` | `llm/src/build_docx.py:483`, `:22`, `:36` |
| Công thức hiện ô vuông/ký tự lạ | Font Symbol `U+F0xx` | `fix_symbol_pua` | `llm/src/build_docx.py:435` |
| Hệ phương trình bị lệch ngoặc, mất `\right.` | OCR làm rơi `\right.` giữa chuỗi hệ | `fix_missing_right_in_chained_systems` | `llm/src/build_docx.py:172` |
| Công thức vẫn lệch `\left/\right` | OCR lồng sai vị trí | `find_unbalanced_left_right` (chỉ báo) | `llm/src/build_docx.py:188` |
| Bảng xét dấu thành `\frac{ x \quad -3 ...}` | MinerU nhận bảng thành công thức | `looks_like_table_formula` → ảnh | `llm/src/build_docx.py:606`, `:652` |
| Bảng chân trị/bảng nhỏ mất ô | MinerU nhận bảng HTML hỏng | `looks_like_garbled_table`, `swap_garbled_tables_for_images` | `llm/src/build_docx.py:697`, `:812` |
| Cả đoạn dày chữ thành một khối LaTeX khổng lồ | MinerU "ảo giác" cả vùng | `swap_degenerate_math_for_images` | `llm/src/build_docx.py:790` |
| Trang đáp số xáo thứ tự, mỗi đáp số một dòng | OCR đọc bảng đáp số theo zig-zag | `fix_answer_key_tables` | `llm/src/build_docx.py:357` |
| Công thức display hỏng, không có ảnh MinerU | Pandoc không dịch được display math | `_swap_failed_math_for_images` cắt `bbox` từ PDF | `llm/src/build_docx.py:1146` |
| Công thức inline hỏng, không có ảnh riêng | Pandoc không dịch được inline math | `_swap_failed_math_for_images` cắt đoạn từ PDF | `llm/src/build_docx.py:1146` |
| Công thức đúng nhưng bị thay bằng ảnh | Heuristic bảng-công thức quá tay | chỉnh `looks_like_table_formula` hoặc bỏ khóa khỏi `force` | `llm/src/build_docx.py:606`, `:652` |

## 2. Quy trình xử lý một công thức sai

### Bước 1 — Xác định công thức nằm ở đâu

Mở file làm việc `for_word.md` (hoặc `work.md` trong test). Tìm đúng chuỗi LaTeX đang sai. Đối
chiếu với ảnh gốc cùng trang trong PDF.

Nếu log có dòng:

```text
[CẢNH BÁO] N công thức lệch \left/\right (sẽ không thành Equation, rớt về text thô):
  - vị trí ký tự 1234: left=2 right=1 | ...
```

thì đây là công thức cần ưu tiên. Vị trí là offset trong Markdown, không phải số trang.

### Bước 2 — Phân loại lỗi

- **Lỗi cú pháp nhẹ**: `\bf`, `\begin{array}{l l}`, `\hline`, `\boxed`, `\dot \mathbf{Y}`,
  `\right` dư ở cuối. → Để `fix_texmath_compat` xử lý; nếu chưa xử lý, bổ sung rule vào
  `fix_texmath_compat_one()` (`llm/src/build_docx.py:483`).
- **Lỗi cấu trúc**: thiếu `\right.` giữa chuỗi hệ. → `fix_missing_right_in_chained_systems()`
  (`llm/src/build_docx.py:172`). Hàm chỉ nhận kết quả khi số `\left` = số `\right`; nếu không,
  giữ nguyên và báo.
- **Lỗi nội dung**: OCR đọc sai ký hiệu, mất số, sai dấu. → Không có cách sửa cấu trúc an toàn.
  Dùng ảnh gốc hoặc sửa tay.
- **Bảng bị nhận thành công thức**: → Mục 3.
- **Công thức quá dài, nhiều `\begin{array}` lồng**: → `swap_degenerate_math_for_images()`
  (`llm/src/build_docx.py:790`).

### Bước 3 — Chọn cách xử lý

| Mức độ | Cách xử lý | Kết quả |
|---|---|---|
| Cú pháp nhẹ, sửa được chắc chắn | Bổ sung rule vào `fix_texmath_compat_one` | Equation thật, sửa được trong Word |
| Thiếu `\right.` theo mẫu chuỗi hệ | `fix_missing_right_in_chained_systems` | Equation thật nếu cân bằng lại |
| Sai nội dung, không chắc | Ảnh gốc của công thức | Đúng hình, không sửa được |
| Bảng-công thức | Ảnh gốc của bảng | Đúng bảng, không sửa được |
| Inline math hỏng | Cắt cả đoạn văn từ PDF | Đúng đoạn, không sửa được |

### Bước 4 — Kiểm chứng

```bash
python3 -m pytest tests/test_build_docx_fixes.py -q
python3 pdf_to_word.py --pdf input/<file>.pdf --output /tmp/<file>.docx
```

Mở DOCX, kiểm 3 thứ:

1. Công thức là Equation (bấm vào được, không phải ảnh) hay ảnh (biết chấp nhận).
2. Nội dung khớp ảnh gốc.
3. Không còn chuỗi `\begin`, `\frac`, `\left` trong phần văn bản.

Kiểm nhanh bằng XML:

```bash
python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("/tmp/<file>.docx")
xml = z.read("word/document.xml").decode("utf-8")
print("OMML:", xml.count("<m:oMath"))
print("media:", [n for n in z.namelist() if n.startswith("word/media/")])
print("TeX thô:", any(s in xml for s in ("\\begin{array}", "\\frac", "\\left")))
PY
```

## 3. Bảng bị nhận thành công thức

### 3.1 Dấu hiệu

- Trong Markdown, vùng đáng lẽ là bảng lại nằm trong `$$...$$`.
- LaTeX có `\begin{array}{|c|c|}`, `\hline`, `\begin{tabular}`, hoặc rất nhiều `&` và `\text{}`.
- DOCX hiện một "công thức" dài, các cột dính vào nhau, nội dung không khớp bảng gốc.
- Pandoc có thể vẫn dịch được — đó là trường hợp nguy hiểm nhất, vì không có lỗi để bắt.

### 3.2 Code hiện tại

`looks_like_table_formula()` (`llm/src/build_docx.py:606`) nhận diện:

```python
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

`build_math_image_map()` (`llm/src/build_docx.py:652`) đưa khóa vào `force`; nếu không có
`img_path` thì cắt `bbox` từ `input.pdf`:

```python
if img is None and table_like and pdf.exists():
    page, bbox = it.get("page_idx"), it.get("bbox")
    if isinstance(page, int) and bbox:
        png = crop_dir / f"table_formula_{len(out) + 1}.png"
        if _crop_pdf_region(str(pdf), page, bbox, png):
            img = str(png)
if img:
    out[key] = img
if table_like:
    force.append(key)
```

`_swap_failed_math_for_images()` (`llm/src/build_docx.py:1146`) thay `$$...$$` bằng
`![](...)`, kể cả khi Pandoc không báo lỗi, vì khóa nằm trong `force`.

### 3.3 Khi nào dùng ảnh gốc, khi nào cố sửa thành bảng Word

**Dùng ảnh gốc** khi:

- bảng có ô gộp nhiều cấp, đường kẻ chéo, tô màu;
- bảng xét dấu, bảng biến thiên có mũi tên;
- bảng chứa công thức phức tạp trong từng ô;
- ưu tiên "nội dung đúng" hơn "sửa được".

**Cố dựng bảng Word** khi:

- bảng lưới đơn giản, không gộp ô;
- cần người dùng sửa nội dung sau;
- MinerU xuất HTML sạch, `looks_like_garbled_table()` trả `False`.

### 3.4 Chỉnh khi heuristic quá tay

Nếu một ma trận/công thức thật bị thay bằng ảnh:

1. Mở `math_images.json` trong thư mục work.
2. Tìm khóa LaTeX tương ứng trong `force`.
3. Bỏ khóa khỏi `force` (giữ trong `map` nếu vẫn muốn dự phòng khi Pandoc lỗi).
4. Chạy lại `md_to_docx`.

Nếu muốn sửa tận gốc: thêm điều kiện loại trừ vào `looks_like_table_formula()` — ví dụ kiểm tra
`\left[`, `\left(`, `\begin{pmatrix}`, `\begin{cases}` trước khi kết luận là bảng. Sau khi sửa,
thêm test vào `tests/test_build_docx_fixes.py`.

### 3.5 Thêm ảnh thủ công cho một công thức

Trong `math_images.json`:

```json
{
  "map": {
    "\\begin{array}{|c|c|} ... \\end{array}": "/duong/dan/tuyet/doi/crop.png"
  },
  "force": [
    "\\begin{array}{|c|c|} ... \\end{array}"
  ]
}
```

Khóa phải là LaTeX **sau** các bước sửa (`_final_math_key`), không phải bản gốc trong content_list.
Cách chắc chắn nhất: lấy khóa từ `math_images.json` do pipeline vừa ghi, rồi thêm đường dẫn ảnh.

## 4. Các lỗi công thức cụ thể

### 4.1 `\bf` kiểu cũ

**Triệu chứng:** DOCX còn `{ \bf x }` hoặc công thức bị bỏ qua.

**Fix:** `fix_legacy_tex_bf()` (`llm/src/build_docx.py:22`) đổi `{ \bf X }` → `\mathbf{X}`.

**Khi nào bổ sung:** nếu gặp `\bfseries`, `\sf`, `\cal` chưa được xử lý, thêm vào
`fix_font_declarations()` (`llm/src/build_docx.py:442`).

### 4.2 Đạo hàm cấp 2

**Triệu chứng:** `f''` thành `f ^ {"}` hoặc mất dấu.

**Fix:** `fix_broken_double_prime()` (`llm/src/build_docx.py:36`) đổi `^ {"}` → `^ {\prime \prime}`.

**Giới hạn:** chỉ xử lý dấu ngoặc kép trong số mũ; không xử lý mọi ký tự Unicode giống dấu nháy.

### 4.3 Ký tự font Symbol

**Triệu chứng:** ô vuông, ký tự `ï¿½`, hoặc ký tự private-use.

**Fix:** `fix_symbol_pua()` (`llm/src/build_docx.py:435`). Bảng ánh xạ nằm ở `_SYMBOL_UP`,
`_SYMBOL_LO`, `_SYMBOL_SPECIAL`.

**Khi nào bổ sung:** nếu gặp ký tự `U+F0xx` chưa có trong bảng, thêm vào `_SYMBOL_SPECIAL`.

### 4.4 Array và texmath

**Triệu chứng:** `\begin{array}{l l}` không parse; `\hline` làm hỏng; `\boxed` không hiểu;
`\dot \mathbf{Y}` không parse.

**Fix:** `fix_texmath_compat_one()` (`llm/src/build_docx.py:483`). Hàm xử lý:

- bỏ khoảng trắng trong khai báo cột;
- bỏ `\hline`;
- cân bằng `\begin{array}` / `\end{array}`;
- bỏ `\boxed`, `\displaylimits`;
- đổi `\bf`, `\tt`, `\rm`, `\it`;
- thêm ngoặc cho accent;
- bỏ `\right` dư ở cuối.

**Cẩn thận:** `\hline` bị xóa trong công thức. Nếu `\hline` là dấu hiệu bảng, việc nhận diện bảng
phải chạy **trước** bước này. Trong pipeline, `looks_like_table_formula()` chạy trên bản gốc trong
`build_math_image_map()`, trước `fix_texmath_compat`.

### 4.5 Hệ phương trình chuỗi

**Triệu chứng:** nhiều hệ nối bằng `\Leftrightarrow`, một hệ mất `\right.`, công thức rớt về text.

**Fix:** `fix_missing_right_in_chained_systems()` (`llm/src/build_docx.py:172`). Hàm chỉ sửa khi:

- phát hiện `\end{array}` đi ngay trước mũi tên;
- đang có `\left` chưa đóng;
- sau khi sửa, số `\left` = số `\right`.

Nếu không thỏa, giữ nguyên và `find_unbalanced_left_right()` báo.

### 4.6 Công thức display hỏng, không có ảnh MinerU

**Triệu chứng:** Pandoc báo `Could not convert TeX math ...`, DOCX còn nguyên TeX thô; công thức
không có `img_path` trong content_list.

**Fix:** `build_math_image_map()` lưu `bbox` cho mọi equation; `_swap_failed_math_for_images()`
(`llm/src/build_docx.py:1146`) cắt đúng `bbox` từ `input.pdf` và thay bằng ảnh.

**Giới hạn:** phụ thuộc `bbox` và `page_idx` của MinerU. Nếu `bbox` sai, ảnh sai; kiểm bằng mắt.

### 4.7 Công thức inline hỏng

**Triệu chứng:** một câu văn có `$...$` không thành Equation, hoặc cả đoạn bị thay bằng ảnh.

**Fix:** `_swap_failed_math_for_images()` (`llm/src/build_docx.py:1146`) cắt cả đoạn từ PDF theo
`block_regions.json` nếu không có ảnh công thức riêng.

**Giới hạn:** cắt theo `bbox` của khối text; nếu `bbox` bao cả cột hoặc sai trang, ảnh sai. Kiểm
bằng mắt trong DOCX.

### 4.8 Trang đáp số

**Triệu chứng:** đáp số xáo thứ tự, mỗi đáp số một dòng, chữ nghiêng kiểu công thức.

**Fix:** `fix_answer_key_tables()` (`llm/src/build_docx.py:357`) gom các khối `$$` liền nhau sau
tiêu đề "ĐÁP SỐ", parse nhãn `1a)`, sắp xếp theo số câu/chữ cái, dựng lại bảng 5 cột hoặc tab stop.

**Khi nào dùng:** chỉ khi có tiêu đề "ĐÁP SỐ" và ≥ 3 mục parse được. Nếu bảng đáp số có cấu trúc
khác, thêm mẫu nhãn vào `_ANS_LABEL_RE` (`llm/src/build_docx.py:222`).

### 4.9 Khối LaTeX ảo giác

**Triệu chứng:** một đoạn dày chữ hoặc bảng bị biến thành công thức > 1500 ký tự, nhiều
`\begin{array}` lồng nhau.

**Fix:** `swap_degenerate_math_for_images()` (`llm/src/build_docx.py:790`) cắt đúng vùng từ PDF.
Điều kiện: type `text`, dài > 1500 ký tự, ≥ 3 `\begin{array}`, có `bbox` và `page_idx`.

## 5. Chỗ nào nên dùng code — bảng quyết định

| Việc cần làm | Dùng code nào | File:line |
|---|---|---|
| Thêm một rule sửa cú pháp texmath | `fix_texmath_compat_one` | `llm/src/build_docx.py:483` |
| Sửa lỗi font tiếng Việt cũ | `fix_legacy_vietnamese_mojibake` | `llm/src/build_docx.py:91` |
| Sửa ký tự Symbol | `fix_symbol_pua` | `llm/src/build_docx.py:435` |
| Phát hiện công thức lệch ngoặc | `find_unbalanced_left_right` | `llm/src/build_docx.py:188` |
| Thay công thức hỏng bằng ảnh MinerU hoặc bbox PDF | `build_math_image_map` | `llm/src/build_docx.py:652` |
| Thay bảng-công thức bằng ảnh | `looks_like_table_formula` + `force` | `llm/src/build_docx.py:606` |
| Thay bảng HTML hỏng bằng ảnh bảng | `swap_garbled_tables_for_images` | `llm/src/build_docx.py:812` |
| Thay khối LaTeX ảo giác bằng ảnh PDF | `swap_degenerate_math_for_images` | `llm/src/build_docx.py:790` |
| Dựng lại trang đáp số | `fix_answer_key_tables` | `llm/src/build_docx.py:357` |
| Đo CER/WER/PER | `llm/src/metrics.py` | `evaluate_pages` (`:264`), CLI (`:383`) |
| Chạy lại toàn bộ | `pdf_to_word.py` | `main()` |

## 6. Checklist trước khi báo cáo

- [ ] Mở DOCX, đếm công thức là Equation và công thức là ảnh; ghi rõ tỉ lệ nếu cần.
- [ ] Kiểm 5 công thức phức tạp nhất bằng mắt, đối chiếu PDF gốc.
- [ ] Kiểm 3 bảng: một bảng thường, một bảng gộp ô, một bảng bị nghi nhận thành công thức.
- [ ] Kiểm trang đáp số (nếu có).
- [ ] Chạy `python3 -m pytest tests/test_metrics.py tests/test_build_docx_fixes.py -q`.
- [ ] Nếu báo CER/WER/PER: ghi rõ ground truth, phiên bản MinerU/Pandoc/Python, cách chuẩn hóa,
      và không dùng chính đầu ra làm tham chiếu.
- [ ] Không viết "chính xác 100%" hay "mọi công thức" khi chưa có ground truth.

## 7. Giới hạn đã biết

- `looks_like_table_formula()` là heuristic; có thể bỏ sót bảng 2–3 cột hoặc thay nhầm ma trận
  không bọc ngoặc.
- `fix_missing_right_in_chained_systems()` chỉ xử lý mẫu `\end{array}` + mũi tên; không xử lý mọi
  kiểu lồng ngoặc.
- `fix_texmath_compat_one()` xóa `\hline`; mọi logic nhận diện bảng phải chạy trước.
- Ảnh cắt theo `bbox` phụ thuộc MinerU; `bbox` sai thì ảnh sai.
- Chưa có ground truth → chưa có CER/WER/PER thực tế; các ngưỡng "CER < 2–5%" trong báo cáo là
  mốc tham khảo, không phải kết quả đo của đồ án.
