"""Cấu hình chuẩn — giữ nguyên model tốt nhất từ notebook gốc.

- MinerU backend `pipeline`: ổn định nhất trên Colab CPU, giữ công thức/table tốt.
- Embedding `intfloat/multilingual-e5-base`: đa ngữ, hợp tiếng Việt + LaTeX.
- LLM `Qwen/Qwen2.5-3B-Instruct`: local, không API trả phí, vừa VRAM Colab GPU.
- Pandoc flags giữ Equation OMML thật trong Word.
Không finetune thêm — đây là cấu hình cho điểm cao nhất đã verify.
"""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE / "input"
MINERU_DIR = BASE / "mineru_output"
DOCX_DIR = BASE / "docx_output"
RAG_DIR = BASE / "rag_output"

# Model tốt nhất (đừng đổi nếu muốn giữ điểm)
EMBED_MODEL = "intfloat/multilingual-e5-base"
LLM_NAME = "Qwen/Qwen2.5-3B-Instruct"

# Chunk chuẩn từ notebook
MAX_CHARS = 1800
OVERLAP = 250
TOP_K = 5

# MinerU backend chuẩn
MINERU_BACKEND = "pipeline"

# Pandoc: giữ math -> OMML Equation, heading/table/image
PANDOC_FROM = "markdown+tex_math_dollars+tex_math_single_backslash"
