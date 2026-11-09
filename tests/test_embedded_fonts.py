"""Moving / editing text keeps the PDF's own (embedded, subset) fonts."""
import collections
from pathlib import Path

import pymupdf
import pytest

from leafweaving.core import multi, text_edit
from leafweaving.core.document import PdfDocument
from leafweaving.core.embedded_fonts import PageFontIndex, drawn_strings, parse_tounicode
from leafweaving.core.fonts import FontRegistry

CJK_FAMILY = "Droid Sans Fallback Regular"


def _subset_pdf(tmp_path) -> PdfDocument:
    """A PDF like real-world ones: a *subset* CJK font plus an unembedded Helvetica."""
    d = pymupdf.open()
    p = d.new_page()
    tw = pymupdf.TextWriter(p.rect)
    tw.append((60, 100), "請求書 No.1234", font=pymupdf.Font("cjk"), fontsize=14)
    tw.append((60, 140), "株式会社 御中", font=pymupdf.Font("cjk"), fontsize=12)
    tw.write_text(p)
    p.insert_text((60, 200), "Total 20,000", fontname="helv", fontsize=12)
    d.subset_fonts()
    path = tmp_path / "subset.pdf"
    d.save(str(path), garbage=3, deflate=True)
    pdf = PdfDocument.open(str(path))
    fonts = {f[3] for f in pdf.page(0).get_fonts(full=True)}
    assert any("+" in f for f in fonts), fonts  # really a subset
    return pdf


def _state(pdf):
    return collections.Counter((s.text, s.font) for s in text_edit.get_spans(pdf.page(0)))


def _registry():
    return FontRegistry(scan=False, use_cache=False)


def test_group_move_keeps_embedded_fonts(tmp_path):
    pdf = _subset_pdf(tmp_path)
    before = _state(pdf)
    for i in range(6):
        multi.move_items(pdf, 0, text_edit.get_spans(pdf.page(0)), [], [], (-1) ** i * 7, 5,
                         registry=_registry())
        assert _state(pdf) == before, f"round {i}"


def test_single_move_keeps_embedded_font(tmp_path):
    pdf = _subset_pdf(tmp_path)
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("株式"))
    text_edit.move_span(pdf, span, 10, 20, registry=_registry())
    moved = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("株式"))
    assert moved.font == span.font and moved.text == span.text
    assert abs(moved.origin.x - span.origin.x - 10) < 0.5 and abs(moved.origin.y - span.origin.y - 20) < 0.5


def test_edit_with_existing_glyphs_keeps_font(tmp_path):
    pdf = _subset_pdf(tmp_path)
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("請求書"))
    text_edit.replace_span(pdf, span, "請求書 No.4321", registry=_registry())   # glyphs all present
    new = [s for s in text_edit.get_spans(pdf.page(0)) if s.text == "請求書 No.4321"]
    assert new and new[0].font == span.font


def test_edit_with_missing_glyph_falls_back_and_text_is_exact(tmp_path):
    pdf = _subset_pdf(tmp_path)
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("請求書"))
    text_edit.replace_span(pdf, span, "見積書 No.5-6", registry=_registry())    # 見積/5/-/6 not in subset
    new = [s for s in text_edit.get_spans(pdf.page(0)) if s.text == "見積書 No.5-6"]
    assert new, [s.text for s in text_edit.get_spans(pdf.page(0))]
    assert "+" not in new[0].font  # a real substitute, not the subset


def test_latin_unembedded_font_edits_freely(tmp_path):
    pdf = _subset_pdf(tmp_path)
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("Total"))
    text_edit.replace_span(pdf, span, "Grand total 99,999", registry=_registry())
    new = [s for s in text_edit.get_spans(pdf.page(0)) if s.text == "Grand total 99,999"]
    assert new and new[0].font == span.font


def test_explicit_font_choice_is_respected(tmp_path):
    pdf = _subset_pdf(tmp_path)
    reg = _registry()
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("Total"))
    text_edit.replace_span(pdf, span, "Total 20,000", font_info=reg.get("Courier"), registry=reg)
    new = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text == "Total 20,000")
    assert "mono" in new.font.lower() or "cour" in new.font.lower()


def test_fallback_text_layer_matches_written_text():
    """Glyphs shared by several characters ('-' / U+2012, ' ' / NBSP) must extract as written."""
    pdf = PdfDocument.new()
    reg = _registry()
    text_edit.write_text(pdf.page(0), pymupdf.Point(50, 100), "814-0055 片山 太郎",
                         reg.get("CJK Fallback (Droid Sans Fallback)"), 12)
    assert pdf.page(0).get_text().strip() == "814-0055 片山 太郎"


def test_index_respects_subset_glyphs(tmp_path):
    pdf = _subset_pdf(tmp_path)
    ix = PageFontIndex(pdf.page(0))
    assert ix.can_write(CJK_FAMILY, "御中 4321")
    assert not ix.can_write(CJK_FAMILY, "御中 5")     # '5' never drawn -> not in the subset


def test_content_tokenizer():
    content = (b"q BT /F1 12 Tf (a\\(b\\)c\\101) Tj [(x) -250 <0041>] TJ ET "
               b"BI /W 1 /H 1 /BPC 8 /CS /G ID \x00EI\x01 EI Q "
               b"BT /F2 9 Tf <00410042> Tj ET % comment (no) Tj\n")
    got = list(drawn_strings(content))
    assert got == [("F1", b"a(b)cA"), ("F1", b"x"), ("F1", b"\x00A"), ("F2", b"\x00A\x00B")]


def test_tounicode_ranges():
    cmap = (b"2 beginbfchar <01> <0041> <02> <D83DDE00> endbfchar "
            b"1 beginbfrange <10> <12> <0061> endbfrange "
            b"1 beginbfrange <20> <21> [<3042> <3044>] endbfrange")
    m = parse_tounicode(cmap)
    assert m[1] == "A" and m[2] == "\U0001F600"
    assert [m[0x10], m[0x11], m[0x12]] == ["a", "b", "c"]
    assert m[0x20] == "あ" and m[0x21] == "い"


REAL = Path.home() / "Downloads" / "VIM株式会社御中_2026年10月動画編集代行_請求書_INV-0000000017.pdf"


@pytest.mark.skipif(not REAL.exists(), reason="local sample invoice not available")
def test_real_invoice_keeps_ipa_gothic():
    pdf = PdfDocument.open(str(REAL))
    before = _state(pdf)
    for i in range(5):
        multi.move_items(pdf, 0, text_edit.get_spans(pdf.page(0)), [], [], (-1) ** i * 4, -3)
    assert _state(pdf) == before
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text == "20,000円")
    text_edit.replace_span(pdf, span, "30,000円")
    assert any(s.text == "30,000円" and s.font == "IPAPGothic" for s in text_edit.get_spans(pdf.page(0)))


# ----------------------------------------------------------- review regressions
def _rename_fonts(pdf: PdfDocument, names: dict[str, tuple[str, str]]):
    """Give the page's Type0 fonts specific /BaseFont names: res -> (type0, descendant)."""
    doc = pdf.doc
    for xref, _e, _t, _b, res, _enc, _r in pdf.page(0).get_fonts(full=True):
        if res in names:
            top, desc = names[res]
            doc.xref_set_key(xref, "BaseFont", "/" + top)
            dk, dv = doc.xref_get_key(xref, "DescendantFonts")
            dxref = int(dv.strip("[]").split()[0])
            doc.xref_set_key(dxref, "BaseFont", "/" + desc)
    data = doc.tobytes()
    return PdfDocument.open_bytes(data) if hasattr(PdfDocument, "open_bytes") else _reopen(data)


def _reopen(data: bytes) -> PdfDocument:
    import tempfile
    import os

    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return PdfDocument.open(path)


def _two_font_pdf(tmp_path, reg_text="Hello World", bold_text="Hold Bold"):
    d = pymupdf.open()
    p = d.new_page()
    p.insert_font(fontname="FR", fontbuffer=pymupdf.Font("cjk").buffer)
    # a byte-different copy, so that PyMuPDF does not merge both into one font object
    p.insert_font(fontname="FB", fontbuffer=pymupdf.Font("cjk").buffer + b"\0\0\0\0")
    p.insert_text((60, 100), bold_text, fontname="FB", fontsize=12)
    p.insert_text((60, 140), reg_text, fontname="FR", fontsize=12)
    d.subset_fonts()
    path = tmp_path / "two.pdf"
    d.save(str(path), garbage=3)
    return PdfDocument.open(str(path))


def test_weights_never_mix_by_name_prefix(tmp_path):
    pdf = _rename_fonts(_two_font_pdf(tmp_path), {"FR": ("AAAAAA+TestNeue", "AAAAAA+TestNeue"),
                                                  "FB": ("BBBBBB+TestNeue-Bold", "BBBBBB+TestNeue-Bold")})
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text == "Hello World")
    assert span.font == "TestNeue"
    text_edit.replace_span(pdf, span, "Hello Hold", registry=_registry())
    new = [s for s in text_edit.get_spans(pdf.page(0)) if "Hello" in s.text]
    assert [(s.text, s.font) for s in new] == [("Hello Hold", "TestNeue")]


def test_cid_font_named_by_cmap_is_reused(tmp_path):
    pdf = _rename_fonts(_two_font_pdf(tmp_path), {"FR": ("AAAAAA+Mincho-Identity-H", "AAAAAA+Mincho")})
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text == "Hello World")
    assert PageFontIndex(pdf.page(0)).can_write(span.font, "World Hello", pdf.page(0))
    text_edit.move_span(pdf, span, 5, 5, registry=_registry())
    assert any(s.text == "Hello World" and s.font == span.font for s in text_edit.get_spans(pdf.page(0)))


def test_rotated_page_never_loses_text(tmp_path):
    pdf = _subset_pdf(tmp_path)
    pdf.page(0).set_rotation(90)
    before = sorted(s.text for s in text_edit.get_spans(pdf.page(0)))
    span = next(s for s in text_edit.get_spans(pdf.page(0)) if s.text.startswith("株式"))
    text_edit.move_span(pdf, span, 0, 10, registry=_registry())
    multi.move_items(pdf, 0, text_edit.get_spans(pdf.page(0)), [], [], 3, 3, registry=_registry())
    assert sorted(s.text for s in text_edit.get_spans(pdf.page(0))) == before


def test_invisible_ocr_font_is_not_reused():
    pdf = PdfDocument.new()
    page = pdf.page(0)
    page.insert_text((60, 100), "Invoice 123", fontname="helv", fontsize=12, render_mode=3)
    span = text_edit.get_spans(page)[0]
    assert not PageFontIndex(page).can_write(span.font, "Invoice 321", page)
    text_edit.replace_span(pdf, span, "Invoice 321", registry=_registry())
    kinds = {t["type"] for t in pdf.page(0).get_texttrace()}
    assert kinds == {0}  # written visibly (fill), not as invisible text


@pytest.mark.skipif(FontRegistry(scan=True).get("Hiragino Sans W3") is None, reason="needs Hiragino (macOS)")
def test_shared_glyph_mapping_is_stable():
    reg = FontRegistry(scan=True)
    pdf = PdfDocument.new()
    hira = reg.get("Hiragino Sans W3")
    text_edit.write_text(pdf.page(0), pymupdf.Point(50, 100), "TEL 03-1234-5678", hira, 12)
    text_edit.write_text(pdf.page(0), pymupdf.Point(50, 140), "A‒B", hira, 12)
    assert pdf.page(0).get_text().splitlines()[0] == "TEL 03-1234-5678"
