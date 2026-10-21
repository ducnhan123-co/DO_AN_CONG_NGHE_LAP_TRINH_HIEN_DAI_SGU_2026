"""Sửa lỗi OCR tiếng Việt + chuẩn hoá cấu trúc heading cho DOCX.

Chỉ dùng cho nhánh DOCX (build_docx.prepare_work_md), không đụng RAG.
Các thay thế dưới đây là cụm từ đã đối chiếu trên PDF gốc Toán 11 KNTT;
áp dụng theo ranh giới từ nên không sửa bừa các từ đúng khác.
"""
from __future__ import annotations

import re

# (pattern, replacement) — chạy lần lượt, pattern là regex.
_VI_FIXES: list[tuple[str, str]] = [
    # lỗi chữ cái / dấu thanh đã gặp thực tế
    (r"\bHinh\b", "Hình"),
    (r"\btử giác\b", "tứ giác"),
    (r"\btử diện\b", "tứ diện"),
    (r"\bTử diện\b", "Tứ diện"),
    (r"\btử điện\b", "tứ diện"),
    (r"\bTử điện\b", "Tứ diện"),
    (r"\bbồi vì\b", "bởi vì"),
    (r"\bBồi vì\b", "Bởi vì"),
    (r"\bcác định của\b", "các đỉnh của"),
    (r"\btrau đổi\b", "trau dồi"),
    (r"\bchiểm lĩnh\b", "chiếm lĩnh"),
    (r"\bnày sinh\b", "nảy sinh"),
    (r"\bVi tử giác\b", "Vì tứ giác"),
    (r"\bbốn định của\b", "bốn đỉnh của"),
    (r"\bchứng tờ\b", "chứng tỏ"),
    (r"\bchứng minh ràng\b", "chứng minh rằng"),
    (r"\bhệ trực\b", "hệ trục"),
    (r"\btrực toạ\b", "trục tọa"),
    (r"\bthằng đúng\b", "thẳng đứng"),
    (r"\bbản ra khởi\b", "bắn ra khỏi"),
    (r"\bthia\b", "thìa"),
    (r"\bmức một\b", "múc một"),
    (r"\bkè chia\b", "kẻ chia"),
    (r"\bkè ô\b", "kẻ ô"),
    (r"\btình hướng\b", "tình huống"),
    (r"\bmáy phần\b", "mấy phần"),
    (r"\bĐằng thức\b", "Đẳng thức"),
    (r"\bNHÂN ĐỘI\b", "NHÂN ĐÔI"),
    (r"\bĐối 33\b", "Đổi 33"),
    (r"\bTHUẬT NOW\b", "THUẬT NGỮ"),
    (r"\bTHUẤT NGỮ\b", "THUẬT NGỮ"),
    (r"\bTHUẬT NOỮ\b", "THUẬT NGỮ"),
    (r"\bTHUẤT NG[ỮŨ]\b", "THUẬT NGỮ"),
    (r"\bKI[ẾÊ]N TH[ỨƯ]C,\s*K[ĨỈI]+ NĂNG\b", "KIẾN THỨC, KĨ NĂNG"),
    (r"\bChú y\b", "Chú ý"),
    (r"\bcảm tay\b", "cầm tay"),
    (r"\bcâm tay\b", "cầm tay"),
    (r"\brời từ\b", "rồi từ"),
    (r"\bthấy/cô\b", "thầy/cô"),
    (r"\bthời lưỡng\b", "thời lượng"),
    (r"\bvị dụ\b", "ví dụ"),
    (r"\bkiến thứ\b", "kiến thức"),
    (r"\btỉnh số\b", "tính số"),
    # vẽ / về, để / đề
    (r"\bđã về ở\b", "đã vẽ ở"),
    (r"\bđồ thị đã về\b", "đồ thị đã vẽ"),
    (r"\bĐề về đồ thị\b", "Để vẽ đồ thị"),
    (r"\bcần về đồ thị\b", "cần vẽ đồ thị"),
    (r"\bcần về phần\b", "cần vẽ phần"),
    (r"\bvề đường tròn tâm\b", "vẽ đường tròn tâm"),
    (r"\bđề (hàm|kim|làm|giải|tìm|tính|vẽ|về|xác định|chứng minh|biết|cho|tạo|kiểm tra|so sánh)\b",
     r"để \1"),
    (r"\bĐề (hàm|kim|làm|giải|tìm|tính|vẽ|về|xác định|chứng minh|biết|cho|tạo|kiểm tra|so sánh)\b",
     r"Để \1"),
    (r"\bhấy\b", "hãy"),
    (r"\bHấy\b", "Hãy"),
    # dấu thanh lệch
    (r"\btúr\b", "tứ"),
    (r"\btoạ\b", "tọa"),
    (r"\bTuỷ\b", "Tuỳ"),
    (r"\btuỷ\b", "tuỳ"),
    (r"\blủi\b", "lùi"),
    (r"\bđĩ\b", "đi"),
    (r"\bsó\b", "số"),
    (r"\bSó\b", "Số"),
    (r"\bđãy\b", "dãy"),
    (r"\bĐãy\b", "Dãy"),
    (r"\bmãu\b", "mẫu"),
    (r"\bMãu\b", "Mẫu"),
    (r"\bmảu\b", "mẫu"),
    (r"\bdẫy\b", "dãy"),
    (r"\bDẫy\b", "Dãy"),
    (r"\bluợng\b", "lượng"),
    (r"\bLuợng\b", "Lượng"),
    (r"\bTím\b", "Tìm"),
    # lỗi dấu trong tiêu đề mục / bài
    (r"\bGIÁ TRI\b", "GIÁ TRỊ"),
    (r"\bGiá tri\b", "Giá trị"),
    (r"\bCÔNG THỨC CÔNG\b", "CÔNG THỨC CỘNG"),
    (r"\bHÀM SỐ CHẢN\b", "HÀM SỐ CHẴN"),
    (r"\bHÀM SỐ LỆ\b", "HÀM SỐ LẺ"),
    (r"\bTÚ PHÂN VỊ\b", "TỨ PHÂN VỊ"),
    (r"\bTú phân vị\b", "Tứ phân vị"),
    (r"\bMÔT CỦA\b", "MỐT CỦA"),
    (r"\bMÂU SỐ\b", "MẪU SỐ"),
    (r"\bMẢU SỐ\b", "MẪU SỐ"),
    (r"\bGIÓI THIỆU\b", "GIỚI THIỆU"),
    (r"\bĐƯỜNG THẮNG\b", "ĐƯỜNG THẲNG"),
    (r"\bđường thắng\b", "đường thẳng"),
    (r"\bMẶT PHẮNG\b", "MẶT PHẲNG"),
    (r"\bMẶT PHĂNG\b", "MẶT PHẲNG"),
    (r"\bMẶT PHẢNG\b", "MẶT PHẲNG"),
    (r"\bmặt phắng\b", "mặt phẳng"),
    (r"\bKHÔNG GIÁN\b", "KHÔNG GIAN"),
    (r"\bTÚ DIỆN\b", "TỨ DIỆN"),
    (r"\bTHỦA NHẬN\b", "THỪA NHẬN"),
    (r"\bBIỂU DIỂN\b", "BIỂU DIỄN"),
    (r"\bDỸY SỐ\b", "DÃY SỐ"),
    (r"\bDẪY SỐ\b", "DÃY SỐ"),
    (r"\bĐ Bak Y SỐ\b", "DÃY SỐ"),
    (r"\bD Bak Y SỐ\b", "DÃY SỐ"),
    (r"\bDĀY SỐ\b", "DÃY SỐ"),
    (r"\bKHÁI NIÊM\b", "KHÁI NIỆM"),
    (r"\bLUỘNG GIÁC\b", "LƯỢNG GIÁC"),
    (r"\bTUẬN HOÀN\b", "TUẦN HOÀN"),
    (r"\bBIẾN ĐỐI\b", "BIẾN ĐỔI"),
    (r"\bTỔNG QUẤT\b", "TỔNG QUÁT"),
    (r"\bSỐ TIÊN\b", "SỐ TIỀN"),
    (r"\bCÂM TAY\b", "CẦM TAY"),
    (r"\bĐƠ XU THẾ\b", "ĐO XU THẾ"),
    (r"\bGHẾP NHÓM\b", "GHÉP NHÓM"),
    (r"\bMÃU SỐ\b", "MẪU SỐ"),
    (r"GIÁ TRỊ LƯỢNG GIÁC CỦA GỐC LƯỢNG GIÁC",
     "GIÁ TRỊ LƯỢNG GIÁC CỦA GÓC LƯỢNG GIÁC"),
    (r"\bĐƠN VỊ ĐO GÓC VÀ ĐỘ DÀI CUNG TRÒN\b", "ĐƠN VỊ ĐO GÓC VÀ ĐỘ DÀI CUNG TRÒN"),
]


def fix_vietnamese_ocr(text: str) -> str:
    # Bộ sửa này đã đối chiếu riêng trên Toán 11 KNTT; sách khác (Vật lí…)
    # không áp dụng để tránh sửa sai (vd "tụ điện" thành "tứ diện").
    if not _is_toan11(text):
        return text
    for pat, rep in _VI_FIXES:
        text = re.sub(pat, rep, text)
    # nhãn hoạt động: H01/HOS/HD6/H① -> HĐn
    text = re.sub(r"\bH0(\d)\b", r"HĐ\1", text)
    text = re.sub(r"\bHOS\b", "HĐ5", text)
    text = re.sub(r"\bHD(\d)\b", r"HĐ\1", text)
    text = re.sub(r"\bH①", "HĐ1", text)
    text = re.sub(r"\bH②", "HĐ2", text)
    text = re.sub(r"\bH③", "HĐ3", text)
    text = re.sub(r"\bH④", "HĐ4", text)
    text = re.sub(r"\bH⑤", "HĐ5", text)
    return text


# ---------------------------------------------------------------------------
# Cấu trúc sách Toán 11 KNTT tập 1 (lấy từ chính trang MỤC LỤC của PDF)
# ---------------------------------------------------------------------------
_BOOK_MARKERS = ("TOÁN 11", "TRI THỨC")

_CHAPTERS = {
    "I": "HÀM SỐ LƯỢNG GIÁC VÀ PHƯƠNG TRÌNH LƯỢNG GIÁC",
    "II": "DÃY SỐ. CẤP SỐ CỘNG VÀ CẤP SỐ NHÂN",
    "III": "CÁC SỐ ĐẶC TRƯNG ĐO XU THẾ TRUNG TÂM CỦA MẪU SỐ LIỆU GHÉP NHÓM",
    "IV": "QUAN HỆ SONG SONG TRONG KHÔNG GIAN",
    "V": "GIỚI HẠN. HÀM SỐ LIÊN TỤC",
}

_LESSONS = [
    ("I", 1, "Giá trị lượng giác của góc lượng giác"),
    ("I", 2, "Công thức lượng giác"),
    ("I", 3, "Hàm số lượng giác"),
    ("I", 4, "Phương trình lượng giác cơ bản"),
    ("II", 5, "Dãy số"),
    ("II", 6, "Cấp số cộng"),
    ("II", 7, "Cấp số nhân"),
    ("III", 8, "Mẫu số liệu ghép nhóm"),
    ("III", 9, "Các số đặc trưng đo xu thế trung tâm"),
    ("IV", 10, "Đường thẳng và mặt phẳng trong không gian"),
    ("IV", 11, "Hai đường thẳng song song"),
    ("IV", 12, "Đường thẳng và mặt phẳng song song"),
    ("IV", 13, "Hai mặt phẳng song song"),
    ("IV", 14, "Phép chiếu song song"),
    ("V", 15, "Giới hạn của dãy số"),
    ("V", 16, "Giới hạn của hàm số"),
    ("V", 17, "Hàm số liên tục"),
]

_CHAP_RE = re.compile(r"^#+\s*CHƯƠNG\s+(I{1,3}|IV|V)\s+(?!\.)")
_THUAT_RE = re.compile(r"^#+\s*THU[ẤẬ]T\b")
_HEAD_RE = re.compile(r"^(#{1,6})\s*(.*)$")


def _is_toan11(text: str) -> bool:
    return all(m in text for m in _BOOK_MARKERS)


def _strip_heading(line: str) -> str:
    m = _HEAD_RE.match(line.strip())
    return m.group(2).strip() if m else line.strip()


def normalize_book_headings(text: str) -> str:
    """Chuẩn hoá heading để mục lục Word khớp cấu trúc sách.

    - Sách khác: chỉ hạ các heading rác phổ biến (Giải, Ví dụ, BÀI TẬP...).
    - Đúng Toán 11 KNTT: dựng lại Chương/Bài theo đúng mục lục gốc.
    """
    lines = text.split("\n")
    is_book = _is_toan11(text)

    # Hạ heading rác dùng chung cho mọi tài liệu toán
    _NOISE = re.compile(
        r"^(Giải|Ví dụ\b|Luyện tập\b|Chú [ýy]\b|Nhận xét\b|BÀI TẬP\b|"
        r"A\s*-\s*TRẮC NGHIỆM|B\s*-\s*TỰ LUẬN|Em có biết\?|MỤC TIÊU|"
        r"Chuẩn bị:|Thực hiện:|Bảng\s+\d+\.\d+|Kí hiệu tổng|Góc công nghệ|"
        r"THU[ẤẬ]T NG[ỮŨ]|KI[ẾÊ]N TH[ỨƯ]C)")
    if not is_book:
        for i, line in enumerate(lines):
            s = line.strip()
            if not s.startswith("#"):
                continue
            body = _strip_heading(s)
            if _NOISE.match(body):
                lines[i] = body
        return "\n".join(lines)

    # 1) Chương thật: "CHƯƠNG I <title>" (không có dấu chấm ngay sau số hiệu)
    chapter_starts: list[int] = []
    for i, line in enumerate(lines):
        m = _CHAP_RE.match(line.strip())
        if m:
            roman = m.group(1)
            lines[i] = f"# CHƯƠNG {roman}. {_CHAPTERS[roman]}"
            chapter_starts.append(i)

    first_chapter = chapter_starts[0] if chapter_starts else len(lines)

    # 2) Mục lục in trong sách + bìa: hạ thành text thường
    seen_cover: set[str] = set()
    for i, line in enumerate(lines):
        if i >= first_chapter:
            break
        s = line.strip()
        if not s.startswith("#"):
            continue
        body = _strip_heading(s)
        if body in ("TOÁN", "11", "TẬP MỘT"):
            if body in seen_cover:
                lines[i] = ""
            else:
                seen_cover.add(body)
                lines[i] = body
        elif body in ("HƯỚNG DẪN SỬ DỤNG SÁCH", "LỜI NÓI ĐẦU"):
            lines[i] = f"# {body}"
        else:
            lines[i] = body

    # 3) Mỗi bài bắt đầu bằng khối THUẬT NGỮ -> gắn lại "## Bài N. Tên bài"
    appendix = next(
        (i for i, l in enumerate(lines)
         if l.strip().startswith("#") and "HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM" in l),
        len(lines))

    lesson_iter = iter(_LESSONS)
    remove: set[int] = set()
    for ci, start in enumerate(chapter_starts):
        end = chapter_starts[ci + 1] if ci + 1 < len(chapter_starts) else appendix
        anchors = [i for i in range(start, end)
                   if _THUAT_RE.match(lines[i].strip())]
        for a in anchors:
            try:
                _ch, num, title = next(lesson_iter)
            except StopIteration:
                break

            title_idx = None
            for j in range(a - 1, max(start, a - 10), -1):
                s = lines[j].strip()
                if not s.startswith("#"):
                    continue
                body = _strip_heading(s)
                if re.match(r"^B[àa]i\b", body) or re.fullmatch(r"\d+", body):
                    remove.add(j)
                    continue
                if re.match(r"^(THU|KIẾN|KIÊN)", body):
                    continue
                if body and body == body.upper() and len(body) > 3:
                    title_idx = j
                    break

            new_head = f"## Bài {num}. {title}"
            if title_idx is not None:
                lines[title_idx] = new_head
            else:
                lines[a] = new_head + "\n" + lines[a]

    for i in remove:
        lines[i] = ""

    # Gộp lại vì phần chèn bài có thể tạo newline trong cùng một phần tử
    lines = "\n".join(lines).split("\n")

    # 3b) OCR làm mất heading "BÀI TẬP CUỐI CHƯƠNG" -> chèn lại trước A - TRẮC NGHIỆM
    chapter_starts = [i for i, l in enumerate(lines) if l.startswith("# CHƯƠNG ")]
    appendix = next(
        (i for i, l in enumerate(lines)
         if l.strip().startswith("#") and "HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM" in l),
        len(lines))
    inserts: list[tuple[int, str]] = []
    for ci, start in enumerate(chapter_starts):
        end = chapter_starts[ci + 1] if ci + 1 < len(chapter_starts) else appendix
        m_ch = re.match(r"^# CHƯƠNG (\S+)\.", lines[start])
        roman = m_ch.group(1) if m_ch else "?"
        has_bt = any(re.match(r"^#+\s*BÀI TẬP CUỐI CHƯƠNG", lines[i].strip(), re.I)
                     for i in range(start, end))
        if has_bt:
            continue
        last_trac = None
        for i in range(start, end):
            if re.match(r"^#+\s*A\s*-\s*TRẮC NGHIỆM", lines[i].strip()):
                last_trac = i
        if last_trac is not None:
            inserts.append((last_trac, f"## Bài tập cuối chương {roman}"))
    for idx, new_line in sorted(inserts, reverse=True):
        lines.insert(idx, new_line)

    chapter_starts = [i for i, l in enumerate(lines) if l.startswith("# CHƯƠNG ")]
    appendix = next(
        (i for i, l in enumerate(lines)
         if l.strip().startswith("#") and "HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM" in l),
        len(lines))

    # 4) Phụ lục cuối sách
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("#"):
            # bảng thuật ngữ có thể bị OCR thành dòng thường, không phải heading
            if s in ("BẢNG TRA CỨU THUẬT NGỮ", "Bảng tra cứu thuật ngữ"):
                lines[i] = "# Bảng tra cứu thuật ngữ"
            elif s in ("BẢNG GIẢI THÍCH THUẬT NGỮ", "Bảng giải thích thuật ngữ"):
                lines[i] = "# Bảng giải thích thuật ngữ"
            continue
        body = _strip_heading(s)
        if body == "HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM":
            lines[i] = "# HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM"
        elif body == "MỘT VÀI ÁP DỤNG CỦA TOÁN HỌC TRONG TÀI CHÍNH":
            lines[i] = "## Một vài áp dụng của Toán học trong tài chính"
        elif body == "LỰC CĂNG MẶT NGOÀI CỦA NƯỚC":
            lines[i] = "## Lực căng mặt ngoài của nước"
        elif body in ("BẢNG TRA CỨU THUẬT NGỮ", "Bảng tra cứu thuật ngữ"):
            lines[i] = "# Bảng tra cứu thuật ngữ"
        elif body in ("BẢNG GIẢI THÍCH THUẬT NGỮ", "Bảng giải thích thuật ngữ"):
            lines[i] = "# Bảng giải thích thuật ngữ"

    # 5) Hạ cấp các heading còn lại: mục 1. -> h3, a) -> h4, HĐ -> h4, còn lại -> text
    for i, line in enumerate(lines):
        s = line.strip()
        if not s.startswith("#"):
            continue
        lvl = len(s) - len(s.lstrip("#"))
        body = _strip_heading(s)
        if lvl == 1:
            if (body.startswith("CHƯƠNG ") or body in
                    ("HƯỚNG DẪN SỬ DỤNG SÁCH", "LỜI NÓI ĐẦU",
                     "HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM",
                     "Bảng tra cứu thuật ngữ", "Bảng giải thích thuật ngữ")):
                lines[i] = f"# {body}"
            else:
                lines[i] = body
            continue

        if re.fullmatch(r"Bài(\s+\d+)?", body) or re.fullmatch(r"\d+", body):
            lines[i] = ""          # mảnh "Bài"/"13" sót lại từ OCR
        elif re.match(r"^Bài \d+\.", body):
            lines[i] = f"## {body}"
        elif re.match(r"^BÀI TẬP CUỐI CHƯƠNG", body, re.IGNORECASE):
            body = re.sub(r"^BÀI TẬP CUỐI CHƯƠNG\s+", "Bài tập cuối chương ",
                          body, flags=re.IGNORECASE)
            lines[i] = f"## {body}"
        elif re.match(r"^\d+\.", body):
            lines[i] = f"### {body}"
        elif re.match(r"^[a-z]\)", body):
            lines[i] = f"#### {body}"
        elif re.match(r"^HĐ\d", body):
            lines[i] = f"#### {body}"
        elif body in ("Một vài áp dụng của Toán học trong tài chính",
                      "Lực căng mặt ngoài của nước"):
            lines[i] = f"## {body}"
        else:
            lines[i] = body

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mục lục tĩnh (điền sẵn) để Word/WPS/Pages đều thấy ngay, không bị trống.
# Số trang lấy đúng theo trang MỤC LỤC của bản in; khi người dùng bấm cập nhật
# field trong Word, Word sẽ thay bằng số trang thật của file DOCX.
# ---------------------------------------------------------------------------
_LESSON_PAGES = {
    1: 5, 2: 17, 3: 22, 4: 31,
    5: 42, 6: 48, 7: 52,
    8: 58, 9: 62,
    10: 70, 11: 78, 12: 84, 13: 88, 14: 95,
    15: 104, 16: 111, 17: 119,
}
_CHAPTER_BT_PAGES = {"I": 40, "II": 56, "III": 69, "IV": 102, "V": 123}


def toc_entries() -> list[tuple[int, str, str]]:
    """(cấp, tiêu đề, số trang bản in) — đúng như mục lục sách."""
    out: list[tuple[int, str, str]] = []
    for ch in ("I", "II", "III", "IV", "V"):
        out.append((1, f"CHƯƠNG {ch}. {_CHAPTERS[ch]}", ""))
        for c, n, title in _LESSONS:
            if c == ch:
                out.append((2, f"Bài {n}. {title}", str(_LESSON_PAGES[n])))
        out.append((2, f"Bài tập cuối chương {ch}", str(_CHAPTER_BT_PAGES[ch])))
    out.append((1, "HOẠT ĐỘNG THỰC HÀNH TRẢI NGHIỆM", ""))
    out.append((2, "Một vài áp dụng của Toán học trong tài chính", "124"))
    out.append((2, "Lực căng mặt ngoài của nước", "128"))
    out.append((1, "Bảng tra cứu thuật ngữ", "130"))
    out.append((1, "Bảng giải thích thuật ngữ", "131"))
    return out


def _toc_paragraph(level: int, text: str, page: str, tab_pos: int = 9026) -> str:
    from xml.sax.saxutils import escape

    indent = 0 if level == 1 else 360
    bold = "<w:b/>" if level == 1 else ""
    fonts = ('<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" '
             'w:cs="Times New Roman" w:eastAsia="Times New Roman"/>')
    body = (f'<w:r><w:rPr>{fonts}{bold}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')
    if page:
        body += (f'<w:r><w:rPr>{fonts}</w:rPr><w:tab/></w:r>'
                 f'<w:r><w:rPr>{fonts}</w:rPr><w:t>{escape(page)}</w:t></w:r>')
    return ('<w:p><w:pPr><w:tabs><w:tab w:val="right" w:leader="dot" '
            f'w:pos="{tab_pos}"/></w:tabs>'
            '<w:spacing w:before="0" w:after="60"/>'
            f'<w:ind w:left="{indent}"/></w:pPr>{body}</w:p>')


def finalize_docx_toc(docx_path) -> None:
    """Điền sẵn kết quả TOC + đưa mục lục ra sau bìa + đặt khổ A4."""
    import re
    import shutil
    import zipfile
    from pathlib import Path

    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path) as zin:
        items = [(i, zin.read(i.filename)) for i in zin.infolist()]
    xml = next(data for info, data in items if info.filename == "word/document.xml")
    x = xml.decode("utf-8")

    field_re = re.compile(
        r'<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/>'
        r'<w:instrText[^>]*>TOC[^<]*</w:instrText>'
        r'<w:fldChar w:fldCharType="separate"/>'
        r'<w:fldChar w:fldCharType="end"/></w:r></w:p>')
    m = field_re.search(x)
    if not m:
        return

    is_toan = ("TOÁN 11" in x and "TRI THỨC" in x)
    if is_toan:
        entries = "".join(_toc_paragraph(lvl, text, page)
                          for lvl, text, page in toc_entries())
        result = (
            '<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/>'
            '<w:instrText xml:space="preserve">TOC \\o "1-2" \\h \\z \\u</w:instrText>'
            '<w:fldChar w:fldCharType="separate"/></w:r></w:p>'
            + entries +
            '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')
        x = x[:m.start()] + result + x[m.end():]

    x = x.replace(
        '<w:p><w:pPr><w:pStyle w:val="TOCHeading"/></w:pPr>'
        '<w:r><w:t xml:space="preserve">MỤC LỤC</w:t></w:r></w:p>',
        '<w:p><w:pPr><w:pStyle w:val="TOCHeading"/>'
        '<w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/>'
        '<w:color w:val="C00000"/><w:sz w:val="40"/></w:rPr>'
        '<w:t xml:space="preserve">MỤC LỤC</w:t></w:r></w:p>')


    # Tách khối mục lục ra khỏi đầu tài liệu và chèn sau bìa (trước HƯỚNG DẪN)
    sdt_re = re.compile(
        r'<w:sdt><w:sdtPr><w:docPartObj>'
        r'<w:docPartGallery w:val="Table of Contents"/>.*?</w:sdt>', re.S)
    ms = sdt_re.search(x)
    if ms and not is_toan:
        x = x[:ms.start()] + x[ms.end():]      # sách khác: bỏ TOC trống
    elif ms and is_toan:
        block = ms.group(0)
        x = x[:ms.start()] + x[ms.end():]
        anchor = x.find("HƯỚNG DẪN SỬ DỤNG SÁCH")
        if anchor > 0:
            pstart = x.rfind("<w:p>", 0, anchor)
            brk = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
            x = x[:pstart] + brk + block + brk + x[pstart:]

    # Khổ A4 + lề 1 inch (sách gốc A4)
    if "<w:pgSz" not in x:
        x = x.replace(
            "<w:sectPr>",
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
            'w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>',
            1)

    tmp = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info, data in items:
            if info.filename == "word/document.xml":
                data = x.encode("utf-8")
            zout.writestr(info.filename, data)
    shutil.move(str(tmp), str(docx_path))


def render_cover_pages(pdf_path, out_dir, dpi: int = 150) -> list:
    """Render bìa thật từ PDF gốc: trang 2 (bìa màu) rồi trang 1 (ảnh bìa trong)."""
    from pathlib import Path

    import pymupdf

    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    out = []
    pages = ((1, "cover_title.jpg"), (0, "cover_photo.jpg")) \
        if "toan11" in pdf_path.stem.lower() else ((0, "cover_title.jpg"),)
    for idx, name in pages:
        dst = out_dir / name
        if not dst.exists() and idx < doc.page_count:
            pix = doc[idx].get_pixmap(dpi=dpi)
            pix.save(str(dst), jpg_quality=90)
        if dst.exists():
            out.append(dst.resolve())
    return out


_DATA_URI_RE = __import__("re").compile(
    r"!\[([^\]]*)\]\(\s*(data:image/([a-zA-Z0-9.+-]+);base64,([^)]*))\)",
    __import__("re").S)


def extract_data_images(markdown_text: str, out_dir) -> str:
    """Tách ảnh base64 ra file trước khi sửa text.

    Tránh việc các regex sửa tiếng Việt chạm vào chuỗi base64 (từng làm hỏng
    ảnh và biến cả khối base64 thành chữ trong DOCX).
    """
    import base64
    import hashlib
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def repl(m):
        alt, mime, payload = m.group(1), m.group(3).lower(), m.group(4)
        try:
            data = base64.b64decode(re.sub(r"\s+", "", payload), validate=False)
        except Exception:
            return m.group(0)
        ext = {"jpeg": "jpg", "jpg": "jpg", "png": "png",
               "webp": "webp", "gif": "gif"}.get(mime, "jpg")
        dst = out_dir / (hashlib.sha1(data).hexdigest()[:16] + "." + ext)
        if not dst.exists():
            dst.write_bytes(data)
        return f"![{alt}]({dst.resolve()})"

    return _DATA_URI_RE.sub(repl, markdown_text)
