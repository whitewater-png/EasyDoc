"""Page thumbnail strip with drag & drop reordering."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from ..core.document import PdfDocument

THUMB_WIDTH = 110


class ThumbnailList(QListWidget):
    page_activated = Signal(int)
    reorder_requested = Signal(list)  # new order (list of old indices)
    files_dropped = Signal(list)      # local files dragged in from the OS

    def __init__(self, parent=None):
        super().__init__(parent)
        # Icon mode, flowing left-to-right with wrapping inside a fixed, narrow
        # widget: only one item fits per row, so items stack vertically with the
        # page number rendered under each thumbnail.
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Snap)
        self.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.5)))
        self.setGridSize(QSize(THUMB_WIDTH + 30, int(THUMB_WIDTH * 1.5) + 34))
        self.setSpacing(6)
        self.setUniformItemSizes(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setFixedWidth(THUMB_WIDTH + 60)
        self.pdf: Optional[PdfDocument] = None
        self._pending: list[int] = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_some)
        self.currentRowChanged.connect(self._on_current)
        self.model().rowsMoved.connect(self._on_rows_moved)

    def set_document(self, pdf: Optional[PdfDocument]) -> None:
        self.pdf = pdf
        self.rebuild()

    def rebuild(self, current: Optional[int] = None) -> None:
        self.blockSignals(True)
        self.clear()
        self._pending = []
        if self.pdf is not None:
            for i in range(self.pdf.page_count):
                item = QListWidgetItem(str(i + 1))
                item.setData(Qt.UserRole, i)
                item.setTextAlignment(Qt.AlignHCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                # Fixed size hint so the layout reserves room for the icon
                # before it has been rendered.
                item.setSizeHint(QSize(THUMB_WIDTH + 20, int(THUMB_WIDTH * 1.5) + 28))
                self.addItem(item)
                self._pending.append(i)
            if current is not None and 0 <= current < self.pdf.page_count:
                self.setCurrentRow(current)
        self.blockSignals(False)
        if self._pending:
            self._timer.start()

    def _render_some(self) -> None:
        if self.pdf is None or not self._pending:
            self._timer.stop()
            return
        for _ in range(3):
            if not self._pending:
                break
            i = self._pending.pop(0)
            if i >= self.pdf.page_count or i >= self.count():
                continue
            page = self.pdf.page(i)
            zoom = THUMB_WIDTH / max(page.rect.width, 1)
            pix = self.pdf.render(i, zoom)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            self.item(i).setIcon(QIcon(QPixmap.fromImage(img)))

    def _on_current(self, row: int) -> None:
        if row >= 0:
            self.page_activated.emit(row)

    def _on_rows_moved(self, *_args) -> None:
        order = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        if order != list(range(self.count())):
            self.reorder_requested.emit(order)

    def selected_pages(self) -> list[int]:
        rows = sorted(self.row(it) for it in self.selectedItems())
        if not rows and self.currentRow() >= 0:
            rows = [self.currentRow()]
        return rows

    @staticmethod
    def _local_files(event) -> list[str]:
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, event) -> None:
        if self._local_files(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._local_files(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        files = self._local_files(event)
        if files:
            event.acceptProposedAction()
            self.files_dropped.emit(files)
        else:
            super().dropEvent(event)
