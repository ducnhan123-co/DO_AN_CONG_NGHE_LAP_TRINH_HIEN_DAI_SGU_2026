# Chay va kiem tra

## Cai dat

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
mineru-kit --help
pandoc --version
```

`mineru-kit` phai la MinerU 4.x. Tesseract (`vie+eng`) chi duoc dung khi API fallback OCR cho PDF scan va MinerU khong kha dung.

## CLI

```bash
python main.py --pdf input/<ten-file>.pdf --skip-llm
python main.py --pdf input/<ten-file>.pdf --force
```

Moi lan chay tao `runs/<ten-file>_<hash>/`, gom Markdown, DOCX Equation, structured data, chunks, validation va LlamaIndex. Kiem tra nhanh:

```bash
find runs -name validation.json -o -name '*.docx' -o -name docstore.json
```

`validation.json` phai co `ok: true`; chunk khong duoc chua base64, thieu source, hay cat doi delimiter cong thuc.

## Web

```bash
uvicorn backend.app.main:app --reload --port 8000
python3 -m http.server 5173 --directory frontend
```

Mo `http://127.0.0.1:5173`, upload PDF va doi trang thai `San sang hoi dap`. Dat `ENABLE_LOCAL_LLM=1` khi muon Qwen tong hop; mac dinh API chi tra cac doan E5 co trich dan de khong tai model 3B tren may khong co GPU.

## Test

```bash
python3 -m tests.test_chunking
python3 -m tests.test_latex_norm
python3 -m unittest backend.tests.test_api -v
```
