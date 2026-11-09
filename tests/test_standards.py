import pikepdf
import pytest

from leafweaving.core import standards
from leafweaving.core.document import PdfDocument


def test_plain_and_version(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    out = tmp_path / "plain.pdf"
    res = standards.save_document(pdf, out, standards.SaveOptions())
    assert res.engine == "pymupdf" and out.exists()

    out2 = tmp_path / "v17.pdf"
    res = standards.save_document(pdf, out2, standards.SaveOptions(pdf_version="1.7", linearize=True))
    assert res.engine == "pikepdf"
    with pikepdf.open(str(out2)) as p:
        assert p.pdf_version == "1.7"
        assert p.is_linearized


def test_best_effort_pdfa(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    out = tmp_path / "a2b.pdf"
    res = standards.save_document(pdf, out, standards.SaveOptions(standard="pdfa-2b", prefer_ghostscript=False))
    assert res.engine == "best-effort"
    assert any("Ghostscript" in w for w in res.warnings)
    assert standards.verify_standard_claim(out) == "PDF/A-2b"
    with pikepdf.open(str(out)) as p:
        assert p.pdf_version == "1.7"
        assert "/OutputIntents" in p.Root


def test_best_effort_pdfx(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    out = tmp_path / "x3.pdf"
    res = standards.save_document(pdf, out, standards.SaveOptions(standard="pdfx-3", prefer_ghostscript=False))
    assert res.engine == "best-effort"
    assert standards.verify_standard_claim(out) == "PDF/X-3:2003"


@pytest.mark.skipif(standards.find_ghostscript() is None, reason="Ghostscript not installed")
@pytest.mark.parametrize("std,expected", [("pdfa-1b", "PDF/A-1b"), ("pdfa-2b", "PDF/A-2b"), ("pdfa-3b", "PDF/A-3b")])
def test_ghostscript_pdfa(sample_pdf, tmp_path, std, expected):
    pdf = PdfDocument.open(sample_pdf)
    out = tmp_path / f"{std}.pdf"
    res = standards.save_document(pdf, out, standards.SaveOptions(standard=std))
    assert res.engine == "ghostscript"
    assert standards.verify_standard_claim(out) == expected
    with pikepdf.open(str(out)) as p:
        assert "/OutputIntents" in p.Root
        assert p.Root.OutputIntents[0].S == "/GTS_PDFA1"


@pytest.mark.skipif(standards.find_ghostscript() is None, reason="Ghostscript not installed")
def test_ghostscript_pdfx(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    out = tmp_path / "x.pdf"
    res = standards.save_document(pdf, out, standards.SaveOptions(standard="pdfx-3"))
    assert res.engine == "ghostscript"
    with pikepdf.open(str(out)) as p:
        assert "/OutputIntents" in p.Root
        assert str(p.docinfo.get("/GTS_PDFXVersion", "")) == "PDF/X-3:2003"
