"""Main window wiring the core operations to the Qt widgets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pymupdf
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QSizePolicy, QSplitter, QTabBar, QToolBar, QVBoxLayout, QWidget)

from .. import __version__
from ..core import multi, pages, printserver, redact, shapes, standards, text_edit, updater
from ..core.document import PdfDocument
from ..core.fonts import FontRegistry, default_registry
from . import printing
from .dialogs import (BulkTextDialog, ColorButton, ExtractDialog, FontCombo, InsertPageDialog, MergeDialog, PrinterSetupDialog,
                      SaveAsDialog, SplitDialog, TextDialog)
from .i18n import tr
from .icons import icon
from .page_view import PageView, Tool
from .split_pane import SplitPane
from .update_dialog import UpdateDialog
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


class _UpdateThread(QThread):
    found = Signal(object)   # updater.Release or None
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self) -> None:  # pragma: no cover - network thread
        try:
            self.found.emit(updater.check())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


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
        self.pdf: Optional[PdfDocument] = None  # the document of the current tab
        self.docs: list[PdfDocument] = []       # one entry per tab, in tab order
        self.registry = registry or default_registry(scan=False)
        self.settings = settings or QSettings("leafwright", "leafwright")
        self.print_server: Optional[printserver.PrintServer] = None

        self.view = PageView(self)
        self.thumbs = ThumbnailList(self)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self.thumbs)
        splitter.addWidget(self.view)
        self.split_pane = SplitPane(self)
        self.split_pane.hide()
        splitter.addWidget(self.split_pane)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setCollapsible(1, False)
        self.splitter = splitter
        splitter.setHandleWidth(1)

        self.tabbar = QTabBar(self)
        self.tabbar.setTabsClosable(True)
        self.tabbar.setMovable(True)
        self.tabbar.setExpanding(False)
        self.tabbar.setDocumentMode(True)
        self.tabbar.setUsesScrollButtons(True)
        self.tabbar.setElideMode(Qt.ElideMiddle)
        self.tabbar.hide()
        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tabbar)
        lay.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabCloseRequested.connect(self.close_tab)
        self.tabbar.tabMoved.connect(lambda a, b: self.docs.insert(b, self.docs.pop(a)))

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

        self._active_view = self.view
        for v in (self.view, self.split_pane.view):
            v.span_clicked.connect(lambda sp, v=v: self._edit_span(sp, v))
            v.text_point_clicked.connect(lambda pt, v=v: self._new_text(pt, v))
            v.shape_drawn.connect(lambda k, a, b, v=v: self._shape_drawn(k, a, b, v))
            v.selection_changed.connect(lambda n, v=v: self._on_selection_changed(v))
            v.items_moved.connect(lambda items, dx, dy, v=v: self._items_moved(items, dx, dy, v))
            v.edit_selection_requested.connect(lambda items, v=v: self._edit_selection(items, v))
            v.drawing_clicked.connect(lambda d, v=v: self._erase_drawing(d, v))
            v.pressed.connect(lambda v=v: self._set_active_view(v))
        self.view.files_dropped.connect(self.open_paths)
        self.thumbs.files_dropped.connect(self.open_paths)
        self.split_pane.view.files_dropped.connect(self.open_paths)
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
        self.act_close_tab = act("act.close_tab", lambda: self.close_tab(self.tabbar.currentIndex()), "Ctrl+W")
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
        self.act_edit_sel = act("act.edit_sel", self.edit_selected_text, "Ctrl+Return")
        self.act_redact_sel = act("act.redact_sel", self.redact_selected, "Ctrl+Shift+K", icon_name="redact")
        self.act_select_all = act("act.select_all", self.select_all, QKeySequence.SelectAll)
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
        self.act_split_view = act("act.split_view", None, "Ctrl+\\", checkable=True, icon_name="split_view")
        self.act_split_view.toggled.connect(self._toggle_split_view)
        self.act_zoom_fit = act("act.zoom_fit", self.view.fit_width, "Ctrl+0", icon_name="zoom_fit")
        self.act_zoom_100 = act("act.zoom_100", lambda: self.view.set_zoom(1.0), "Ctrl+1")
        self.act_add_font = act("act.add_font", self.add_font_file, icon_name="font")
        self.act_about = act("act.about", self.about)
        self.act_check_update = act("act.check_update", lambda: self.check_for_updates(silent=False))
        self.act_auto_update = act("act.auto_update", None, checkable=True)
        self.act_auto_update.setChecked(self.settings.value("update/auto", True, type=bool))
        self.act_auto_update.toggled.connect(lambda on: self.settings.setValue("update/auto", on))

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, key, sc in ((Tool.SELECT, "tool.select", "V"), (Tool.TEXT, "tool.text", "T"),
                              (Tool.RECT, "tool.rect", "R"), (Tool.ELLIPSE, "tool.ellipse", "E"),
                              (Tool.LINE, "tool.line", "L"), (Tool.ARROW, "tool.arrow", "A"),
                              (Tool.ERASE, "tool.erase", "X"), (Tool.REDACT, "tool.redact", "K")):
            a = act(key, None, sc, checkable=True, icon_name=tool.value)
            a.triggered.connect(lambda _c=False, t=tool: self._set_tool(t))
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(tr("menu.file"))
        for a in (self.act_new, self.act_open, self.act_close_tab, self.act_save, self.act_saveas, None, self.act_print,
                  self.act_vprinter, self.act_vprinter_setup, None, self.act_merge, None, self.act_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.edit"))
        for a in (self.act_undo, self.act_redo, None, self.act_select_all, self.act_edit_sel, self.act_delete_sel,
                  None, self.act_redact_sel):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.page"))
        for a in (self.act_rot_left, self.act_rot_right, None, self.act_insert_page, self.act_del_page,
                  self.act_move_up, self.act_move_down, None, self.act_merge, self.act_extract, self.act_split):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.view"))
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit, self.act_zoom_100, None, self.act_split_view):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu(tr("menu.tools"))
        for a in self.tool_actions.values():
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_add_font)
        m = mb.addMenu(tr("menu.help"))
        m.addAction(self.act_check_update)
        m.addAction(self.act_auto_update)
        m.addSeparator()
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
            ("grp.view", (self.act_zoom_out, self.act_zoom_in, self.act_zoom_fit, self.act_split_view)),
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
        self.snap_check = QCheckBox(tr("lbl.snap"))
        self.snap_check.setToolTip(tr("tip.snap"))
        self.snap_check.setChecked(self.settings.value("view/snap", True, type=bool))
        self.snap_check.toggled.connect(self._set_snap)
        style.addWidget(self.snap_check)
        self._set_snap(self.snap_check.isChecked())
        # Deliberately not remembered: the risky mode must be chosen each session.
        self.redact_crossing_check = QCheckBox(tr("lbl.redact_crossing"))
        self.redact_crossing_check.setToolTip(tr("tip.redact_crossing"))
        style.addWidget(self.redact_crossing_check)
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
        self.split_pane.view.set_tool(tool)
        self.tool_actions[tool].setChecked(True)
        tip = {Tool.SELECT: "tip.select", Tool.TEXT: "tip.text", Tool.ERASE: "tip.erase",
               Tool.REDACT: "tip.redact"}.get(tool, "tip.shape")
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
        tp = self._tpdf()
        self.act_undo.setEnabled(bool(tp and tp.can_undo))
        self.act_redo.setEnabled(bool(tp and tp.can_redo))
        self._update_selection_actions()
        self.act_close_tab.setEnabled(bool(self.docs))
        self.act_split_view.setEnabled(bool(self.docs))
        self._sync_split_pane()
        self.drop_hint.setVisible(not has)
        self.tabbar.setVisible(bool(self.docs))
        for i, d in enumerate(self.docs):
            self.tabbar.setTabText(i, self._tab_title(d))
            self.tabbar.setTabToolTip(i, d.path or "")
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

    def _set_snap(self, on: bool) -> None:
        self.view.snap_enabled = on
        self.split_pane.view.snap_enabled = on
        self.settings.setValue("view/snap", on)

    def _target_view(self) -> PageView:
        """The pane that editing, undo/redo, save and delete act on (the one clicked last)."""
        if self._active_view is self.split_pane.view and self.split_pane.isVisible() and self.split_pane.pdf is not None:
            return self._active_view
        return self.view

    def _tpdf(self) -> Optional[PdfDocument]:
        return self._target_view().pdf

    def _set_active_view(self, view: PageView) -> None:
        if self._active_view is view:
            return
        self._active_view = view
        self.split_pane.set_active(view is self.split_pane.view)
        self._update_selection_actions()
        self._update_state()

    def _on_selection_changed(self, view: PageView) -> None:
        if view is self._target_view():
            self._update_selection_actions()

    def _update_selection_actions(self) -> None:
        view = self._target_view()
        self.act_delete_sel.setEnabled(view.has_selection())
        self.act_redact_sel.setEnabled(view.has_selection())
        self.act_edit_sel.setEnabled(bool(view.selected_spans()))
        self.act_select_all.setEnabled(view.pdf is not None and view.pdf.page_count > 0)

    def _toggle_split_view(self, on: bool) -> None:
        self.split_pane.setVisible(on and bool(self.docs))
        if not on:
            self._active_view = self.view
            self.split_pane.set_active(False)
            self.split_pane.view.set_document(None)
            self.split_pane.pdf = None
        if on:
            self._sync_split_pane(prefer_other=True)
            total = max(self.splitter.width() - self.thumbs.width(), 2)
            self.splitter.setSizes([self.thumbs.width(), total // 2, total // 2])
            QTimer.singleShot(0, self._refit_panes)

    def _refit_panes(self) -> None:
        self.view.fit_width()
        if self.split_pane.pdf is not None:
            self.split_pane.view.fit_width()

    def _sync_split_pane(self, prefer_other: bool = False) -> None:
        if not self.act_split_view.isChecked():
            return
        if not self.docs:
            self.split_pane.hide()
            return
        self.split_pane.show()
        others = [d for d in self.docs if d is not self.pdf]
        prefer = others[0] if (prefer_other and others) else self.pdf
        self.split_pane.set_documents(self.docs, [self._tab_title(d) for d in self.docs], prefer=prefer)

    @staticmethod
    def _tab_title(pdf: PdfDocument) -> str:
        name = Path(pdf.path).name if pdf.path else "untitled.pdf"
        return f"{'*' if pdf.dirty else ''}{name}"

    def _on_doc_changed(self, pdf: Optional[PdfDocument] = None) -> None:
        """Called by PdfDocument after any mutation (incl. undo/redo)."""
        if pdf is not None and pdf is not self.pdf:
            self._update_state()  # background tab: only its title changes
            self.split_pane.refresh_if(pdf)
            return
        self.view.refresh()
        if pdf is not None:
            self.split_pane.refresh_if(pdf)
        self.thumbs.rebuild(self.view.pno)
        self._update_state()

    def _attach(self, pdf: PdfDocument) -> None:
        """Open ``pdf`` in a new tab and make it the current one."""
        pdf.add_listener(lambda p=pdf: self._on_doc_changed(p))
        self.docs.append(pdf)
        self.tabbar.blockSignals(True)
        idx = self.tabbar.addTab(self._tab_title(pdf))
        self.tabbar.setCurrentIndex(idx)
        self.tabbar.blockSignals(False)
        self._on_tab_changed(idx)

    def _on_tab_changed(self, index: int) -> None:
        if self.pdf is not None:  # remember where we were in the tab we leave
            self.pdf._ui_state = (self.view.pno, self.view.zoom)
        self.pdf = self.docs[index] if 0 <= index < len(self.docs) else None
        self.view.set_document(self.pdf)
        self.thumbs.set_document(self.pdf)
        if self.pdf is not None:
            state = getattr(self.pdf, "_ui_state", None)
            if state:
                self.view.pno = min(state[0], self.pdf.page_count - 1)
                self.view.set_zoom(state[1])
            else:
                self.view.fit_width()
            self.thumbs.setCurrentRow(self.view.pno)
        self._update_state()

    def close_tab(self, index: int) -> None:
        if not 0 <= index < len(self.docs):
            return
        if index != self.tabbar.currentIndex():
            self.tabbar.setCurrentIndex(index)
        if not self._confirm_discard():
            return
        pdf = self.docs[index]
        # Detach every view of the document before its file handle goes away.
        self.view.set_document(None)
        self.thumbs.set_document(None)
        self.pdf = None
        self.docs.pop(index)
        self.tabbar.blockSignals(True)
        self.tabbar.removeTab(index)
        self.tabbar.blockSignals(False)
        pdf.close()
        self._on_tab_changed(self.tabbar.currentIndex())

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
        if paths:
            event.acceptProposedAction()
            self.open_paths(paths)

    # ---------------------------------------------------------------- file
    def new_document(self) -> None:
        self._attach(PdfDocument.new())

    def open_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("act.open"), "", tr("filter.open"))
        if paths:
            self.open_paths(paths)

    def open_paths(self, paths: list[str]) -> None:
        for path in paths:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        path = os.path.normpath(path)      # Qt hands over "C:/x/y.pdf" on Windows
        # Already open? Just switch to its tab.
        try:
            real = os.path.realpath(path)
            for i, d in enumerate(self.docs):
                if d.path and os.path.realpath(d.path) == real:
                    self.tabbar.setCurrentIndex(i)
                    return
        except OSError:
            pass
        try:
            pdf = PdfDocument.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("msg.error"), tr("msg.open_failed", exc))
            return
        self._attach(pdf)

    def save(self) -> None:
        self.save_doc(self._tpdf())

    def save_doc(self, pdf: Optional[PdfDocument]) -> None:
        if pdf is None:
            return
        if not pdf.path or not pdf.path.lower().endswith(".pdf"):
            self.save_as_doc(pdf)
            return
        try:
            res = standards.save_document(pdf, pdf.path, standards.SaveOptions())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)
            return
        self.statusBar().showMessage(tr("msg.saved", res.path, res.engine), 5000)
        self._update_state()

    def save_as(self) -> None:
        self.save_as_doc(self._tpdf())

    def save_as_doc(self, pdf: Optional[PdfDocument]) -> None:
        if pdf is None:
            return
        meta = pdf.doc.metadata or {}
        default = pdf.path or os.path.join(os.path.expanduser("~"), "untitled.pdf")
        dlg = SaveAsDialog(default, meta.get("title") or "", meta.get("author") or "", self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            res = standards.save_document(pdf, dlg.path, dlg.options())
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
        """Ask about unsaved changes of the *current* tab."""
        if self.pdf is None or not self.pdf.dirty:
            return True
        ret = QMessageBox.question(self, tr("app.title"), tr("msg.unsaved"),
                                   QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if ret == QMessageBox.Save:
            self.save_doc(self.pdf)
            return not self.pdf.dirty
        return ret == QMessageBox.Discard

    def closeEvent(self, event: QCloseEvent) -> None:
        ok = True
        for i in range(len(self.docs) - 1, -1, -1):
            if self.docs[i].dirty:
                self.tabbar.setCurrentIndex(i)
                if not self._confirm_discard():
                    ok = False
                    break
        if ok:
            if self._scan_thread is not None and self._scan_thread.isRunning():
                self._scan_thread.wait(5000)
            if self.print_server is not None:
                self.print_server.stop()
            t = getattr(self, "_update_thread", None)
            if t is not None and t.isRunning():
                t.wait(3000)
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
        self.open_path(path)
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- edit
    def undo(self) -> None:
        pdf = self._tpdf()
        if pdf and pdf.undo():
            self._update_state()

    def redo(self) -> None:
        pdf = self._tpdf()
        if pdf and pdf.redo():
            self._update_state()

    def select_all(self) -> None:
        self._target_view().select_all()

    def redact_selected(self) -> None:
        """Redact the area of every selected object (text, drawings, annotations)."""
        view = self._target_view()
        items = view.selected_items()
        if not view.pdf or not items:
            return
        try:
            redact.redact(view.pdf, view.pno, remove_crossing=self.redact_crossing_check.isChecked(),
                          rects=[text_edit.redact_box(i.rect) if i.kind == "span" else i.rect
                                               for i in items])
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def delete_selected(self) -> None:
        view = self._target_view()
        items = view.selected_items()
        if not view.pdf or not items:
            return
        try:
            multi.delete_items(view.pdf, view.pno, [i.obj for i in items if i.kind == "span"],
                               [i.obj for i in items if i.kind == "drawing"],
                               [i.obj for i in items if i.kind == "annot"])
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def edit_selected_text(self) -> None:
        view = self._target_view()
        self._edit_selection(view.selected_items(), view)

    def _edit_selection(self, items, view: PageView) -> None:
        """Edit the text of the selection: one text -> normal dialog, several -> bulk dialog."""
        spans = [i.obj for i in items if i.kind == "span"]
        if not spans:
            return
        if len(spans) == 1:
            self._edit_span(spans[0], view)
            return
        first = spans[0]
        match = self.registry.match_pdf_font(first.font, first.flags)
        dlg = BulkTextDialog(self.registry, len(spans), first.size, first.color, match.name, self)
        if dlg.exec() != QDialog.Accepted:
            return
        if not dlg.has_changes():
            self.statusBar().showMessage(tr("msg.bulk_nothing"), 4000)
            return
        try:
            multi.edit_spans(view.pdf, spans, dlg.find(), dlg.replace(), dlg.font(), dlg.size(), dlg.color(),
                             registry=self.registry)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _edit_span(self, span: text_edit.TextSpan, view: PageView) -> None:
        match = self.registry.match_pdf_font(span.font, span.flags)
        dlg = TextDialog(self.registry, span.text, match.name, span.font, span.size, span.color, editing=True, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            text_edit.replace_span(view.pdf, span, dlg.result_text(), dlg.result_font(), dlg.result_size(),
                                   dlg.result_color(), registry=self.registry)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _new_text(self, point: pymupdf.Point, view: PageView) -> None:
        dlg = TextDialog(self.registry, "", self.font_combo.currentText(), None, self.size_spin.value(),
                         self.stroke_btn.color() or (0, 0, 0), editing=False, parent=self)
        if dlg.exec() != QDialog.Accepted or not dlg.result_text().strip():
            return
        try:
            text_edit.add_text(view.pdf, view.pno, point, dlg.result_text(), dlg.result_font(),
                               dlg.result_size(), dlg.result_color())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _shape_drawn(self, kind: str, p1: pymupdf.Point, p2: pymupdf.Point, view: PageView) -> None:
        try:
            if kind == Tool.REDACT.value:
                redact.redact(view.pdf, view.pno, [pymupdf.Rect(p1, p2)],
                              remove_crossing=self.redact_crossing_check.isChecked())
                return
            shapes.add_shape(view.pdf, view.pno, kind, p1, p2, self._style())
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _items_moved(self, items, dx: float, dy: float, view: PageView) -> None:
        try:
            multi.move_items(view.pdf, view.pno, [i.obj for i in items if i.kind == "span"],
                             [i.obj for i in items if i.kind == "drawing"],
                             [i.obj for i in items if i.kind == "annot"], dx, dy, registry=self.registry)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _erase_drawing(self, drawing: shapes.Drawing, view: PageView) -> None:
        shapes.delete_drawing(view.pdf, view.pno, drawing.rect)

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

    def check_for_updates(self, silent: bool = True) -> None:
        """Look for a newer release in the background.  ``silent`` (the startup check)
        stays quiet unless an update exists; it also honours the opt-out and skipped version."""
        if silent and not self.act_auto_update.isChecked():
            return
        if getattr(self, "_update_thread", None) is not None and self._update_thread.isRunning():
            return
        self._update_thread = _UpdateThread(self)
        self._update_thread.found.connect(lambda rel: self._on_update_result(rel, silent))
        self._update_thread.failed.connect(lambda msg: None if silent else
                                           QMessageBox.warning(self, tr("act.check_update").replace("&", ""),
                                                               tr("msg.update_failed", msg)))
        self._update_thread.start()

    def _on_update_result(self, rel, silent: bool) -> None:
        if rel is None:
            if not silent:
                QMessageBox.information(self, tr("act.check_update").replace("&", ""),
                                        tr("msg.update_none", __version__))
            return
        if silent and self.settings.value("update/skipped", "") == rel.version:
            return
        dlg = UpdateDialog(rel, self)
        dlg.exec()
        if dlg.skipped:
            self.settings.setValue("update/skipped", rel.version)

    def about(self) -> None:
        import pikepdf
        from PySide6.QtCore import qVersion

        QMessageBox.about(self, tr("act.about"),
                          tr("msg.about", __version__, pymupdf.VersionBind, pikepdf.__version__, qVersion()))
