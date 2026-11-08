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
from .embedded_fonts import PageFontIndex
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
    direction: tuple[float, float] = (1.0, 0.0)

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
                    direction=tuple(line.get("dir", (1.0, 0.0))),
                ))
    return spans


def span_at(page: pymupdf.Page, point: pymupdf.Point) -> Optional[TextSpan]:
    for span in get_spans(page):
        if span.bbox.contains(point):
            return span
    return None


def _pick_font(text: str, font: pymupdf.Font, fallback: pymupdf.Font) -> pymupdf.Font:
    """One font for the whole line.  Mixing fonts inside a line made MuPDF report it as
    several spans, which then split apart when moved; when ``font`` lacks a glyph the
    CJK fallback (which also covers Latin) is used for the entire line instead."""
    if all(ch.isspace() or font.has_glyph(ord(ch)) for ch in text):
        return font
    return fallback


def redact_box(bbox: pymupdf.Rect) -> pymupdf.Rect:
    """Redaction rectangle for a span: pulled in on every side so that glyphs of
    neighbouring spans/lines (whose boxes merely touch this one) are left alone."""
    box = pymupdf.Rect(bbox)
    dy = box.height * 0.2
    box.x0 += 0.5
    box.x1 -= 0.5
    box.y0 += dy
    box.y1 -= dy
    return box


def write_text(page: pymupdf.Page, origin: pymupdf.Point, text: str, font_info: FontInfo,
               size: float, color: Sequence[float] = (0, 0, 0)) -> pymupdf.Rect:
    """Write ``text`` with its baseline starting at ``origin``.  Returns the bbox."""
    font = font_info.load()
    fallback = pymupdf.Font("cjk")
    writer = pymupdf.TextWriter(page.rect)
    pos = pymupdf.Point(origin)
    # NBSP & friends are missing from many fonts (the glyph is silently dropped, so the
    # gap collapsed and the line fell apart into separate spans); write plain spaces.
    text = text.translate({0xA0: " ", 0x2007: " ", 0x202F: " ", 0x3000: "\u3000"})
    lines = text.split("\n")
    written: list[tuple[pymupdf.Font, str]] = []
    for i, line in enumerate(lines):
        x = pos.x
        y = pos.y + i * size * 1.2
        f = _pick_font(line, font, fallback)
        writer.append((x, y), line, font=f, fontsize=size)
        written.append((f, line))
    writer.write_text(page, color=tuple(color))
    fix_tounicode(page, written)
    return writer.text_rect


_CMAP_HEAD = (b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
              b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
              b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
              b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n")
_CMAP_TAIL = b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"


def fix_tounicode(page: pymupdf.Page, written: Sequence[tuple[pymupdf.Font, str]]) -> None:
    """Make the text layer say what was written.

    Fonts such as Hiragino share one glyph between several characters ('-' and
    U+2012, ' ' and NBSP); MuPDF's generated ToUnicode then picks the other one, so
    copy/search/re-editing saw '‒' instead of '-'."""
    from .embedded_fonts import parse_tounicode  # local import: avoid a cycle

    wanted: dict[str, dict[int, str]] = {}
    for f, line in written:
        m = wanted.setdefault(f.name, {})
        for ch in line:
            gid = f.has_glyph(ord(ch))
            if gid:
                m[gid] = ch
    doc = page.parent
    patched = False
    for xref, _ext, typ, basefont, _res, enc, referencer in page.get_fonts(full=True):
        if referencer or typ != "Type0" or enc != "Identity-H":
            continue
        m = wanted.get(basefont)
        if not m:
            continue
        kind, val = doc.xref_get_key(xref, "ToUnicode")
        if kind != "xref":
            continue
        tu_xref = int(val.split()[0])
        current = parse_tounicode(doc.xref_stream(tu_xref) or b"")
        # One glyph can only carry one character.  On a clash the lowest code point
        # wins ('-' over U+2012, ' ' over NBSP), so writing a rare variant later never
        # changes what earlier text extracts as.
        changes = {g: ch for g, ch in m.items()
                   if current.get(g) != ch and (len(current.get(g) or "") != 1 or ord(ch) < ord(current[g]))}
        if not changes:
            continue
        current.update(changes)
        items = sorted((g, t) for g, t in current.items() if t and g <= 0xFFFF)
        body = bytearray()
        for k in range(0, len(items), 100):
            chunk = items[k:k + 100]
            body += f"{len(chunk)} beginbfchar\n".encode()
            for g, t in chunk:
                body += f"<{g:04X}> <{t.encode('utf-16-be').hex().upper()}>\n".encode()
            body += b"endbfchar\n"
        doc.update_stream(tu_xref, _CMAP_HEAD + bytes(body) + _CMAP_TAIL)
        patched = True
    if patched:
        # MuPDF caches loaded fonts (with their old ToUnicode) in its resource store;
        # empty it so that text extraction sees the corrected mapping right away.
        pymupdf.TOOLS.store_shrink(100)


def write_span_text(page: pymupdf.Page, index: Optional[PageFontIndex], origin: pymupdf.Point, text: str,
                    span: TextSpan, size: float, color: Sequence[float],
                    font_info: Optional[FontInfo] = None,
                    registry: Optional[FontRegistry] = None) -> bool:
    """Write ``text`` for ``span`` keeping its typeface as far as possible.

    Without an explicit ``font_info`` the page's own embedded font is used when every
    glyph is available in it (``index`` must be built *before* the old text was
    redacted); otherwise the closest installed font.  Returns True when the original
    embedded font was used."""
    lines = text.split("\n")
    horizontal = abs(span.direction[0] - 1.0) < 1e-3 and abs(span.direction[1]) < 1e-3
    if font_info is None and index is not None and horizontal \
            and all(index.can_write(span.font, ln, page) for ln in lines if ln):
        substitute = None
        for i, ln in enumerate(lines):
            if not ln:
                continue
            at = pymupdf.Point(origin.x, origin.y + i * size * 1.2)
            if not index.write(page, at, ln, span.font, size, color):
                # never lose text: the old glyphs are already redacted
                substitute = substitute or (registry or default_registry()).match_pdf_font(span.font, span.flags)
                write_text(page, at, ln, substitute, size, color)
        return substitute is None
    if font_info is None:
        font_info = (registry or default_registry()).match_pdf_font(span.font, span.flags)
    write_text(page, origin, text, font_info, size, color)
    return False


def replace_span(pdf: PdfDocument, span: TextSpan, new_text: str,
                 font_info: Optional[FontInfo] = None, size: Optional[float] = None,
                 color: Optional[Sequence[float]] = None,
                 registry: Optional[FontRegistry] = None) -> None:
    """Replace the text of one span.  Empty ``new_text`` just deletes it.
    ``font_info=None`` keeps the original typeface (embedded font if possible)."""
    registry = registry or default_registry()
    page = pdf.page(span.page)
    size = size or span.size
    color = color if color is not None else span.color

    pdf.snapshot()
    index = PageFontIndex(page) if font_info is None else None
    page.add_redact_annot(redact_box(span.bbox))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    if new_text:
        write_span_text(page, index, span.origin, new_text, span, size, color, font_info, registry)
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


def move_span(pdf: PdfDocument, span: TextSpan, dx: float, dy: float,
              registry: Optional[FontRegistry] = None) -> None:
    """Move one text span by (dx, dy) page units: remove the glyphs and rewrite
    the same text (same size/colour, best matching font) at the new origin."""
    registry = registry or default_registry()
    page = pdf.page(span.page)
    pdf.snapshot()
    index = PageFontIndex(page)
    page.add_redact_annot(redact_box(span.bbox))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    write_span_text(page, index, pymupdf.Point(span.origin.x + dx, span.origin.y + dy), span.text,
                    span, span.size, span.color, registry=registry)
    pdf.mutated()
