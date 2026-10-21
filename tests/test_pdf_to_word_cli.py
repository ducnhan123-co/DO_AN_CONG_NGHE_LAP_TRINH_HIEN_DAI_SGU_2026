import zipfile
from pathlib import Path
import pytest
from docx import Document
from pdf_to_word import check_word, validate_pdf

def test_reject_missing_or_wrong_suffix(tmp_path):
    with pytest.raises(ValueError):
        validate_pdf(tmp_path / "none.pdf")
    fake=tmp_path / "x.txt"
    fake.write_bytes(b"%PDF-1234")
    with pytest.raises(ValueError):
        validate_pdf(fake)

def test_reject_fake_pdf_with_correct_suffix(tmp_path):
    fake=tmp_path / "x.pdf"
    fake.write_bytes(b"NOT A PDF")
    with pytest.raises(ValueError):
        validate_pdf(fake)

def test_accept_pdf_magic_header(tmp_path):
    pdf=tmp_path / "t.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% minimal header check only")
    validate_pdf(pdf)

def test_docx_preflight_and_equation_count(tmp_path):
    p=tmp_path/"a.docx"
    doc=Document()
    doc.add_paragraph("SGU PDF to Word")
    doc.save(p)
    checks=check_word(p)
    assert checks["bytes"]>0 and checks["media_files"]==0
    assert checks["omml_tags"]==0

def test_reject_invalid_docx_zip(tmp_path):
    p=tmp_path/"a.docx"
    p.write_bytes(b"not a valid zip")
    with pytest.raises(zipfile.BadZipFile):
        check_word(p)
