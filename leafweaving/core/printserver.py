"""A tiny "virtual printer": a raw (JetDirect / port 9100 style) print server.

Any application can print to leafweaving once the operating system has a printer
queue whose port points at ``127.0.0.1:<port>``:

* **Windows**: a *Standard TCP/IP port* on 127.0.0.1 with the built-in
  "Microsoft Print To PDF" (or "Microsoft XPS Document Writer") driver.
* **macOS / Linux (CUPS)**: ``lpadmin -p leafweaving -E -v socket://127.0.0.1:9100 -m raw``.
  A raw queue forwards the application's own spool data (PDF on macOS and on
  modern Linux desktops) unchanged.

Whatever arrives (PDF, XPS/OpenXPS or PostScript) is converted to PDF and
handed to a callback.  PostScript needs Ghostscript and always runs under
``-dSAFER``: anything on the machine can connect to the port, so a job is
untrusted input.  Requests that look like HTTP are refused, so a web page
cannot push documents into the printer (cross-protocol printing), and jobs
are capped in size, duration and number of simultaneous connections.
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
import time
from pathlib import Path
from typing import Callable, Optional

import pymupdf

from .standards import find_ghostscript, ghostscript_for_untrusted_input

DEFAULT_PORT = 9100
PRINTER_NAME = "Leafweaving PDF"
MAX_JOB_BYTES = 256 * 1024 * 1024   # a print job larger than this is dropped
MAX_JOB_SECONDS = 300               # total time a sender may take to deliver a job
MAX_CONNECTIONS = 2                 # simultaneous jobs; further connections are closed

_HTTP_METHODS = (b"GET ", b"POST ", b"PUT ", b"HEAD ", b"OPTIONS ", b"DELETE ", b"PATCH ",
                 b"CONNECT ", b"TRACE ", b"PRI * HTTP")


def inbox_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    d = base / "leafweaving" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def looks_like_http(data: bytes) -> bool:
    """True for an HTTP request (what a browser sends when a page targets the port)."""
    head = data.lstrip()[:64].upper()
    return head.startswith(_HTTP_METHODS)


def looks_like_browser_noise(data: bytes) -> bool:
    """HTTP, or a TLS ClientHello (a page loading https://127.0.0.1:<port>/)."""
    return looks_like_http(data) or data[:2] == b"\x16\x03"


def looks_complete(data: bytes) -> bool:
    """Does ``data`` end like a whole document?  Used when the sender goes quiet
    without closing the connection: a complete job is delivered, a truncated one
    is dropped."""
    if detect_format(data) == "pjl":
        data = _strip_pjl(data)
    tail = data[-(64 * 1024 + 64):]
    fmt = detect_format(data)
    if fmt == "pdf":
        return b"%%EOF" in data[-2048:]
    if fmt == "ps":
        return b"%%EOF" in tail or b"%%Trailer" in tail
    if fmt == "xps":
        return b"PK\x05\x06" in tail           # zip end-of-central-directory record
    return False


class NotAPrintJob(RuntimeError):
    """Data that is not a print job at all: dropped without telling the user,
    because a web page can send it and must not be able to raise dialogs."""


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
    pdf = data.find(b"%PDF-")
    ps = data.find(b"%!PS")
    idx = min(i for i in (pdf, ps, len(data)) if i >= 0)
    if idx < len(data):
        end = data.rfind(b"\x1b%-12345X")
        if end > idx:
            data = data[:end]
        return data[idx:]
    return data


def convert_to_pdf(data: bytes, out_path: Path) -> Path:
    """Convert raw spool data to a PDF file at ``out_path``.  Raises on failure."""
    if looks_like_browser_noise(data):
        raise NotAPrintJob("Refused a request that is not a print job (HTTP/TLS).")
    fmt = detect_format(data)
    if fmt == "pjl":
        data = _strip_pjl(data)
        fmt = detect_format(data)
    if fmt == "unknown":
        # Not PDF, XPS or PostScript: refuse silently and keep nothing on disk.
        raise NotAPrintJob("Unrecognised print data (expected PDF, XPS or PostScript).")
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
        gs = ghostscript_for_untrusted_input()
        if not gs:
            if find_ghostscript():
                raise RuntimeError("PostScript print job refused: Ghostscript 10.08.0 or newer is required "
                                   "to convert it safely.  Update Ghostscript, use a PDF/XPS printer driver, "
                                   "or set LEAFWEAVING_TRUST_GHOSTSCRIPT=1 for a distribution build with the "
                                   "security fixes backported.")
            raise RuntimeError("PostScript print job received but Ghostscript is not installed. "
                               "Install Ghostscript or use a PDF/XPS printer driver.")
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "job.ps")
            Path(src).write_bytes(data)
            cmd = [gs, "-dBATCH", "-dNOPAUSE", "-dQUIET", "-dSAFER", "-sDEVICE=pdfwrite",
                   "-dAutoRotatePages=/None", f"-sOutputFile={out_path}", src]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0 or not out_path.exists():
                raise RuntimeError(f"Ghostscript failed: {proc.stderr[:500]}")
        return out_path
    raise NotAPrintJob("Unrecognised print data (expected PDF, XPS or PostScript).")  # pragma: no cover


class _Handler(socketserver.StreamRequestHandler):
    timeout = 30

    def handle(self) -> None:
        server = self.server
        if not server.slots.acquire(blocking=False):  # type: ignore[attr-defined]
            return  # too many simultaneous jobs: drop the connection
        try:
            self._receive()
        finally:
            server.slots.release()  # type: ignore[attr-defined]

    def _receive(self) -> None:
        buf = bytearray()
        deadline = time.monotonic() + MAX_JOB_SECONDS
        checked = False
        while True:
            if time.monotonic() > deadline:
                self.server.report("Print job took too long and was dropped.")  # type: ignore[attr-defined]
                return
            try:
                chunk = self.request.recv(65536)
            except socket.timeout:
                # The sender went quiet without closing.  Some clients never
                # half-close, so a job that ends like a whole document is
                # delivered; a truncated one must not be, as if it were whole.
                if buf and not looks_like_browser_noise(bytes(buf[:64])):
                    if looks_complete(bytes(buf)):
                        break
                    self.server.report("Incomplete print job (the sender stopped sending) was dropped.")  # type: ignore[attr-defined]
                return
            if not chunk:
                break
            buf += chunk
            if not checked and len(buf.lstrip()) >= 16:
                checked = True
                if looks_like_browser_noise(bytes(buf)):
                    # A web page aiming at the port: drop it silently (no dialog,
                    # so a page cannot flood the user with error messages either).
                    return
            if len(buf) > MAX_JOB_BYTES:
                self.server.report(f"Print job larger than {MAX_JOB_BYTES // (1024 * 1024)} MB was dropped.")  # type: ignore[attr-defined]
                return
        if buf and not looks_like_browser_noise(bytes(buf[:64])):
            self.server.deliver(bytes(buf))  # type: ignore[attr-defined]


class _Server(socketserver.ThreadingTCPServer):
    # On Windows SO_REUSEADDR would let another process bind the same port and
    # steal jobs; SO_EXCLUSIVEADDRUSE is the safe equivalent there.
    allow_reuse_address = not sys.platform.startswith("win")
    daemon_threads = True

    def __init__(self, addr, callback, error_callback):
        self.callback = callback
        self.error_callback = error_callback
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(addr, _Handler)

    def server_bind(self) -> None:
        if sys.platform.startswith("win") and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def report(self, msg: str) -> None:
        if self.error_callback:
            self.error_callback(msg)

    def deliver(self, data: bytes) -> None:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = inbox_dir() / f"print_{stamp}.pdf"
        try:
            path = convert_to_pdf(data, out)
        except NotAPrintJob:
            return                      # silently: see NotAPrintJob
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
        self._thread = threading.Thread(target=self._server.serve_forever, name="leafweaving-printserver", daemon=True)
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
            f'Add-PrinterPort -Name "leafweaving_{port}" -PrinterHostAddress "127.0.0.1" -PortNumber {port}',
            f'Add-Printer -Name "{name}" -DriverName "Microsoft Print To PDF" -PortName "leafweaving_{port}"',
        ]
    queue = name.replace(" ", "_")
    return [f"lpadmin -p {queue} -E -v socket://127.0.0.1:{port} -m raw -o printer-is-shared=false"]


def remove_commands(port: int = DEFAULT_PORT, name: str = PRINTER_NAME) -> list[str]:
    if sys.platform.startswith("win"):
        return [f'Remove-Printer -Name "{name}"', f'Remove-PrinterPort -Name "leafweaving_{port}"']
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
