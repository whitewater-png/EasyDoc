"""Application look: Fusion style with a light, modern palette and stylesheet."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtGui import QColor, QCursor, QPalette
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

ACCENT = "#2f6fed"
BG = "#f4f6fa"
SURFACE = "#ffffff"
BORDER = "#d9dfe8"
TEXT = "#1f2937"
MUTED = "#6b7280"

QSS = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QMenuBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 6px 10px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: #e8efff; color: {ACCENT}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: #e8efff; color: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 6px 8px; }}

QToolBar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px 8px; spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {BORDER}; margin: 6px 8px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 8px; padding: 5px 7px; color: {TEXT}; }}
QToolButton:hover {{ background: #eef2f9; border-color: {BORDER}; }}
QToolButton:pressed {{ background: #e2e9f6; }}
QToolButton:checked {{ background: #e8efff; border-color: #b9cdfb; color: {ACCENT}; }}
QToolButton:disabled {{ color: #b8bfcc; }}
QToolBar QLabel {{ color: {MUTED}; font-weight: 600; padding: 0 2px; }}
QLabel#groupLabel {{ color: {MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 0 6px; }}

QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 8px; }}

QListWidget {{ background: {BG}; border: none; border-right: 1px solid {BORDER}; padding: 6px; outline: 0; }}
QListWidget::item {{ border-radius: 8px; padding: 4px; color: {MUTED}; }}
QListWidget::item:hover {{ background: #e9eef7; }}
QListWidget::item:selected {{ background: #dbe6ff; color: {ACCENT}; }}

QGraphicsView {{ border: none; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 14px; color: {TEXT}; }}
QPushButton:hover {{ background: #f0f4fb; }}
QPushButton:default {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
QPushButton:default:hover {{ background: #2558c7; }}
QPushButton:disabled {{ color: #b8bfcc; }}

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
  background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px; padding: 4px 8px; color: {TEXT};
  selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QSpinBox, QDoubleSpinBox {{ padding: 3px 2px 3px 6px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{ width: 18px; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: #e8efff; selection-color: {ACCENT}; }}

QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c3cbd9; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #a9b4c7; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c3cbd9; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QCheckBox, QRadioButton {{ color: {TEXT}; spacing: 8px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px; padding: 10px 8px 4px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QToolTip {{ background: #1f2937; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor(BG))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#1f2937"))
    pal.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(QSS)


class _TooltipPlacer(QObject):
    """Show tooltips right below-right of the mouse pointer.

    Qt anchors a tooltip to the widget rect on some platforms (notably macOS
    with tool buttons), which can put it far away from the cursor."""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.ToolTip and isinstance(obj, QWidget):
            text = obj.toolTip()
            if text:
                QToolTip.showText(QCursor.pos() + QPoint(14, 18), text, obj)
                return True
        return False


def install_tooltip_placer(app: QApplication) -> None:
    placer = _TooltipPlacer(app)
    app.installEventFilter(placer)
    app._tooltip_placer = placer  # keep a reference
