# Mac-hosted MinerU + Math Repair + DOCX, with Cloudflare HTTPS demo

Architecture: Mac hosts FastAPI, MinerU 4, Math Repair/DOCX, chunks and BM25 keyword lookup. FastAPI also serves the HTML frontend at the same origin. There is no E5 embedding, Qwen local, LlamaIndex or Ollama.

The current Apple M5 Mac has 32 GB unified memory. Use native macOS for MinerU Standard, not Docker Linux. Memory is ample enough to start experiments but performance depends on PDF sizes.

## Install

In repository root:

    uv pip install --python .venv/bin/python -r backend/requirements-backend.txt
    brew install pandoc cloudflared
    .venv/bin/mineru-kit version
    .venv/bin/mineru-kit models download --tier standard

MinerU may still install Torch/Transformers for its own layout, OCR and VLM; these ARE NOT E5 or Qwen chat models.

## Start demo

Terminal 1:

    ./scripts/run_mac_backend.sh

Script prints a random HTTP Basic password and username for this run. Keep credentials private and the terminal open. Uvicorn only binds 127.0.0.1:8000, with MAX_QUEUED_JOBS=2 and SERVE_FRONTEND=true.

Terminal 2:

    ./scripts/expose_mac_demo.sh

Cloudflare prints a temporary HTTPS address ending with trycloudflare.com. The script forces HTTP/2 over TCP because QUIC repeatedly failed on the tested Mac network; Cloudflare Quick Tunnel over HTTP/2 connected successfully. Open this NEW address (not the old Render frontend URL); enter the username/password printed in terminal 1. The FastAPI server returns frontend/config.js pointing at window.location.origin, so all FE and API requests go to the Mac behind the same tunnel domain. No Git commit is needed when the temporary tunnel hostname changes.

Use curl with the demo password:

    curl -u demo:<PASSWORD> http://127.0.0.1:8000/api/health

Expect ok=true, ai_pipeline_enabled=true, search_backend=keyword_bm25.
Upload a small PDF, poll /api/doc/{id}, inspect /api/documents/{id}/artifacts, and download/open DOCX.

## Limitations

Quick Tunnel is for temporary testing, not production. URLs change when the tunnel restarts; Mac must stay awake and online. Stopping either process makes the service unavailable. HTTP Basic is temporary demo protection; for production, use a named tunnel, proper identity/access controls, rate limits and quotas. No router port forwarding is needed. PDF, DOCX and SQLite are saved on Mac under backend/data; back them up if needed.

Search is BM25 keyword matching (not semantic vector RAG); chat returns cited excerpts, not generated explanations. Math Repair and DOCX conversion remain MinerU-based. For stable URLs, use Cloudflare Named Tunnel with a Cloudflare-managed domain or Tailscale Funnel.

If the public URL is unavailable, inspect the second terminal logs. If tunnel connection repeatedly fails, inspect outgoing TCP/7844 access, DNS and VPN restrictions. Prefer a named Cloudflare Tunnel for an enduring hostname.


## Pipeline Kiet + Render FE

Code from branch kiet commit 524bff8 is in src/ and the standalone
entrypoint kiet_cli.py. Duplicate kiet_ref/ sources are removed.
Render Static Site FE -> Cloudflare HTTPS -> existing POST /api/upload ->
FastAPI Mac job subprocess kiet_cli.py -> Kiết DOCX/audit/repair ->
existing GET /api/docx/{id} -> browser. No separate Kiet API is introduced.

On the Render Static Site press Ket noi Mac / Mac CLI. Enter the current
Cloudflare Quick Tunnel URL and the demo credentials shown by the Mac.
Credentials are stored in the browser tab sessionStorage only.
The CORS preflight is handled without requiring Basic credentials,
while requests and PDF.js carry Authorization explicitly.

For stable demos Mac launcher sets KIET_TIER=standard (tested on test3.pdf).
Original Kiet CLI defaults to advanced; opt in by setting
KIET_TIER=advanced before launching. Advanced was not confirmed on this
machine within the test window.

The Kiết DOCX file is copied byte-for-byte; the adapter does NOT run a
different DOCX converter. BM25 chunks are auxiliary: without reliable
page metadata the fallback sets page=null and does not invent citations.
MinerU OCR/VLM model weights are required; do not erase their cache.
