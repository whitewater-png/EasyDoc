"""Print pipeline tests: Qt printer rendering (to PDF) and the virtual print server."""
import os
import socket
import subprocess
import threading
import time

import pymupdf
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LEAFWEAVING_LANG", "en")

from leafweaving.core import printserver, standards  # noqa: E402
from leafweaving.core.document import PdfDocument  # noqa: E402


def test_print_document_to_pdf_printer(sample_pdf, tmp_path):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtPrintSupport import QPrinter

    from leafweaving.ui import printing

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    pdf = PdfDocument.open(sample_pdf)
    out = tmp_path / "printed.pdf"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out))
    n = printing.print_document(pdf, printer, [0, 2])
    assert n == 2
    with pymupdf.open(str(out)) as d:
        assert d.page_count == 2
        # Pages were rasterised, so expect an image on each printed page.
        assert d[0].get_images()


def _send(port: int, data: bytes) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(data)


def _server(tmp_path, monkeypatch):
    monkeypatch.setattr(printserver, "inbox_dir", lambda: tmp_path)
    results, errors = [], []
    done = threading.Event()

    def cb(path):
        results.append(path)
        done.set()

    def err(msg):
        errors.append(msg)
        done.set()

    srv = printserver.PrintServer(cb, err, port=0)
    srv.start()
    return srv, results, errors, done


def test_detect_format():
    assert printserver.detect_format(b"%PDF-1.7 ...") == "pdf"
    assert printserver.detect_format(b"%!PS-Adobe-3.0\n") == "ps"
    assert printserver.detect_format(b"PK\x03\x04...") == "xps"
    assert printserver.detect_format(b"\x1b%-12345X@PJL\n%!PS-Adobe") == "pjl"
    assert printserver.detect_format(b"hello") == "unknown"


def test_server_receives_pdf(sample_pdf, tmp_path, monkeypatch):
    srv, results, errors, done = _server(tmp_path, monkeypatch)
    try:
        _send(srv.port, open(sample_pdf, "rb").read())
        assert done.wait(10), "no callback"
        assert not errors
        assert len(results) == 1 and results[0].endswith(".pdf")
        with pymupdf.open(results[0]) as d:
            assert d.page_count == 3
    finally:
        srv.stop()
    assert not srv.running


def test_server_rejects_garbage_silently(tmp_path, monkeypatch):
    """Not a document: dropped with neither a document nor an error dialog
    (a web page can send such data; it must not be able to raise dialogs)."""
    srv, results, errors, done = _server(tmp_path, monkeypatch)
    try:
        _send(srv.port, b"this is not a document at all")
        assert not done.wait(1.5)
        assert not errors and not results
        assert not list(tmp_path.iterdir())
    finally:
        srv.stop()


@pytest.mark.skipif(standards.ghostscript_for_untrusted_input() is None,
                    reason="Ghostscript without known security bugs (see standards.GS_WITHOUT_KNOWN_BUGS) not installed")
def test_server_converts_postscript(sample_pdf, tmp_path, monkeypatch):
    gs = standards.find_ghostscript()
    ps = tmp_path / "job.ps"
    subprocess.run([gs, "-dBATCH", "-dNOPAUSE", "-dQUIET", "-sDEVICE=ps2write", f"-sOutputFile={ps}", sample_pdf],
                   check=True, timeout=120)
    srv, results, errors, done = _server(tmp_path, monkeypatch)
    try:
        _send(srv.port, b"\x1b%-12345X@PJL JOB\n" + ps.read_bytes() + b"\x1b%-12345X")
        assert done.wait(60), "no callback"
        assert not errors, errors
        with pymupdf.open(results[0]) as d:
            assert d.page_count == 3
            assert "Hello World" in d[0].get_text()
    finally:
        srv.stop()


def test_setup_commands_mention_port():
    cmds = printserver.setup_commands(9123)
    assert any("9123" in c for c in cmds)
    assert printserver.remove_commands()
