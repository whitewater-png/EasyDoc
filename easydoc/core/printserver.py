"""A tiny "virtual printer": a raw (JetDirect / port 9100 style) print server.

Any application can print to easydoc once the operating system has a printer
queue whose port points at ``127.0.0.1:<port>``:

* **Windows**: a *Standard TCP/IP port* on 127.0.0.1 with the built-in
  "Microsoft Print To PDF" (or "Microsoft XPS Document Writer") driver.
* **macOS / Linux (CUPS)**: ``lpadmin -p easydoc -E -v socket://127.0.0.1:9100 -m raw``.
  A raw queue forwards the application's own spool data (PDF on macOS and on
  modern Linux desktops) unchanged.

Whatever arrives (PDF, XPS/OpenXPS or PostScript) is converted to PDF and
handed to a callback.  PostScript needs Ghostscript.
"""
from __future__ import annotations

import datetime as _dt
import os
import platform
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

import pymupdf

from .standards import find_ghostscript

DEFAULT_PORT = 9100
PRINTER_NAME = "EasyDoc PDF"


def inbox_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    d = base / "easydoc" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def detect_format(data: bytes) -> str:
    head = data.lstrip()[:1024]
    if head.startswith(b"\x1b%-12345X"):  # PJL wrapper around PS/PCL
        return "pjl"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"%!PS") or head.startswith(b"\x04%!PS") or b"%!PS-Adobe" in head:
        return "ps"
    if data[:2] == b"PK":
        return "xps"
    return "unknown"


def _strip_pjl(data: bytes) -> bytes:
    """Remove a PJL envelope and return the enclosed PostScript if any."""
    idx = data.find(b"%!PS")
    if idx >= 0:
        end = data.rfind(b"\x1b%-12345X")
        if end > idx:
            data = data[:end]
        return data[idx:]
    return data


def convert_to_pdf(data: bytes, out_path: Path) -> Path:
    """Convert raw spool data to a PDF file at ``out_path``.  Raises on failure."""
    fmt = detect_format(data)
    if fmt == "pjl":
        data = _strip_pjl(data)
        fmt = detect_format(data)
    if fmt == "pdf":
        out_path.write_bytes(data)
        return out_path
    if fmt == "xps":
        doc = pymupdf.open(stream=data, filetype="xps")
        try:
            out_path.write_bytes(doc.convert_to_pdf())
        finally:
            doc.close()
        return out_path
    if fmt == "ps":
        gs = find_ghostscript()
        if not gs:
            raise RuntimeError("PostScript print job received but Ghostscript is not installed. "
                               "Install Ghostscript or use a PDF/XPS printer driver.")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "job.ps")
            Path(src).write_bytes(data)
            cmd = [gs, "-dBATCH", "-dNOPAUSE", "-dQUIET", "-dNOSAFER", "-sDEVICE=pdfwrite",
                   "-dAutoRotatePages=/None", f"-sOutputFile={out_path}", src]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0 or not out_path.exists():
                raise RuntimeError(f"Ghostscript failed: {proc.stderr[:500]}")
        return out_path
    # Unknown: let MuPDF have a try (it sniffs many formats).
    try:
        doc = pymupdf.open(stream=data)
        try:
            out_path.write_bytes(doc.convert_to_pdf() if not doc.is_pdf else doc.tobytes())
        finally:
            doc.close()
        return out_path
    except Exception as exc:  # noqa: BLE001
        raw = out_path.with_suffix(".bin")
        raw.write_bytes(data)
        raise RuntimeError(f"Unrecognised print data (saved as {raw.name}): {exc}") from exc


class _Handler(socketserver.StreamRequestHandler):
    timeout = 30

    def handle(self) -> None:
        chunks = []
        while True:
            try:
                chunk = self.request.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        if data:
            self.server.deliver(data)  # type: ignore[attr-defined]


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, addr, callback, error_callback):
        super().__init__(addr, _Handler)
        self.callback = callback
        self.error_callback = error_callback

    def deliver(self, data: bytes) -> None:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = inbox_dir() / f"print_{stamp}.pdf"
        try:
            path = convert_to_pdf(data, out)
        except Exception as exc:  # noqa: BLE001
            if self.error_callback:
                self.error_callback(str(exc))
            return
        if self.callback:
            self.callback(str(path))


class PrintServer:
    """Background raw print server; ``callback(path)`` is called per job."""

    def __init__(self, callback: Callable[[str], None], error_callback: Optional[Callable[[str], None]] = None,
                 host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.callback = callback
        self.error_callback = error_callback
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> int:
        if self._server is not None:
            return self.port
        self._server = _Server((self.host, self.port), self.callback, self.error_callback)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="easydoc-printserver", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None


# ------------------------------------------------------------- OS integration
def setup_commands(port: int = DEFAULT_PORT, name: str = PRINTER_NAME) -> list[str]:
    """Shell commands that create a printer queue pointing at the server."""
    if sys.platform.startswith("win"):
        return [
            f'Add-PrinterPort -Name "easydoc_{port}" -PrinterHostAddress "127.0.0.1" -PortNumber {port}',
            f'Add-Printer -Name "{name}" -DriverName "Microsoft Print To PDF" -PortName "easydoc_{port}"',
        ]
    queue = name.replace(" ", "_")
    return [f"lpadmin -p {queue} -E -v socket://127.0.0.1:{port} -m raw -o printer-is-shared=false"]


def remove_commands(port: int = DEFAULT_PORT, name: str = PRINTER_NAME) -> list[str]:
    if sys.platform.startswith("win"):
        return [f'Remove-Printer -Name "{name}"', f'Remove-PrinterPort -Name "easydoc_{port}"']
    return [f"lpadmin -x {name.replace(' ', '_')}"]


def printer_installed(name: str = PRINTER_NAME) -> Optional[bool]:
    """True/False when it can be determined, None when unknown."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
                                 capture_output=True, text=True, timeout=20).stdout
            return name in out.splitlines()
        if shutil.which("lpstat"):
            out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=20).stdout
            return name.replace(" ", "_") in out
    except Exception:  # noqa: BLE001
        return None
    return None


def install_printer(port: int = DEFAULT_PORT, name: str = PRINTER_NAME, remove: bool = False) -> tuple[bool, str]:
    """Try to create (or remove) the queue, asking for elevation where needed."""
    cmds = remove_commands(port, name) if remove else setup_commands(port, name)
    script = "; ".join(cmds)
    try:
        if sys.platform.startswith("win"):
            # Run elevated: Add-Printer needs administrator rights.
            inner = script.replace('"', '\\"')
            ps = (f'Start-Process powershell -Verb RunAs -Wait -ArgumentList '
                  f'\'-NoProfile -ExecutionPolicy Bypass -Command "{inner}"\'')
            proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=180)
        elif sys.platform == "darwin":
            osa = script.replace("\\", "\\\\").replace('"', '\\"')
            proc = subprocess.run(["osascript", "-e", f'do shell script "{osa}" with administrator privileges'],
                                  capture_output=True, text=True, timeout=180)
        else:
            if shutil.which("pkexec"):
                proc = subprocess.run(["pkexec", "sh", "-c", script], capture_output=True, text=True, timeout=180)
            else:
                proc = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=180)
        ok = proc.returncode == 0
        return ok, (proc.stdout + proc.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def os_hint() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
