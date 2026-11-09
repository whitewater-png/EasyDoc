"""Second pane for side-by-side comparison of another open PDF."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ..core.document import PdfDocument
from .i18n import tr
from .page_view import PageView


class SplitPane(QWidget):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf: Optional[PdfDocument] = None
        self._docs: list[PdfDocument] = []
        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        self.combo.currentIndexChanged.connect(self._on_choose)
        self.prev_btn = QToolButton()
        self.prev_btn.setText("◀")
        self.next_btn = QToolButton()
        self.next_btn.setText("▶")
        self.page_lbl = QLabel("")
        self.fit_btn = QToolButton()
        self.fit_btn.setText(tr("act.zoom_fit").replace("&", ""))
        self.close_btn = QToolButton()
        self.close_btn.setText("✕")
        self.close_btn.setToolTip(tr("act.split_view_close"))
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 4)
        for w in (self.combo, self.prev_btn, self.page_lbl, self.next_btn, self.fit_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.close_btn)
        self.view = PageView(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.active_bar = QFrame()
        self.active_bar.setFixedHeight(3)
        self.active_bar.setStyleSheet("background: transparent;")
        lay.addWidget(self.active_bar)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        self.next_btn.clicked.connect(lambda: self._step(1))
        self.fit_btn.clicked.connect(self.view.fit_width)
        self.close_btn.clicked.connect(self.closed)

    def set_active(self, active: bool) -> None:
        """Highlight the pane when it is the target of editing commands."""
        self.active_bar.setStyleSheet("background: #2f6fed;" if active else "background: transparent;")

    # ------------------------------------------------------------------ docs
    def set_documents(self, docs: list[PdfDocument], titles: list[str], prefer: Optional[PdfDocument] = None) -> None:
        """Refresh the list of choosable documents, keeping the current choice if possible."""
        keep = self.pdf if self.pdf in docs else prefer
        self.combo.blockSignals(True)
        self.combo.clear()
        self._docs = list(docs)
        self.combo.addItems(titles)
        self.combo.blockSignals(False)
        if keep in self._docs:
            self.combo.setCurrentIndex(self._docs.index(keep))
        self._show(self._docs[self.combo.currentIndex()] if self._docs else None, reload=keep is not self.pdf)

    def _on_choose(self, index: int) -> None:
        self._show(self._docs[index] if 0 <= index < len(self._docs) else None, reload=True)

    def _show(self, pdf: Optional[PdfDocument], reload: bool = True) -> None:
        if pdf is not self.pdf:
            self.pdf = pdf
            self.view.set_document(pdf)
            if pdf is not None:
                self.view.fit_width()
        elif reload:
            self.view.refresh()
        self._update_label()

    def refresh_if(self, pdf: PdfDocument) -> None:
        """Called when ``pdf`` changed in the main pane."""
        if pdf is self.pdf:
            self.view.refresh()
            self._update_label()

    def _step(self, delta: int) -> None:
        if self.pdf is not None:
            self.view.set_page(self.view.pno + delta)
            self._update_label()

    def _update_label(self) -> None:
        if self.pdf is None:
            self.page_lbl.setText("")
        else:
            self.page_lbl.setText(tr("lbl.page_of", self.view.pno + 1, self.pdf.page_count))
