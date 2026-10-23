#!/usr/bin/env bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
PYTHON="$REPO/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing venv; create it with: uv venv --python 3.12 .venv" >&2
  exit 1
fi
if ! "$PYTHON" -c 'import fastapi, sqlalchemy, pydantic_settings, uvicorn, mineru, cv2' 2>/dev/null; then
  echo "Missing dependencies; run: uv pip install --python .venv/bin/python -r backend/requirements-backend.txt" >&2
  exit 1
fi
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Missing pandoc; run: brew install pandoc" >&2
  exit 1
fi
export AI_PIPELINE_ENABLED=true
export KIET_CLI_ENABLED=true
export KIET_TIER="${KIET_TIER:-standard}"
export SERVE_FRONTEND=true
export MINERU_PREWARM=false
export MINERU_WORKERS=0
export MINERU_DEVICE="${MINERU_DEVICE:-mps}"
export MAX_QUEUED_JOBS="${MAX_QUEUED_JOBS:-2}"
export DEMO_AUTH_USER="${DEMO_AUTH_USER:-demo}"
if [[ -z "${DEMO_AUTH_PASSWORD:-}" ]]; then
  export DEMO_AUTH_PASSWORD="$(openssl rand -hex 12)"
fi
PORT="${MATCHPDF_PORT:-8000}"
echo "Mac FastAPI: http://127.0.0.1:$PORT"
echo "Demo username: $DEMO_AUTH_USER"
echo "Temporary password: $DEMO_AUTH_PASSWORD"
echo "Keep this terminal open; start the tunnel in another terminal."
exec "$PYTHON" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "$PORT" --workers 1
