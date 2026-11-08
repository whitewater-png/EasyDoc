"""Dialogs: text editing, save-as with standards, split, extract, merge, insert page."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from ..core import standards
from ..core.fonts import FontInfo, FontRegistry
from ..core.pages import PAGE_SIZES
from .i18n import tr


def qcolor_to_rgb(c: QColor) -> tuple[float, float, float]:
    return c.redF(), c.greenF(), c.blueF()


def rgb_to_qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*rgb)


class ColorButton(QPushButton):
    """Button showing a colour swatch; ``None`` means "no colour"."""

    def __init__(self, color: Optional[tuple] = (0, 0, 0), allow_none: bool = False, parent=None):
        super().__init__(parent)
        self.allow_none = allow_none
        self._color: Optional[QColor] = rgb_to_qcolor(color) if color is not None else None
        self.setFixedWidth(64)
        self.clicked.connect(self._pick)
        self._update()

    def color(self) -> Optional[tuple[float, float, float]]:
        return qcolor_to_rgb(self._color) if self._color is not None else None

    def set_color(self, rgb: Optional[tuple]) -> None:
        self._color = rgb_to_qcolor(rgb) if rgb is not None else None
        self._update()

    def _update(self) -> None:
        if self._color is None:
            self.setText(tr("lbl.none"))
            self.setStyleSheet("")
        else:
            self.setText("")
            self.setStyleSheet(f"background-color: {self._color.name()}; border: 1px solid #555;")

    def _pick(self) -> None:
        dlg = QColorDialog(self._color or QColor(0, 0, 0), self)
        if self.allow_none:
            dlg.setOption(QColorDialog.ShowAlphaChannel, True)
        if dlg.exec() == QDialog.Accepted:
            c = dlg.selectedColor()
            if self.allow_none and c.alpha() == 0:
                self._color = None
            else:
                c.setAlpha(255)
                self._color = c
            self._update()


class FontCombo(QComboBox):
    def __init__(self, registry: FontRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setMinimumWidth(200)
        self.reload()

    def reload(self, select: Optional[str] = None) -> None:
        cur = select or self.currentText()
        self.blockSignals(True)
        self.clear()
        names = self.registry.names()
        self.addItems(names)
        if cur in names:
            self.setCurrentText(cur)
        self.blockSignals(False)

    def font_info(self) -> FontInfo:
        info = self.registry.get(self.currentText())
        return info or self.registry.get("Helvetica")


class TextDialog(QDialog):
    """Edit an existing span or create new text."""

    def __init__(self, registry: FontRegistry, text: str = "", font_name: Optional[str] = None,
                 original_font: Optional[str] = None, size: float = 12.0, color=(0, 0, 0),
                 editing: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.edit_text") if editing else tr("dlg.new_text"))
        self.delete_requested = False
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumSize(380, 110)
        lay.addWidget(QLabel(tr("dlg.text")))
        lay.addWidget(self.edit)
        form = QFormLayout()
        self.font_combo = FontCombo(registry)
        if font_name:
            self.font_combo.reload(font_name)
        if original_font:
            form.addRow(QLabel(tr("dlg.original_font", original_font)))
        form.addRow(tr("lbl.font"), self.font_combo)
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(1, 400)
        self.size_spin.setDecimals(1)
        self.size_spin.setValue(size)
        form.addRow(tr("lbl.size"), self.size_spin)
        self.color_btn = ColorButton(color)
        form.addRow(tr("dlg.color"), self.color_btn)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if editing:
            del_btn = buttons.addButton(tr("dlg.delete_text"), QDialogButtonBox.DestructiveRole)
            del_btn.clicked.connect(self._delete)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.edit.setFocus()

    def _delete(self) -> None:
        self.delete_requested = True
        self.accept()

    def result_text(self) -> str:
        return "" if self.delete_requested else self.edit.toPlainText()

    def result_font(self) -> FontInfo:
        return self.font_combo.font_info()

    def result_size(self) -> float:
        return self.size_spin.value()

    def result_color(self):
        return self.color_btn.color() or (0, 0, 0)


class SaveAsDialog(QDialog):
    def __init__(self, default_path: str, title: str = "", author: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.saveas"))
        self.path = default_path
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.std_combo = QComboBox()
        for key, spec in standards.STANDARDS.items():
            self.std_combo.addItem(spec["label"], key)
        form.addRow(tr("dlg.standard"), self.std_combo)

        self.ver_combo = QComboBox()
        self.ver_combo.addItem(tr("dlg.keep"), None)
        for v in standards.PDF_VERSIONS:
            self.ver_combo.addItem(f"PDF {v}", v)
        form.addRow(tr("dlg.version"), self.ver_combo)

        self.title_edit = QLineEdit(title)
        self.author_edit = QLineEdit(author)
        form.addRow(tr("dlg.title_meta"), self.title_edit)
        form.addRow(tr("dlg.author_meta"), self.author_edit)
        lay.addLayout(form)

        self.linearize = QCheckBox(tr("dlg.linearize"))
        self.compress = QCheckBox(tr("dlg.compress"))
        self.compress.setChecked(True)
        lay.addWidget(self.linearize)
        lay.addWidget(self.compress)

        gs = standards.find_ghostscript()
        info = QLabel(tr("dlg.gs_found", gs) if gs else tr("dlg.gs_missing"))
        info.setWordWrap(True)
        info.setStyleSheet("color: %s;" % ("#2e7d32" if gs else "#c62828"))
        lay.addWidget(info)

        self.std_combo.currentIndexChanged.connect(self._std_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._choose_file)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _std_changed(self, _idx: int) -> None:
        key = self.std_combo.currentData()
        spec = standards.STANDARDS[key]
        locked = spec.get("version") is not None
        self.ver_combo.setEnabled(not locked)
        if locked:
            idx = self.ver_combo.findData(spec["version"])
            if idx >= 0:
                self.ver_combo.setCurrentIndex(idx)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("dlg.saveas"), self.path, tr("filter.pdf"))
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.path = path
        self.accept()

    def options(self) -> standards.SaveOptions:
        return standards.SaveOptions(
            standard=self.std_combo.currentData(),
            pdf_version=self.ver_combo.currentData(),
            linearize=self.linearize.isChecked(),
            compress=self.compress.isChecked(),
            title=self.title_edit.text() or None,
            author=self.author_edit.text() or None,
        )


class _OutDirRow(QWidget):
    def __init__(self, default_dir: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(default_dir)
        btn = QPushButton(tr("dlg.browse"))
        btn.clicked.connect(self._browse)
        lay.addWidget(self.edit)
        lay.addWidget(btn)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("dlg.out_dir"), self.edit.text())
        if d:
            self.edit.setText(d)

    def text(self) -> str:
        return self.edit.text()


class SplitDialog(QDialog):
    def __init__(self, page_count: int, default_dir: str, default_prefix: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.split"))
        lay = QVBoxLayout(self)
        self.every_radio = QRadioButton(tr("dlg.split_every"))
        self.every_radio.setChecked(True)
        self.every_spin = QSpinBox()
        self.every_spin.setRange(1, max(1, page_count))
        self.every_spin.setValue(1)
        row = QHBoxLayout()
        row.addWidget(self.every_radio)
        row.addWidget(self.every_spin)
        lay.addLayout(row)
        self.ranges_radio = QRadioButton(tr("dlg.split_ranges"))
        lay.addWidget(self.ranges_radio)
        self.ranges_edit = QPlainTextEdit()
        self.ranges_edit.setPlaceholderText(tr("lbl.ranges_help"))
        self.ranges_edit.setMinimumHeight(80)
        lay.addWidget(self.ranges_edit)
        form = QFormLayout()
        self.out_dir = _OutDirRow(default_dir)
        form.addRow(tr("dlg.out_dir"), self.out_dir)
        self.prefix = QLineEdit(default_prefix)
        form.addRow(tr("dlg.prefix"), self.prefix)
        lay.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def mode(self) -> str:
        return "every" if self.every_radio.isChecked() else "ranges"

    def every(self) -> int:
        return self.every_spin.value()

    def ranges(self) -> list[str]:
        return [ln.strip() for ln in self.ranges_edit.toPlainText().splitlines() if ln.strip()]


class ExtractDialog(QDialog):
    def __init__(self, page_count: int, preselected: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.extract"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("dlg.extract_ranges")))
        self.edit = QLineEdit(preselected)
        self.edit.setPlaceholderText(tr("lbl.ranges_help") + f"  (1-{page_count})")
        lay.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def ranges(self) -> str:
        return self.edit.text()


class MergeDialog(QDialog):
    def __init__(self, page_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.merge"))
        self.page_count = page_count
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for label, slot in ((tr("dlg.add_files"), self._add), (tr("dlg.remove"), self._remove),
                            (tr("dlg.up"), lambda: self._move(-1)), (tr("dlg.down"), lambda: self._move(1))):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(QLabel(tr("dlg.insert_at")))
        self.pos_edit = QLineEdit("")
        self.pos_edit.setPlaceholderText(str(page_count))
        lay.addWidget(self.pos_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(520, 360)

    def _add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("dlg.add_files"), "", tr("filter.open"))
        for f in files:
            self.list.addItem(f)

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        if row < 0 or not (0 <= row + delta < self.list.count()):
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row + delta, item)
        self.list.setCurrentRow(row + delta)

    def files(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def insert_at(self) -> int:
        txt = self.pos_edit.text().strip()
        if not txt:
            return -1
        try:
            return max(0, min(int(txt), self.page_count))
        except ValueError:
            return -1


class InsertPageDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("dlg.insert_page"))
        lay = QFormLayout(self)
        self.size_combo = QComboBox()
        for name in PAGE_SIZES:
            self.size_combo.addItem(name, name)
        lay.addRow(tr("dlg.page_size"), self.size_combo)
        self.pos_combo = QComboBox()
        self.pos_combo.addItem(tr("dlg.after_current"), "after")
        self.pos_combo.addItem(tr("dlg.before_current"), "before")
        lay.addRow(tr("dlg.position"), self.pos_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    def size(self) -> tuple[float, float]:
        return PAGE_SIZES[self.size_combo.currentData()]

    def after(self) -> bool:
        return self.pos_combo.currentData() == "after"
