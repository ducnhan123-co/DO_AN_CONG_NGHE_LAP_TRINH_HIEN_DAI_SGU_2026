# """MinerU content_list.json (hoặc Markdown fallback) -> structured_data.json chuẩn.

# Schema mỗi block:
#   block_id, doc_id, source, page (1-based | None), section ("A > B"),
#   content_type (heading|text|formula|table|image|list|code),
#   text, formula_latex, image_path
# """
# import json
# import re
# from pathlib import Path
# from typing import Dict, List, Optional

# BASE64_RE = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+")
# EMPTY_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*\)")
# SKIP_TYPES = {"header", "footer", "page_number", "aside_text", "page_footnote"}


# def clean_text(s) -> str:
#     if not s:
#         return ""
#     s = BASE64_RE.sub("", str(s))          # <-- fix base64 chui vào chunk
#     s = EMPTY_IMG_RE.sub("", s)
#     return s.strip()


# def strip_math_delims(s: str) -> str:
#     s = s.strip()
#     for a, b in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
#         if len(s) >= len(a) + len(b) and s.startswith(a) and s.endswith(b):
#             return s[len(a):len(s) - len(b)].strip()
#     return s


# def _join(v) -> str:
#     if not v:
#         return ""
#     if isinstance(v, str):
#         return clean_text(v)
#     return clean_text(" ".join(str(x) for x in v))


# def normalize_blocks(raw: List[Dict], source: str, doc_id: str) -> List[Dict]:
#     blocks: List[Dict] = []
#     stack: Dict[int, str] = {}
#     section = "Document"

#     def add(page, ctype, text, latex=None, img=None):
#         blocks.append({
#             "block_id": len(blocks), "doc_id": doc_id, "source": source,
#             "page": page, "section": section, "content_type": ctype,
#             "text": text, "formula_latex": latex, "image_path": img,
#         })

#     for item in raw:
#         t = item.get("type", "text")
#         if t in SKIP_TYPES:
#             continue
#         pidx = item.get("page_idx")
#         page = pidx + 1 if isinstance(pidx, int) else None

#         if t == "text":
#             text = clean_text(item.get("text"))
#             if not text:
#                 continue
#             level = item.get("text_level")
#             if level:
#                 stack = {k: v for k, v in stack.items() if k < level}
#                 stack[level] = text
#                 section = " > ".join(stack[k] for k in sorted(stack))
#                 add(page, "heading", text)
#             else:
#                 add(page, "text", text)
#         elif t == "equation":
#             text = clean_text(item.get("text"))
#             latex = strip_math_delims(text) if text else None
#             add(page, "formula", text, latex, item.get("img_path"))
#         elif t == "table":
#             parts = [_join(item.get("table_caption")),
#                      clean_text(item.get("table_body")),
#                      _join(item.get("table_footnote"))]
#             add(page, "table", "\n".join(p for p in parts if p),
#                 img=item.get("img_path"))
#         elif t == "image":
#             add(page, "image", _join(item.get("image_caption")),
#                 img=item.get("img_path"))
#         elif t == "list":
#             items = item.get("list_items") or []
#             text = "\n".join("- " + clean_text(i) for i in items if clean_text(i))
#             if text:
#                 add(page, "list", text)
#         elif t == "code":
#             text = clean_text(item.get("code_body") or item.get("text"))
#             if text:
#                 add(page, "code", text)
#         else:  # type lạ: giữ nếu có text
#             text = clean_text(item.get("text"))
#             if text:
#                 add(page, "text", text)
#     return blocks


# def markdown_to_raw(md: str) -> List[Dict]:
#     """Fallback khi không có content_list.json: tách heading / $$..$$ / bảng / đoạn."""
#     raw: List[Dict] = []
#     lines = md.splitlines()
#     i, para = 0, []

#     def flush_para():
#         if para:
#             txt = "\n".join(para).strip()
#             if txt.startswith(("<table", "|")):
#                 raw.append({"type": "table", "table_body": txt})
#             elif txt:
#                 raw.append({"type": "text", "text": txt})
#             para.clear()

#     while i < len(lines):
#         ln = lines[i]
#         m = re.match(r"^(#{1,6})\s+(.*)", ln)
#         if m:
#             flush_para()
#             raw.append({"type": "text", "text": m.group(2).strip(),
#                         "text_level": len(m.group(1))})
#         elif ln.strip().startswith("$$"):
#             flush_para()
#             buf = [ln]
#             if not (ln.strip().endswith("$$") and len(ln.strip()) > 2):
#                 i += 1
#                 while i < len(lines):
#                     buf.append(lines[i])
#                     if lines[i].strip().endswith("$$"):
#                         break
#                     i += 1
#             raw.append({"type": "equation", "text": "\n".join(buf)})
#         elif not ln.strip():
#             flush_para()
#         else:
#             para.append(ln)
#         i += 1
#     flush_para()
#     return raw


# def load_raw(content_list_path: Optional[Path], md_path: Optional[Path]) -> List[Dict]:
#     if content_list_path:
#         data = json.loads(Path(content_list_path).read_text(encoding="utf-8"))
#         if isinstance(data, list):
#             return data
#     if md_path:
#         print("[structured] Không có content_list.json -> fallback Markdown (không có page).")
#         return markdown_to_raw(Path(md_path).read_text(encoding="utf-8"))
#     raise FileNotFoundError("Không có content_list.json lẫn Markdown.")


# def save_structured(blocks: List[Dict], path: Path) -> Path:
#     path.write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
#     return path

"""MinerU content_list.json (hoặc Markdown fallback) -> structured_data.json chuẩn.

Schema mỗi block:
  block_id, doc_id, source, page (1-based | None), section ("A > B"),
  content_type (heading|text|formula|table|image|list|code),
  text, formula_latex, image_path
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

BASE64_RE = re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+")
EMPTY_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*\)")
SKIP_TYPES = {"header", "footer", "page_number", "aside_text", "page_footnote"}


def clean_text(s) -> str:
    if not s:
        return ""
    s = BASE64_RE.sub("", str(s))          # <-- fix base64 chui vào chunk
    s = EMPTY_IMG_RE.sub("", s)
    return s.strip()


def strip_math_delims(s: str) -> str:
    s = s.strip()
    for a, b in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if len(s) >= len(a) + len(b) and s.startswith(a) and s.endswith(b):
            return s[len(a):len(s) - len(b)].strip()
    return s


def _join(v) -> str:
    if not v:
        return ""
    if isinstance(v, str):
        return clean_text(v)
    return clean_text(" ".join(str(x) for x in v))


def normalize_blocks(raw: List[Dict], source: str, doc_id: str) -> List[Dict]:
    blocks: List[Dict] = []
    stack: Dict[int, str] = {}
    section = "Document"

    def add(page, ctype, text, latex=None, img=None):
        blocks.append({
            "block_id": len(blocks), "doc_id": doc_id, "source": source,
            "page": page, "section": section, "content_type": ctype,
            "text": text, "formula_latex": latex, "image_path": img,
        })

    for item in raw:
        t = item.get("type", "text")
        if t in SKIP_TYPES:
            continue
        pidx = item.get("page_idx")
        page = pidx + 1 if isinstance(pidx, int) else None

        if t == "text":
            text = clean_text(item.get("text"))
            if not text:
                continue
            level = item.get("text_level")
            if level:
                stack = {k: v for k, v in stack.items() if k < level}
                stack[level] = text
                section = " > ".join(stack[k] for k in sorted(stack))
                add(page, "heading", text)
            else:
                add(page, "text", text)
        elif t == "equation":
            text = clean_text(item.get("text"))
            latex = strip_math_delims(text) if text else None
            add(page, "formula", text, latex, item.get("img_path"))
        elif t == "table":
            parts = [_join(item.get("table_caption")),
                     clean_text(item.get("table_body")),
                     _join(item.get("table_footnote"))]
            add(page, "table", "\n".join(p for p in parts if p),
                img=item.get("img_path"))
        elif t == "image":
            add(page, "image", _join(item.get("image_caption")),
                img=item.get("img_path"))
        elif t == "list":
            items = item.get("list_items") or []
            text = "\n".join("- " + clean_text(i) for i in items if clean_text(i))
            if text:
                add(page, "list", text)
        elif t == "code":
            text = clean_text(item.get("code_body") or item.get("text"))
            if text:
                add(page, "code", text)
        else:  # type lạ: giữ nếu có text
            text = clean_text(item.get("text"))
            if text:
                add(page, "text", text)
    return blocks


def markdown_to_raw(md: str) -> List[Dict]:
    """Fallback khi không có content_list.json: tách heading / $$..$$ / bảng / đoạn."""
    raw: List[Dict] = []
    lines = md.splitlines()
    i, para = 0, []

    def flush_para():
        if para:
            txt = "\n".join(para).strip()
            if txt.startswith(("<table", "|")):
                raw.append({"type": "table", "table_body": txt})
            elif txt:
                raw.append({"type": "text", "text": txt})
            para.clear()

    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            flush_para()
            raw.append({"type": "text", "text": m.group(2).strip(),
                        "text_level": len(m.group(1))})
        elif ln.strip().startswith("$$"):
            flush_para()
            buf = [ln]
            if not (ln.strip().endswith("$$") and len(ln.strip()) > 2):
                i += 1
                while i < len(lines):
                    buf.append(lines[i])
                    if lines[i].strip().endswith("$$"):
                        break
                    i += 1
            raw.append({"type": "equation", "text": "\n".join(buf)})
        elif not ln.strip():
            flush_para()
        else:
            para.append(ln)
        i += 1
    flush_para()
    return raw


def load_raw(content_list_path: Optional[Path], md_path: Optional[Path],
            md_text: Optional[str] = None) -> List[Dict]:
    """md_text (tuỳ chọn): nội dung Markdown đã fix sẵn (vd. fix_legacy_tex_bf
    trong build_docx.py), dùng thay vì đọc lại md_path từ đĩa, để DOCX và RAG
    dùng chung một bản dữ liệu sạch thay vì lệch nhau."""
    if content_list_path:
        data = json.loads(Path(content_list_path).read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    if md_text is not None or md_path:
        print("[structured] Không có content_list.json -> fallback Markdown (không có page).")
        text = md_text if md_text is not None else Path(md_path).read_text(encoding="utf-8")
        return markdown_to_raw(text)
    raise FileNotFoundError("Không có content_list.json lẫn Markdown.")


def save_structured(blocks: List[Dict], path: Path) -> Path:
    path.write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    return path