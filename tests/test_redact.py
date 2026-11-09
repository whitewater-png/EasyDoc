"""Redaction: content under the area is gone for good and the black box is locked."""
import pymupdf

from leafwright.core import multi, redact, shapes
from leafwright.core.document import PdfDocument

AREA = pymupdf.Rect(60, 80, 260, 110)   # covers "Page 1 Hello World" on line 1 only


def _black_at(page: pymupdf.Page, pt) -> bool:
    pix = page.get_pixmap(clip=pymupdf.Rect(pt[0] - 1, pt[1] - 1, pt[0] + 1, pt[1] + 1))
    return all(v < 30 for v in pix.pixel(0, 0))


def test_text_is_removed_and_area_blacked_out(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    assert redact.redact(pdf, 0, [AREA]) == 1
    page = pdf.page(0)
    text = page.get_text()
    assert "Hello" not in text and "Page 1" not in text
    assert "Second line of text" in text          # the line below is untouched
    assert page.search_for("Hello") == []
    assert _black_at(page, (160, 95))


def test_box_is_not_selectable(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    redact.redact(pdf, 0, [AREA])
    page = pdf.page(0)
    assert all(not AREA.contains(d.rect) for d in shapes.list_drawings(page))
    assert shapes.drawing_at(page, pymupdf.Point(160, 95)) is None


def test_shapes_images_annots_under_area_are_removed(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    page = pdf.page(0)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(pymupdf.Rect(300, 500, 400, 600), pixmap=pix)
    page.add_rect_annot(pymupdf.Rect(310, 310, 330, 330))
    page.add_freetext_annot(pymupdf.Rect(100, 700, 250, 720), "secret note")
    area = pymupdf.Rect(290, 290, 410, 610)
    redact.redact(pdf, 0, [area, pymupdf.Rect(90, 690, 120, 730)])
    page = pdf.page(0)
    assert [d for d in page.get_drawings() if d["fill"] == (0.0, 0.0, 1.0)] == []   # blue box gone
    assert list(page.annots()) == []
    assert "secret" not in page.get_text()
    # The image is still on the page but its pixels inside the area are no longer red.
    for info in page.get_images(full=True):
        img = pymupdf.Pixmap(pdf.doc, info[0])
        assert img.pixel(img.width // 2, img.height // 2)[:3] != (255, 0, 0)


def test_marks_survive_save_and_undo(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    redact.redact(pdf, 0, [AREA])
    out = tmp_path / "out.pdf"
    out.write_bytes(pdf.to_bytes())
    again = PdfDocument.open(str(out))
    assert len(redact.marks(again.page(0))) == 1
    assert "Hello" not in again.page(0).get_text()
    assert redact.marks(again.page(1)) == []
    pdf.undo()
    assert "Hello" in pdf.page(0).get_text() and redact.marks(pdf.page(0)) == []


def test_box_survives_erasing_or_moving_an_enclosing_drawing(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    page = pdf.page(0)
    frame = page.new_shape()
    frame.draw_rect(pymupdf.Rect(40, 60, 300, 130))
    frame.finish(color=(0, 0.5, 0), width=1)
    frame.commit()
    redact.redact(pdf, 0, [AREA])
    page = pdf.page(0)
    # A frame around the area overlaps it, so it is locked against the UI ...
    assert not [d for d in shapes.list_drawings(page) if d.data.get("color") == (0.0, 0.5, 0.0)]

    # ... and even when moved / erased through the API the black box is painted again.
    def frame_drawing():
        raw = next(d for d in pdf.page(0).get_drawings() if d.get("color") == (0.0, 0.5, 0.0))
        return shapes.Drawing(rect=pymupdf.Rect(raw["rect"]), kind=raw["type"], data=raw)
    multi.move_items(pdf, 0, [], [frame_drawing()], [], 0, 300)
    assert _black_at(pdf.page(0), (160, 95))
    shapes.delete_drawing(pdf, 0, frame_drawing().rect)
    assert _black_at(pdf.page(0), (160, 95))


def test_overlapping_redactions_keep_both_boxes(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    redact.redact(pdf, 0, [AREA])
    redact.redact(pdf, 0, [pymupdf.Rect(200, 90, 400, 150)])
    page = pdf.page(0)
    assert len(redact.marks(page)) == 2
    assert _black_at(page, (80, 95)) and _black_at(page, (350, 140))


def test_area_off_the_page_is_ignored(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    assert redact.redact(pdf, 0, [pymupdf.Rect(-200, -200, -100, -100)]) == 0
    assert not pdf.can_undo


def _outside_changes(before: pymupdf.Pixmap, after: pymupdf.Pixmap, areas, margin=2) -> int:
    """Number of pixels that changed OUTSIDE the (slightly grown) areas."""
    grown = [pymupdf.Rect(a) + (-margin, -margin, margin, margin) for a in areas]
    n = 0
    for y in range(before.height):
        for x in range(before.width):
            if any(g.contains(pymupdf.Point(x + 0.5, y + 0.5)) for g in grown):
                continue
            if before.pixel(x, y) != after.pixel(x, y):
                n += 1
    return n


def _raw_page(content: bytes, w=200, h=200):
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)
    xref = page.get_contents()[0] if page.get_contents() else None
    if xref is None:
        page.insert_text((0, -10), " ")
        xref = page.get_contents()[0]
    doc.update_stream(xref, content)
    return doc, page


def test_rotated_page_is_redacted(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=300)
    page.insert_text((400, 250), "OTHERSECRET", fontsize=16)
    page.set_rotation(90)
    pdf = PdfDocument(doc)
    target = page.search_for("OTHERSECRET")[0]          # already unrotated coordinates
    assert redact.redact(pdf, 0, [target + (-2, -2, 2, 2)]) == 1
    assert "OTHERSECRET" not in pdf.page(0).get_text()


def test_nothing_outside_the_area_changes_and_crossing_drawings_are_locked(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(10, 10, 290, 190), color=None, fill=(0.9, 0.9, 1.0))  # background
    page.draw_rect(pymupdf.Rect(20, 30, 280, 150), color=(0, 0, 0), width=1)        # table frame
    page.draw_line((20, 90), (280, 90), color=(0, 0, 0), width=1)                    # row line through area
    page.draw_bezier((90, 80), (120, 40), (140, 130), (200, 85), color=(0, 0, 1))   # curve crossing the edge
    page.draw_rect(pymupdf.Rect(110, 85, 130, 95), color=(1, 0, 0), width=1)        # fully inside
    page.insert_text((100, 95), "CONFIDENTIAL", fontsize=10)
    before = page.get_pixmap()
    pdf = PdfDocument(doc)
    area = pymupdf.Rect(95, 80, 180, 100)
    redact.redact(pdf, 0, [area])
    page = pdf.page(0)
    assert "CONFIDENTIAL" not in page.get_text()
    assert _outside_changes(before, page.get_pixmap(), [area]) == 0
    assert not [d for d in page.get_drawings() if d.get("color") == (1.0, 0.0, 0.0)]   # inside: removed
    # Drawings crossing the edge are kept as they are but cannot be selected / moved.
    selectable = [d.data.get("color") for d in shapes.list_drawings(page)]
    assert (0.0, 0.0, 1.0) not in selectable
    assert shapes.drawing_at(page, pymupdf.Point(60, 90)) is None          # the row line
    assert shapes.drawing_at(page, pymupdf.Point(250, 30)) is None         # the frame


def test_clipped_fill_and_white_cover_outside_area_are_untouched():
    # A full-page red fill clipped to a small square, and a white rectangle hiding an image:
    # both touch the area.  Nothing outside the area may change.
    content = (b"q 140 140 40 40 re W n 1 0 0 rg 0 0 400 400 re f Q\n"
               b"q 0 0 1 rg 20 20 80 80 re f Q\n"            # "secret" blue block
               b"q 1 1 1 rg 10 10 100 100 re f Q\n")         # white cover over it
    doc, page = _raw_page(content)
    before = page.get_pixmap()
    pdf = PdfDocument(doc)
    areas = [pymupdf.Rect(150, 30, 190, 60), pymupdf.Rect(90, 140, 120, 170)]
    redact.redact(pdf, 0, areas)
    assert _outside_changes(before, pdf.page(0).get_pixmap(), areas) == 0


def test_shared_resources_do_not_keep_removed_images(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=300, height=300)
    doc.new_page(width=300, height=300)
    w = h = 16
    img = doc.get_new_xref()
    doc.update_object(img, f"<</Type/XObject/Subtype/Image/Width {w}/Height {h}/ColorSpace/DeviceRGB/BitsPerComponent 8>>")
    doc.update_stream(img, (b"SECRETIMG" * 100)[: w * h * 3], compress=False)
    res = doc.get_new_xref()
    doc.update_object(res, f"<</XObject<</Im {img} 0 R>>>>")
    for i, body in enumerate((b"q 50 0 0 50 100 100 cm /Im Do Q", b"")):
        c = doc.get_new_xref()
        doc.update_object(c, "<<>>")
        doc.update_stream(c, body, compress=False)
        doc.xref_set_key(doc.page_xref(i), "Contents", f"{c} 0 R")
        doc.xref_set_key(doc.page_xref(i), "Resources", f"{res} 0 R")
    pdf = PdfDocument(doc)
    redact.redact(pdf, 0, [pymupdf.Rect(90, 140, 160, 210)])
    assert b"SECRETIMG" not in pdf.to_bytes(deflate=False)


def test_actual_text_is_dropped(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "X", fontsize=12)
    xref = page.get_contents()[0]
    data = doc.xref_stream(xref)
    doc.update_stream(xref, b"/Span <</ActualText (ACTUAL\\)SECRET (nested))>> BDC\n" + data + b"\nEMC\n")
    pdf = PdfDocument(doc)
    redact.redact(pdf, 0, [pymupdf.Rect(60, 80, 120, 110)])
    out = tmp_path / "a.pdf"
    out.write_bytes(pdf.to_bytes(deflate=False))
    assert b"SECRET" not in out.read_bytes()


def test_alt_texts_in_properties_inline_and_structure_tree_are_dropped():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "X", fontsize=12)
    xref = page.get_contents()[0]
    data = doc.xref_stream(xref)
    doc.update_stream(xref, b"/Span /P0 BDC /Figure <</Alt (SECRETALT) /E <53454352455445>>> BDC\n"
                      + data + b"\nEMC EMC\n")
    kind, value = doc.xref_get_key(page.xref, "Resources")
    res_xref = int(value.split()[0]) if kind == "xref" else page.xref
    doc.xref_set_key(res_xref, "Properties" if kind == "xref" else "Resources/Properties",
                     "<</P0 <</ActualText (SECRETPROP)>>>>")
    root = doc.get_new_xref()
    elem = doc.get_new_xref()
    doc.update_object(elem, f"<</Type/StructElem/S/P/Pg {page.xref} 0 R/Alt (SECRETSTRUCT)>>")
    doc.update_object(root, f"<</Type/StructTreeRoot/K {elem} 0 R>>")
    doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")
    pdf = PdfDocument(doc)
    redact.redact(pdf, 0, [pymupdf.Rect(60, 80, 120, 110)])
    blob = pdf.to_bytes(deflate=False)
    for secret in (b"SECRETALT", b"53454352455445", b"SECRETPROP", b"SECRETSTRUCT"):
        assert secret not in blob, secret


def test_link_outside_area_on_rotated_page_is_kept():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    link = pymupdf.Rect(400, 700, 500, 720)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": link, "uri": "https://a.example"})
    page.set_rotation(90)
    pdf = PdfDocument(pymupdf.open("pdf", doc.tobytes()))
    reported = pymupdf.Rect(pdf.page(0).get_links()[0]["from"])   # rotated coordinates
    assert not reported.intersects(link)
    redact.redact(pdf, 0, [reported])          # an area that does NOT touch the real link
    assert len(pdf.page(0).get_links()) == 1
    redact.redact(pdf, 0, [link + (-5, -5, 5, 5)])
    assert pdf.page(0).get_links() == []


def test_marks_follow_extracted_and_merged_pages(sample_pdf, tmp_path):
    from leafwright.core import pages

    pdf = PdfDocument.open(sample_pdf)
    redact.redact(pdf, 1, [AREA])
    pages.extract_pages(pdf, [2, 1], tmp_path / "x.pdf")
    x = PdfDocument.open(str(tmp_path / "x.pdf"))
    assert redact.marks(x.page(0)) == [] and len(redact.marks(x.page(1))) == 1
    assert shapes.drawing_at(x.page(1), pymupdf.Point(160, 95)) is None
    pages.split_every(pdf, 2, tmp_path / "parts")
    assert len(redact.marks(PdfDocument.open(str(tmp_path / "parts" / "part_001.pdf")).page(1))) == 1
    base = PdfDocument.open(sample_pdf)
    pages.merge_files(base, [tmp_path / "x.pdf"], insert_at=0)
    assert len(redact.marks(base.page(1))) == 1 and redact.marks(base.page(0)) == []


def test_repeated_area_is_recorded_once_and_lines_can_be_redacted(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    redact.redact(pdf, 0, [AREA])
    redact.redact(pdf, 0, [AREA])
    assert len(redact.marks(pdf.page(0))) == 1
    assert redact.redact(pdf, 0, [pymupdf.Rect(300, 500, 400, 500)]) == 1   # zero-height (a line)


def test_drawing_moved_into_area_stays_selectable(sample_pdf):
    pdf = PdfDocument.open(sample_pdf)
    redact.redact(pdf, 0, [pymupdf.Rect(50, 250, 450, 450)])   # also removes the blue box
    page = pdf.page(0)
    s = page.new_shape()
    s.draw_rect(pymupdf.Rect(100, 300, 120, 320))
    s.finish(color=(1, 0, 0), width=1)
    s.commit()
    assert any(d.data.get("color") == (1.0, 0.0, 0.0) for d in shapes.list_drawings(pdf.page(0)))


def _signature_page():
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(pymupdf.Rect(10, 10, 290, 190), color=None, fill=(0.9, 0.9, 1.0))   # background
    page.draw_bezier((60, 100), (90, 40), (120, 160), (200, 95), color=(0, 0, 1), width=2)  # "signature"
    return doc


def test_crossing_signature_is_kept_and_locked_by_default():
    doc = _signature_page()
    pdf = PdfDocument(doc)
    redact.redact(pdf, 0, [pymupdf.Rect(110, 70, 170, 130)])
    page = pdf.page(0)
    sig = [d for d in page.get_drawings() if d.get("color") == (0.0, 0.0, 1.0)]
    assert len(sig) == 1                                                      # data still in the file
    assert all(d.data.get("color") != (0.0, 0.0, 1.0) for d in shapes.list_drawings(page))  # but locked


def test_remove_crossing_deletes_the_whole_signature_from_the_file():
    doc = _signature_page()
    pdf = PdfDocument(doc)
    redact.redact(pdf, 0, [pymupdf.Rect(110, 70, 170, 130)], remove_crossing=True)
    page = pdf.page(0)
    assert [d for d in page.get_drawings() if d.get("color") == (0.0, 0.0, 1.0)] == []
    # The documented side effect: the page background touching the area is gone too.
    assert [d for d in page.get_drawings() if d.get("fill") == (0.8999999761581421, 0.8999999761581421, 1.0)] == []
    saved = PdfDocument(pymupdf.open("pdf", pdf.to_bytes(deflate=False)))
    assert [d for d in saved.page(0).get_drawings() if d.get("color") == (0.0, 0.0, 1.0)] == []
