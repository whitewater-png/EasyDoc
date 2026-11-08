"""Headless smoke tests for the Qt layer (offscreen platform)."""
import os

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EASYDOC_LANG", "en")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPointF, Qt  # noqa: E402
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
