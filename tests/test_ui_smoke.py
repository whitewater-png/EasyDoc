"""Headless smoke tests for the Qt layer (offscreen platform)."""
import os

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EASYDOC_LANG", "en")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from easydoc.core.document import PdfDocument  # noqa: E402
from easydoc.core.fonts import FontRegistry  # noqa: E402
from easydoc.ui.main_window import MainWindow  # noqa: E402
from easydoc.ui.page_view import Tool  # noqa: E402


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
    from easydoc.core import text_edit

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

    from easydoc.core import printserver

    monkeypatch.setattr(printserver, "inbox_dir", lambda: tmp_path)
    window.settings.setValue("vprinter/port", 0)  # ephemeral port
    window.act_vprinter.setChecked(True)
    assert window.print_server is not None and window.print_server.running
    port = window.print_server.port
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(open(sample_pdf, "rb").read())
    deadline = time.time() + 10
    while time.time() < deadline and not (window.pdf.path or "").startswith(str(tmp_path)):
        app.processEvents()
        time.sleep(0.05)
    assert (window.pdf.path or "").startswith(str(tmp_path))
    window.act_vprinter.setChecked(False)
    assert not window.print_server.running


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
    from easydoc.core import text_edit

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
    from easydoc.core import shapes

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
    from easydoc.ui.logo import draw_logo

    pm = draw_logo(128)
    assert pm.width() == 128 and not pm.toImage().pixelColor(64, 64).alpha() == 0


def test_split_right_pane_is_editable(window, app, tmp_path):
    from easydoc.core import text_edit

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
    from easydoc.core import text_edit

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
    from easydoc.core import updater
    from easydoc.ui import main_window as mw

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
