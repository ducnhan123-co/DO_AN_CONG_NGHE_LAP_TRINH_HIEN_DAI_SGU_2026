"""Vá chỗ MinerU làm mất / nhận dạng hỏng trên trang SCAN (không có lớp chữ) khi dựng DOCX.

Đã gặp (ảnh in sẵn, vở viết tay, cheat-sheet chụp):
  - MinerU bỏ hẳn một dòng chữ (vd "and there was light." cuối trang)        -> recover_gap_text(): OCR vùng bị bỏ sót
  - MinerU trả khối chữ RỖNG/quá thưa cho cả nửa trang (chữ viết tay)         -> swap_unreadable_blocks(): chèn ảnh cắt từ PDF gốc
Chỉ động vào trang không có lớp chữ; PDF chữ thật không bị đổi gì. Thiếu cv2/tesseract thì bỏ qua, không lỗi.
Chỉ ảnh hưởng DOCX (RAG vẫn dùng chữ MinerU như cũ).
"""
import functools
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

KEEP = ("text", "equation", "table", "image")
MAX_OCR = 60         # trần số vùng OCR mỗi tài liệu: sách scan dài không được kéo DOCX chậm hàng chục phút
MIN_CONF = 80        # ngưỡng tin cậy OCR để chèn chữ khôi phục (đo: đúng >= 86, rác <= 73)


def crop_region(pdf: str, page: int, bbox: list, out_png: Path, dpi: int = 200, pad: float = 4) -> bool:
    """Cắt vùng bbox (chuẩn hoá 0-1000) của trang PDF ra PNG."""
    try:
        import fitz
        pg = fitz.open(pdf)[page]
        r = pg.rect
        clip = fitz.Rect(r.x0 + bbox[0] / 1000 * r.width - pad, r.y0 + bbox[1] / 1000 * r.height - pad,
                         r.x0 + bbox[2] / 1000 * r.width + pad, r.y0 + bbox[3] / 1000 * r.height + pad) & r
        out_png.parent.mkdir(parents=True, exist_ok=True)
        pg.get_pixmap(dpi=dpi, clip=clip).save(str(out_png))
        return True
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def _lang() -> str:
    try:
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True).stdout.split()
    except OSError:
        return ""
    return "vie+eng" if "vie" in out and "eng" in out else ("eng" if "eng" in out else "")


def _ocr_png(png: Path):
    """-> (văn bản, độ tin cậy trung bình 0-100 của tesseract). Đo: dòng đúng >= 86, dòng rác 58-73."""
    lang = _lang()
    if not lang:
        return "", 0.0
    out = subprocess.run(["tesseract", str(png), "stdout", "-l", lang, "--psm", "6", "tsv"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.splitlines()[1:]
    lines, confs = {}, []
    for ln in out:
        c = ln.split("\t")
        if len(c) >= 12 and c[11].strip() and float(c[10]) >= 0:
            lines.setdefault(tuple(c[2:5]), []).append(c[11].strip())
            confs.append(float(c[10]))
    return "\n".join(" ".join(w) for w in lines.values()), (sum(confs) / len(confs) if confs else 0.0)


def _is_scan_page(page) -> bool:
    return len(page.get_text().strip()) < 20


def find_gaps(page, blocks: List[list], dpi: int = 100) -> List[list]:
    """Vùng có chữ/nét mực mà KHÔNG khối MinerU nào phủ -> [bbox 0-1000]. Bỏ qua mép trang (bóng/viền ảnh chụp)."""
    import cv2
    import fitz
    import numpy as np
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    g = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    h, w = g.shape
    ink = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    for b in blocks:   # che vùng MinerU đã xử lý (+ lề 1.5%)
        x0, y0, x1, y1 = (int(max(0, v / 1000 - m) * s) for v, m, s in
                          ((b[0], .015, w), (b[1], .015, h), (b[2], -.015, w), (b[3], -.015, h)))
        ink[y0:y1, x0:x1] = 0
    merged = cv2.dilate(ink, cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * .05), int(h * .012))))
    n, _, stats, _ = cv2.connectedComponentsWithStats(merged)
    out, edge = [], .015
    for i in range(1, n):
        x, y, cw, ch, _ = stats[i]
        if cw < .08 * w or ch < .012 * h or x < edge * w or y < edge * h or x + cw > (1 - edge) * w or y + ch > (1 - edge) * h:
            continue
        if ink[y:y + ch, x:x + cw].mean() / 255 < .02:      # toàn bụi
            continue
        out.append([round(x / w * 1000), round(y / h * 1000), round((x + cw) / w * 1000), round((y + ch) / h * 1000)])
    return sorted(out, key=lambda b: b[1])


def _locate(md: str, it: dict, pos: int = 0) -> Optional[re.Match]:
    tok = re.sub(r"\s+", " ", re.sub(r"^\$\$|\$\$$", "", (it.get("text") or "").strip())).split()[:6]
    if not tok or len(" ".join(tok)) < 4:
        return None
    return re.compile(r"\s+".join(re.escape(x) for x in tok)).search(md, pos)


def _span(md: str, it: dict, pos: int = 0):
    """(đầu, cuối) của khối `it` trong md: khớp 6 từ đầu rồi 6 từ cuối. None nếu không thấy."""
    m = _locate(md, it, pos)
    if not m:
        return None
    tok = re.sub(r"\s+", " ", (it.get("text") or "").strip()).split()[-6:]
    e = re.compile(r"\s+".join(re.escape(x) for x in tok)).search(md, m.start())
    return m.start(), (e.end() if e else m.end())


def recover_gap_text(md: str, items: List[dict], pdf: Path, work_dir: Path) -> str:
    """OCR các vùng của trang scan mà MinerU bỏ sót, chèn vào Markdown đúng thứ tự đọc (trước khối kế tiếp trên trang)."""
    try:
        import fitz
        doc = fitz.open(str(pdf))
    except Exception:  # noqa: BLE001
        return md
    if not _lang():
        return md
    found, tried, inserts = 0, 0, []
    for pi, page in enumerate(doc):
        if not _is_scan_page(page):
            continue
        on_page = [it for it in items if it.get("page_idx") == pi and it.get("bbox")]
        try:
            gaps = find_gaps(page, [it["bbox"] for it in on_page])
        except Exception:  # noqa: BLE001 - thiếu cv2 / lỗi render
            continue
        for k, gb in enumerate(gaps):
            if tried >= MAX_OCR:
                break
            tried += 1
            png = work_dir / f"gap_{pi}_{k}.png"
            if not crop_region(str(pdf), pi, gb, png, dpi=300, pad=6):
                continue
            text, conf = _ocr_png(png)
            text = text.lstrip("| ")
            alnum = sum(c.isalnum() for c in text)
            if conf < MIN_CONF or alnum < 4 or alnum < .5 * len(re.sub(r"\s", "", text)):    # rác/nét vẽ/đọc không chắc -> bỏ
                continue
            nxt = next((it for it in on_page if it["type"] in KEEP and it["bbox"][1] >= gb[1] and _locate(md, it)), None)
            at = None
            if nxt:
                m = _locate(md, nxt)
                at = md.rfind("\n", 0, m.start()) + 1
                if md.count("$$", 0, at) % 2:      # không chèn vào giữa khối $$ ... $$
                    at = None
            inserts.append((len(md) if at is None else at, "\n\n" + text + "\n\n"))
            found += 1
    for at, t in sorted(inserts, key=lambda x: -x[0]):
        md = md[:at] + t + md[at:]
    if found:
        print(f"[DOCX] khôi phục {found} dòng chữ MinerU bỏ sót trên trang scan (OCR)")
    return md


def swap_unreadable_blocks(md: str, items: List[dict], pdf: Path, work_dir: Path) -> str:
    """Khối chữ lớn trên trang scan mà MinerU trả RỖNG hoặc thưa bất thường (chữ viết tay) -> ảnh cắt từ PDF gốc,
    thay vì mất nội dung / để chữ rác. Thưa = ký tự nhận được < 25% số ký tự kỳ vọng của vùng đó ở cỡ chữ 10pt."""
    try:
        import fitz
        doc = fitz.open(str(pdf))
    except Exception:  # noqa: BLE001
        return md
    scan = {i for i, p in enumerate(doc) if _is_scan_page(p)}
    def _frac(it):
        b = it["bbox"]
        return (b[2] - b[0]) * (b[3] - b[1]) / 1e6

    def _bad(it):
        r = doc[it["page_idx"]].rect
        alnum = sum(c.isalnum() for c in (it.get("text") or ""))
        f = _frac(it)
        return (not (it.get("text") or "").strip() and f >= .03) or (f >= .12 and alnum < .25 * f * r.width * r.height / 85)

    # trang scan có khối thân bài hỏng = chữ viết tay: mọi khối thân bài lớn của trang đó đều không tin được -> ảnh hết, khỏi lẫn chữ rác với ảnh
    hand = {it["page_idx"] for it in items if it.get("type") == "text" and it.get("bbox") and it.get("page_idx") in scan
            and _frac(it) >= .12 and _bad(it)}
    pos, n, swaps = 0, 0, []
    for it in items:
        if it.get("type") not in KEEP or not it.get("bbox"):
            continue
        pi = it.get("page_idx")
        sp = _span(md, it, pos)
        if sp:
            pos = sp[1]
        if it["type"] != "text" or pi not in scan:
            continue
        b, txt = it["bbox"], (it.get("text") or "").strip()
        if not (_bad(it) or (pi in hand and _frac(it) >= .12)):
            continue
        png = work_dir / "crops" / f"unreadable_{n}.png"
        if not crop_region(str(pdf), pi, b, png):
            continue
        n += 1
        img = f"\n\n![]({png})\n\n"
        swaps.append((sp[0], sp[1], img) if (txt and sp) else (pos, pos, img))
    for a, z, img in sorted(swaps, key=lambda x: -x[0]):
        md = md[:a] + img + md[z:]
    if n:
        print(f"[DOCX] {n} khối chữ quá thưa/rỗng trên trang scan -> dùng ảnh cắt từ PDF gốc")
    return md
