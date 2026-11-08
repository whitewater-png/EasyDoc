"""Main window wiring the core operations to the Qt widgets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pymupdf
from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QSizePolicy, QSplitter, QToolBar, QWidget)

from .. import __version__
from ..core import pages, printserver, shapes, standards, text_edit
from ..core.document import PdfDocument
from ..core.fonts import FontRegistry, default_registry
from . import printing
from .dialogs import (ColorButton, ExtractDialog, FontCombo, InsertPageDialog, MergeDialog, PrinterSetupDialog,
                      SaveAsDialog, SplitDialog, TextDialog)
from .i18n import tr
from .icons import icon
from .page_view import PageView, Tool
from .thumbnails import ThumbnailList


class _FontScanThread(QThread):
    done = Signal()

    def __init__(self, registry: FontRegistry, parent=None):
        super().__init__(parent)
        self.registry = registry

    def run(self) -> None:  # pragma: no cover - threading
        try:
            self.registry.scan()
        finally:
            self.done.emit()


class MainWindow(QMainWindow):
    # Print jobs arrive on a server thread; marshal them onto the GUI thread.
    _job_received = Signal(str)
    _job_failed = Signal(str)

    def __init__(self, registry: Optional[FontRegistry] = None, scan_fonts: bool = True,
                 settings: Optional[QSettings] = None):
        super().__init__()
        self.setWindowTitle(tr("app.title"))
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self.pdf: Optional[PdfDocument] = None
        self.registry = registry or default_registry(scan=False)
        self.settings = settings or QSettings("easydoc", "easydoc")
        self.print_server: Optional[printserver.PrintServer] = None

        self.view = PageView(self)
        self.thumbs = ThumbnailList(self)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.thumbs)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)
        self.setCentralWidget(splitter)

        self.drop_hint = QLabel(tr("lbl.drop_hint"), self.view)
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setStyleSheet("color: #c9d1de; font-size: 18px; background: transparent;")

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self.status_page = QLabel()
        self.status_zoom = QLabel()
        self.status_printer = QLabel()
        self.statusBar().addPermanentWidget(self.status_printer)
        self.statusBar().addPermanentWidget(self.status_page)
        self.statusBar().addPermanentWidget(self.status_zoom)

        self.view.span_clicked.connect(self._edit_span)
        self.view.text_point_clicked.connect(self._new_text)
        self.view.shape_drawn.connect(self._shape_drawn)
        self.view.annot_selected.connect(lambda x: self.act_delete_sel.setEnabled(x >= 0))
        self.view.annot_moved.connect(self._annot_moved)
        self.view.drawing_clicked.connect(self._erase_drawing)
        self.view.zoom_changed.connect(lambda z: self.status_zoom.setText(tr("lbl.zoom", int(z * 100))))
        self.thumbs.page_activated.connect(self._goto_page)
        self.thumbs.reorder_requested.connect(self._reorder)
        self._job_received.connect(self._on_print_job)
        self._job_failed.connect(lambda msg: QMessageBox.warning(self, tr("dlg.vprinter"), tr("msg.job_failed", msg)))

        self._set_tool(Tool.SELECT)
        self._update_state()
        self._scan_thread: Optional[_FontScanThread] = None
        if scan_fonts:
            self._scan_thread = _FontScanThread(self.registry, self)
            self._scan_thread.done.connect(lambda: self.font_combo.reload())
            self._scan_thread.start()
        if self.settings.value("vprinter/enabled", False, type=bool):
            self.act_vprinter.setChecked(True)
            self._toggle_vprinter(True)

    # ------------------------------------------------------------------ UI
    def _build_actions(self) -> None:
        def act(key, slot, shortcut=None, checkable=False, icon_name=None):
            a = QAction(tr(key), self)
            if shortcut:
                a.setShortcut(shortcut)
            a.setCheckable(checkable)
            if icon_name:
                a.setIcon(icon(icon_name))
            if slot:
                a.triggered.connect(slot)
            plain = tr(key).replace("&", "")
            a.setToolTip(f"{plain}  ({a.shortcut().toString()})" if shortcut else plain)
            return a

        self.act_new = act("act.new", self.new_document, QKeySequence.New, icon_name="new")
        self.act_open = act("act.open", self.open_dialog, QKeySequence.Open, icon_name="open")
        self.act_save = act("act.save", self.save, QKeySequence.Save, icon_name="save")
        self.act_saveas = act("act.saveas", self.save_as, QKeySequence.SaveAs, icon_name="export")
        self.act_print = act("act.print", self.print_document, QKeySequence.Print, icon_name="print")
        self.act_vprinter = act("act.vprinter", None, checkable=True, icon_name="vprinter")
        self.act_vprinter.toggled.connect(self._toggle_vprinter)
        self.act_vprinter_setup = act("act.vprinter_setup", self.vprinter_setup)
        self.act_merge = act("act.merge", self.merge_dialog, "Ctrl+M", icon_name="merge")
        self.act_quit = act("act.quit", self.close, QKeySequence.Quit)
        self.act_undo = act("act.undo", self.undo, QKeySequence.Undo, icon_name="undo")
        self.act_redo = act("act.redo", self.redo, QKeySequence.Redo, icon_name="redo")
        self.act_delete_sel = act("act.delete_sel", self.delete_selected, QKeySequence.Delete)
        self.act_rot_left = act("act.rot_left", lambda: self.rotate(-90), "Ctrl+[", icon_name="rot_left")
        self.act_rot_right = act("act.rot_right", lambda: self.rotate(90), "Ctrl+]", icon_name="rot_right")
        self.act_del_page = act("act.del_page", self.delete_page, "Ctrl+Shift+D", icon_name="del_page")
        self.act_insert_page = act("act.insert_page", self.insert_page, "Ctrl+Shift+N", icon_name="insert_page")
        self.act_move_up = act("act.move_up", lambda: self.move_page(-1), "Ctrl+Shift+Up", icon_name="move_up")
        self.act_move_down = act("act.move_down", lambda: self.move_page(1), "Ctrl+Shift+Down", icon_name="move_down")
        self.act_extract = act("act.extract", self.extract_dialog, "Ctrl+E", icon_name="extract")
        self.act_split = act("act.split", self.split_dialog, "Ctrl+Shift+S", icon_name="split")
        self.act_zoom_in = act("act.zoom_in", lambda: self.view.set_zoom(self.view.zoom * 1.25), QKeySequence.ZoomIn, icon_name="zoom_in")
        self.act_zoom_out = act("act.zoom_out", lambda: self.view.set_zoom(self.view.zoom / 1.25), QKeySequence.ZoomOut, icon_name="zoom_out")
        self.act_zoom_fit = act("act.zoom_fit", self.view.fit_width, "Ctrl+0", icon_name="zoom_fit")
        self.act_zoom_100 = act("act.zoom_100", lambda: self.view.set_zoom(1.0), "Ctrl+1")
        self.act_add_font = act("act.add_font", self.add_font_file, icon_name="font")
        self.act_about = act("act.about", self.about)

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, key, sc in ((Tool.SELECT, "tool.select", "V"), (Tool.TEXT, "tool.text", "T"),
                              (Tool.RECT, "tool.rect", "R"), (Tool.ELLIPSE, "tool.ellipse", "E"),
                              (Tool.LINE, "tool.line", "L"), (Tool.ARROW, "tool.arrow", "A"),
                              (Tool.ERASE, "tool.erase", "X")):
            a = act(key, None, sc, checkable=True, icon_name=tool.value)
            a.triggered.connect(lambda _c=False, t=tool: self._set_tool(t))
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(tr("menu.file"))
        for a in (self.act_new, self.act_open, self.act_save, self.act_saveas, None, self.act_print,
                  self.act_vprinter, self.act_vprinter_setup, None, self.act_merge, None, self.act_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.edit"))
        for a in (self.act_undo, self.act_redo, None, self.act_delete_sel):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.page"))
        for a in (self.act_rot_left, self.act_rot_right, None, self.act_insert_page, self.act_del_page,
                  self.act_move_up, self.act_move_down, None, self.act_merge, self.act_extract, self.act_split):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.view"))
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit, self.act_zoom_100):
            m.addAction(a)
        m = mb.addMenu(tr("menu.tools"))
        for a in self.tool_actions.values():
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_add_font)
        m = mb.addMenu(tr("menu.help"))
        m.addAction(self.act_about)

    @staticmethod
    def _group_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("groupLabel")
        return lbl

    def _build_toolbars(self) -> None:
        # Row 1: document-level commands, grouped and labelled.
        tb = QToolBar("main", self)
        tb.setMovable(False)
        tb.setIconSize(tb.iconSize() * 1.15)
        self.addToolBar(tb)
        groups = [
            ("grp.file", (self.act_new, self.act_open, self.act_save, self.act_saveas, self.act_print, self.act_vprinter)),
            ("grp.edit", (self.act_undo, self.act_redo)),
            ("grp.page", (self.act_rot_left, self.act_rot_right, self.act_insert_page, self.act_del_page,
                          self.act_move_up, self.act_move_down, self.act_merge, self.act_extract, self.act_split)),
            ("grp.view", (self.act_zoom_out, self.act_zoom_in, self.act_zoom_fit)),
        ]
        for i, (key, actions) in enumerate(groups):
            if i:
                tb.addSeparator()
            tb.addWidget(self._group_label(tr(key)))
            for a in actions:
                tb.addAction(a)

        # Row 2: drawing tools + style properties.
        style = QToolBar("tools", self)
        style.setMovable(False)
        style.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        style.setIconSize(tb.iconSize() * 1.2)
        self.addToolBarBreak()
        self.addToolBar(style)
        style.addWidget(self._group_label(tr("grp.tools")))
        for a in self.tool_actions.values():
            style.addAction(a)
        style.addSeparator()
        style.addWidget(QLabel(tr("lbl.stroke")))
        self.stroke_btn = ColorButton((0.86, 0.12, 0.12))
        style.addWidget(self.stroke_btn)
        style.addWidget(QLabel(tr("lbl.fill")))
        self.fill_btn = ColorButton(None, allow_none=True)
        style.addWidget(self.fill_btn)
        style.addWidget(QLabel(tr("lbl.width")))
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.1, 50)
        self.width_spin.setValue(1.5)
        self.width_spin.setDecimals(1)
        self.width_spin.setFixedWidth(72)
        style.addWidget(self.width_spin)
        style.addSeparator()
        style.addWidget(QLabel(tr("lbl.font")))
        self.font_combo = FontCombo(self.registry)
        self.font_combo.setMinimumWidth(170)
        self.font_combo.setMaximumWidth(170)
        style.addWidget(self.font_combo)
        style.addAction(self.act_add_font)
        style.widgetForAction(self.act_add_font).setToolButtonStyle(Qt.ToolButtonIconOnly)
        style.addWidget(QLabel(tr("lbl.size")))
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(1, 400)
        self.size_spin.setValue(12)
        self.size_spin.setDecimals(1)
        self.size_spin.setFixedWidth(74)
        style.addWidget(self.size_spin)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        style.addWidget(spacer)

    # --------------------------------------------------------------- state
    def _style(self) -> shapes.ShapeStyle:
        return shapes.ShapeStyle(stroke=self.stroke_btn.color(), fill=self.fill_btn.color(),
                                 width=self.width_spin.value())

    def _set_tool(self, tool: Tool) -> None:
        self.view.set_tool(tool)
        self.tool_actions[tool].setChecked(True)
        tip = {Tool.SELECT: "tip.select", Tool.TEXT: "tip.text", Tool.ERASE: "tip.erase"}.get(tool, "tip.shape")
        self.statusBar().showMessage(tr(tip))

    def _update_state(self) -> None:
        has = self.pdf is not None and self.pdf.page_count > 0
        for a in (self.act_save, self.act_saveas, self.act_print, self.act_merge, self.act_rot_left, self.act_rot_right,
                  self.act_del_page, self.act_insert_page, self.act_move_up, self.act_move_down,
                  self.act_extract, self.act_split, self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit,
                  self.act_zoom_100):
            a.setEnabled(has)
        for a in self.tool_actions.values():
            a.setEnabled(has)
        self.act_undo.setEnabled(bool(self.pdf and self.pdf.can_undo))
        self.act_redo.setEnabled(bool(self.pdf and self.pdf.can_redo))
        self.act_delete_sel.setEnabled(self.view.selected_xref() >= 0)
        self.drop_hint.setVisible(not has)
        if has:
            self.status_page.setText(tr("lbl.page_of", self.view.pno + 1, self.pdf.page_count))
            name = Path(self.pdf.path).name if self.pdf.path else "untitled.pdf"
            self.setWindowTitle(f"{'*' if self.pdf.dirty else ''}{name} - {tr('app.title')}")
        else:
            self.status_page.setText("")
            self.setWindowTitle(tr("app.title"))
        self.status_zoom.setText(tr("lbl.zoom", int(self.view.zoom * 100)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.drop_hint.setGeometry(self.view.rect())

    def _on_doc_changed(self) -> None:
        """Called by PdfDocument after any mutation (incl. undo/redo)."""
        self.view.refresh()
        self.thumbs.rebuild(self.view.pno)
        self._update_state()

    def _attach(self, pdf: PdfDocument) -> None:
        if self.pdf is not None:
            self.pdf.close()
        self.pdf = pdf
        pdf.add_listener(self._on_doc_changed)
        self.view.set_document(pdf)
        self.thumbs.set_document(pdf)
        self.thumbs.setCurrentRow(0)
        self.view.fit_width()
        self._update_state()

    def _require_doc(self) -> bool:
        if self.pdf is None or self.pdf.page_count == 0:
            self.statusBar().showMessage(tr("msg.need_doc"), 4000)
            return False
        return True

    def _error(self, exc: Exception) -> None:
        QMessageBox.critical(self, tr("msg.error"), str(exc))

    # --------------------------------------------------------- drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if not paths:
            return
        self.open_path(paths[0])
        if len(paths) > 1 and self.pdf is not None:
            try:
                pages.merge_files(self.pdf, paths[1:])
            except Exception as exc:  # noqa: BLE001
                self._error(exc)

    # ---------------------------------------------------------------- file
    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self._attach(PdfDocument.new())

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("act.open"), "", tr("filter.open"))
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        if not self._confirm_discard():
            return
        try:
            pdf = PdfDocument.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("msg.error"), tr("msg.open_failed", exc))
            return
        self._attach(pdf)

    def save(self) -> None:
        if not self._require_doc():
            return
        if not self.pdf.path or not self.pdf.path.lower().endswith(".pdf"):
            self.save_as()
            return
        try:
            res = standards.save_document(self.pdf, self.pdf.path, standards.SaveOptions())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return
        self.statusBar().showMessage(tr("msg.saved", res.path, res.engine), 5000)
        self._update_state()

    def save_as(self) -> None:
        if not self._require_doc():
            return
        meta = self.pdf.doc.metadata or {}
        default = self.pdf.path or os.path.join(os.path.expanduser("~"), "untitled.pdf")
        dlg = SaveAsDialog(default, meta.get("title") or "", meta.get("author") or "", self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            res = standards.save_document(self.pdf, dlg.path, dlg.options())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return
        if res.warnings:
            QMessageBox.warning(self, tr("msg.saved_warn"), "\n".join(res.warnings))
        self.statusBar().showMessage(tr("msg.saved", res.path, res.engine), 5000)
        self._update_state()

    def merge_dialog(self) -> None:
        if not self._require_doc():
            return
        dlg = MergeDialog(self.pdf.page_count, self)
        if dlg.exec() != QDialog.Accepted or not dlg.files():
            return
        try:
            n = pages.merge_files(self.pdf, dlg.files(), dlg.insert_at())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return
        self.statusBar().showMessage(tr("msg.merge_done", n), 5000)

    def _confirm_discard(self) -> bool:
        if self.pdf is None or not self.pdf.dirty:
            return True
        ret = QMessageBox.question(self, tr("app.title"), tr("msg.unsaved"),
                                   QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if ret == QMessageBox.Save:
            self.save()
            return not self.pdf.dirty
        return ret == QMessageBox.Discard

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard():
            if self._scan_thread is not None and self._scan_thread.isRunning():
                self._scan_thread.wait(5000)
            if self.print_server is not None:
                self.print_server.stop()
            event.accept()
        else:
            event.ignore()

    # ------------------------------------------------------------- printing
    def print_document(self) -> None:
        if not self._require_doc():
            return
        try:
            n = printing.print_with_dialog(self.pdf, self, self.view.pno)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("msg.error"), tr("msg.print_failed", exc))
            return
        if n:
            self.statusBar().showMessage(tr("msg.printed", n), 5000)

    def _vprinter_port(self) -> int:
        return int(self.settings.value("vprinter/port", printserver.DEFAULT_PORT))

    def _toggle_vprinter(self, on: bool) -> None:
        if on:
            if self.print_server is None:
                self.print_server = printserver.PrintServer(
                    callback=self._job_received.emit, error_callback=self._job_failed.emit,
                    port=self._vprinter_port())
            try:
                port = self.print_server.start()
            except OSError as exc:
                self.print_server = None
                self.act_vprinter.blockSignals(True)
                self.act_vprinter.setChecked(False)
                self.act_vprinter.blockSignals(False)
                QMessageBox.warning(self, tr("dlg.vprinter"), tr("msg.vprinter_fail", self._vprinter_port(), exc))
                return
            self.status_printer.setText("🖨 " + tr("msg.vprinter_on", port))
        else:
            if self.print_server is not None:
                self.print_server.stop()
            self.status_printer.setText("")
            self.statusBar().showMessage(tr("msg.vprinter_off"), 4000)
        self.settings.setValue("vprinter/enabled", on)

    def vprinter_setup(self) -> None:
        dlg = PrinterSetupDialog(self._vprinter_port(), self)
        dlg.exec()
        if dlg.port != self._vprinter_port():
            self.settings.setValue("vprinter/port", dlg.port)
            if self.act_vprinter.isChecked():
                self._toggle_vprinter(False)
                if self.print_server is not None:
                    self.print_server.port = dlg.port
                self._toggle_vprinter(True)

    def _on_print_job(self, path: str) -> None:
        """A converted print job is ready: show it (new window if we have unsaved work)."""
        self.statusBar().showMessage(tr("msg.job_received", path), 8000)
        if self.pdf is not None and self.pdf.dirty:
            win = MainWindow(registry=self.registry, scan_fonts=False, settings=self.settings)
            win.open_path(path)
            win.show()
            if not hasattr(self, "_child_windows"):
                self._child_windows = []
            self._child_windows.append(win)
            return
        self.open_path(path)
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- edit
    def undo(self) -> None:
        if self.pdf and self.pdf.undo():
            self._update_state()

    def redo(self) -> None:
        if self.pdf and self.pdf.redo():
            self._update_state()

    def delete_selected(self) -> None:
        xref = self.view.selected_xref()
        if self.pdf and xref >= 0:
            shapes.delete_annot(self.pdf, self.view.pno, xref)

    def _edit_span(self, span: text_edit.TextSpan) -> None:
        match = self.registry.match_pdf_font(span.font, span.flags)
        dlg = TextDialog(self.registry, span.text, match.name, span.font, span.size, span.color, editing=True, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            text_edit.replace_span(self.pdf, span, dlg.result_text(), dlg.result_font(), dlg.result_size(),
                                   dlg.result_color(), registry=self.registry)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _new_text(self, point: pymupdf.Point) -> None:
        dlg = TextDialog(self.registry, "", self.font_combo.currentText(), None, self.size_spin.value(),
                         self.stroke_btn.color() or (0, 0, 0), editing=False, parent=self)
        if dlg.exec() != QDialog.Accepted or not dlg.result_text().strip():
            return
        try:
            text_edit.add_text(self.pdf, self.view.pno, point, dlg.result_text(), dlg.result_font(),
                               dlg.result_size(), dlg.result_color())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _shape_drawn(self, kind: str, p1: pymupdf.Point, p2: pymupdf.Point) -> None:
        try:
            shapes.add_shape(self.pdf, self.view.pno, kind, p1, p2, self._style())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _annot_moved(self, xref: int, dx: float, dy: float) -> None:
        shapes.move_annot(self.pdf, self.view.pno, xref, dx, dy)

    def _erase_drawing(self, drawing: shapes.Drawing) -> None:
        shapes.delete_drawing(self.pdf, self.view.pno, drawing.rect)

    # ---------------------------------------------------------------- pages
    def _goto_page(self, pno: int) -> None:
        if self.pdf is not None and pno != self.view.pno:
            self.view.set_page(pno)
            self._update_state()

    def _selected_pages(self) -> list[int]:
        sel = self.thumbs.selected_pages()
        return sel or [self.view.pno]

    def rotate(self, degrees: int) -> None:
        if self._require_doc():
            pages.rotate_pages(self.pdf, self._selected_pages(), degrees)

    def delete_page(self) -> None:
        if not self._require_doc():
            return
        try:
            pages.delete_pages(self.pdf, self._selected_pages())
        except ValueError as exc:
            self._error(exc)

    def insert_page(self) -> None:
        if not self._require_doc():
            return
        dlg = InsertPageDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        w, h = dlg.size()
        idx = self.view.pno + (1 if dlg.after() else 0)
        pages.insert_blank_page(self.pdf, idx, w, h)
        self.view.set_page(idx)
        self.thumbs.setCurrentRow(idx)

    def move_page(self, delta: int) -> None:
        if not self._require_doc():
            return
        src = self.view.pno
        dst = src + delta
        if 0 <= dst < self.pdf.page_count:
            pages.move_page(self.pdf, src, dst)
            self.view.set_page(dst)
            self.thumbs.setCurrentRow(dst)

    def _reorder(self, order: list[int]) -> None:
        try:
            pages.reorder_pages(self.pdf, order)
        except ValueError as exc:
            self._error(exc)

    def extract_dialog(self) -> None:
        if not self._require_doc():
            return
        pre = ",".join(str(p + 1) for p in self._selected_pages())
        dlg = ExtractDialog(self.pdf.page_count, pre, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            pnos = pages.parse_ranges(dlg.ranges(), self.pdf.page_count)
        except ValueError as exc:
            self._error(exc)
            return
        base = Path(self.pdf.path).with_suffix("") if self.pdf.path else Path.home() / "extract"
        out, _ = QFileDialog.getSaveFileName(self, tr("dlg.extract"), f"{base}_pages.pdf", tr("filter.pdf"))
        if not out:
            return
        try:
            pages.extract_pages(self.pdf, pnos, out)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return
        self.statusBar().showMessage(tr("msg.extract_done", len(pnos), out), 5000)

    def split_dialog(self) -> None:
        if not self._require_doc():
            return
        src = Path(self.pdf.path) if self.pdf.path else None
        default_dir = str(src.parent) if src else os.path.expanduser("~")
        prefix = src.stem if src else "part"
        dlg = SplitDialog(self.pdf.page_count, default_dir, prefix, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            if dlg.mode() == "every":
                files = pages.split_every(self.pdf, dlg.every(), dlg.out_dir.text(), dlg.prefix.text())
            else:
                files = pages.split_ranges(self.pdf, dlg.ranges(), dlg.out_dir.text(), dlg.prefix.text())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return
        self.statusBar().showMessage(tr("msg.split_done", len(files), dlg.out_dir.text()), 5000)

    # ---------------------------------------------------------------- misc
    def add_font_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("act.add_font"), "", tr("filter.font"))
        if not path:
            return
        info = self.registry.add_file(path)
        if info is not None:
            self.font_combo.reload(info.name)

    def about(self) -> None:
        import pikepdf
        from PySide6.QtCore import qVersion

        QMessageBox.about(self, tr("act.about"),
                          tr("msg.about", __version__, pymupdf.VersionBind, pikepdf.__version__, qVersion()))
