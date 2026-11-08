"""Application entry point."""
from __future__ import annotations

import argparse
import sys
import warnings


def main(argv: list[str] | None = None) -> int:
    warnings.filterwarnings("ignore", category=FutureWarning)
    parser = argparse.ArgumentParser(prog="easydoc", description="Lightweight GUI PDF editor")
    parser.add_argument("file", nargs="?", help="PDF (or image/XPS/EPUB) to open")
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("easydoc")
    app.setOrganizationName("easydoc")
    win = MainWindow()
    win.show()
    if args.file:
        win.open_path(args.file)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
