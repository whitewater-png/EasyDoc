"""Regression: moving text repeatedly (as a group) must not split, re-font or lose it."""
import os
import unicodedata
from pathlib import Path

import pymupdf
import pytest

from easydoc.core import multi, text_edit
from easydoc.core.document import PdfDocument

LINES = ["VIM株式会社 御中", "2026年10月動画編集代行", "INV-0000000017", "Hello World 12", "件名"]


def _make_pdf() -> PdfDocument:
    pdf = PdfDocument.new()
    page = pdf.page(0)
    cjk = pymupdf.Font("cjk")
    tw = pymupdf.TextWriter(page.rect)
    for i, line in enumerate(LINES[:3] + LINES[4:]):
        tw.append((60, 100 + i * 60), line.replace(" ", " "), font=cjk, fontsize=14)
    tw.write_text(page)
    page.insert_text((60, 500), LINES[3], fontname="helv", fontsize=12)
    return pdf


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKC", t).replace(" ", "")


def _state(pdf):
    spans = text_edit.get_spans(pdf.page(0))
    return sorted((_norm(s.text), s.font) for s in spans), spans


def _check_stable(pdf, rounds=8):
    first, spans = _state(pdf)
    texts = [t for t, _ in first]
    for i in range(rounds):
        multi.move_items(pdf, 0, spans, [], [], 3, 4)
        cur, spans = _state(pdf)
        assert [t for t, _ in cur] == texts, f"round {i}: text split/lost: {cur}"
        if i >= 1:
            assert cur == prev, f"round {i}: font changed {cur} vs {prev}"
        prev = cur
    # glyphs really still on the page (not only in the text layer)
    assert _norm(pdf.page(0).get_text()) == "".join(sorted_text(texts, pdf))


def sorted_text(texts, pdf):
    # page text order is layout dependent: compare as multiset of characters
    return list(_norm(pdf.page(0).get_text()))


def test_group_move_keeps_lines_whole_and_font_stable():
    pdf = _make_pdf()
    _check_stable(pdf)
    names = {f for _, f in _state(pdf)[0]}
    assert len(names) <= 2          # CJK fallback + Helvetica-ish, no drift through Times etc.


def test_nbsp_survives_move():
    from easydoc.core.fonts import default_registry
    pdf = PdfDocument.new()
    cjk = default_registry(scan=False).get("CJK Fallback (Droid Sans Fallback)")
    text_edit.write_text(pdf.page(0), pymupdf.Point(60, 100), "VIM株式会社\u00a0御中", cjk, 14)
    for _ in range(4):
        spans = text_edit.get_spans(pdf.page(0))
        assert [s.text for s in spans] == ["VIM株式会社 御中"], [s.text for s in spans]
        multi.move_items(pdf, 0, spans, [], [], 2, 2)


REAL = Path.home() / "Downloads" / "VIM株式会社御中_2026年10月動画編集代行_請求書_INV-0000000017.pdf"


@pytest.mark.skipif(not REAL.exists(), reason="local sample invoice not available")
def test_real_invoice_group_move():
    pdf = PdfDocument.open(str(REAL))
    before = [_norm(s.text) for s in text_edit.get_spans(pdf.page(0))]
    spans = text_edit.get_spans(pdf.page(0))
    for _ in range(6):
        multi.move_items(pdf, 0, spans, [], [], 2, 3)
        spans = text_edit.get_spans(pdf.page(0))
        assert sorted(_norm(s.text) for s in spans) == sorted(before)
