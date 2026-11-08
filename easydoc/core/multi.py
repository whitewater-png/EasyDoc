"""Operations on several selected objects at once (one undo step each)."""
from __future__ import annotations

from typing import Optional, Sequence

import pymupdf

from . import shapes
from .document import PdfDocument
from .fonts import FontInfo, FontRegistry, default_registry
from .embedded_fonts import PageFontIndex
from .text_edit import TextSpan, redact_box, write_span_text


def _remove_spans(page: pymupdf.Page, spans: Sequence[TextSpan]) -> None:
    """Remove the glyphs of every span with ONE redaction pass, so that text that is
    about to be re-written elsewhere is never wiped by a later span's redaction."""
    if not spans:
        return
    for span in spans:
        page.add_redact_annot(redact_box(span.bbox))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)


def move_items(pdf: PdfDocument, pno: int, spans: Sequence[TextSpan], drawings: Sequence[shapes.Drawing],
               annot_xrefs: Sequence[int], dx: float, dy: float,
               registry: Optional[FontRegistry] = None) -> None:
    """Move text spans, content-stream drawings and annotations together by (dx, dy)."""
    registry = registry or default_registry()
    page = pdf.page(pno)
    with pdf.batch():
        index = PageFontIndex(page) if spans else None   # before the redaction
        _remove_spans(page, spans)
        movable = [d for d in drawings if d.data and d.data.get("items")]
        for d in movable:
            shapes.remove_drawing(page, d.rect)
        for s in spans:
            write_span_text(page, index, pymupdf.Point(s.origin.x + dx, s.origin.y + dy), s.text, s,
                            s.size, s.color, registry=registry)
        for d in movable:
            shapes.redraw_drawing(page, d, dx, dy)
        for xref in annot_xrefs:
            shapes.move_annot(pdf, pno, xref, dx, dy)
        pdf.mutated()


def edit_spans(pdf: PdfDocument, spans: Sequence[TextSpan], find: str = "", replace: str = "",
               font: Optional[FontInfo] = None, size: Optional[float] = None, color=None,
               registry: Optional[FontRegistry] = None) -> int:
    """Change several spans at once.  ``None`` font / size / color keep each span's own
    value; a non-empty ``find`` string is replaced inside every span's text.  Returns the
    number of spans that were rewritten."""
    registry = registry or default_registry()
    if not spans:
        return 0
    page = pdf.page(spans[0].page)
    with pdf.batch():
        plan = []
        for s in spans:
            text = s.text.replace(find, replace) if find else s.text
            plan.append((s, text))
        index = PageFontIndex(page) if font is None else None   # before the redaction
        _remove_spans(page, [s for s, _ in plan])
        for s, text in plan:
            if text.strip():
                write_span_text(page, index, s.origin, text, s, size or s.size,
                                color if color is not None else s.color, font, registry)
        pdf.mutated()
    return len(plan)


def delete_items(pdf: PdfDocument, pno: int, spans: Sequence[TextSpan], drawings: Sequence[shapes.Drawing],
                 annot_xrefs: Sequence[int]) -> None:
    page = pdf.page(pno)
    with pdf.batch():
        _remove_spans(page, spans)
        for d in drawings:
            shapes.remove_drawing(page, d.rect)
        for xref in annot_xrefs:
            shapes.delete_annot(pdf, pno, xref)
        pdf.mutated()
