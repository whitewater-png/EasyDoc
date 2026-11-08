"""Document wrapper with snapshot based undo/redo.

The wrapper owns a ``pymupdf.Document`` and keeps a bounded stack of
serialized snapshots.  Snapshots are cheap to take for ordinary documents and
make every operation (text edits, shapes, page manipulation) undoable without
each operation having to implement its own inverse.
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Callable, Iterable, Optional

warnings.filterwarnings("ignore", category=FutureWarning, module="fitz")
import pymupdf  # noqa: E402

MAX_UNDO = 30


class PdfDocument:
    """A PyMuPDF document plus undo/redo and change notification."""

    def __init__(self, doc: Optional[pymupdf.Document] = None, path: Optional[str] = None):
        self.doc: pymupdf.Document = doc if doc is not None else pymupdf.open()
        self.path: Optional[str] = path
        self.dirty = False
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self._listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ io
    @classmethod
    def open(cls, path: str | Path, password: Optional[str] = None) -> "PdfDocument":
        doc = pymupdf.open(str(path))
        if doc.needs_pass:
            if password is None or not doc.authenticate(password):
                raise PermissionError("This PDF is password protected.")
        if not doc.is_pdf:
            # Convert images / XPS / EPUB etc. to PDF so that we can edit them.
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            doc = pymupdf.open("pdf", pdf_bytes)
        return cls(doc, str(path))

    @classmethod
    def new(cls, width: float = 595, height: float = 842) -> "PdfDocument":
        doc = pymupdf.open()
        doc.new_page(width=width, height=height)
        return cls(doc, None)

    def to_bytes(self, **kwargs) -> bytes:
        kwargs.setdefault("garbage", 3)
        kwargs.setdefault("deflate", True)
        return self.doc.tobytes(**kwargs)

    def close(self) -> None:
        if self.doc is not None and not self.doc.is_closed:
            self.doc.close()

    # ------------------------------------------------------------ listeners
    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ------------------------------------------------------------- undo/redo
    def snapshot(self) -> None:
        """Record the current state so that the next mutation can be undone."""
        self._undo.append(self.doc.tobytes(garbage=0, deflate=False))
        if len(self._undo) > MAX_UNDO:
            del self._undo[0]
        self._redo.clear()

    def _restore(self, data: bytes) -> None:
        old = self.doc
        self.doc = pymupdf.open("pdf", data)
        old.close()
        self.dirty = True
        self.notify()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.doc.tobytes(garbage=0, deflate=False))
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.doc.tobytes(garbage=0, deflate=False))
        self._restore(self._redo.pop())
        return True

    def mutated(self) -> None:
        """Call after a change has been applied to ``self.doc``."""
        self.dirty = True
        self.notify()

    # --------------------------------------------------------------- helpers
    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page(self, pno: int) -> pymupdf.Page:
        return self.doc[pno]

    def render(self, pno: int, zoom: float = 1.0, alpha: bool = False) -> pymupdf.Pixmap:
        page = self.doc[pno]
        return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=alpha, annots=True)

    def page_sizes(self) -> Iterable[tuple[float, float]]:
        for page in self.doc:
            r = page.rect
            yield (r.width, r.height)
