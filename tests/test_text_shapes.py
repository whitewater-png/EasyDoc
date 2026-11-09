import pymupdf

from leafweaving.core import shapes, text_edit
from leafweaving.core.document import PdfDocument
from leafweaving.core.fonts import FontRegistry


def test_spans_and_replace(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    reg = FontRegistry(scan=False)
    spans = text_edit.get_spans(pdf.page(0))
    assert [s.text for s in spans] == ["Page 1 Hello World", "Second line of text"]
    span = spans[0]
    assert span.size == 14
    text_edit.replace_span(pdf, span, "Edited title", registry=reg)
    txt = pdf.page(0).get_text()
    assert "Edited title" in txt
    assert "Hello World" not in txt
    assert "Second line of text" in txt  # neighbour untouched
    new_span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text == "Edited title")
    assert abs(new_span.origin.y - span.origin.y) < 1.0
    assert abs(new_span.origin.x - span.origin.x) < 1.0
    assert new_span.size == 14
    assert pdf.undo()
    assert "Hello World" in pdf.page(0).get_text()


def test_replace_with_cjk_fallback(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    reg = FontRegistry(scan=False)
    span = text_edit.get_spans(pdf.page(0))[0]
    text_edit.replace_span(pdf, span, "日本語テキスト ABC", registry=reg)
    assert "日本語テキスト ABC" in pdf.page(0).get_text()


def test_add_text(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    reg = FontRegistry(scan=False)
    text_edit.add_text(pdf, 1, pymupdf.Point(100, 500), "New\nTwo lines", reg.get("Times Bold"), 18, (1, 0, 0))
    txt = pdf.page(1).get_text()
    assert "New" in txt and "Two lines" in txt


def test_font_matching():
    reg = FontRegistry(scan=False)
    assert reg.match_pdf_font("ABCDEF+Arial-BoldMT", 16).builtin == "hebo"
    assert reg.match_pdf_font("TimesNewRoman", 4 | 2).builtin == "tiit"
    assert reg.match_pdf_font("CourierNew", 8).builtin == "cour"
    assert reg.match_pdf_font("Helvetica", 0).builtin == "helv"


def test_shapes_add_delete_move(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    style = shapes.ShapeStyle(stroke=(0, 0, 1), fill=(1, 1, 0), width=3)
    xref = shapes.add_shape(pdf, 0, "rect", pymupdf.Point(50, 50), pymupdf.Point(150, 120), style)
    assert len(list(pdf.page(0).annots())) == 1
    hit = shapes.annot_at(pdf.page(0), pymupdf.Point(100, 100))
    assert hit is not None and hit.xref == xref
    assert shapes.move_annot(pdf, 0, xref, 10, 10)
    hit = shapes.annot_at(pdf.page(0), pymupdf.Point(60, 60))
    assert hit is not None
    assert shapes.delete_annot(pdf, 0, xref)
    assert len(list(pdf.page(0).annots())) == 0

    shapes.add_shape(pdf, 0, "ellipse", pymupdf.Point(50, 50), pymupdf.Point(150, 120), style)
    shapes.add_shape(pdf, 0, "line", pymupdf.Point(10, 10), pymupdf.Point(90, 90), style)
    xa = shapes.add_shape(pdf, 0, "arrow", pymupdf.Point(10, 200), pymupdf.Point(90, 290), style)
    assert len(list(pdf.page(0).annots())) == 3
    assert shapes.move_annot(pdf, 0, xa, 5, 5)
    shapes.add_ink(pdf, 0, [[pymupdf.Point(1, 1), pymupdf.Point(20, 30), pymupdf.Point(40, 10)]], style)
    shapes.add_text_box(pdf, 0, pymupdf.Rect(200, 600, 400, 640), "box", fontsize=12)
    assert len(list(pdf.page(0).annots())) == 5


def test_delete_content_drawing(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    page = pdf.page(0)
    d = shapes.drawing_at(page, pymupdf.Point(350, 330))
    assert d is not None
    shapes.delete_drawing(pdf, 0, d.rect)
    assert shapes.drawing_at(pdf.page(0), pymupdf.Point(350, 330)) is None
    assert "Hello World" in pdf.page(0).get_text()  # text kept


def test_repeated_annot_moves_do_not_distort():
    import pymupdf
    from leafweaving.core import shapes
    from leafweaving.core.document import PdfDocument

    pdf = PdfDocument.new()
    xref = shapes.add_shape(pdf, 0, "rect", pymupdf.Point(100, 100), pymupdf.Point(200, 160),
                            shapes.ShapeStyle(stroke=(1, 0, 0), width=3))
    page = pdf.page(0)
    r0 = pymupdf.Rect(list(page.annots())[0].rect)
    for _ in range(3):
        assert shapes.move_annot(pdf, 0, xref, 10, 5)
    page = pdf.page(0)
    r = pymupdf.Rect(list(page.annots())[0].rect)
    assert (round(r.x0 - r0.x0, 3), round(r.y0 - r0.y0, 3)) == (30, 15)
    assert (round(r.width, 3), round(r.height, 3)) == (round(r0.width, 3), round(r0.height, 3))
