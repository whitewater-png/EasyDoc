"""Printing the current document with Qt's print support."""
from __future__ import annotations

from typing import Optional, Sequence

import pymupdf
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter

from ..core.document import PdfDocument

MAX_DPI = 300


def print_document(pdf: PdfDocument, printer: QPrinter, pnos: Optional[Sequence[int]] = None) -> int:
    """Render pages with MuPDF and paint them onto ``printer``.  Returns pages printed."""
    if pnos is None:
        pnos = list(range(pdf.page_count))
    if not pnos:
        return 0
    dpi = min(printer.resolution() or 300, MAX_DPI)
    painter = QPainter()
    first = True
    for pno in pnos:
        page = pdf.page(pno)
        rect = page.rect  # rotated page rect in points
        landscape = rect.width > rect.height
        layout = printer.pageLayout()
        layout.setPageSize(QPageSize(QPageSize.PageSizeId.A4) if layout.pageSize().id() == QPageSize.PageSizeId.Custom
                           else layout.pageSize())
        layout.setOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
        if first:
            printer.setPageLayout(layout)
            if not painter.begin(printer):
                raise RuntimeError("could not start printing")
            first = False
        else:
            printer.setPageLayout(layout)
            printer.newPage()
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False, annots=True)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        target = printer.pageRect(QPrinter.Unit.DevicePixel)
        scale = min(target.width() / img.width(), target.height() / img.height())
        w, h = img.width() * scale, img.height() * scale
        x = target.x() + (target.width() - w) / 2
        y = target.y() + (target.height() - h) / 2
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(QRectF(x, y, w, h), img)
    painter.end()
    return len(pnos)


def print_with_dialog(pdf: PdfDocument, parent=None, current_page: int = 0) -> int:
    """Show the native print dialog and print.  Returns pages printed (0 if cancelled)."""
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName((pdf.path or "leafwright").rsplit("/", 1)[-1])
    dlg = QPrintDialog(printer, parent)
    dlg.setMinMax(1, pdf.page_count)
    dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)
    dlg.setOption(QPrintDialog.PrintDialogOption.PrintCurrentPage, True)
    dlg.setOption(QPrintDialog.PrintDialogOption.PrintToFile, True)
    if dlg.exec() != QPrintDialog.Accepted:
        return 0
    rng = printer.printRange()
    if rng == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
        pnos = list(range(printer.fromPage() - 1, printer.toPage()))
    elif rng == QPrinter.PrintRange.CurrentPage:
        pnos = [current_page]
    else:
        pnos = list(range(pdf.page_count))
    copies = max(1, printer.copyCount()) if not printer.supportsMultipleCopies() else 1
    total = 0
    for _ in range(copies):
        total += print_document(pdf, printer, pnos)
    return total
