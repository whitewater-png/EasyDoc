"""The Leafwright logo: an "E" and a "D" sharing one stem on a gradient squircle."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient


def draw_logo(size: int = 512) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    s = size / 100.0
    p.scale(s, s)

    # Squircle body with a diagonal indigo -> blue -> cyan gradient.
    body = QRectF(4, 4, 92, 92)
    g = QLinearGradient(body.topLeft(), body.bottomRight())
    g.setColorAt(0.0, QColor("#6d5dfc"))
    g.setColorAt(0.55, QColor("#2f6fed"))
    g.setColorAt(1.0, QColor("#12c2e9"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(body, 22, 22)
    # Soft highlight in the upper-left corner for depth.
    glow = QRadialGradient(QPointF(28, 20), 60)
    glow.setColorAt(0.0, QColor(255, 255, 255, 70))
    glow.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(glow)
    p.drawRoundedRect(body, 22, 22)

    def stroke(color: QColor, w: float = 8.5) -> None:
        pen = QPen(color, w)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

    # Soft drop shadow of the letters.
    for dy, alpha in ((2.2, 40),):
        p.save()
        p.translate(0, dy)
        _letters(p, stroke, QColor(10, 20, 80, alpha), QColor(10, 20, 80, alpha))
        p.restore()
    _letters(p, stroke, QColor("#ffffff"), QColor("#b6f3ff"))
    p.end()
    return pm


def _letters(p: QPainter, stroke, e_color: QColor, d_color: QColor) -> None:
    # D: shared stem at x=50, bowl to the right.
    d = QPainterPath()
    d.moveTo(50, 27)
    d.lineTo(58, 27)
    d.arcTo(QRectF(34, 27, 48, 46), 90, -180)
    d.lineTo(50, 73)
    d.closeSubpath()
    stroke(d_color)
    p.drawPath(d)
    # E: stem + three bars ending on the shared stem.
    e = QPainterPath()
    e.moveTo(50, 27)
    e.lineTo(25, 27)
    e.lineTo(25, 73)
    e.lineTo(50, 73)
    e.moveTo(25, 50)
    e.lineTo(44, 50)
    stroke(e_color)
    p.drawPath(e)


def logo_icon() -> QIcon:
    ic = QIcon()
    for sz in (16, 32, 64, 128, 256, 512):
        ic.addPixmap(draw_logo(sz))
    return ic
