# PDF to DOCX

The `frontend/` upload page sends PDF files to the FastAPI service in `backend/`.
The backend validates each PDF, stores it under `backend/data/documents/`, and
processes jobs sequentially:

```text
upload → PDF validation / SHA-256 / page count
       → mineru-kit parse → rag_toan/src/build_docx.py → DOCX validation
```

`backend/data/app.db` is the source of truth for document names, jobs, stages,
and progress. SQLite may also keep uncheckpointed writes in `app.db-wal` while
the service is running. Per-document files in `documents/<id>/` are mirrored
for compatibility with the existing `rag_toan` layout:

```text
backend/data/
  input/<id>_<filename>.pdf
  docx_output/<id>_<display-name>.docx
  docx_output/<id>_<display-name>_for_docx.md
  runs/<filename-stem>_<id>/
    backend_run.json
    mineru/, structured_data.json, chunks.json, validation.json, logs/...
```

The mirrors are created for existing documents when the API starts and updated
as jobs progress. Renaming updates the mirrored output name and run manifest;
deleting a document removes its owned mirrors and its `documents/<id>/` folder.
Identifiers in mirror filenames prevent same-name uploads from overwriting each
other. Do not edit mirror files directly; upload, rename, retry, and delete
through the API so the database and files remain consistent.

The document API supports upload (`POST /api/documents`), progress and job
history (`GET /api/documents`, `GET /api/jobs/{id}`), and DOCX download
(`GET /api/documents/{id}/docx`). Completed documents with the same SHA-256 and
MinerU tier reuse the existing DOCX unless upload uses `?force=true`.

## Run locally

From the project root, install the project dependencies, ensure `mineru-kit` and
Pandoc are available on `PATH`, then start the API:

```powershell
python -m pip install -r requirements.txt
uvicorn backend.app.main:app --port 8000
```

Open `http://127.0.0.1:8000/`. MinerU and DOCX generation run in the background
with one document active at a time. Configure the backend with
`backend/.env` (see `backend/.env.example`). The `rag_toan` directory is detected
automatically when it is alongside `backend/`, or can be set with
`RAG_TOAN_DIR`.

Run a PDF from the command line with:

```powershell
python -m backend.app.cli path\to\document.pdf
```
