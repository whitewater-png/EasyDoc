"""Headless smoke tests for the Qt layer (offscreen platform)."""
import os

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LEAFWEAVING_LANG", "en")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from leafweaving.core.document import PdfDocument  # noqa: E402
from leafweaving.core.fonts import FontRegistry  # noqa: E402
from leafweaving.ui.main_window import MainWindow  # noqa: E402
from leafweaving.ui.page_view import Tool  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, sample_pdf, tmp_path):
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    win = MainWindow(registry=FontRegistry(scan=False), scan_fonts=False, settings=settings)
    win.resize(1200, 800)
    win.show()
    win.open_path(sample_pdf)
    app.processEvents()
    yield win
    win.pdf.dirty = False
    win.close()


def test_open_and_navigate(window, app):
    assert window.pdf.page_count == 3
    assert window.thumbs.count() == 3
    window.thumbs.setCurrentRow(2)
    app.processEvents()
    assert window.view.pno == 2
    assert "3 / 3" in window.status_page.text()


def test_draw_shape_and_delete(window, app):
    window._set_tool(Tool.RECT)
    view = window.view
    vp = view.viewport()
    p1 = view.mapFromScene(QPointF(50, 50))
    p2 = view.mapFromScene(QPointF(200, 150))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p1)
    QTest.mouseMove(vp, p2)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p2)
    app.processEvents()
    page = window.pdf.page(0)  # keep the page alive while using its annotations
    annots = list(page.annots())
    assert len(annots) == 1
    assert annots[0].type[0] == pymupdf.PDF_ANNOT_SQUARE

    window._set_tool(Tool.SELECT)
    mid = view.mapFromScene(QPointF(125, 100))
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, mid)
    app.processEvents()
    assert view.selected_xref() == annots[0].xref
    window.delete_selected()
    app.processEvents()
    assert list(window.pdf.page(0).annots()) == []
    assert window.pdf.can_undo
    window.undo()
    assert len(list(window.pdf.page(0).annots())) == 1


def test_rotate_delete_undo_via_actions(window, app):
    window.act_rot_right.trigger()
    app.processEvents()
    assert window.pdf.page(0).rotation == 90
    window.act_del_page.trigger()
    app.processEvents()
    assert window.pdf.page_count == 2
    assert window.thumbs.count() == 2
    window.act_undo.trigger()
    app.processEvents()
    assert window.pdf.page_count == 3


def test_coordinate_roundtrip_rotated(window, app):
    window.act_rot_right.trigger()
    app.processEvents()
    view = window.view
    pt = pymupdf.Point(100, 200)
    rect = view.to_scene(pymupdf.Rect(pt, pt + (1, 1)))
    back = view.to_page(QPointF(rect.x(), rect.y()))
    assert abs(back.x - 100) < 1.5 and abs(back.y - 200) < 1.5


def test_reorder_from_thumbnails(window, app):
    window._reorder([2, 0, 1])
    app.processEvents()
    assert window.pdf.page(0).get_text().startswith("Page 3")


def test_new_document(app, tmp_path):
    from PySide6.QtCore import QSettings

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    win = MainWindow(registry=FontRegistry(scan=False), scan_fonts=False, settings=settings)
    win.new_document()
    assert win.pdf.page_count == 1
    win.pdf.dirty = False
    win.close()


def test_edit_text_then_save_roundtrip(window, app, tmp_path):
    """Edit a span through the window, overwrite-save, reopen from disk."""
    from leafweaving.core import text_edit

    path = window.pdf.path
    span = text_edit.get_spans(window.pdf.page(0))[0]
    text_edit.replace_span(window.pdf, span, "Saved edit 保存", registry=window.registry)
    assert window.pdf.dirty
    window.save()
    assert not window.pdf.dirty
    assert "*" not in window.windowTitle()
    with pymupdf.open(path) as d:
        txt = d[0].get_text()
    assert "Saved edit 保存" in txt and "Hello World" not in txt
    assert os.path.getsize(path) < 200_000  # fallback font was subsetted


def test_virtual_printer_toggle_and_job(window, app, tmp_path, monkeypatch, sample_pdf):
    import socket
    import time

    from leafweaving.core import printserver

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(printserver, "inbox_dir", lambda: tmp_path)
    asked = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: asked.append(self.text()) or QMessageBox.StandardButton.Open)
    window.settings.setValue("vprinter/port", 0)  # ephemeral port
    window.act_vprinter.setChecked(True)
    assert window.print_server is not None and window.print_server.running
    port = window.print_server.port
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(open(sample_pdf, "rb").read())
    deadline = time.time() + 10
    inbox_job = str(tmp_path / "print_")      # sample.pdf is in tmp_path too: wait for the job itself
    while time.time() < deadline and not (window.pdf.path or "").startswith(inbox_job):
        app.processEvents()
        time.sleep(0.05)
    assert (window.pdf.path or "").startswith(inbox_job)
    assert asked and "3" in asked[0]          # the user was asked before it opened
    # Two more jobs while a question is up: asked one after the other, not nested.
    depth, worst = [0], [0]

    def exec_(self):
        depth[0] += 1
        worst[0] = max(worst[0], depth[0])
        window._on_print_job(str(sample_pdf)) if len(asked) == 1 else None   # arrives mid-question
        asked.append(self.text())
        depth[0] -= 1
        return QMessageBox.StandardButton.Ignore

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    window._on_print_job(str(sample_pdf))
    assert len(asked) == 3 and worst[0] == 1
    window.act_vprinter.setChecked(False)
    assert not window.print_server.running


def test_about_shows_legal_notices(window, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.append((self.text(), self.textFormat())) or 0)
    window.about()
    text, fmt = seen[0]
    assert fmt == Qt.TextFormat.PlainText
    for needle in ("Copyright", "Artifex", "Qt Company", "Affero", "LICENSES", "github.com/whitewater-png/Leafweaving"):
        assert needle in text, needle


def test_toolbar_has_buttons_for_every_feature(window):
    from PySide6.QtWidgets import QToolBar

    actions = set()
    for tb in window.findChildren(QToolBar):
        actions.update(a for a in tb.actions() if not a.isSeparator() and a.text())
    for a in (window.act_new, window.act_open, window.act_save, window.act_saveas, window.act_print,
              window.act_vprinter, window.act_undo, window.act_redo, window.act_rot_left, window.act_rot_right,
              window.act_insert_page, window.act_del_page, window.act_move_up, window.act_move_down,
              window.act_merge, window.act_extract, window.act_split, window.act_zoom_in, window.act_zoom_out,
              window.act_zoom_fit, *window.tool_actions.values()):
        assert a in actions, a.text()
        assert not a.icon().isNull(), a.text()


def _drag(view, app, scene_from, scene_to):
    vp = view.viewport()
    a = view.mapFromScene(QPointF(*scene_from))
    b = view.mapFromScene(QPointF(*scene_to))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(vp, (a + b) / 2)
    QTest.mouseMove(vp, b)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, b)
    app.processEvents()


def test_drag_moves_existing_text(window, app):
    from leafweaving.core import text_edit

    window._set_tool(Tool.SELECT)
    page = window.pdf.page(0)
    span = text_edit.get_spans(page)[0]
    z = window.view.zoom
    cx, cy = (span.bbox.x0 + span.bbox.x1) / 2 * z, (span.bbox.y0 + span.bbox.y1) / 2 * z
    _drag(window.view, app, (cx, cy), (cx + 60, cy + 90))
    moved = [s for s in text_edit.get_spans(window.pdf.page(0)) if s.text == span.text]
    assert moved and abs(moved[0].bbox.x0 - span.bbox.x0 - 60 / z) < 2 and abs(moved[0].bbox.y0 - span.bbox.y0 - 90 / z) < 2


def test_drag_moves_shape_annotation(window, app):
    window._set_tool(Tool.RECT)
    _drag(window.view, app, (300, 300), (400, 380))
    window._set_tool(Tool.SELECT)
    page = window.pdf.page(0)
    before = pymupdf.Rect(list(page.annots())[0].rect)
    _drag(window.view, app, (350, 340), (350 + 40, 340 + 30))
    page2 = window.pdf.page(0)
    after = pymupdf.Rect(list(page2.annots())[0].rect)
    z = window.view.zoom
    assert abs(after.x0 - before.x0 - 40 / z) < 1 and abs(after.y0 - before.y0 - 30 / z) < 1


def test_drag_moves_content_drawing(window, app):
    from leafweaving.core import shapes

    page = window.pdf.page(0)
    page.draw_rect(pymupdf.Rect(100, 400, 200, 460), color=(1, 0, 0), fill=(0.9, 0.9, 0))
    window.pdf.mutated()
    window.pdf.dirty = False
    app.processEvents()
    z = window.view.zoom
    window._set_tool(Tool.SELECT)
    _drag(window.view, app, (150 * z, 430 * z), (150 * z + 50, 430 * z + 20))
    rects = [d.rect for d in shapes.list_drawings(window.pdf.page(0)) if d.rect.width < 150 and d.rect.width > 50]
    assert any(abs(r.x0 - (100 + 50 / z)) < 1.5 and abs(r.y0 - (400 + 20 / z)) < 1.5 for r in rects), rects


def test_tabs_multiple_documents(window, app, tmp_path):
    first = window.pdf
    window.new_document()
    assert len(window.docs) == 2 and window.tabbar.count() == 2
    assert window.pdf is window.docs[1] and window.pdf is not first
    window.tabbar.setCurrentIndex(0)
    app.processEvents()
    assert window.pdf is first and window.thumbs.count() == 3
    # same file again just re-selects its tab
    window.tabbar.setCurrentIndex(1)
    window.open_path(first.path)
    assert len(window.docs) == 2 and window.pdf is first
    window.docs[1].dirty = False
    window.close_tab(1)
    assert len(window.docs) == 1 and window.tabbar.count() == 1 and window.pdf is first


def test_drop_files_opens_tabs(window, app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDropEvent

    other = tmp_path / "other.pdf"
    d = pymupdf.open()
    d.new_page()
    d.save(str(other))
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(other))])
    from PySide6.QtGui import QDragEnterEvent

    assert window.view.viewport().acceptDrops() and window.acceptDrops()
    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(window.view.viewport(), enter)
    assert enter.isAccepted()
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(window.view.viewport(), ev)
    app.processEvents()
    assert len(window.docs) == 2 and window.pdf.path == str(other)


def test_split_view_shows_two_documents(window, app, tmp_path):
    other = tmp_path / "second.pdf"
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "SECOND")
    d.save(str(other))
    window.open_path(str(other))
    window.act_split_view.setChecked(True)
    app.processEvents()
    pane = window.split_pane
    assert pane.isVisible() and len(pane._docs) == 2
    assert pane.pdf is not window.pdf          # compares a different document side by side
    window.tabbar.setCurrentIndex(0)
    app.processEvents()
    assert pane.pdf is not None and window.pdf.path != pane.pdf.path or pane.pdf is window.pdf
    window.act_split_view.setChecked(False)
    assert not pane.isVisible()
    window.close_tab(1)
    assert len(window.docs) == 1


def test_logo_renders(app):
    from leafweaving.ui.logo import draw_logo

    pm = draw_logo(128)
    assert pm.width() == 128 and not pm.toImage().pixelColor(64, 64).alpha() == 0


def test_split_right_pane_is_editable(window, app, tmp_path):
    from leafweaving.core import text_edit

    other = tmp_path / "second.pdf"
    d = pymupdf.open()
    d.new_page().insert_text((72, 100), "SECOND", fontsize=20)
    d.save(str(other))
    left = window.pdf
    window.open_path(str(other))
    window.tabbar.setCurrentIndex(0)
    window.act_split_view.setChecked(True)
    app.processEvents()
    app.processEvents()
    right = window.split_pane.view
    assert right.pdf is not None and right.pdf is not left and not right.readonly
    window._set_tool(Tool.RECT)
    _drag(right, app, (150, 200), (250, 280))
    assert len(list(right.pdf.page(0).annots())) == 1       # drawn on the right document
    assert list(left.page(0).annots()) == []                # left document untouched
    assert right.pdf.dirty and window._target_view() is right
    assert window.act_undo.isEnabled()
    window.undo()                                           # undo targets the right document
    assert list(right.pdf.page(0).annots()) == []
    # moving the right pane's text
    window._set_tool(Tool.SELECT)
    z = right.zoom
    span = text_edit.get_spans(right.pdf.page(0))[0]
    cx, cy = (span.bbox.x0 + span.bbox.x1) / 2 * z, (span.bbox.y0 + span.bbox.y1) / 2 * z
    _drag(right, app, (cx, cy), (cx + 40, cy + 40))
    moved = text_edit.get_spans(right.pdf.page(0))[0]
    assert moved.bbox.y0 > span.bbox.y0 + 10
    # saving saves the right pane's document
    right.pdf.dirty = True
    window.save()
    assert not right.pdf.dirty
    left.dirty = False
    right.pdf.dirty = False


def test_move_snaps_to_other_object_edges(window, app):
    from leafweaving.core import text_edit

    page = window.pdf.page(0)
    spans = text_edit.get_spans(page)
    ref = spans[0]
    # a second block of text placed below, with a different left edge
    page.insert_text((ref.bbox.x0 + 40, 400), "snapme", fontsize=12)
    window.pdf.mutated()
    app.processEvents()
    z = window.view.zoom
    target = [s for s in text_edit.get_spans(window.pdf.page(0)) if s.text == "snapme"][0]
    window._set_tool(Tool.SELECT)
    # drag "snapme" left by ~38pt (2pt short of aligning with the first span's left edge)
    cx, cy = (target.bbox.x0 + target.bbox.x1) / 2 * z, (target.bbox.y0 + target.bbox.y1) / 2 * z
    window.snap_check.setChecked(True)
    _drag(window.view, app, (cx, cy), (cx - 38 * z, cy))
    moved = [s for s in text_edit.get_spans(window.pdf.page(0)) if s.text == "snapme"][0]
    assert abs(moved.bbox.x0 - ref.bbox.x0) < 0.6          # snapped onto the other text's left edge
    assert window.view._guides == []                         # guides are removed after the drop
    # with snapping off the raw offset is kept
    window.snap_check.setChecked(False)
    t2 = moved
    cx, cy = (t2.bbox.x0 + t2.bbox.x1) / 2 * z, (t2.bbox.y0 + t2.bbox.y1) / 2 * z
    _drag(window.view, app, (cx, cy), (cx + 30 * z + 3, cy))
    moved2 = [s for s in text_edit.get_spans(window.pdf.page(0)) if s.text == "snapme"][0]
    assert abs(moved2.bbox.x0 - (t2.bbox.x0 + 30 + 3 / z)) < 1.2


def test_update_dialog_and_menu(window, app, monkeypatch):
    from leafweaving.core import updater
    from leafweaving.ui import main_window as mw

    rel = updater.parse_release({"tag_name": "v9.0.0", "body": "changes", "html_url": "https://x",
                                 "assets": []})
    shown = []

    class FakeDlg:
        skipped = True

        def __init__(self, release, parent=None):
            shown.append(release.version)

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "UpdateDialog", FakeDlg)
    window._on_update_result(rel, silent=True)
    assert shown == ["9.0.0"] and window.settings.value("update/skipped") == "9.0.0"
    window._on_update_result(rel, silent=True)           # skipped version stays quiet at start-up
    assert shown == ["9.0.0"]
    window._on_update_result(rel, silent=False)          # manual check always shows it
    assert shown == ["9.0.0", "9.0.0"]
    window.act_auto_update.setChecked(False)
    assert window.settings.value("update/auto", True, type=bool) is False


def _multi_page(window, app):
    """Replace page 1 content with three known text lines + one drawn rectangle."""
    from leafweaving.core import text_edit

    page = window.pdf.page(0)
    for i, label in enumerate(("alpha", "bravo", "charlie")):
        page.insert_text((80, 120 + i * 60), label, fontsize=18)
    page.draw_rect(pymupdf.Rect(300, 100, 380, 160), color=(0, 0, 1))
    window.pdf.mutated()
    window.pdf.dirty = False
    app.processEvents()
    spans = {s.text: s for s in text_edit.get_spans(window.pdf.page(0)) if s.text in ("alpha", "bravo", "charlie")}
    return spans


def _click(view, app, scene_pt, modifier=Qt.NoModifier):
    vp = view.viewport()
    a = view.mapFromScene(QPointF(*scene_pt))
    QTest.mousePress(vp, Qt.LeftButton, modifier, a)
    QTest.mouseRelease(vp, Qt.LeftButton, modifier, a)
    app.processEvents()


def _center(span, z):
    return ((span.bbox.x0 + span.bbox.x1) / 2 * z, (span.bbox.y0 + span.bbox.y1) / 2 * z)


def test_shift_click_builds_multi_selection(window, app):
    spans = _multi_page(window, app)
    window.snap_check.setChecked(False)
    view, z = window.view, window.view.zoom
    window._set_tool(Tool.SELECT)
    _click(view, app, _center(spans["alpha"], z), Qt.ShiftModifier)
    _click(view, app, _center(spans["charlie"], z), Qt.ShiftModifier)
    assert sorted(s.text for s in view.selected_spans()) == ["alpha", "charlie"]
    _click(view, app, _center(spans["charlie"], z), Qt.ShiftModifier)      # toggles off
    assert [s.text for s in view.selected_spans()] == ["alpha"]
    _click(view, app, (z * 500, z * 700))                                   # empty space clears
    assert not view.has_selection()


def test_rubber_band_selects_and_group_moves_as_one_undo(window, app):
    from leafweaving.core import text_edit

    spans = _multi_page(window, app)
    window.snap_check.setChecked(False)
    view, z = window.view, window.view.zoom
    window._set_tool(Tool.SELECT)
    # drag a box around alpha + bravo + the rectangle (not charlie)
    _drag(view, app, (z * 40, z * 70), (z * 420, z * 190))
    texts = {s.text for s in view.selected_spans()}
    assert {"alpha", "bravo"} <= texts and "charlie" not in texts
    assert any(i.kind == "drawing" for i in view.selected_items())
    undo_before = len(window.pdf._undo)
    _drag(view, app, _center(spans["alpha"], z), (_center(spans["alpha"], z)[0] + 50, _center(spans["alpha"], z)[1] + 40))
    assert len(window.pdf._undo) == undo_before + 1                         # whole group = one undo step
    now = {s.text: s for s in text_edit.get_spans(window.pdf.page(0))}
    assert abs(now["alpha"].bbox.x0 - spans["alpha"].bbox.x0 - 50 / z) < 1.5
    assert abs(now["bravo"].bbox.y0 - spans["bravo"].bbox.y0 - 40 / z) < 1.5
    assert abs(now["charlie"].bbox.x0 - spans["charlie"].bbox.x0) < 0.5     # untouched
    rects = [d.rect for d in __import__("leafweaving.core.shapes", fromlist=["x"]).list_drawings(window.pdf.page(0))]
    assert any(abs(r.x0 - (300 + 50 / z)) < 1.5 for r in rects)
    window.undo()
    back = {s.text: s for s in text_edit.get_spans(window.pdf.page(0))}
    assert abs(back["alpha"].bbox.x0 - spans["alpha"].bbox.x0) < 0.5


def test_bulk_text_edit_changes_all_selected(window, app):
    from leafweaving.core import multi, text_edit

    spans = _multi_page(window, app)
    chosen = [spans["alpha"], spans["bravo"]]
    n_undo = len(window.pdf._undo)
    multi.edit_spans(window.pdf, chosen, find="a", replace="A", size=24, color=(1, 0, 0), registry=window.registry)
    assert len(window.pdf._undo) == n_undo + 1
    now = {s.text: s for s in text_edit.get_spans(window.pdf.page(0))}
    assert "AlphA" in now and "brAvo" in now and "charlie" in now
    assert abs(now["AlphA"].size - 24) < 0.5 and now["AlphA"].color == (1.0, 0.0, 0.0)
    assert abs(now["charlie"].size - 18) < 0.5


def test_delete_key_removes_whole_selection(window, app):
    from leafweaving.core import text_edit

    spans = _multi_page(window, app)
    window.snap_check.setChecked(False)
    view, z = window.view, window.view.zoom
    _click(view, app, _center(spans["alpha"], z), Qt.ShiftModifier)
    _click(view, app, _center(spans["bravo"], z), Qt.ShiftModifier)
    window.delete_selected()
    left = [s.text for s in text_edit.get_spans(window.pdf.page(0))]
    assert "alpha" not in left and "bravo" not in left and "charlie" in left


def test_text_dialog_keeps_original_font_by_default(app):
    from leafweaving.core.fonts import FontRegistry
    from leafweaving.ui.dialogs import TextDialog

    reg = FontRegistry(scan=False, use_cache=False)
    dlg = TextDialog(reg, "abc", "Helvetica", "IPAPGothic", 12, (0, 0, 0), editing=True)
    assert dlg.keep_chk.isChecked() and not dlg.font_combo.isEnabled()
    assert dlg.result_font() is None                     # None = keep the original font
    dlg.keep_chk.setChecked(False)
    assert dlg.font_combo.isEnabled() and dlg.result_font().name == "Helvetica"
    new = TextDialog(reg, "", "Helvetica", None, 12, (0, 0, 0), editing=False)
    assert new.keep_chk is None and new.result_font().name == "Helvetica"


def test_redact_tool_and_redact_selection(window, app):
    from leafweaving.core import redact

    window._set_tool(Tool.REDACT)
    view = window.view
    vp = view.viewport()
    z = view.zoom
    p1 = view.mapFromScene(QPointF(60 * z, 80 * z))
    p2 = view.mapFromScene(QPointF(260 * z, 108 * z))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p1)
    QTest.mouseMove(vp, p2)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p2)
    app.processEvents()
    page = window.pdf.page(0)
    assert "Hello" not in page.get_text()
    assert len(redact.marks(page)) == 1

    # Select-all must not pick up the black box; redacting the selection removes the rest.
    window._set_tool(Tool.SELECT)
    window.view.select_all()
    assert all(not redact.is_redacted(window.pdf.page(0), i.rect) for i in window.view.selected_items())
    window.redact_selected()
    app.processEvents()
    assert "Second line" not in window.pdf.page(0).get_text()
    window.pdf.undo()
    assert "Second line" in window.pdf.page(0).get_text()


def test_redact_crossing_option(window, app):
    assert not window.redact_crossing_check.isChecked()          # never remembered: off at start
    page = window.pdf.page(0)
    s = page.new_shape()
    s.draw_bezier((60, 400), (90, 340), (120, 460), (200, 395))
    s.finish(color=(0, 0, 1), width=2)
    s.commit()
    window.redact_crossing_check.setChecked(True)
    window._shape_drawn("redact", pymupdf.Point(110, 370), pymupdf.Point(170, 430), window.view)
    app.processEvents()
    assert [d for d in window.pdf.page(0).get_drawings() if d.get("color") == (0.0, 0.0, 1.0)] == []
