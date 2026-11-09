"""Application entry point."""
from __future__ import annotations

import argparse
import sys
import warnings


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore", category=FutureWarning)
    parser = argparse.ArgumentParser(prog="Leafweaving", description="Lightweight GUI PDF editor")
    parser.add_argument("file", nargs="?", help="PDF (or image/XPS/EPUB) to open")
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow
    from .ui.logo import logo_icon
    from .ui.theme import apply_theme, install_tooltip_placer

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Leafweaving")
    app.setOrganizationName("Leafweaving")
    apply_theme(app)
    install_tooltip_placer(app)
    app.setWindowIcon(logo_icon())
    win = MainWindow()
    win.show()
    if args.file:
        win.open_path(args.file)
    from PySide6.QtCore import QTimer

    QTimer.singleShot(2500, win.check_for_updates)  # background check shortly after start-up
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
