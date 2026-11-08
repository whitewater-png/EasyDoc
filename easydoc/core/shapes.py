"""Vector shapes.

New shapes are added as *annotations* (Square / Circle / Line / Ink / FreeText),
which keeps them selectable and deletable later on.  Existing vector drawings
that are baked into the page content stream can be removed with a redaction
restricted to line art.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

import pymupdf

from .document import PdfDocument

ShapeKind = str  # "rect" | "ellipse" | "line" | "arrow"


@dataclass
class ShapeStyle:
    stroke: Optional[tuple[float, float, float]] = (0.0, 0.0, 0.0)
    fill: Optional[tuple[float, float, float]] = None
    width: float = 1.5
    opacity: float = 1.0


def _apply_style(annot: pymupdf.Annot, style: ShapeStyle) -> None:
    annot.set_colors(stroke=style.stroke, fill=style.fill)
    annot.set_border(width=style.width)
    if style.opacity < 1.0:
        annot.set_opacity(style.opacity)
    annot.update()


def add_shape(pdf: PdfDocument, pno: int, kind: ShapeKind,
              p1: pymupdf.Point, p2: pymupdf.Point, style: Optional[ShapeStyle] = None) -> int:
    """Add a shape between two corner / end points. Returns the annotation xref."""
    style = style or ShapeStyle()
    page = pdf.page(pno)
    pdf.snapshot()
    if kind in ("rect", "ellipse"):
        rect = pymupdf.Rect(p1, p2).normalize()
        if rect.is_empty or rect.width < 1 or rect.height < 1:
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + max(rect.width, 1), rect.y0 + max(rect.height, 1))
        annot = page.add_rect_annot(rect) if kind == "rect" else page.add_circle_annot(rect)
    elif kind in ("line", "arrow"):
        annot = page.add_line_annot(p1, p2)
        if kind == "arrow":
            annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
    else:
        raise ValueError(f"unknown shape kind {kind!r}")
    _apply_style(annot, style)
    pdf.mutated()
    return annot.xref


def add_ink(pdf: PdfDocument, pno: int, strokes: Sequence[Sequence[pymupdf.Point]],
            style: Optional[ShapeStyle] = None) -> int:
    style = style or ShapeStyle()
    page = pdf.page(pno)
    pdf.snapshot()
    annot = page.add_ink_annot([[tuple(p) for p in s] for s in strokes])
    _apply_style(annot, style)
    pdf.mutated()
    return annot.xref


def add_text_box(pdf: PdfDocument, pno: int, rect: pymupdf.Rect, text: str, fontsize: float = 12,
                 text_color=(0, 0, 0), fill_color=None, border_color=None, fontname: str = "helv") -> int:
    """Add an editable FreeText annotation (a text box that can be moved/deleted)."""
    page = pdf.page(pno)
    pdf.snapshot()
    annot = page.add_freetext_annot(rect, text, fontsize=fontsize, fontname=fontname,
                                    text_color=text_color, fill_color=fill_color,
                                    border_color=border_color, border_width=1 if border_color else 0)
    annot.update()
    pdf.mutated()
    return annot.xref


def annot_at(page: pymupdf.Page, point: pymupdf.Point, tolerance: float = 3.0) -> Optional[pymupdf.Annot]:
    """Return the top-most annotation whose rectangle contains ``point``."""
    hit = None
    for annot in page.annots():
        r = pymupdf.Rect(annot.rect)
        r.x0 -= tolerance
        r.y0 -= tolerance
        r.x1 += tolerance
        r.y1 += tolerance
        if r.contains(point):
            hit = annot  # keep iterating so the last (top-most) wins
    return hit


def delete_annot(pdf: PdfDocument, pno: int, xref: int) -> bool:
    page = pdf.page(pno)
    for annot in page.annots():
        if annot.xref == xref:
            pdf.snapshot()
            page.delete_annot(annot)
            pdf.mutated()
            return True
    return False


def _shift_numbers(pdf: PdfDocument, xref: int, key: str, dx: float, dy: float) -> None:
    """Translate a PDF number array such as /Rect or /L (x y x y ...) in place.
    PDF user space has its y axis pointing up, hence ``-dy``."""
    kind, value = pdf.doc.xref_get_key(xref, key)
    if kind != "array":
        return
    nums = [float(v) for v in value.strip("[]").split()]
    for k in range(0, len(nums) - 1, 2):
        nums[k] += dx
        nums[k + 1] -= dy
    pdf.doc.xref_set_key(xref, key, "[" + " ".join(f"{n:.4f}" for n in nums) + "]")


def move_annot(pdf: PdfDocument, pno: int, xref: int, dx: float, dy: float) -> bool:
    """Translate an annotation.  Only the geometry keys are shifted; the existing
    appearance stream is reused, so repeated moves never distort the shape
    (regenerating it with ``annot.update()`` grew the rect on every move)."""
    page = pdf.page(pno)
    for annot in page.annots():
        if annot.xref == xref:
            pdf.snapshot()
            for key in ("Rect", "L"):
                _shift_numbers(pdf, xref, key, dx, dy)
            kind, value = pdf.doc.xref_get_key(xref, "InkList")
            if kind == "array" and "[" in value:
                nested = re.findall(r"\[([^\[\]]*)\]", value)
                lists = []
                for chunk in nested:
                    nums = [float(v) for v in chunk.split()]
                    nums = [n + dx if k % 2 == 0 else n - dy for k, n in enumerate(nums)]
                    lists.append("[" + " ".join(f"{n:.4f}" for n in nums) + "]")
                pdf.doc.xref_set_key(xref, "InkList", "[" + " ".join(lists) + "]")
            pdf.mutated()
            return True
    return False


@dataclass
class Drawing:
    rect: pymupdf.Rect
    kind: str  # "f" fill, "s" stroke, "fs" both
    data: Optional[dict] = None  # raw ``page.get_drawings()`` entry (used to redraw when moving)


def list_drawings(page: pymupdf.Page) -> list[Drawing]:
    out = []
    for d in page.get_drawings():
        r = d.get("rect")
        if r is None:
            continue
        r = pymupdf.Rect(r)
        if r.is_empty or r.is_infinite:
            continue
        out.append(Drawing(rect=r, kind=d.get("type", "s"), data=d))
    return out


def drawing_at(page: pymupdf.Page, point: pymupdf.Point, tolerance: float = 2.0,
               skip_background: bool = False) -> Optional[Drawing]:
    """Return the smallest content-stream drawing whose bbox contains ``point``.

    With ``skip_background`` drawings covering most of the page are ignored so that
    dragging on empty paper never grabs a page-sized background rectangle."""
    best = None
    page_area = page.rect.get_area()
    for d in list_drawings(page):
        if skip_background and d.rect.get_area() > 0.6 * page_area:
            continue
        r = pymupdf.Rect(d.rect) + (-tolerance, -tolerance, tolerance, tolerance)
        if r.contains(point):
            if best is None or r.get_area() < best.rect.get_area():
                best = d
    return best


def delete_drawing(pdf: PdfDocument, pno: int, rect: pymupdf.Rect) -> None:
    """Remove vector line art fully covered by ``rect`` (text and images are kept)."""
    page = pdf.page(pno)
    pdf.snapshot()
    # Inflate so that stroke widths extending past the path bbox are covered.
    m = 2.0
    page.add_redact_annot(pymupdf.Rect(rect) + (-m, -m, m, m))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                          text=pymupdf.PDF_REDACT_TEXT_NONE)
    pdf.mutated()


def remove_drawing(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    """Redaction-remove the line art covered by ``rect`` (no snapshot / notification)."""
    m = 2.0
    page.add_redact_annot(pymupdf.Rect(rect) + (-m, -m, m, m))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                          text=pymupdf.PDF_REDACT_TEXT_NONE)


def redraw_drawing(page: pymupdf.Page, drawing: Drawing, dx: float, dy: float) -> bool:
    """Draw ``drawing`` again, offset by (dx, dy) (no snapshot / notification)."""
    d = drawing.data
    if not d or not d.get("items"):
        return False
    shape = page.new_shape()
    off = pymupdf.Point(dx, dy)
    for item in d["items"]:
        op = item[0]
        if op == "l":
            shape.draw_line(pymupdf.Point(item[1]) + off, pymupdf.Point(item[2]) + off)
        elif op == "c":
            shape.draw_bezier(pymupdf.Point(item[1]) + off, pymupdf.Point(item[2]) + off,
                              pymupdf.Point(item[3]) + off, pymupdf.Point(item[4]) + off)
        elif op == "re":
            shape.draw_rect(pymupdf.Rect(item[1]) + (dx, dy, dx, dy))
        elif op == "qu":
            shape.draw_quad(pymupdf.Quad(*[pymupdf.Point(p) + off for p in item[1]]))
    kind = d.get("type", "s")
    shape.finish(
        fill=d.get("fill") if "f" in kind else None,
        color=d.get("color") if "s" in kind else None,
        width=d.get("width") or 1.0,
        closePath=bool(d.get("closePath", False)),
        even_odd=bool(d.get("even_odd", False)),
        fill_opacity=d.get("fill_opacity") if d.get("fill_opacity") is not None else 1,
        stroke_opacity=d.get("stroke_opacity") if d.get("stroke_opacity") is not None else 1,
        dashes=d.get("dashes") or None,
        lineCap=(d.get("lineCap") or [0])[0] if isinstance(d.get("lineCap"), (list, tuple)) else (d.get("lineCap") or 0),
        lineJoin=d.get("lineJoin") or 0,
    )
    shape.commit()
    return True


def move_drawing(pdf: PdfDocument, pno: int, drawing: Drawing, dx: float, dy: float) -> bool:
    """Move a content-stream vector drawing by removing it and redrawing it offset."""
    if not drawing.data or not drawing.data.get("items"):
        return False
    page = pdf.page(pno)
    pdf.snapshot()
    remove_drawing(page, drawing.rect)
    redraw_drawing(page, drawing, dx, dy)
    pdf.mutated()
    return True
