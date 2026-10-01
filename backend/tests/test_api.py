"""Focused HTTP checks for the MatchPDF contract; model execution stays mocked."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_data_dir = main.DATA_DIR
        self.previous_dir = main.store.data_dir
        main.DATA_DIR = main.store.data_dir = Path(self.temp.name)
        main.store.docs.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.store.docs.clear()
        main.DATA_DIR = self.previous_data_dir
        main.store.data_dir = self.previous_dir
        self.temp.cleanup()

    def test_upload_uses_matchpdf_contract(self):
        def index(doc_id, name, path):
            main.store.docs[doc_id] = {"name": name, "file": path, "pages": ["Noi dung PDF du dai de index."],
                                       "chunks": [{"page": 1, "text": "Noi dung PDF du dai de index."}],
                                       "ocr": False, "parser": "pypdf"}
            return {"doc_id": doc_id, "name": name, "num_pages": 1, "num_chunks": 1, "parser": "pypdf"}

        with patch.object(main.store, "index_upload", side_effect=index), patch.object(main.store, "upgrade_mineru"):
            response = self.client.post("/api/upload", files={"f": ("lesson.pdf", b"%PDF-1.7 test", "application/pdf")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["parser"], "mineru_running")
        self.assertRegex(response.json()["doc_id"], r"^[0-9a-f]{10}$")

    def test_rejects_non_pdf(self):
        response = self.client.post("/api/upload", files={"f": ("notes.txt", b"text", "text/plain")})
        self.assertEqual(response.status_code, 415)


if __name__ == "__main__":
    unittest.main()
