FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
		pandoc \
		libglib2.0-0 \
		libgl1 \
		libgomp1 \
		tesseract-ocr \
		tesseract-ocr-eng \
		tesseract-ocr-vie \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
COPY backend/requirements-backend.txt ./backend/requirements-backend.txt

RUN python -m pip install --upgrade pip \
	&& python -m pip install -r backend/requirements-backend.txt

COPY . .

RUN mkdir -p /app/backend/data

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
