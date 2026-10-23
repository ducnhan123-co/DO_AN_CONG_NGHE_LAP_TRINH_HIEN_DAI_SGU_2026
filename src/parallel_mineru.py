"""Chạy MinerU SONG SONG nhiều tiến trình (mặc định 2) cho 1 file PDF.

Ý tưởng:
  - PDF N trang được chia thành `workers` dải trang LIÊN TIẾP, bắt đầu từ trang 1.
    Ví dụ PDF 200 trang, 2 tiến trình:
        phần 1: trang   1 - 100
        phần 2: trang 101 - 200
    Nếu không chia hết (vd. 203 trang) thì phần đầu nhận thêm 1 trang:
        102 + 101.
  - Mỗi phần được cắt ra thành 1 PDF nhỏ, rồi chạy `mineru-kit parse` trong
    1 tiến trình riêng (các tiến trình OS chạy cùng lúc).
  - Khi các phần xong, GHÉP lại theo đúng thứ tự trang:
        * Markdown: nối phần 1 -> N
        * content_list.json: cộng offset vào `page_idx` để số trang vẫn đúng
          với PDF gốc (RAG vẫn trả đúng page)
        * ảnh: gom về 1 thư mục images/, đổi tên thêm tiền tố p<k>_ để không
          trùng tên, đồng thời sửa đường dẫn trong Markdown + content_list.json
  - Kết quả ghép được ghi vào `out_dir` y như khi chạy MinerU 1 lần, nên
    find_mineru_outputs(), find_content_list(), prepare_work_md()... ở phía sau
    KHÔNG cần sửa gì.

Có cơ chế "resume": phần nào đã chạy xong (có file .done) sẽ được bỏ qua ở lần
chạy sau, trừ khi force=True. Nếu 1 phần lỗi, các phần còn lại vẫn được giữ.
"""
import json
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pypdf import PdfReader, PdfWriter

from src.run_mineru import find_content_list

IMG_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
DONE_MARK = ".done"

_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _find_md(d: Path):
    """File .md lớn nhất trong thư mục (None nếu chưa có)."""
    mds = [p for p in d.rglob("*.md") if p.is_file()]
    return max(mds, key=lambda p: p.stat().st_size) if mds else None


def _part_finished(part_out: Path) -> bool:
    """Phần này đã chạy XONG thành công ở lần trước chưa?

    mineru-kit (tier advanced) chỉ xuất .md (ảnh nhúng base64), KHÔNG có
    *_content_list.json, nên không dùng content_list làm tiêu chí thành công.
    Tiêu chí: có .md và (có file .done, hoặc log ghi 'Parsed N input(s)').
    """
    if _find_md(part_out) is None:
        return False
    if (part_out / DONE_MARK).exists():
        return True
    log = part_out / "mineru_log.txt"
    if log.exists():
        txt = log.read_text(encoding="utf-8", errors="ignore")
        return re.search(r"^Parsed \d+ input", txt, re.M) is not None
    return False


# --------------------------------------------------------------------------- #
# 1. Chia trang
# --------------------------------------------------------------------------- #
def split_page_ranges(total_pages: int, n_parts: int) -> List[Tuple[int, int]]:
    """Chia `total_pages` thành tối đa `n_parts` dải liên tiếp, bắt đầu từ trang đầu.

    Trả về list (start, end) theo chỉ số trang 0-based, end là EXCLUSIVE.
    Các dải đầu nhận thêm 1 trang nếu không chia hết. Không bao giờ trả dải rỗng.
    """
    n_parts = max(1, min(n_parts, total_pages))
    base, extra = divmod(total_pages, n_parts)
    ranges, start = [], 0
    for k in range(n_parts):
        size = base + (1 if k < extra else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def split_pdf(pdf_path: Path, ranges: List[Tuple[int, int]], parts_dir: Path) -> List[Path]:
    """Cắt PDF gốc thành các file nhỏ theo `ranges`. Bỏ qua phần đã cắt rồi."""
    parts_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))
    out_files = []
    for k, (s, e) in enumerate(ranges):
        part_pdf = parts_dir / f"part_{k + 1}_p{s + 1}-{e}.pdf"
        if not part_pdf.exists():
            writer = PdfWriter()
            for i in range(s, e):
                writer.add_page(reader.pages[i])
            with open(part_pdf, "wb") as f:
                writer.write(f)
        out_files.append(part_pdf)
    return out_files


# --------------------------------------------------------------------------- #
# 2. Chạy 1 phần (1 tiến trình mineru-kit)
# --------------------------------------------------------------------------- #
def _run_one_part(idx: int, part_pdf: Path, part_out: Path, tier: str,
                  force: bool, page_label: str, delay: float = 0.0) -> Path:
    part_out.mkdir(parents=True, exist_ok=True)
    done = part_out / DONE_MARK
    if not force and _part_finished(part_out):
        done.write_text("ok", encoding="utf-8")
        _log(f"[Phần {idx}] {page_label}: đã xong từ lần chạy trước, bỏ qua.")
        return part_out

    if delay > 0:                       # so le thời điểm nạp model, tránh 4 model nạp cùng lúc
        time.sleep(delay)
    cmd = ["mineru-kit", "parse", str(part_pdf), "-o", str(part_out), "--tier", tier]
    _log(f"[Phần {idx}] {page_label}: bắt đầu -> {' '.join(cmd)}")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    # Log từng phần ra file riêng để 4 tiến trình không in lẫn vào nhau.
    (part_out / "mineru_log.txt").write_text(
        f"$ {' '.join(cmd)}\n\n--- STDOUT ---\n{res.stdout}\n\n--- STDERR ---\n{res.stderr}\n",
        encoding="utf-8")
    if res.returncode != 0:
        tail = "\n".join((res.stderr or res.stdout or "").strip().splitlines()[-5:])
        raise RuntimeError(
            f"Phần {idx} ({page_label}) lỗi (exit {res.returncode}), "
            f"xem {part_out / 'mineru_log.txt'}\n{tail}")
    if _find_md(part_out) is None:
        raise RuntimeError(
            f"Phần {idx} ({page_label}) chạy xong nhưng không thấy file .md "
            f"trong {part_out}")
    done.write_text("ok", encoding="utf-8")
    _log(f"[Phần {idx}] {page_label}: xong sau {time.time() - t0:.0f}s")
    return part_out


# --------------------------------------------------------------------------- #
# 3. Ghép kết quả
# --------------------------------------------------------------------------- #
def _largest(paths):
    paths = list(paths)
    return max(paths, key=lambda p: p.stat().st_size) if paths else None


def merge_parts(part_outs: List[Path], ranges: List[Tuple[int, int]],
                out_dir: Path, stem: str) -> Tuple[Path, Optional[Path]]:
    """Ghép output của các phần (đã sắp theo thứ tự trang) thành 1 output duy nhất.

    Trả về (md_path, content_list_path).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "images"
    img_dir.mkdir(exist_ok=True)

    md_chunks: List[str] = []
    merged_items: List[Dict] = []
    all_have_cl = True      # chỉ ghép content_list.json nếu MỌI phần đều có

    for k, (part_out, (start, _end)) in enumerate(zip(part_outs, ranges), 1):
        md_path = _largest(p for p in part_out.rglob("*.md") if p.is_file())
        cl_path = find_content_list(part_out)
        if md_path is None:
            raise FileNotFoundError(f"Phần {k}: thiếu file .md trong {part_out}")
        base = md_path.parent

        # --- ảnh: copy sang images/ chung với tiền tố p<k>_ ---
        rename: Dict[str, str] = {}
        for img in base.rglob("*"):
            if not (img.is_file() and img.suffix.lower() in IMG_SUFFIXES):
                continue
            rel = img.relative_to(base)
            new_rel = rel.parent / f"p{k}_{rel.name}"
            dst = out_dir / new_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, dst)
            rename[rel.as_posix()] = new_rel.as_posix()

        pattern = None
        if rename:
            keys = sorted(rename, key=len, reverse=True)
            pattern = re.compile("|".join(re.escape(x) for x in keys))

        def fix_paths(text: str) -> str:
            return pattern.sub(lambda m: rename[m.group(0)], text) if pattern else text

        # --- markdown ---
        md_chunks.append(fix_paths(md_path.read_text(encoding="utf-8", errors="ignore")).strip())

        # --- content_list (nếu có): sửa đường dẫn ảnh + cộng offset trang ---
        if cl_path is None:
            all_have_cl = False
            continue
        items = json.loads(fix_paths(cl_path.read_text(encoding="utf-8")))
        if not isinstance(items, list):
            raise ValueError(f"Phần {k}: content_list.json không phải list")
        for it in items:
            if isinstance(it.get("page_idx"), int):
                it["page_idx"] += start          # <-- giữ đúng số trang của PDF gốc
        merged_items.extend(items)

    md_out = out_dir / f"{stem}.md"
    md_out.write_text("\n\n".join(c for c in md_chunks if c) + "\n", encoding="utf-8")
    cl_out = None
    if all_have_cl and merged_items:
        cl_out = out_dir / f"{stem}_content_list.json"
        cl_out.write_text(json.dumps(merged_items, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    else:
        _log("[MinerU] mineru-kit không xuất content_list.json -> chỉ ghép Markdown "
             "(main.py sẽ tự dùng chế độ fallback từ Markdown).")
    return md_out, cl_out


# --------------------------------------------------------------------------- #
# 4. Hàm chính, thay thế run_mineru() trong main.py
# --------------------------------------------------------------------------- #
def run_mineru_parallel(pdf_path: Path, out_dir: Path, workers: int = 2,
                        tier: str = "standard", force: bool = False,
                        min_pages_per_worker: int = 5,
                        stagger: float = 20.0, retry_sequential: bool = True) -> None:
    """Chạy MinerU bằng `workers` tiến trình song song rồi ghép kết quả vào out_dir.

    - Nếu out_dir đã có kết quả ghép và không force -> bỏ qua.
    - stagger: các phần khởi động cách nhau N giây (mặc định 20s ~ thời gian nạp model).
    - retry_sequential: phần nào lỗi khi chạy song song sẽ được chạy lại TUẦN TỰ
      từng phần một (ít tốn RAM/VRAM hơn) trước khi báo lỗi.
    - PDF quá ngắn (< workers * min_pages_per_worker trang) tự giảm số tiến trình
      để không tốn công nạp model cho những phần chỉ vài trang.
    """
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not force and (find_content_list(out_dir) or _find_md(out_dir)):
        _log(f"[MinerU] Đã có output cho PDF này, bỏ qua chạy lại: {out_dir}")
        _log("         (dùng --force nếu muốn chạy lại MinerU)")
        return

    total = len(PdfReader(str(pdf_path)).pages)
    n = max(1, min(workers, total // max(1, min_pages_per_worker)))
    ranges = split_page_ranges(total, n)
    _log(f"[MinerU] {pdf_path.name}: {total} trang -> {len(ranges)} tiến trình song song")
    for k, (s, e) in enumerate(ranges, 1):
        _log(f"         phần {k}: trang {s + 1} - {e}  ({e - s} trang)")

    parts_root = out_dir.parent / "mineru_parts"       # nằm NGOÀI out_dir để không lẫn
    if force and parts_root.exists():
        shutil.rmtree(parts_root)
    part_pdfs = split_pdf(pdf_path, ranges, parts_root / "pdf")

    part_outs = [parts_root / "out" / p.stem for p in part_pdfs]
    failed: Dict[int, str] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futs = {
            pool.submit(_run_one_part, k, pdf, outp, tier, force,
                        f"trang {s + 1}-{e}", (k - 1) * stagger): k
            for k, (pdf, outp, (s, e)) in enumerate(zip(part_pdfs, part_outs, ranges), 1)
        }
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as ex:                     # noqa: BLE001
                failed[futs[fut]] = str(ex)
                _log(f"[LỖI] {ex}")

    if failed and retry_sequential:
        _log(f"[MinerU] {len(failed)} phần lỗi khi chạy song song -> chạy lại TUẦN TỰ từng phần...")
        for k in sorted(failed):
            s, e = ranges[k - 1]
            try:
                _run_one_part(k, part_pdfs[k - 1], part_outs[k - 1], tier, True,
                              f"trang {s + 1}-{e} (chạy lại)")
                del failed[k]
            except Exception as ex:                     # noqa: BLE001
                failed[k] = str(ex)
                _log(f"[LỖI] {ex}")

    if failed:
        raise RuntimeError(
            "Một số phần MinerU vẫn lỗi (các phần đã xong được giữ lại, "
            "chạy lại lệnh cũ sẽ chỉ chạy các phần lỗi):\n  - "
            + "\n  - ".join(failed[k] for k in sorted(failed)))

    _log(f"[MinerU] Cả {len(ranges)} phần xong sau {time.time() - t0:.0f}s, đang ghép...")
    md_out, cl_out = merge_parts(part_outs, ranges, out_dir, pdf_path.stem)
    (out_dir / "parallel_info.json").write_text(
        json.dumps({"total_pages": total,
                    "ranges_1based": [[s + 1, e] for s, e in ranges]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[MinerU] Đã ghép: {md_out.name}" + (f", {cl_out.name}" if cl_out else ""))