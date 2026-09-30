"""Test DoD trên dữ liệu giả lập theo schema MinerU. Chạy: python -m tests.test_chunking"""
from llm.chunking import build_chunks
from llm.structured import markdown_to_raw, normalize_blocks
from llm.validate import validate_chunks

B64 = "data:image/png;base64," + "A1b2C3d4+/=" * 200


def fake_doc(tag: str):
    filler = "Đây là đoạn giải thích về định lý và chứng minh. " * 34
    return [
        {"type": "text", "text": f"Chương 1 {tag}", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "1.1 Giới hạn", "text_level": 2, "page_idx": 0},
        {"type": "text", "page_idx": 0,
         "text": filler + " Ta có $$ \\lim_{x \\to 0} \\frac{\\sin x}{x} = 1 $$ và tiếp theo $a+b$ là số. " + filler},
        {"type": "equation", "text": "$$\n\\int_0^1 x^2 dx = \\frac{1}{3}\n$$", "page_idx": 1},
        {"type": "image", "img_path": "images/a.jpg", "image_caption": [f"Hình {tag}"], "page_idx": 1},
        {"type": "text", "text": f"Ảnh nhúng ![x]({B64}) hết.", "page_idx": 1},
        {"type": "table", "table_body": "<table><tr><td>1</td></tr></table>",
         "table_caption": ["Bảng 1"], "page_idx": 2},
        {"type": "header", "text": "HEADER RÁC", "page_idx": 2},
        {"type": "page_number", "text": "3", "page_idx": 2},
    ]


def run(tag, doc_id):
    blocks = normalize_blocks(fake_doc(tag), source=f"{tag}.pdf", doc_id=doc_id)
    chunks = build_chunks(blocks, 1800, 250)
    return blocks, chunks, validate_chunks(chunks, f"{tag}.pdf", doc_id)


def test_all():
    for tag, did in (("docA", "aaaa"), ("docB", "bbbb")):
        blocks, chunks, rep = run(tag, did)
        assert rep["ok"], rep["problems"]
        assert all("data:image" not in c["text"] for c in chunks)
        assert all(c["source"] == f"{tag}.pdf" for c in chunks)
        assert all(c["page"] is not None for c in chunks)
        assert not any("HEADER RÁC" in c["text"] for c in chunks)
        joined = "\n".join(c["text"] for c in chunks)
        assert "\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1" in joined
        assert "\\int_0^1 x^2 dx" in joined
        assert max(c["n_chars"] for c in chunks) <= 1800 + 50
        print(f"{tag}: OK  chunks={rep['n_chunks']} formula_chunks={rep['n_with_formula']}")


def test_markdown_fallback():
    md = "# Tiêu đề\n\nĐoạn văn.\n\n$$\nx^2+y^2=z^2\n$$\n\n## Mục 2\n\nHết."
    blocks = normalize_blocks(markdown_to_raw(md), "m.pdf", "cccc")
    assert [b["content_type"] for b in blocks] == ["heading", "text", "formula", "heading", "text"]
    assert blocks[2]["formula_latex"] == "x^2+y^2=z^2"


if __name__ == "__main__":
    test_all(); test_markdown_fallback(); print("ALL PASSED")
