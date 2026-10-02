"""MinerU content_list -> công thức + ngữ cảnh; tìm kiếm FTS5 an toàn."""
import re

SKIP = {"header", "footer", "page_number", "aside_text", "page_footnote"}
MAX_FORMULAS = 500
CTX_CHARS = 300


def _strip_delims(text: str) -> str:
    text = (text or "").strip()
    for left, right in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if len(text) >= len(left) + len(right) and text.startswith(left) and text.endswith(right):
            return text[len(left):len(text) - len(right)].strip()
    return text


def parse_content_list(items: list[dict]) -> list[dict]:
    stack: dict[int, str] = {}
    section, last_text, waiting, out = "", "", [], []
    for item in items:
        kind = item.get("type", "text")
        if kind in SKIP:
            continue
        page_idx = item.get("page_idx")
        if kind == "text":
            text = (item.get("text") or "").strip()
            if not text:
                continue
            level = item.get("text_level")
            if level:
                stack = {k: v for k, v in stack.items() if k < level}
                stack[level] = text
                section = " > ".join(stack[k] for k in sorted(stack))
                continue
            for formula in waiting:
                formula["ctx_after"] = text[:CTX_CHARS]
            waiting, last_text = [], text
        elif kind == "equation" and len(out) < MAX_FORMULAS:
            latex = _strip_delims(item.get("text"))
            if not latex:
                continue
            formula = {"page": page_idx + 1 if isinstance(page_idx, int) else None, "section": section,
                       "latex": latex, "ctx_before": last_text[-CTX_CHARS:], "ctx_after": ""}
            out.append(formula)
            waiting.append(formula)
    return out


def fts_query(question: str) -> str | None:
    """Tách token chữ/số, bọc nháy kép rồi nối OR -> không dính cú pháp FTS5."""
    tokens = list(dict.fromkeys(re.findall(r"\w{2,}", (question or "").lower())))[:12]
    return " OR ".join(f'"{token}"' for token in tokens) or None
