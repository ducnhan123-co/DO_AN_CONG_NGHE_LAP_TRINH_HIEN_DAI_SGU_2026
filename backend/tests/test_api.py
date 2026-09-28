"""Small HTTP smoke test; model execution is mocked, not duplicated here."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_dir = main.DATA_DIR
        main.DATA_DIR = Path(self.temp.name)
        main.DOCUMENTS.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.DATA_DIR = self.previous_dir
        self.temp.cleanup()

    def test_upload_then_query(self):
        with patch.object(main, "process_pdf", return_value={"chunk_count": 1}), patch.object(
            main, "answer_question", return_value={"answer": "ok", "sources": []}
        ):
            response = self.client.post(
                "/api/documents", files={"file": ("lesson.pdf", b"%PDF-1.7 test", "application/pdf")}
            )
            self.assertEqual(response.status_code, 202)
            document_id = response.json()["id"]
            self.assertEqual(self.client.get(f"/api/documents/{document_id}").json()["status"], "ready")
            answer = self.client.post(
                f"/api/documents/{document_id}/questions", json={"question": "Noi dung la gi?"}
            )
            self.assertEqual(answer.json()["answer"], "ok")

    def test_rejects_non_pdf(self):
        response = self.client.post(
            "/api/documents", files={"file": ("notes.txt", b"text", "text/plain")}
        )
        self.assertEqual(response.status_code, 415)


if __name__ == "__main__":
    unittest.main()
