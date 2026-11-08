"""Crisp, theme-independent icons drawn with QPainter (no image assets needed)."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK = QColor("#2b3445")
ACCENT = QColor("#2f6fed")
SOFT = QColor("#9aa7bd")


def _pix(size: int = 64) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def _pen(color=INK, w=5.0) -> QPen:
    pen = QPen(color, w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _page(p: QPainter, fill="#ffffff") -> None:
    path = QPainterPath()
    path.moveTo(16, 6)
    path.lineTo(40, 6)
    path.lineTo(52, 18)
    path.lineTo(52, 58)
    path.lineTo(16, 58)
    path.closeSubpath()
    p.setPen(_pen(INK, 4))
    p.setBrush(QColor(fill))
    p.drawPath(path)
    p.drawPolyline(QPolygonF([QPointF(40, 6), QPointF(40, 18), QPointF(52, 18)]))


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    pm, p = _pix()
    n = name
    if n == "new":
        _page(p)
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(34, 28, 34, 46)
        p.drawLine(25, 37, 43, 37)
    elif n == "open":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#ffd27a"))
        p.drawRoundedRect(QRectF(8, 18, 48, 36), 5, 5)
        p.setBrush(QColor("#ffe3a3"))
        p.drawRoundedRect(QRectF(8, 12, 22, 12), 4, 4)
    elif n == "save":
        p.setPen(_pen(INK, 4))
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRectF(10, 10, 44, 44), 6, 6)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(20, 10, 24, 14))
        p.drawRoundedRect(QRectF(18, 34, 28, 20), 3, 3)
    elif n == "export":
        _page(p)
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(34, 26, 34, 48)
        p.drawPolyline(QPolygonF([QPointF(25, 39), QPointF(34, 48), QPointF(43, 39)]))
    elif n == "print":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(18, 6, 28, 16))
        p.setBrush(QColor("#dfe6f3"))
        p.drawRoundedRect(QRectF(8, 22, 48, 24), 5, 5)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(18, 38, 28, 18))
        p.setBrush(ACCENT)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(48, 30), 3, 3)
    elif n == "vprinter":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#dfe6f3"))
        p.drawRoundedRect(QRectF(8, 22, 48, 24), 5, 5)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(18, 38, 28, 18))
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(32, 4, 32, 20)
        p.drawPolyline(QPolygonF([QPointF(24, 12), QPointF(32, 20), QPointF(40, 12)]))
    elif n == "undo" or n == "redo":
        path = QPainterPath()
        path.moveTo(16, 36)
        path.cubicTo(16, 18, 48, 18, 48, 36)
        p.setPen(_pen(INK, 5))
        p.drawPath(path)
        p.setBrush(INK)
        p.setPen(Qt.NoPen)
        tri = QPolygonF([QPointF(6, 34), QPointF(26, 34), QPointF(16, 48)])
        p.drawPolygon(tri)
        if n == "redo":
            pm2 = pm.transformed(__import__("PySide6.QtGui", fromlist=["QTransform"]).QTransform().scale(-1, 1))
            p.end()
            return QIcon(pm2)
    elif n == "select":
        p.setPen(_pen(INK, 3))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([QPointF(16, 8), QPointF(16, 50), QPointF(27, 40), QPointF(34, 56),
                                 QPointF(41, 53), QPointF(34, 38), QPointF(48, 38)]))
    elif n == "text":
        f = QFont("Georgia", 40, QFont.Bold)
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "T")
    elif n == "rect":
        p.setPen(_pen(INK, 5))
        p.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 60))
        p.drawRect(QRectF(10, 14, 44, 36))
    elif n == "ellipse":
        p.setPen(_pen(INK, 5))
        p.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 60))
        p.drawEllipse(QRectF(8, 14, 48, 36))
    elif n == "line":
        p.setPen(_pen(INK, 5))
        p.drawLine(10, 54, 54, 10)
    elif n == "arrow":
        p.setPen(_pen(INK, 5))
        p.drawLine(10, 54, 50, 14)
        p.drawPolyline(QPolygonF([QPointF(30, 12), QPointF(52, 12), QPointF(52, 34)]))
    elif n == "erase":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#f7a1a1"))
        p.save()
        p.translate(32, 32)
        p.rotate(-45)
        p.drawRoundedRect(QRectF(-22, -10, 44, 20), 4, 4)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(-22, -10, 18, 20))
        p.restore()
        p.setPen(_pen(SOFT, 4))
        p.drawLine(28, 56, 58, 56)
    elif n in ("rot_left", "rot_right"):
        path = QPainterPath()
        path.moveTo(50, 32)
        path.arcTo(QRectF(14, 14, 36, 36), 0, 270)
        p.setPen(_pen(INK, 5))
        p.drawPath(path)
        p.setBrush(INK)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(44, 20), QPointF(60, 20), QPointF(52, 34)]))
        if n == "rot_left":
            from PySide6.QtGui import QTransform
            p.end()
            return QIcon(pm.transformed(QTransform().scale(-1, 1)))
    elif n == "del_page":
        _page(p)
        p.setPen(_pen(QColor("#d64545"), 5))
        p.drawLine(26, 30, 42, 46)
        p.drawLine(42, 30, 26, 46)
    elif n == "insert_page":
        _page(p, "#eef3ff")
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(34, 28, 34, 46)
        p.drawLine(25, 37, 43, 37)
    elif n in ("move_up", "move_down"):
        p.setPen(_pen(INK, 5))
        if n == "move_up":
            p.drawLine(32, 54, 32, 14)
            p.drawPolyline(QPolygonF([QPointF(18, 28), QPointF(32, 12), QPointF(46, 28)]))
        else:
            p.drawLine(32, 10, 32, 50)
            p.drawPolyline(QPolygonF([QPointF(18, 36), QPointF(32, 52), QPointF(46, 36)]))
    elif n == "merge":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(6, 10, 20, 26))
        p.drawRect(QRectF(6, 30, 20, 26))
        p.setPen(_pen(ACCENT, 5))
        p.drawLine(30, 32, 52, 32)
        p.drawPolyline(QPolygonF([QPointF(44, 24), QPointF(54, 32), QPointF(44, 40)]))
    elif n == "extract":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(8, 8, 26, 34))
        p.setBrush(QColor("#eef3ff"))
        p.setPen(_pen(ACCENT, 4))
        p.drawRect(QRectF(30, 24, 26, 34))
    elif n == "split":
        p.setPen(_pen(INK, 4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(6, 12, 22, 40))
        p.drawRect(QRectF(36, 12, 22, 40))
        pen = _pen(ACCENT, 4)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawLine(32, 6, 32, 58)
    elif n in ("zoom_in", "zoom_out", "zoom_fit"):
        p.setPen(_pen(INK, 5))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(8, 8, 34, 34))
        p.drawLine(38, 38, 56, 56)
        p.setPen(_pen(ACCENT, 5))
        if n == "zoom_fit":
            p.drawLine(16, 25, 34, 25)
            p.drawPolyline(QPolygonF([QPointF(20, 20), QPointF(15, 25), QPointF(20, 30)]))
            p.drawPolyline(QPolygonF([QPointF(30, 20), QPointF(35, 25), QPointF(30, 30)]))
        else:
            p.drawLine(17, 25, 33, 25)
            if n == "zoom_in":
                p.drawLine(25, 17, 25, 33)
    elif n == "font":
        f = QFont("Arial", 34, QFont.Bold)
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "Aa")
    else:
        p.setPen(_pen(INK, 5))
        p.drawEllipse(QRectF(12, 12, 40, 40))
    p.end()
    return QIcon(pm)
