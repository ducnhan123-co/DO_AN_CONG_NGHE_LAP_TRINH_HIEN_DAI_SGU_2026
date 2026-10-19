"""`mineru-kit parse` GIẢ LẬP — chỉ để dev giao diện / chạy test mà không cần tải model MinerU.

    MINERU_CMD="python tests/fake_mineru_kit.py"  python run.py

Nhận cùng tham số như lệnh thật:  parse <pdf> -o <out_dir> --tier <tier>
Sinh Markdown (có công thức LaTeX) cho mỗi trang của PDF vào <out_dir>/<tên_pdf>/auto/<tên_pdf>.md.

Biến môi trường điều khiển giả lập:
  FAKE_SLEEP=3            số giây "xử lý" (mặc định 1)
  FAKE_FAIL=1             luôn thoát với mã lỗi 3
  FAKE_FAIL_ONCE=<file>   nếu file này tồn tại: xóa nó rồi thoát lỗi (để thử nút "Thử lại")
"""
import argparse
import os
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--tier", default="advanced")
    args, _ = ap.parse_known_args()

    print(f"fake mineru-kit: parse {args.pdf} tier={args.tier}", flush=True)
    time.sleep(float(os.environ.get("FAKE_SLEEP", "1")))

    once = os.environ.get("FAKE_FAIL_ONCE")
    if os.environ.get("FAKE_FAIL") == "1" or (once and Path(once).exists()):
        if once and Path(once).exists():
            Path(once).unlink()
        print("fake mineru-kit: giả lập lỗi", file=sys.stderr, flush=True)
        return 3

    from pypdf import PdfReader
    pdf = Path(args.pdf)
    n = len(PdfReader(str(pdf)).pages)
    out = Path(args.output) / pdf.stem / "auto"
    out.mkdir(parents=True, exist_ok=True)
    parts = []
    for i in range(1, n + 1):
        parts.append(
            f"# Chương {i}: Đạo hàm và tích phân\n\n"
            f"Định nghĩa {i}. Cho hàm số $f(x)=x^{{{i}}}+1$ xác định trên $\\mathbb{{R}}$. "
            f"Đạo hàm của $f$ tại $x_0$ là giới hạn của tỉ số sau:\n\n"
            f"$$ f'(x_0)=\\lim_{{h\\to 0}}\\frac{{f(x_0+h)-f(x_0)}}{{h}} $$\n\n"
            f"Ví dụ {i}. Tính $\\int_0^1 x^{i}\\,dx = \\frac{{1}}{{{i + 1}}}$.\n")
    (out / f"{pdf.stem}.md").write_text("\n".join(parts), encoding="utf-8")
    print(f"Parsed 1 input(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
