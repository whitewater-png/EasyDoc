"""Interactive page canvas."""
from __future__ import annotations

from enum import Enum
from typing import Optional

import pymupdf
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPixmapItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsView)

from ..core import shapes, text_edit
from ..core.document import PdfDocument


class Tool(Enum):
    SELECT = "select"
    TEXT = "text"
    RECT = "rect"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    ERASE = "erase"


class PageView(QGraphicsView):
    span_clicked = Signal(object)            # TextSpan
    text_point_clicked = Signal(object)      # pymupdf.Point
    shape_drawn = Signal(str, object, object)  # kind, p1, p2
    annot_selected = Signal(int)             # xref or -1
    annot_moved = Signal(int, float, float)  # xref, dx, dy
    drawing_clicked = Signal(object)         # shapes.Drawing
    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor(70, 70, 75)))
        self.setDragMode(QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        self.pdf: Optional[PdfDocument] = None
        self.pno = 0
        self.zoom = 1.0
        self.tool = Tool.SELECT

        self._pix_item: Optional[QGraphicsPixmapItem] = None
        self._hover_item: Optional[QGraphicsRectItem] = None
        self._sel_item: Optional[QGraphicsRectItem] = None
        self._rubber = None
        self._spans: Optional[list[text_edit.TextSpan]] = None
        self._drag_start: Optional[QPointF] = None
        self._sel_xref = -1
        self._sel_rect: Optional[pymupdf.Rect] = None
        self._moving = False
        # Keep a strong reference to the current Page: PyMuPDF annotations are
        # unbound as soon as their Page object is garbage collected.
        self._cur_page: Optional[pymupdf.Page] = None

    # ----------------------------------------------------------------- state
    def set_document(self, pdf: Optional[PdfDocument]) -> None:
        self.pdf = pdf
        self.pno = 0
        self._sel_xref = -1
        self.refresh()

    def set_page(self, pno: int) -> None:
        if self.pdf is None:
            return
        self.pno = max(0, min(pno, self.pdf.page_count - 1))
        self._sel_xref = -1
        self.refresh()
        self.verticalScrollBar().setValue(0)

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.1, min(8.0, zoom))
        self.refresh()
        self.zoom_changed.emit(self.zoom)

    def fit_width(self) -> None:
        if self.pdf is None or self.pdf.page_count == 0:
            return
        w = self.pdf.page(self.pno).rect.width
        avail = self.viewport().width() - 24
        if w > 0 and avail > 0:
            self.set_zoom(avail / w)

    def set_tool(self, tool: Tool) -> None:
        self.tool = tool
        self._clear_hover()
        if tool is not Tool.SELECT:
            self._select_annot(-1)
        self.setCursor(Qt.ArrowCursor if tool in (Tool.SELECT, Tool.ERASE) else Qt.CrossCursor)

    def selected_xref(self) -> int:
        return self._sel_xref

    # --------------------------------------------------------------- drawing
    def refresh(self) -> None:
        self._scene.clear()
        self._pix_item = self._hover_item = self._sel_item = self._rubber = None
        self._spans = None
        self._cur_page = None
        if self.pdf is None or self.pdf.page_count == 0:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            return
        self.pno = min(self.pno, self.pdf.page_count - 1)
        self._cur_page = self.pdf.page(self.pno)
        pix = self.pdf.render(self.pno, self.zoom)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        self._pix_item = self._scene.addPixmap(QPixmap.fromImage(img))
        self._scene.setSceneRect(QRectF(-12, -12, pix.width + 24, pix.height + 24))
        if self._sel_xref >= 0:
            self._draw_selection()

    # ------------------------------------------------------------ coordinates
    def _page(self) -> pymupdf.Page:
        if self._cur_page is None:
            self._cur_page = self.pdf.page(self.pno)
        return self._cur_page

    def to_page(self, scene_pt: QPointF) -> pymupdf.Point:
        p = pymupdf.Point(scene_pt.x() / self.zoom, scene_pt.y() / self.zoom)
        return p * self._page().derotation_matrix

    def to_scene(self, rect: pymupdf.Rect) -> QRectF:
        r = pymupdf.Rect(rect) * self._page().rotation_matrix * pymupdf.Matrix(self.zoom, self.zoom)
        r.normalize()
        return QRectF(r.x0, r.y0, r.width, r.height)

    def _spans_cached(self) -> list[text_edit.TextSpan]:
        if self._spans is None:
            self._spans = text_edit.get_spans(self._page())
        return self._spans

    # --------------------------------------------------------------- helpers
    def _clear_hover(self) -> None:
        if self._hover_item is not None:
            self._scene.removeItem(self._hover_item)
            self._hover_item = None

    def _show_hover(self, rect: pymupdf.Rect, color: QColor) -> None:
        self._clear_hover()
        pen = QPen(color, 1.5, Qt.DashLine)
        self._hover_item = self._scene.addRect(self.to_scene(rect), pen, QBrush(QColor(color.red(), color.green(), color.blue(), 40)))

    def _draw_selection(self) -> None:
        if self._sel_item is not None:
            self._scene.removeItem(self._sel_item)
            self._sel_item = None
        if self._sel_xref < 0 or self.pdf is None:
            return
        for annot in self._page().annots():
            if annot.xref == self._sel_xref:
                self._sel_rect = pymupdf.Rect(annot.rect)
                pen = QPen(QColor(0, 120, 255), 2, Qt.DashLine)
                self._sel_item = self._scene.addRect(self.to_scene(self._sel_rect), pen)
                return
        self._sel_xref = -1

    def _select_annot(self, xref: int) -> None:
        self._sel_xref = xref
        self._draw_selection()
        self.annot_selected.emit(xref)

    # ---------------------------------------------------------------- events
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.pdf is None or self.pdf.page_count == 0 or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        page_pt = self.to_page(scene_pt)
        self._drag_start = scene_pt

        if self.tool is Tool.SELECT:
            annot = shapes.annot_at(self._page(), page_pt)
            if annot is not None:
                self._select_annot(annot.xref)
                self._moving = True
                return
            self._select_annot(-1)
            span = text_edit.span_at(self._page(), page_pt)
            if span is not None:
                self.span_clicked.emit(span)
            return
        if self.tool is Tool.TEXT:
            self.text_point_clicked.emit(page_pt)
            return
        if self.tool is Tool.ERASE:
            d = shapes.drawing_at(self._page(), page_pt)
            if d is not None:
                self.drawing_clicked.emit(d)
            return
        # shape tools: start rubber band
        pen = QPen(QColor(0, 120, 255), 1.5, Qt.DashLine)
        if self.tool in (Tool.LINE, Tool.ARROW):
            self._rubber = QGraphicsLineItem(scene_pt.x(), scene_pt.y(), scene_pt.x(), scene_pt.y())
        elif self.tool is Tool.ELLIPSE:
            self._rubber = QGraphicsEllipseItem(QRectF(scene_pt, scene_pt))
        else:
            self._rubber = QGraphicsRectItem(QRectF(scene_pt, scene_pt))
        self._rubber.setPen(pen)
        self._scene.addItem(self._rubber)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.pdf is None or self.pdf.page_count == 0:
            return super().mouseMoveEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        if self._rubber is not None and self._drag_start is not None:
            if isinstance(self._rubber, QGraphicsLineItem):
                self._rubber.setLine(self._drag_start.x(), self._drag_start.y(), scene_pt.x(), scene_pt.y())
            else:
                self._rubber.setRect(QRectF(self._drag_start, scene_pt).normalized())
            return
        if self._moving and self._drag_start is not None and self._sel_item is not None:
            delta = scene_pt - self._drag_start
            base = self.to_scene(self._sel_rect)
            self._sel_item.setRect(base.translated(delta))
            return
        # hover feedback
        page_pt = self.to_page(scene_pt)
        if self.tool is Tool.SELECT:
            annot = shapes.annot_at(self._page(), page_pt)
            if annot is not None:
                self._show_hover(annot.rect, QColor(0, 120, 255))
                return
            span = text_edit.span_at(self._page(), page_pt)
            if span is not None:
                self._show_hover(span.bbox, QColor(255, 140, 0))
                return
            self._clear_hover()
        elif self.tool is Tool.ERASE:
            d = shapes.drawing_at(self._page(), page_pt)
            if d is not None:
                self._show_hover(d.rect, QColor(220, 30, 30))
            else:
                self._clear_hover()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is None:
            return super().mouseReleaseEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        start = self._drag_start
        self._drag_start = None
        if self._rubber is not None:
            self._scene.removeItem(self._rubber)
            self._rubber = None
            if (scene_pt - start).manhattanLength() >= 3:
                self.shape_drawn.emit(self.tool.value, self.to_page(start), self.to_page(scene_pt))
            return
        if self._moving:
            self._moving = False
            delta_scene = scene_pt - start
            if delta_scene.manhattanLength() >= 2 and self._sel_xref >= 0:
                p0 = self.to_page(start)
                p1 = self.to_page(scene_pt)
                self.annot_moved.emit(self._sel_xref, p1.x - p0.x, p1.y - p0.y)
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._clear_hover()
        super().leaveEvent(event)
