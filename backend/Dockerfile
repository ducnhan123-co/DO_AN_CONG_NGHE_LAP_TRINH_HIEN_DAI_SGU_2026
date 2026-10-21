FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONUTF8=1

# tesseract: dò cột | libgl/glib: opencv, pymupdf | fonts: render PDF khi dò cột
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-vie libglib2.0-0 libgl1 poppler-utils fonts-liberation curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pandoc
ARG TARGETARCH
ARG PANDOC_VERSION=3.1.3
RUN curl -fsSL -o /tmp/pandoc.deb \
      "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${TARGETARCH}.deb" \
    && apt-get update && apt-get install -y /tmp/pandoc.deb && rm -f /tmp/pandoc.deb \
    && rm -rf /var/lib/apt/lists/* && pandoc --version | head -1

WORKDIR /app
COPY backend/requirements.txt backend/requirements-mineru.txt backend/requirements-rag.txt /tmp/req/
RUN pip install -r /tmp/req/requirements.txt

# Lớp MinerU tách riêng để cache 
RUN pip install -r /tmp/req/requirements-mineru.txt

# Tải model ngay lúc build để người dùng đầu tiên không phải đợi (và máy chạy không cần internet).
ARG PRELOAD_MODELS=1
ARG PRELOAD_TIER=standard
RUN if [ "$PRELOAD_MODELS" = "1" ]; then mineru-kit models download --tier "$PRELOAD_TIER"; fi

# (tùy chọn) RAG index: docker build --build-arg WITH_RAG=1 ...
ARG WITH_RAG=0
RUN if [ "$WITH_RAG" = "1" ]; then pip install -r /tmp/req/requirements-rag.txt; fi

COPY rag_toan /app/rag_toan
COPY frontend /app/frontend
COPY backend  /app/backend

WORKDIR /app/backend
ENV DATA_DIR=/app/backend/data HOST=0.0.0.0 PORT=8000 MINERU_TIER=advanced
VOLUME ["/app/backend/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/api/health || exit 1
# MỘT process duy nhất (hàng đợi nằm trong process) — không dùng --workers
CMD ["python", "run.py"]
