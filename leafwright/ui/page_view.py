"""Interactive page canvas."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import pymupdf
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap,
                           QWheelEvent)
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
    REDACT = "redact"


SNAP_PX = 7  # snap distance in screen pixels
GUIDE_COLOR = QColor(255, 0, 140)
SEL_COLOR = QColor(0, 120, 255)
DRAG_THRESHOLD = 4


@dataclass(eq=False)
class SelItem:
    """One selected object: a text span, a content-stream drawing or an annotation."""
    kind: str                 # "span" | "drawing" | "annot"
    obj: Any                  # TextSpan | Drawing | xref (int)
    rect: pymupdf.Rect        # page (unrotated) coordinates
    key: tuple

    @property
    def xref(self) -> int:
        return self.obj if self.kind == "annot" else -1


def _rkey(r: pymupdf.Rect) -> tuple:
    return (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))


def span_item(span: text_edit.TextSpan) -> SelItem:
    return SelItem("span", span, pymupdf.Rect(span.bbox), ("s", *_rkey(span.bbox), span.text))


def drawing_item(d: shapes.Drawing) -> SelItem:
    return SelItem("drawing", d, pymupdf.Rect(d.rect), ("d", *_rkey(d.rect)))


def annot_item(annot: pymupdf.Annot) -> SelItem:
    return SelItem("annot", annot.xref, pymupdf.Rect(annot.rect), ("a", annot.xref))


class PageView(QGraphicsView):
    span_clicked = Signal(object)            # TextSpan (single click on a lone text)
    edit_selection_requested = Signal(list)  # [SelItem] — click inside a multi selection
    text_point_clicked = Signal(object)      # pymupdf.Point
    shape_drawn = Signal(str, object, object)  # kind, p1, p2
    annot_selected = Signal(int)             # first selected annotation xref or -1
    selection_changed = Signal(int)          # number of selected objects
    items_moved = Signal(list, float, float)  # [SelItem], dx, dy (page units)
    drawing_clicked = Signal(object)         # shapes.Drawing (erase tool)
    zoom_changed = Signal(float)
    files_dropped = Signal(list)             # local file paths
    pressed = Signal()                       # any mouse press (marks this pane active)

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
        self._rubber = None
        self._spans: Optional[list[text_edit.TextSpan]] = None
        self._drag_start: Optional[QPointF] = None
        self._sel: list[SelItem] = []
        self._sel_gfx: list[QGraphicsRectItem] = []
        self._mode: Optional[str] = None       # "drag" | "toggle" | "band" while the mouse is down
        self._press_hit: Optional[SelItem] = None
        self._was_selected = False
        self._dragging = False
        self._delta = QPointF(0, 0)
        self._band: Optional[QGraphicsRectItem] = None
        self.snap_enabled = True
        self._snap_cache: Optional[tuple[list[float], list[float]]] = None
        self._guides: list = []
        self.readonly = False  # reference pane: no editing interactions
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        # Keep a strong reference to the current Page: PyMuPDF annotations are
        # unbound as soon as their Page object is garbage collected.
        self._cur_page: Optional[pymupdf.Page] = None

    # ----------------------------------------------------------------- state
    def set_document(self, pdf: Optional[PdfDocument]) -> None:
        self.pdf = pdf
        self.pno = 0
        self._sel = []
        self.refresh()

    def set_page(self, pno: int) -> None:
        if self.pdf is None:
            return
        self.pno = max(0, min(pno, self.pdf.page_count - 1))
        self._sel = []
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
            self.clear_selection()
        self.setCursor(Qt.ArrowCursor if tool in (Tool.SELECT, Tool.ERASE) else Qt.CrossCursor)

    # ------------------------------------------------------------- selection
    def selected_items(self) -> list[SelItem]:
        return list(self._sel)

    def has_selection(self) -> bool:
        return bool(self._sel)

    def selected_xref(self) -> int:
        """xref of the first selected annotation, or -1."""
        return next((i.xref for i in self._sel if i.kind == "annot"), -1)

    def selected_spans(self) -> list[text_edit.TextSpan]:
        return [i.obj for i in self._sel if i.kind == "span"]

    def clear_selection(self) -> None:
        if self._sel:
            self._set_selection([])

    def select_all(self) -> None:
        if self.pdf is None or self.pdf.page_count == 0:
            return
        page = self._page()
        items = [span_item(s) for s in self._spans_cached()]
        items += [drawing_item(d) for d in shapes.list_drawings(page)
                  if d.rect.get_area() <= 0.6 * page.rect.get_area()]
        items += [annot_item(a) for a in page.annots()]
        self._set_selection(items)

    def _set_selection(self, items: list[SelItem]) -> None:
        self._sel = items
        self._draw_selection()
        self.annot_selected.emit(self.selected_xref())
        self.selection_changed.emit(len(items))

    def _draw_selection(self) -> None:
        for g in self._sel_gfx:
            if g.scene() is not None:
                self._scene.removeItem(g)
        self._sel_gfx = []
        pen = QPen(SEL_COLOR, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        for it in self._sel:
            g = self._scene.addRect(self.to_scene(it.rect), pen)
            g.setZValue(500)
            self._sel_gfx.append(g)

    def _is_selected(self, item: SelItem) -> bool:
        return any(i.key == item.key for i in self._sel)

    def _hit(self, page_pt: pymupdf.Point) -> Optional[SelItem]:
        annot = shapes.annot_at(self._page(), page_pt)
        if annot is not None:
            return annot_item(annot)
        span = text_edit.span_at(self._page(), page_pt)
        if span is not None:
            return span_item(span)
        d = shapes.drawing_at(self._page(), page_pt, skip_background=True)
        return drawing_item(d) if d is not None else None

    def _items_in(self, band: pymupdf.Rect) -> list[SelItem]:
        """Objects touched by the rubber band (text: any overlap; shapes: mostly inside)."""
        page = self._page()
        out: list[SelItem] = []

        def mostly(r: pymupdf.Rect) -> bool:
            inter = pymupdf.Rect(r) & band
            if inter.is_empty:
                return False
            return inter.get_area() >= 0.5 * max(r.get_area(), 1e-6) or band.contains(
                pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))

        for s in self._spans_cached():
            if s.bbox.intersects(band):
                out.append(span_item(s))
        for d in shapes.list_drawings(page):
            if d.rect.get_area() <= 0.6 * page.rect.get_area() and mostly(d.rect):
                out.append(drawing_item(d))
        for a in page.annots():
            if mostly(pymupdf.Rect(a.rect)):
                out.append(annot_item(a))
        return out

    # --------------------------------------------------------------- drawing
    def refresh(self) -> None:
        self._scene.clear()
        self._pix_item = self._hover_item = self._rubber = self._band = None
        self._guides = []
        self._sel_gfx = []
        self._snap_cache = None
        self._mode = None
        self._dragging = False
        self._spans = None
        self._cur_page = None
        if self.pdf is None or self.pdf.page_count == 0:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            self._sel = []
            return
        self.pno = min(self.pno, self.pdf.page_count - 1)
        self._cur_page = self.pdf.page(self.pno)
        pix = self.pdf.render(self.pno, self.zoom)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        self._pix_item = self._scene.addPixmap(QPixmap.fromImage(img))
        self._scene.setSceneRect(QRectF(-12, -12, pix.width + 24, pix.height + 24))
        if self._sel:
            # Text / drawings change identity after an edit; annotations survive by xref.
            live = {a.xref: a for a in self._page().annots()}
            kept = [annot_item(live[i.xref]) for i in self._sel if i.kind == "annot" and i.xref in live]
            changed = len(kept) != len(self._sel)
            self._sel = kept
            self._draw_selection()
            if changed:
                self.annot_selected.emit(self.selected_xref())
                self.selection_changed.emit(len(kept))

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

    # ------------------------------------------------------------ snapping
    def _clear_guides(self) -> None:
        for g in self._guides:
            if g.scene() is not None:
                self._scene.removeItem(g)
        self._guides = []

    def _snap_targets(self, excludes: list[QRectF]) -> tuple[list[float], list[float]]:
        """Scene x / y coordinates of the edges of every object that is NOT being moved."""
        if self._snap_cache is not None:
            return self._snap_cache
        rects: list[QRectF] = [self.to_scene(sp.bbox) for sp in self._spans_cached()]
        rects += [self.to_scene(d.rect) for d in shapes.list_drawings(self._page())
                  if d.rect.get_area() <= 0.6 * self._page().rect.get_area()]
        rects += [self.to_scene(pymupdf.Rect(a.rect)) for a in self._page().annots()]

        def same(a: QRectF, b: QRectF) -> bool:
            return (abs(a.left() - b.left()) < 0.5 and abs(a.right() - b.right()) < 0.5
                    and abs(a.top() - b.top()) < 0.5 and abs(a.bottom() - b.bottom()) < 0.5)

        xs: list[float] = []
        ys: list[float] = []
        for r in rects:
            if any(same(r, e) for e in excludes):
                continue
            xs += [r.left(), r.right()]
            ys += [r.top(), r.bottom()]
        self._snap_cache = (xs, ys)
        return self._snap_cache

    def _snap_delta(self, base: QRectF, excludes: list[QRectF], raw: QPointF) -> QPointF:
        """Adjust the drag offset ``raw`` so that an edge of ``base`` lands on a nearby edge
        of another object, and draw the guide lines for it."""
        self._clear_guides()
        if not self.snap_enabled:
            return raw
        xs, ys = self._snap_targets(excludes)
        thr = SNAP_PX

        def best(moving: list[float], targets: list[float]):
            found = None
            for m in moving:
                for t in targets:
                    d = t - m
                    if abs(d) <= thr and (found is None or abs(d) < abs(found[0])):
                        found = (d, t)
            return found

        bx = best([base.left() + raw.x(), base.right() + raw.x()], xs)
        by = best([base.top() + raw.y(), base.bottom() + raw.y()], ys)
        out = QPointF(raw.x() + (bx[0] if bx else 0), raw.y() + (by[0] if by else 0))
        rect = self.sceneRect()
        pen = QPen(GUIDE_COLOR, 1, Qt.DashLine)
        pen.setCosmetic(True)
        if bx:
            self._guides.append(self._scene.addLine(QLineF(bx[1], rect.top(), bx[1], rect.bottom()), pen))
        if by:
            self._guides.append(self._scene.addLine(QLineF(rect.left(), by[1], rect.right(), by[1]), pen))
        for g in self._guides:
            g.setZValue(1000)
        return out

    # ---------------------------------------------------------------- events
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape and self._sel and not self.readonly:
            self.clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.pressed.emit()
        if self.readonly or self.pdf is None or self.pdf.page_count == 0 or event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        scene_pt = self.mapToScene(event.position().toPoint())
        page_pt = self.to_page(scene_pt)
        self._drag_start = scene_pt
        self._snap_cache = None
        self._delta = QPointF(0, 0)
        self._dragging = False
        self._mode = None
        shift = bool(event.modifiers() & Qt.ShiftModifier)

        if self.tool is Tool.SELECT:
            hit = self._hit(page_pt)
            self._press_hit = hit
            if hit is not None:
                if shift:                                   # Shift+click toggles membership
                    if self._is_selected(hit):
                        self._set_selection([i for i in self._sel if i.key != hit.key])
                    else:
                        self._set_selection(self._sel + [hit])
                    self._mode = "toggle"
                else:
                    self._was_selected = self._is_selected(hit)
                    if not self._was_selected:
                        self._set_selection([hit])
                    self._mode = "drag"
                return
            if not shift:
                self.clear_selection()
            self._mode = "band"                             # drag on empty space: rubber band
            self._band = QGraphicsRectItem(QRectF(scene_pt, scene_pt))
            pen = QPen(SEL_COLOR, 1, Qt.DashLine)
            pen.setCosmetic(True)
            self._band.setPen(pen)
            self._band.setBrush(QBrush(QColor(0, 120, 255, 30)))
            self._band.setZValue(900)
            self._scene.addItem(self._band)
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
        if self.tool is Tool.REDACT:
            pen = QPen(QColor(0, 0, 0), 1.5, Qt.DashLine)
            self._rubber.setBrush(QBrush(QColor(0, 0, 0, 110)))
        self._rubber.setPen(pen)
        self._scene.addItem(self._rubber)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.readonly or self.pdf is None or self.pdf.page_count == 0:
            return super().mouseMoveEvent(event)
        scene_pt = self.mapToScene(event.position().toPoint())
        if self._rubber is not None and self._drag_start is not None:
            if isinstance(self._rubber, QGraphicsLineItem):
                self._rubber.setLine(self._drag_start.x(), self._drag_start.y(), scene_pt.x(), scene_pt.y())
            else:
                self._rubber.setRect(QRectF(self._drag_start, scene_pt).normalized())
            return
        if self._mode == "band" and self._band is not None and self._drag_start is not None:
            self._band.setRect(QRectF(self._drag_start, scene_pt).normalized())
            return
        if self._mode == "drag" and self._drag_start is not None:
            if (scene_pt - self._drag_start).manhattanLength() >= DRAG_THRESHOLD:
                self._dragging = True
            if self._dragging:
                self._clear_hover()
                rects = [self.to_scene(i.rect) for i in self._sel]
                base = rects[0]
                for r in rects[1:]:
                    base = base.united(r)
                self._delta = self._snap_delta(base, rects, scene_pt - self._drag_start)
                for g, r in zip(self._sel_gfx, rects):
                    g.setRect(r.translated(self._delta))
                self.setCursor(Qt.ClosedHandCursor)
            return
        if self._mode == "toggle":
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
            d = shapes.drawing_at(self._page(), page_pt, skip_background=True)
            if d is not None:
                self._show_hover(d.rect, QColor(0, 160, 120))
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
        mode, self._mode = self._mode, None
        if self._rubber is not None:
            self._scene.removeItem(self._rubber)
            self._rubber = None
            if (scene_pt - start).manhattanLength() >= 3:
                self.shape_drawn.emit(self.tool.value, self.to_page(start), self.to_page(scene_pt))
            return
        if mode == "band":
            band = self._band
            self._band = None
            if band is not None and band.scene() is not None:
                self._scene.removeItem(band)
            if (scene_pt - start).manhattanLength() >= DRAG_THRESHOLD:
                a, b = self.to_page(start), self.to_page(scene_pt)
                found = self._items_in(pymupdf.Rect(a, b).normalize())
                shift = bool(event.modifiers() & Qt.ShiftModifier)
                if shift:
                    have = {i.key for i in self._sel}
                    found = self._sel + [i for i in found if i.key not in have]
                self._set_selection(found)
            return
        if mode == "drag":
            dragging, self._dragging = self._dragging, False
            self._clear_guides()
            self.setCursor(Qt.ArrowCursor)
            if dragging:
                p0, p1 = self.to_page(start), self.to_page(start + self._delta)
                dx, dy = p1.x - p0.x, p1.y - p0.y
                if abs(dx) + abs(dy) > 0.5:
                    self.items_moved.emit(list(self._sel), dx, dy)
                else:
                    self._draw_selection()
                return
            hit = self._press_hit
            if len(self._sel) > 1 and self._was_selected:
                self.edit_selection_requested.emit(list(self._sel))
            elif hit is not None and hit.kind == "span" and len(self._sel) == 1:
                self.span_clicked.emit(hit.obj)
            return
        if mode == "toggle":
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._clear_hover()
        super().leaveEvent(event)

    # ------------------------------------------------------------ file drops
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
