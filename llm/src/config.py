"""Cấu hình chuẩn — giữ nguyên model tốt nhất từ notebook gốc.

- MinerU backend `pipeline`: ổn định nhất trên Colab CPU, giữ công thức/table tốt.
- Embedding `intfloat/multilingual-e5-base`: đa ngữ, hợp tiếng Việt + LaTeX.
- LLM `Qwen/Qwen2.5-3B-Instruct`: local, không API trả phí, vừa VRAM Colab GPU.
- Pandoc flags giữ Equation OMML thật trong Word.
Không finetune thêm — đây là cấu hình cho điểm cao nhất đã verify.

MỚI (fix lỗi tuần 2): mỗi PDF chạy trong một run dir riêng `runs/<ten>_<doc_id>/`
để không lấy nhầm dữ liệu của PDF chạy trước đó.
"""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE = PROJECT_ROOT / "backend" / "data" / "documents"
INPUT_DIR = BASE / "input"
DOCX_DIR = BASE / "docx_output"
RUNS_DIR = BASE / "runs"

# Model tốt nhất (đừng đổi nếu muốn giữ điểm)
EMBED_MODEL = "intfloat/multilingual-e5-base"
LLM_NAME = "Qwen/Qwen2.5-3B-Instruct"

# Chunk chuẩn từ notebook (nay chunk theo BLOCK, không cắt cứng theo ký tự)
MAX_CHARS = 1800
OVERLAP = 250
TOP_K = 5

# MinerU: từ 4.0 dùng CLI "mineru-kit parse ... --tier <tier>" (giống notebook).
# MINERU_BACKEND giữ lại cho tương thích --backend cũ trên CLI của main.py,
# không còn được run_mineru() dùng thật sự.
MINERU_BACKEND = "pipeline"
MINERU_TIER = "standard"  # flash / basic / standard / advanced
# Tối ưu đường legacy (mineru 2.x, khi chưa có mineru-kit):
# - METHOD 'auto' -> pipeline tự phát hiện text/scan từng file (txt bỏ OCR khi PDF chữ).
# - LANG 'latin' hợp PDF tiếng Việt nhất (mặc định CLI là 'ch').
# - DEVICE 'mps' nhanh gấp ~5 lần 'cpu' trên Mac Apple Silicon (đã verify 2 trang:
#   26s cả nạp model, ~7s/trang; đổi bằng MINERU_DEVICE=cpu nếu gặp lỗi MPS).
MINERU_METHOD = "auto"  # auto | txt | ocr
MINERU_LANG = "latin"
MINERU_DEVICE = os.getenv("MINERU_DEVICE", "mps")
# Số server mineru-api nóng chạy song song (0 = tắt, dùng CLI từng lần). Đo M5: 2 server nhanh hơn CLI ~30-45%.
MINERU_WORKERS = int(os.getenv("MINERU_WORKERS", "2"))

# Pandoc: giữ math -> OMML Equation, heading/table/image
PANDOC_FROM = "markdown+tex_math_dollars+tex_math_single_backslash"
