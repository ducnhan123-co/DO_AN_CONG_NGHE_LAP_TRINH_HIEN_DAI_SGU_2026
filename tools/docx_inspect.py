"""Mở DOCX như người dùng và tìm lỗi: lint tự động + ảnh từng trang DOCX cạnh trang PDF gốc.

    python3 tools/docx_inspect.py out.docx --pdf input.pdf --out /tmp/insp [--pages 1-4]

Ra: <out>/report.json, <out>/compare_p<N>.png (trái PDF gốc | phải DOCX dựng bằng docx-preview trong Chrome).
Lint bắt: TeX rò rỉ thành chữ, ký tự lỗi (ô vuông / vùng PUA), bảng rơi thành chuỗi đoạn 1-3 ký tự, mục lục rỗng,
từ có trong PDF mà DOCX thiếu. Cần: python-docx, PyMuPDF, Pillow, playwright (+ Chrome).
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

CDN = ('<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>'
       '<script src="https://cdn.jsdelivr.net/npm/docx-preview@0.3.7/dist/docx-preview.min.js"></script>')
TEX_LEAK = re.compile(r"\\(?:[A-Za-z]{2,}|[{}])|\$\$?|\\begin|\\end")
BAD_CHAR = re.compile("[\ue000-\uf8ff\ufffd\u25a1]")
M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def lint(docx_path: Path) -> dict:
    import docx
    d = docx.Document(str(docx_path))
    body = d.element.body
    paras = [(i, "".join(t.text or "" for t in p.iter(W_NS + "t"))) for i, p in enumerate(body.iter(W_NS + "p"))]
    issues = {"tex_leak": [], "bad_chars": [], "equation_leak": [], "table_fragments": [], "toc_empty": False}
    for i, txt in paras:
        if TEX_LEAK.search(txt):
            issues["tex_leak"].append({"p": i, "text": txt[:120]})
        if BAD_CHAR.search(txt):
            issues["bad_chars"].append({"p": i, "text": txt[:120]})
    for k, eq in enumerate(body.iter(M_NS + "oMath")):
        t = "".join(x.text or "" for x in eq.iter(M_NS + "t"))
        if re.search(r"\\[A-Za-z]{2,}|\$", t):
            issues["equation_leak"].append({"eq": k, "text": t[:120]})
    in_cell = {i for i, p in enumerate(body.iter(W_NS + "p")) if p.getparent().tag == W_NS + "tc"}
    run = 0                                                    # chuỗi dài đoạn 1-3 ký tự NGOÀI ô bảng = bảng mất cấu trúc
    for i, txt in paras:
        run = run + 1 if 0 < len(txt.strip()) <= 3 and i not in in_cell else 0
        if run == 8:
            issues["table_fragments"].append({"p": i, "text": "≥8 đoạn ngắn liên tiếp (bảng rơi thành chữ rời?)"})
    full = " ".join(t for _, t in paras)
    issues["toc_empty"] = "Table of Contents" in full and len(full) < 20000
    stats = {"paragraphs": len(paras), "equations": sum(1 for _ in body.iter(M_NS + "oMath")),
             "tables": sum(1 for _ in body.iter(W_NS + "tbl")), "images": len(d.inline_shapes)}
    return {"stats": stats, "issues": issues, "text": full}


def missing_words(pdf: Path, docx_text: str) -> dict:
    import fitz
    tok = lambda s: set(re.findall(r"[^\W\d_]{4,}", s.lower()))
    have, out = tok(docx_text), {}
    for n, page in enumerate(fitz.open(str(pdf)), 1):
        miss = sorted(tok(page.get_text()) - have)
        if miss:
            out[n] = {"count": len(miss), "sample": miss[:15]}
    return out


async def render(docx_path: Path, pdf: Path | None, out: Path, pages: range) -> list:
    import fitz
    from PIL import Image
    from playwright.async_api import async_playwright
    out.mkdir(parents=True, exist_ok=True)
    html = out / "_view.html"
    html.write_text(f'<!doctype html><meta charset=utf-8>{CDN}<input type=file id=f><div id=c></div>', encoding="utf-8")
    shots = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True)
        pg = await b.new_page(viewport={"width": 1000, "height": 1300})
        await pg.goto(f"file://{html}")
        await pg.wait_for_function("window.docx && window.JSZip")
        await pg.set_input_files("#f", str(docx_path))
        await pg.evaluate("document.getElementById('f').files[0].arrayBuffer().then(b=>docx.renderAsync(b,"
                          "document.getElementById('c'),null,{inWrapper:false,breakPages:true,ignoreWidth:false}))")
        await pg.wait_for_timeout(3000)
        secs = pg.locator("#c section.docx, #c article")
        n = await secs.count()
        for k in range(n):
            if (k + 1) in pages:
                f = out / f"docx_p{k + 1}.png"
                await secs.nth(k).screenshot(path=str(f))
                shots[k + 1] = f
        await b.close()
    pdfdoc = fitz.open(str(pdf)) if pdf else None
    for k, f in shots.items():
        right = Image.open(f).convert("RGB")
        if pdfdoc and k <= len(pdfdoc):
            pix = pdfdoc[k - 1].get_pixmap(dpi=90)
            left = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            h = max(left.height, right.height)
            canvas = Image.new("RGB", (left.width + right.width + 20, h), "white")
            canvas.paste(left, (0, 0)); canvas.paste(right, (left.width + 20, 0))
        else:
            canvas = right
        canvas.save(out / f"compare_p{k}.png")
    return sorted(shots)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", type=Path)
    ap.add_argument("--pdf", type=Path)
    ap.add_argument("--out", type=Path, default=Path("docx_inspect_out"))
    ap.add_argument("--pages", default="1-3", help="vd 1-4 hoặc 2")
    a = ap.parse_args()
    lo, _, hi = a.pages.partition("-")
    rng = range(int(lo), int(hi or lo) + 1)
    rep = lint(a.docx)
    text = rep.pop("text")
    if a.pdf:
        rep["missing_words_vs_pdf"] = missing_words(a.pdf, text)
    rep["rendered_pages"] = asyncio.run(render(a.docx, a.pdf, a.out, rng))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"stats": rep["stats"], **{k: (len(v) if isinstance(v, list) else v) for k, v in rep["issues"].items()},
                      "rendered": rep["rendered_pages"]}, ensure_ascii=False))
    for k, v in rep["issues"].items():
        if isinstance(v, list):
            for it in v[:6]:
                print(f"  [{k}]", it)
    for pgn, m in list(rep.get("missing_words_vs_pdf", {}).items())[:6]:
        print(f"  [thiếu so với PDF trang {pgn}] {m['count']} từ, vd: {m['sample'][:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
