"""Update notification dialog with in-app download of the new package."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from .. import __version__
from ..core import updater
from .i18n import tr


class _DownloadThread(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, asset: updater.Asset, dest: Path, parent=None):
        super().__init__(parent)
        self.asset, self.dest, self._cancel = asset, dest, False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # pragma: no cover - network thread
        try:
            path = updater.download(self.asset, self.dest, self.progress.emit, lambda: self._cancel)
            self.finished_ok.emit(str(path))
        except InterruptedError:
            self.failed.emit("")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Result: ``skipped`` is True when the user chose to skip this version."""

    def __init__(self, release: updater.Release, parent=None):
        super().__init__(parent)
        self.release = release
        self.asset = updater.pick_asset(release)
        self.skipped = False
        self._thread: _DownloadThread | None = None
        self.setWindowTitle(tr("dlg.update"))
        self.resize(520, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("msg.update_available", release.version, __version__)))
        notes = QPlainTextEdit(release.notes or "")
        notes.setReadOnly(True)
        lay.addWidget(notes, 1)
        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.dl_btn = QPushButton(tr("btn.update_download").replace("&&", "&"))
        self.dl_btn.setDefault(True)
        self.page_btn = QPushButton(tr("btn.update_page"))
        self.skip_btn = QPushButton(tr("btn.update_skip"))
        self.later_btn = QPushButton(tr("btn.update_later"))
        for b in (self.dl_btn, self.page_btn, self.skip_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.later_btn)
        lay.addLayout(row)
        self.dl_btn.clicked.connect(self._download)
        self.page_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release.page_url)))
        self.skip_btn.clicked.connect(self._skip)
        self.later_btn.clicked.connect(self.reject)

    def _skip(self) -> None:
        self.skipped = True
        self.reject()

    def _download(self) -> None:
        if self.asset is None:
            self.status.setText(tr("msg.update_noasset"))
            QDesktopServices.openUrl(QUrl(self.release.page_url))
            return
        dest = Path.home() / "Downloads"
        self.dl_btn.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText(tr("msg.update_downloading", self.asset.name))
        self._thread = _DownloadThread(self.asset, dest, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def _on_done(self, path: str) -> None:
        self.bar.hide()
        self.status.setText(tr("msg.update_done", path))
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))  # reveal in the file manager
        self.dl_btn.setEnabled(True)

    def _on_failed(self, msg: str) -> None:
        self.bar.hide()
        self.dl_btn.setEnabled(True)
        if msg:
            QMessageBox.warning(self, tr("dlg.update"), tr("msg.update_failed", msg))

    def done(self, r: int) -> None:  # stop a running download when the dialog closes
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait(3000)
        super().done(r)
