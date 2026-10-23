#!/usr/bin/env bash
set -euo pipefail
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Install cloudflared: brew install cloudflared" >&2
  exit 1
fi
echo "Start scripts/run_mac_backend.sh in another terminal first."
echo "Quick Tunnel URL is temporary and will change on restart."
echo "Backend should require HTTP Basic auth set by run_mac_backend.sh."
PORT="${MATCHPDF_PORT:-8000}"
exec cloudflared tunnel --protocol http2 --url "http://127.0.0.1:$PORT"
