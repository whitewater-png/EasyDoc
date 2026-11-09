"""Page level operations: rotate, delete, move, insert, merge, extract, split."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Sequence

import pymupdf

from . import redact
from .document import PdfDocument

# Standard page sizes in PDF points (1/72 inch).
PAGE_SIZES = {
    "A4": (595.0, 842.0),
    "A3": (842.0, 1191.0),
    "A5": (420.0, 595.0),
    "B5 (JIS)": (516.0, 729.0),
    "B4 (JIS)": (729.0, 1032.0),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
}


def parse_ranges(spec: str, page_count: int) -> list[int]:
    """Parse a 1-based range specification like ``1-3,5,8-`` into 0-based indices.

    Raises ``ValueError`` on malformed or out-of-range input.
    """
    result: list[int] = []
    spec = spec.strip()
    if not spec:
        raise ValueError("empty range")
    for part in re.split(r"[,\s]+", spec):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m and (m.group(1) or m.group(2)) and "-" in part:
            start = int(m.group(1)) if m.group(1) else 1
            end = int(m.group(2)) if m.group(2) else page_count
        elif part.isdigit():
            start = end = int(part)
        else:
            raise ValueError(f"invalid range: {part!r}")
        if start < 1 or end > page_count or start > end:
            raise ValueError(f"range out of bounds: {part!r} (1-{page_count})")
        result.extend(range(start - 1, end))
    # de-duplicate while preserving order
    seen: set[int] = set()
    ordered = []
    for p in result:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def rotate_pages(pdf: PdfDocument, pnos: Iterable[int], degrees: int) -> None:
    pdf.snapshot()
    for pno in pnos:
        page = pdf.page(pno)
        page.set_rotation((page.rotation + degrees) % 360)
    pdf.mutated()


def delete_pages(pdf: PdfDocument, pnos: Sequence[int]) -> None:
    if not pnos:
        return
    if len(set(pnos)) >= pdf.page_count:
        raise ValueError("cannot delete every page of a document")
    pdf.snapshot()
    pdf.doc.delete_pages(sorted(set(pnos)))
    pdf.mutated()


def move_page(pdf: PdfDocument, src: int, dst: int) -> None:
    """Move page ``src`` so that it ends up at index ``dst``."""
    if src == dst:
        return
    pdf.snapshot()
    # move_page(pno, to) inserts *before* ``to``; adjust for forward moves.
    if dst > src:
        to = -1 if dst >= pdf.page_count - 1 else dst + 1
    else:
        to = dst
    pdf.doc.move_page(src, to)
    pdf.mutated()


def reorder_pages(pdf: PdfDocument, order: Sequence[int]) -> None:
    if sorted(order) != list(range(pdf.page_count)):
        raise ValueError("order must be a permutation of all pages")
    pdf.snapshot()
    pdf.doc.select(list(order))
    pdf.mutated()


def insert_blank_page(pdf: PdfDocument, index: int, width: float = 595, height: float = 842) -> None:
    pdf.snapshot()
    pdf.doc.new_page(pno=index, width=width, height=height)
    pdf.mutated()


def merge_files(pdf: PdfDocument, paths: Sequence[str | Path], insert_at: int = -1) -> int:
    """Append (or insert) every page of the given files.  Returns pages added."""
    if not paths:
        return 0
    pdf.snapshot()
    added = 0
    at = pdf.page_count if insert_at < 0 else insert_at
    for p in paths:
        src = pymupdf.open(str(p))
        try:
            if not src.is_pdf:
                src = pymupdf.open("pdf", src.convert_to_pdf())
            pdf.doc.insert_pdf(src, start_at=at)
            redact.copy_marks(src, range(src.page_count), pdf.doc, at)
            at += src.page_count
            added += src.page_count
        finally:
            src.close()
    pdf.mutated()
    return added


def merge_paths_to_file(paths: Sequence[str | Path], out_path: str | Path) -> int:
    """Merge independent files into a brand-new PDF (does not touch an open doc)."""
    out = pymupdf.open()
    total = 0
    for p in paths:
        src = pymupdf.open(str(p))
        if not src.is_pdf:
            src = pymupdf.open("pdf", src.convert_to_pdf())
        out.insert_pdf(src)
        redact.copy_marks(src, range(src.page_count), out, total)
        total += src.page_count
        src.close()
    out.save(str(out_path), garbage=3, deflate=True)
    out.close()
    return total


def extract_pages(pdf: PdfDocument, pnos: Sequence[int], out_path: str | Path) -> None:
    """Write the selected pages (in the given order) to a new file."""
    out = pymupdf.open()
    for k, pno in enumerate(pnos):
        out.insert_pdf(pdf.doc, from_page=pno, to_page=pno)
        redact.copy_marks(pdf.doc, [pno], out, k)
    out.save(str(out_path), garbage=3, deflate=True)
    out.close()


def split_every(pdf: PdfDocument, n: int, out_dir: str | Path, prefix: str = "part") -> list[str]:
    """Split into chunks of ``n`` pages.  Returns the written file names."""
    if n < 1:
        raise ValueError("chunk size must be >= 1")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    total = pdf.page_count
    for idx, start in enumerate(range(0, total, n), start=1):
        end = min(start + n, total) - 1
        out = pymupdf.open()
        out.insert_pdf(pdf.doc, from_page=start, to_page=end)
        redact.copy_marks(pdf.doc, range(start, end + 1), out, 0)
        fname = os.path.join(str(out_dir), f"{prefix}_{idx:03d}.pdf")
        out.save(fname, garbage=3, deflate=True)
        out.close()
        written.append(fname)
    return written


def split_ranges(pdf: PdfDocument, specs: Sequence[str], out_dir: str | Path, prefix: str = "part") -> list[str]:
    """Split by explicit range specs; each spec becomes one output file."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for idx, spec in enumerate(specs, start=1):
        pnos = parse_ranges(spec, pdf.page_count)
        fname = os.path.join(str(out_dir), f"{prefix}_{idx:03d}.pdf")
        extract_pages(pdf, pnos, fname)
        written.append(fname)
    return written
