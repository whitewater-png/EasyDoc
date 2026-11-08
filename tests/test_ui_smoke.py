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
def window(app, sample_pdf):
    win = MainWindow(registry=FontRegistry(scan=False), scan_fonts=False)
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


def test_new_document(app):
    win = MainWindow(registry=FontRegistry(scan=False), scan_fonts=False)
    win.new_document()
    assert win.pdf.page_count == 1
    win.pdf.dirty = False
    win.close()
