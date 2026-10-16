#!/bin/bash
# Chạy từ thư mục chứa backend/ và frontend/ :  bash backend/tests/ui/run_ui_test.sh   (Linux/macOS/Git Bash; cần: npm i jsdom)
set -e
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"; cd "$ROOT"
WORK="$(mktemp -d)"; export DATA_DIR="$WORK/data" PDF_A="$WORK/a.pdf" PDF_B="$WORK/b.pdf"
python3 - <<PY
import sys; sys.path.insert(0, "backend/tests")
from pathlib import Path
from conftest import make_pdf
make_pdf(Path("$PDF_A"), 46, "Giaitich"); make_pdf(Path("$PDF_B"), 12, "Dai so")
PY
export MINERU_CMD="\"$(which python3)\" \"$ROOT/backend/tests/fake_mineru_kit.py\"" FAKE_MINERU_DELAY_PER_PAGE=0.12
python3 -m uvicorn backend.app.main:app --port 8000 --log-level warning > "$WORK/server.log" 2>&1 &
SPID=$!; trap 'kill $SPID 2>/dev/null' EXIT
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8000/api/health && break; sleep 0.5; done
[ -d node_modules/jsdom ] || (cd backend/tests/ui && npm install jsdom --silent && cd "$ROOT" && NODE_PATH="$ROOT/backend/tests/ui/node_modules" true)
NODE_PATH="$ROOT/backend/tests/ui/node_modules:$ROOT/node_modules" node backend/tests/ui/ui_test.js
