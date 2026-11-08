import warnings

import pymupdf
import pytest

warnings.filterwarnings("ignore", category=FutureWarning)


@pytest.fixture
def sample_pdf(tmp_path):
    """Three page PDF with text, a vector rectangle and distinct page labels."""
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Page {i + 1} Hello World", fontsize=14, fontname="helv")
        page.insert_text((72, 140), "Second line of text", fontsize=12, fontname="tiro")
        shape = page.new_shape()
        shape.draw_rect(pymupdf.Rect(300, 300, 400, 360))
        shape.finish(color=(1, 0, 0), fill=(0, 0, 1), width=2)
        shape.commit()
    path = tmp_path / "sample.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)
