"""The Leafweaving logo: "L" and "W" written as one stroke that sprouts a leaf,
on a green gradient squircle."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

TEAL = "#12a383"


def draw_logo(size: int = 512) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    s = size / 100.0
    p.scale(s, s)

    # Squircle body with a diagonal green -> teal -> sky gradient.
    body = QRectF(4, 4, 92, 92)
    g = QLinearGradient(body.topLeft(), body.bottomRight())
    g.setColorAt(0.0, QColor("#2ecc71"))
    g.setColorAt(0.55, QColor(TEAL))
    g.setColorAt(1.0, QColor("#0e9fc4"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(body, 22, 22)
    # Soft highlight in the upper-left corner for depth.
    glow = QRadialGradient(QPointF(28, 20), 60)
    glow.setColorAt(0.0, QColor(255, 255, 255, 70))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(glow)
    p.drawRoundedRect(body, 22, 22)

    # Soft drop shadow, then the mark itself.
    p.save()
    p.translate(0, 2.2)
    shadow = QColor(10, 40, 40, 45)
    _mark(p, shadow, shadow, None)
    p.restore()
    _mark(p, QColor("#ffffff"), QColor("#d4f7a8"), QColor(TEAL))
    p.end()
    return pm


def _mark(p: QPainter, stroke_color: QColor, leaf_color: QColor, vein_color) -> None:
    # One stroke: the L's stem and foot run straight into the W, whose last
    # rising stroke sprouts the leaf.
    path = QPainterPath()
    path.moveTo(22, 27)
    path.lineTo(22, 74)
    path.lineTo(37, 74)
    path.lineTo(49, 45)
    path.lineTo(61, 74)
    path.lineTo(71, 44)
    pen = QPen(stroke_color, 8.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)

    # Pointed leaf from the stroke's end towards the upper right.
    bx, by, tx, ty, half = 70.0, 47.0, 88.0, 16.0, 13.6
    dx, dy = tx - bx, ty - by
    length = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / length, dx / length
    mx, my = bx + dx * 0.45, by + dy * 0.45
    leaf = QPainterPath()
    leaf.moveTo(bx, by)
    leaf.quadTo(mx + nx * half, my + ny * half, tx, ty)
    leaf.quadTo(mx - nx * half, my - ny * half, bx, by)
    p.setPen(Qt.NoPen)
    p.setBrush(leaf_color)
    p.drawPath(leaf)
    if vein_color is not None:
        vein = QPen(vein_color, 1.6)
        vein.setCapStyle(Qt.RoundCap)
        p.setPen(vein)
        p.drawLine(QPointF(bx + dx * 0.18, by + dy * 0.18), QPointF(bx + dx * 0.82, by + dy * 0.82))


def logo_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 32, 64, 128, 256, 512):
        ic.addPixmap(draw_logo(sz))
    return ic
