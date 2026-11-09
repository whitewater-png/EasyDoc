import os

import pymupdf
import pytest

from leafweaving.core import pages
from leafweaving.core.document import PdfDocument


def test_parse_ranges():
    assert pages.parse_ranges("1-2,3", 5) == [0, 1, 2]
    assert pages.parse_ranges("4-", 5) == [3, 4]
    assert pages.parse_ranges("-2", 5) == [0, 1]
    assert pages.parse_ranges("3 1", 5) == [2, 0]
    with pytest.raises(ValueError):
        pages.parse_ranges("0-2", 5)
    with pytest.raises(ValueError):
        pages.parse_ranges("1-9", 5)
    with pytest.raises(ValueError):
        pages.parse_ranges("abc", 5)


def test_rotate_delete_undo(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    pages.rotate_pages(pdf, [0], 90)
    assert pdf.page(0).rotation == 90
    pages.delete_pages(pdf, [1])
    assert pdf.page_count == 2
    assert pdf.undo()
    assert pdf.page_count == 3
    assert pdf.undo()
    assert pdf.page(0).rotation == 0
    assert pdf.redo()
    assert pdf.page(0).rotation == 90
    with pytest.raises(ValueError):
        pages.delete_pages(pdf, [0, 1, 2])


def _texts(pdf):
    return [pdf.page(i).get_text().split("\n")[0] for i in range(pdf.page_count)]


def test_move_and_reorder(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    pages.move_page(pdf, 0, 2)
    assert _texts(pdf) == ["Page 2 Hello World", "Page 3 Hello World", "Page 1 Hello World"]
    pages.move_page(pdf, 2, 0)
    assert _texts(pdf) == ["Page 1 Hello World", "Page 2 Hello World", "Page 3 Hello World"]
    pages.reorder_pages(pdf, [2, 1, 0])
    assert _texts(pdf) == ["Page 3 Hello World", "Page 2 Hello World", "Page 1 Hello World"]


def test_insert_blank(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    pages.insert_blank_page(pdf, 1, *pages.PAGE_SIZES["A5"])
    assert pdf.page_count == 4
    assert round(pdf.page(1).rect.width) == 420


def test_merge_extract_split(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    added = pages.merge_files(pdf, [sample_pdf], insert_at=1)
    assert added == 3 and pdf.page_count == 6
    assert _texts(pdf)[1] == "Page 1 Hello World"

    out = tmp_path / "extract.pdf"
    pages.extract_pages(pdf, [5, 0], out)
    with pymupdf.open(str(out)) as d:
        assert d.page_count == 2
        assert d[0].get_text().startswith("Page 3")

    files = pages.split_every(pdf, 4, tmp_path / "split")
    assert len(files) == 2
    with pymupdf.open(files[1]) as d:
        assert d.page_count == 2

    files = pages.split_ranges(pdf, ["1-2", "3-"], tmp_path / "split2")
    assert [os.path.basename(f) for f in files] == ["part_001.pdf", "part_002.pdf"]

    merged = tmp_path / "merged.pdf"
    assert pages.merge_paths_to_file([sample_pdf, sample_pdf], merged) == 6
