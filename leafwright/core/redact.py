"""Redaction (墨塗り): permanently remove what is inside an area and black it out.

Unlike drawing a black rectangle on top, the content under the area is deleted
from the PDF itself:

* text whose glyphs overlap the area is removed (it cannot be copied or searched),
* image pixels inside the area are blanked,
* vector drawings lying inside the area are removed,
* annotations, form fields and links overlapping the area are deleted,
* replacement / alternate text (``/ActualText``, ``/Alt``, ``/E``) belonging to the
  page is dropped, and resources other pages share but no longer use are released
  so that removed images or forms do not linger in the saved file.

Vector drawings that only CROSS the edge of an area (page backgrounds, table
frames, long rules…) are left exactly as they are: rebuilding them would change
their stacking order and clipping and could damage or uncover content outside
the area.  The part of such a drawing under the black box stays hidden, and the
drawing is *locked* (it cannot be selected, moved or deleted), so the hidden part
can never be dragged into view.

With ``remove_crossing=True`` those crossing drawings are deleted WHOLE instead,
so none of their data survives.  The cost lands outside the area: MuPDF decides
"crossing" by bounding box (including line width), so page backgrounds, table
frames and nearby thick rules vanish, and a white rectangle that was hiding
something can be removed and uncover it.

Every redacted area is recorded on its page (``/LeafwrightRedactions``) so that
the black box and the locked drawings are excluded from selection, and the box is
painted again whenever another edit's line-art removal would have taken it away.
Areas are in unrotated page coordinates (the same space as ``PageView.to_page``).
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

import pymupdf

from .document import PdfDocument

MARK_KEY = "LeafwrightRedactions"
FILL = (0.0, 0.0, 0.0)
MIN_SIZE = 1.0     # thinner areas (a selected line) are widened to this on each side
ALT_KEYS = ("ActualText", "Alt", "E")


# ------------------------------------------------------------------ marks
def marks(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """The redacted areas recorded on ``page`` (unrotated page coordinates)."""
    kind, value = page.parent.xref_get_key(page.xref, MARK_KEY)
    if kind != "array":
        return []
    try:
        nums = [float(v) for v in value.strip("[]").split()]
    except ValueError:
        return []
    return [pymupdf.Rect(nums[k:k + 4]) for k in range(0, len(nums) - 3, 4)]


def _set_marks(page: pymupdf.Page, rects: Iterable[pymupdf.Rect]) -> None:
    nums = " ".join(f"{r.x0:.3f} {r.y0:.3f} {r.x1:.3f} {r.y1:.3f}" for r in rects)
    page.parent.xref_set_key(page.xref, MARK_KEY, f"[{nums}]")


def copy_marks(src: pymupdf.Document, src_pnos: Iterable[int], dst: pymupdf.Document, dst_start: int) -> None:
    """``insert_pdf`` drops unknown page keys: carry the marks over to the copies."""
    for k, pno in enumerate(src_pnos):
        kind, value = src.xref_get_key(src[pno].xref, MARK_KEY)
        if kind == "array":
            dst.xref_set_key(dst[dst_start + k].xref, MARK_KEY, value)


def _within(inner: pymupdf.Rect, outer: pymupdf.Rect, tol: float = 1.5) -> bool:
    return (inner.x0 >= outer.x0 - tol and inner.y0 >= outer.y0 - tol
            and inner.x1 <= outer.x1 + tol and inner.y1 <= outer.y1 + tol)


def _overlaps(a: pymupdf.Rect, b: pymupdf.Rect, eps: float = 0.5) -> bool:
    """Real overlap (not mere edge contact); works for zero-height / zero-width boxes."""
    return not (a.x1 <= b.x0 + eps or a.x0 >= b.x1 - eps or a.y1 <= b.y0 + eps or a.y0 >= b.y1 - eps)


def is_box_drawing(d: dict) -> bool:
    """A filled black path, i.e. what a redaction paints."""
    fill = d.get("fill")
    return "f" in d.get("type", "") and fill is not None and all(abs(c) < 0.01 for c in fill)


def is_redacted(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    """True if ``rect`` lies inside a redacted area."""
    return any(_within(pymupdf.Rect(rect), m) for m in marks(page))


def is_locked(d: dict, areas: Sequence[pymupdf.Rect]) -> bool:
    """A drawing that must not be selected: a redaction box, or a drawing crossing the
    edge of a redacted area (moving it would uncover the part hidden under the box).
    Drawings lying fully inside an area were added after the redaction and stay free."""
    r = pymupdf.Rect(d["rect"])
    for a in areas:
        if _within(r, a):
            if is_box_drawing(d):
                return True
        elif _overlaps(r, a):
            return True
    return False


# ---------------------------------------------------------------- painting
def _paint(page: pymupdf.Page, rect: pymupdf.Rect) -> None:
    page.draw_rect(rect, color=None, fill=FILL, width=0, overlay=True)


def repaint(page: pymupdf.Page) -> None:
    """Paint the black box of every recorded area that is no longer on the page
    (another edit's line-art removal may have covered and removed it)."""
    ms = marks(page)
    if not ms:
        return
    filled = [pymupdf.Rect(d["rect"]) for d in page.get_drawings() if is_box_drawing(d)]
    for m in ms:
        if not any(f.x0 <= m.x0 + 1 and f.y0 <= m.y0 + 1 and f.x1 >= m.x1 - 1 and f.y1 >= m.y1 - 1
                   for f in filled):
            _paint(page, m)


# ------------------------------------------------------- alternate texts
def _skip_pdf_string(data: bytes, i: int) -> int:
    """Index just past the PDF string (literal or hex) starting at ``data[i]``, or -1."""
    if i >= len(data):
        return -1
    if data[i:i + 1] == b"<" and data[i + 1:i + 2] != b"<":
        j = data.find(b">", i + 1)
        return -1 if j < 0 else j + 1
    if data[i:i + 1] != b"(":
        return -1
    depth, j = 0, i
    while j < len(data):
        c = data[j:j + 1]
        if c == b"\\":
            j += 2
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


_ALT_RE = re.compile(rb"/(?:ActualText|Alt|E)(?![A-Za-z0-9#_.\-])")


def _strip_alt_texts(data: bytes) -> bytes:
    """Remove ``/ActualText``, ``/Alt`` and ``/E`` string entries (marked-content
    property lists).  A key not followed by a string is left untouched."""
    out, i = [], 0
    for m in _ALT_RE.finditer(data):
        if m.start() < i:
            continue
        j = m.end()
        while j < len(data) and data[j:j + 1] in b" \t\r\n\f\x00":
            j += 1
        end = _skip_pdf_string(data, j)
        if end < 0:
            continue
        out.append(data[i:m.start()])
        i = end
    out.append(data[i:])
    return b"".join(out)


def _dict_names(value: str) -> list[str]:
    """Entry names of a /Properties dictionary (every value is a dict or a reference)."""
    return re.findall(r"/([^\s/<>\[\]()]+)\s*(?:<<|\d+\s+\d+\s+R)", value)


def _null_alt_keys(doc: pymupdf.Document, xref: int, prefix: str = "") -> None:
    for key in ALT_KEYS:
        if doc.xref_get_key(xref, prefix + key)[0] not in ("null", "none"):
            doc.xref_set_key(xref, prefix + key, "null")


def _resolve(doc: pymupdf.Document, xref: int, path: Sequence[str]) -> tuple[int, str, str, str]:
    """Follow ``path`` from object ``xref`` through indirect references.  Returns
    (xref of the object holding the last key, key path inside it, kind, value)."""
    prefix, kind, value = "", "null", "null"
    for k, name in enumerate(path):
        kind, value = doc.xref_get_key(xref, prefix + name)
        if kind == "xref" and k < len(path) - 1:
            xref, prefix = int(value.split()[0]), ""
        elif k < len(path) - 1:
            prefix += name + "/"
    return xref, prefix + path[-1], kind, value


def _drop_alt_texts(page: pymupdf.Page) -> None:
    """Replacement / alternate texts survive glyph removal, so drop them for this page:
    inline in its content streams, in its /Properties resources and in structure
    elements that point at it.  Accessibility text of this page is lost with them
    (screen readers then read the remaining glyphs)."""
    doc = page.parent
    for xref in page.get_contents():
        data = doc.xref_stream(xref)
        if data and _ALT_RE.search(data):
            doc.update_stream(xref, _strip_alt_texts(data))
    holder, key, kind, value = _resolve(doc, page.xref, ["Resources", "Properties"])
    if kind == "xref":
        holder, key, kind, value = int(value.split()[0]), "", "dict", doc.xref_object(int(value.split()[0]))
    if kind == "dict":
        for name in _dict_names(value):
            ekind, evalue = doc.xref_get_key(holder, f"{key}/{name}" if key else name)
            if ekind == "xref":
                _null_alt_keys(doc, int(evalue.split()[0]))
            elif ekind == "dict":
                _null_alt_keys(doc, holder, f"{key}/{name}/" if key else f"{name}/")
    if doc.pdf_catalog() and doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null":
        ref = f"{page.xref} 0 R"
        for x in range(1, doc.xref_length()):
            try:
                if doc.xref_get_key(x, "Pg") == ("xref", ref) and doc.xref_get_key(x, "S")[0] == "name":
                    _null_alt_keys(doc, x)
            except Exception:  # noqa: BLE001 - free / broken objects
                continue


# --------------------------------------------------------- shared resources
def _release_shared_resources(page: pymupdf.Page, before: tuple[str, str]) -> None:
    """apply_redactions gives the page its own reduced /Resources, but an image or form
    removed from it stays alive if other pages share the old resource dictionary.
    Clean those pages so they only keep the resources they really use."""
    doc = page.parent
    kind, value = before
    shared = value if kind == "xref" else None
    for other in doc:
        if other.number == page.number:
            continue
        k, v = doc.xref_get_key(other.xref, "Resources")
        if (shared is not None and k == "xref" and v == shared) or k == "null":
            other.clean_contents()


# --------------------------------------------------------------- redaction
def _areas(page: pymupdf.Page, rects: Sequence[pymupdf.Rect]) -> list[pymupdf.Rect]:
    # Clip against the UNROTATED page box: the areas use unrotated coordinates.
    bounds = page.rect * page.derotation_matrix
    out = []
    for r in rects:
        r = pymupdf.Rect(r).normalize()
        if r.width < 2 * MIN_SIZE:
            cx = (r.x0 + r.x1) / 2
            r.x0, r.x1 = cx - MIN_SIZE, cx + MIN_SIZE
        if r.height < 2 * MIN_SIZE:
            cy = (r.y0 + r.y1) / 2
            r.y0, r.y1 = cy - MIN_SIZE, cy + MIN_SIZE
        r &= bounds
        if not r.is_empty:
            out.append(r)
    return out


def redact_page(page: pymupdf.Page, rects: Sequence[pymupdf.Rect],
                remove_crossing: bool = False) -> list[pymupdf.Rect]:
    """Redact ``rects`` on ``page`` (no snapshot / notification).  Returns the areas used."""
    areas = _areas(page, rects)
    if not areas:
        return []
    doc = page.parent
    old_marks = marks(page)
    resources_before = doc.xref_get_key(page.xref, "Resources")

    # Annotations, form fields and links are not all removed by apply_redactions.
    for annot in list(page.annots()):
        if any(pymupdf.Rect(annot.rect).intersects(a) for a in areas):
            page.delete_annot(annot)
    for widget in list(page.widgets()):
        if any(pymupdf.Rect(widget.rect).intersects(a) for a in areas):
            page.delete_widget(widget)
    for link in page.get_links():
        # link["from"] is in rotated page space
        if any((pymupdf.Rect(link["from"]) * page.derotation_matrix).intersects(a) for a in areas):
            page.delete_link(link)

    for a in areas:
        page.add_redact_annot(a, fill=FILL)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                          graphics=(pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED if remove_crossing
                                    else pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED),
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)

    _drop_alt_texts(page)
    _release_shared_resources(page, resources_before)
    new = [a for a in areas if not any(_within(a, m, 0.01) for m in old_marks)]
    _set_marks(page, old_marks + new)
    repaint(page)
    return areas


def redact(pdf: PdfDocument, pno: int, rects: Sequence[pymupdf.Rect], remove_crossing: bool = False) -> int:
    """Redact areas on one page as ONE undo step.  Returns the number of areas redacted.
    ``remove_crossing`` also deletes, whole, every drawing that crosses an area's edge."""
    page = pdf.page(pno)
    if not _areas(page, rects):
        return 0
    pdf.snapshot()
    done = redact_page(page, rects, remove_crossing)
    pdf.mutated()
    return len(done)
