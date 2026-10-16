"""Giả lập `mineru-kit parse <pdf> -o <dir> --tier T [-f zip] --ocr-mode M` cho test (không cần cài MinerU).

Đọc chữ từng trang của PDF đầu vào (pypdf) -> markdown (+ công thức + ảnh).
  * không có `-f zip` (cách rag_toan đang gọi): ghi <dir>/<tên pdf>.md, ảnh NHÚNG BASE64, không có thư mục images/
  * có `-f zip`: đóng gói zip (markdown.md, images/, structured_content.json)
Điều khiển bằng biến môi trường:
  FAKE_MINERU_DELAY_PER_PAGE  giây ngủ mỗi trang (mặc định 0.01)
  FAKE_MINERU_FAIL_FILE       file chứa số lần còn phải lỗi (giảm 1 mỗi lần gọi) -> mô phỏng lỗi tạm thời
  FAKE_MINERU_EXIT            mã thoát sau khi đã ghi zip (mô phỏng lỗi telemetry của onnxruntime)
  FAKE_MINERU_LOG_FILE        ghi thêm 1 dòng mỗi lần gọi (để test đếm số tiến trình chạy cùng lúc)
"""
import base64
import io
import os
import sys
import time
import zipfile
from pathlib import Path

from pypdf import PdfReader


def _log(event: str, name: str) -> None:
    log_file = os.environ.get("FAKE_MINERU_LOG_FILE")
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"{event} {name} {time.time():.3f}\n")


def main() -> int:
    pdf_name = Path(sys.argv[2]).name if len(sys.argv) > 2 else "?"
    _log("start", pdf_name)
    try:
        return _run()
    finally:
        _log("end", pdf_name)


def _run() -> int:
    a = sys.argv[1:]
    assert a and a[0] == "parse", a
    pdf = Path(a[1])
    out = Path(a[a.index("-o") + 1])
    out.mkdir(parents=True, exist_ok=True)

    fail_file = os.environ.get("FAKE_MINERU_FAIL_FILE")
    if fail_file and Path(fail_file).exists():
        left = int(Path(fail_file).read_text().strip() or "0")
        if left > 0:
            Path(fail_file).write_text(str(left - 1))
            print("FAKE MinerU: lỗi giả lập", file=sys.stderr)
            return 1

    reader = PdfReader(str(pdf))
    delay = float(os.environ.get("FAKE_MINERU_DELAY_PER_PAGE", "0.01"))
    zip_mode = "-f" in a and a[a.index("-f") + 1] == "zip"
    parts, images = [], {}
    for i, page in enumerate(reader.pages, 1):
        time.sleep(delay)
        text = (page.extract_text() or "").strip().replace("\n", " ")
        jpg = _tiny_jpeg(i)
        ref = f"images/page_{i}_image_1.jpg" if zip_mode else "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
        parts.append(f"## {text[:40]}\n\n{text} Công thức $x_{i}^2+y^2=z^2$.\n\n$$\n\\frac{{a_{i}}}{{b}}=c\n$$\n\n![]({ref})\n")
        images[f"page_{i}_image_1.jpg"] = jpg
    if not zip_mode:
        (out / f"{pdf.stem}.md").write_text("\n".join(parts), encoding="utf-8")
        print(f"Parsed 1 input(s): {len(reader.pages)} trang")
        return int(os.environ.get("FAKE_MINERU_EXIT", "0"))
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("markdown.md", "\n".join(parts))
        z.writestr("structured_content.json", '{"pages": []}')
        for name, data in images.items():
            z.writestr(f"images/{name}", data)
    (out / "result.zip").write_bytes(zbuf.getvalue())
    print(f"FAKE MinerU: {len(reader.pages)} trang")
    return int(os.environ.get("FAKE_MINERU_EXIT", "0"))


def _tiny_jpeg(seed: int) -> bytes:
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (24, 16), (seed * 37 % 255, 120, 200)).save(buf, "JPEG")
        return buf.getvalue()
    except ImportError:
        return b"\xff\xd8\xff\xd9"


if __name__ == "__main__":
    sys.exit(main())
