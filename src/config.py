"""Configuration for Kiet PDF -> MinerU -> Math Repair -> DOCX CLI.

Optional KIET_WORK_ROOT isolates each upload/job. Original CLI defaults
remain unchanged when called without KIET_WORK_ROOT.
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
_WORK_ROOT = os.environ.get("KIET_WORK_ROOT")
WORK_ROOT = Path(_WORK_ROOT).resolve() if _WORK_ROOT else BASE
INPUT_DIR = WORK_ROOT / "input"
DOCX_DIR = WORK_ROOT / "docx_output"
RUNS_DIR = WORK_ROOT / "runs"

# Chunk chuẩn từ notebook (nay chunk theo BLOCK, không cắt cứng theo ký tự)
MAX_CHARS = 1800
OVERLAP = 250
TOP_K = 5

# MinerU: từ 4.0 dùng CLI "mineru-kit parse ... --tier <tier>" (giống notebook).
# MINERU_BACKEND giữ lại cho tương thích --backend cũ trên CLI của main.py,
# không còn được run_mineru() dùng thật sự.
MINERU_BACKEND = "pipeline"
MINERU_TIER = "advanced"  # flash / basic / standard / advanced

# Pandoc: giữ math -> OMML Equation, heading/table/image
PANDOC_FROM = "markdown+tex_math_dollars+tex_math_single_backslash"
