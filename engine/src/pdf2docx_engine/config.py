"""Cấu hình engine.

STORAGE_DIR: nơi CLI ghi kết quả khi không truyền --out (mặc định <repo>/storage,
đổi bằng biến môi trường PDF2DOCX_STORAGE).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STORAGE_DIR = Path(os.environ.get("PDF2DOCX_STORAGE", ROOT / "storage"))

# MinerU >= 4.0: CLI "mineru-kit parse ... --tier <tier>"
MINERU_TIERS = ("flash", "basic", "standard", "advanced")
MINERU_TIER = "advanced"

# Pandoc: giữ math -> OMML Equation, heading/table/image
PANDOC_FROM = "markdown+tex_math_dollars+tex_math_single_backslash"
