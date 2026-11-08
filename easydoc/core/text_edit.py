"""Text inspection and (simple) text editing.

Editing existing text in a PDF is done the only robust way MuPDF offers:
the original glyphs are removed with a redaction limited to the span's box
and the replacement string is written at the same baseline with a matching
(or user chosen) font.  New text can be placed anywhere with the same writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import pymupdf

from .document import PdfDocument
from .fonts import FontInfo, FontRegistry, default_registry


@dataclass
class TextSpan:
    page: int
    bbox: pymupdf.Rect
    text: str
    font: str
    size: float
    color: tuple[float, float, float]
    origin: pymupdf.Point
    flags: int
    block: int
    line: int

    @property
    def is_bold(self) -> bool:
        return bool(self.flags & 16)

    @property
    def is_italic(self) -> bool:
        return bool(self.flags & 2)


def _int_to_rgb(value: int) -> tuple[float, float, float]:
    return ((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0, (value & 255) / 255.0


def get_spans(page: pymupdf.Page) -> list[TextSpan]:
    """Return every text span of the page in *unrotated* page coordinates."""
    spans: list[TextSpan] = []
    data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    for b_idx, block in enumerate(data.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        for l_idx, line in enumerate(block.get("lines", [])):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                spans.append(TextSpan(
                    page=page.number,
                    bbox=pymupdf.Rect(span["bbox"]),
                    text=text,
                    font=span.get("font", ""),
                    size=float(span.get("size", 11)),
                    color=_int_to_rgb(int(span.get("color", 0))),
                    origin=pymupdf.Point(span.get("origin", (span["bbox"][0], span["bbox"][3]))),
                    flags=int(span.get("flags", 0)),
                    block=b_idx,
                    line=l_idx,
                ))
    return spans


def span_at(page: pymupdf.Page, point: pymupdf.Point) -> Optional[TextSpan]:
    for span in get_spans(page):
        if span.bbox.contains(point):
            return span
    return None


def _runs_with_fallback(text: str, font: pymupdf.Font, fallback: pymupdf.Font):
    """Split text into (chunk, font) runs so that glyphs missing from ``font``
    are rendered with ``fallback`` (which covers CJK)."""
    runs: list[tuple[str, pymupdf.Font]] = []
    current: list[str] = []
    current_font = font
    for ch in text:
        use = font if (ch.isspace() or font.has_glyph(ord(ch))) else fallback
        if use is not current_font and current:
            runs.append(("".join(current), current_font))
            current = []
        current_font = use
        current.append(ch)
    if current:
        runs.append(("".join(current), current_font))
    return runs


def write_text(page: pymupdf.Page, origin: pymupdf.Point, text: str, font_info: FontInfo,
               size: float, color: Sequence[float] = (0, 0, 0)) -> pymupdf.Rect:
    """Write ``text`` with its baseline starting at ``origin``.  Returns the bbox."""
    font = font_info.load()
    fallback = pymupdf.Font("cjk")
    writer = pymupdf.TextWriter(page.rect)
    pos = pymupdf.Point(origin)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        x = pos.x
        y = pos.y + i * size * 1.2
        for chunk, f in _runs_with_fallback(line, font, fallback):
            writer.append((x, y), chunk, font=f, fontsize=size)
            x += f.text_length(chunk, fontsize=size)
    writer.write_text(page, color=tuple(color))
    return writer.text_rect


def replace_span(pdf: PdfDocument, span: TextSpan, new_text: str,
                 font_info: Optional[FontInfo] = None, size: Optional[float] = None,
                 color: Optional[Sequence[float]] = None,
                 registry: Optional[FontRegistry] = None) -> None:
    """Replace the text of one span.  Empty ``new_text`` just deletes it."""
    registry = registry or default_registry()
    page = pdf.page(span.page)
    if font_info is None:
        font_info = registry.match_pdf_font(span.font, span.flags)
    size = size or span.size
    color = color if color is not None else span.color

    pdf.snapshot()
    # A slightly deflated box avoids clipping glyphs of neighbouring spans.
    box = pymupdf.Rect(span.bbox)
    box.x0 += 0.5
    box.x1 -= 0.5
    page.add_redact_annot(box)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    if new_text:
        write_text(page, span.origin, new_text, font_info, size, color)
    pdf.mutated()


def add_text(pdf: PdfDocument, pno: int, point: pymupdf.Point, text: str,
             font_info: FontInfo, size: float = 12, color: Sequence[float] = (0, 0, 0)) -> None:
    """Place new text with its baseline at ``point`` (unrotated page coordinates)."""
    if not text:
        return
    pdf.snapshot()
    page = pdf.page(pno)
    write_text(page, point, text, font_info, size, color)
    pdf.mutated()
