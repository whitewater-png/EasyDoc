"""Security hardening: Ghostscript sandboxing, the virtual printer's input
checks, leftovers after redaction, update integrity and bundled licenses."""
import hashlib
import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import urllib.request

import pymupdf
import pytest

from leafweaving.core import printserver, redact, standards, updater
from leafweaving.core.document import PdfDocument

ROOT = Path(__file__).resolve().parent.parent
EVIL_TITLE = "Quarterly Report" + " " * 200 + ") /DOCINFO pdfmark (%pipe%touch /tmp/pwned) (w) file closefile [ /Title ("


# ------------------------------------------------------------ PostScript text
def _balanced(ps: str) -> bool:
    """True if every ( ... ) literal string is closed (backslash escapes honoured)."""
    depth, i = 0, 0
    while i < len(ps):
        c = ps[i]
        if depth and c == "\\":
            i += 2
            continue
        if c == "(":
            depth += 1
        elif c == ")" and depth:
            depth -= 1
        elif c == ")":
            return False
        i += 1
    return depth == 0


def test_ps_string_cannot_be_broken_out_of():
    assert standards.ps_string("A") == "<FEFF0041>"
    assert set(standards.ps_string(EVIL_TITLE)[1:-1]) <= set("0123456789ABCDEF")
    lit = standards.ps_string(b"C:/Users/a(b)\\c/\xe3\x83\xaa.icc")
    assert lit.startswith("(") and lit.endswith(")") and _balanced(lit)
    assert "\\050" in lit and "\\051" in lit and "\\134" in lit and "\\343" in lit


@pytest.mark.parametrize("kind", ["a", "x"])
def test_definition_file_keeps_hostile_title_inert(kind):
    ps = standards._pdfa_def_ps("/tmp/x/srgb.icc", EVIL_TITLE, kind, "PDF/X-3:2003")
    assert "%pipe%" not in ps and "closefile" not in ps
    assert _balanced(ps)
    ps.encode("ascii")  # Japanese titles must not break the ASCII definition file
    assert "<FEFF" in standards._pdfa_def_ps("/tmp/srgb.icc", "日本語のタイトル", kind)


class _FakeGs:
    """Stands in for subprocess.run: records the command and writes an output file."""

    def __init__(self):
        self.cmds = []

    def __call__(self, cmd, **kw):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, "10.09.0\n", "")
        self.cmds.append(cmd)
        out = next(a.split("=", 1)[1] for a in cmd if a.startswith("-sOutputFile="))
        doc = pymupdf.open()
        doc.new_page()
        doc.save(out)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_pdfa_runs_ghostscript_sandboxed_with_hostile_title(sample_pdf, tmp_path, monkeypatch):
    fake = _FakeGs()
    monkeypatch.setattr(standards, "find_ghostscript", lambda: "/usr/bin/gs")
    monkeypatch.setattr(standards.subprocess, "run", fake)
    pdf = PdfDocument.open(sample_pdf)
    pdf.doc.set_metadata({"title": EVIL_TITLE})
    res = standards.save_document(pdf, tmp_path / "a.pdf", standards.SaveOptions(standard="pdfa-2b"))
    assert res.engine == "ghostscript"
    cmd = fake.cmds[0]
    assert "-dSAFER" in cmd and "-dNOSAFER" not in cmd
    assert any(a.startswith("--permit-file-read=") and a.endswith("srgb.icc") for a in cmd)
    # Japanese title used to fail with UnicodeEncodeError
    pdf.doc.set_metadata({"title": "四半期報告"})
    standards.save_document(pdf, tmp_path / "b.pdf", standards.SaveOptions(standard="pdfa-2b"))


def _gs_version(monkeypatch, ver):
    monkeypatch.setattr(standards, "find_ghostscript", lambda: "/usr/bin/gs")
    monkeypatch.setattr(standards.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, ver + "\n", ""))


def test_old_ghostscript_is_not_trusted(monkeypatch):
    monkeypatch.delenv("LEAFWEAVING_TRUST_GHOSTSCRIPT", raising=False)
    _gs_version(monkeypatch, "9.26")
    assert standards.safe_ghostscript() is None and standards.ghostscript_for_untrusted_input() is None
    assert standards.ghostscript_status()[2] == "old"
    # 10.02.1 (Ubuntu 24.04): fine for the user's own PDF, not for print jobs from anyone
    _gs_version(monkeypatch, "10.02.1")
    assert standards.safe_ghostscript() == "/usr/bin/gs"
    assert standards.ghostscript_for_untrusted_input() is None
    assert standards.ghostscript_status()[2] == "outdated"
    monkeypatch.setenv("LEAFWEAVING_TRUST_GHOSTSCRIPT", "1")   # patched distribution build
    assert standards.ghostscript_for_untrusted_input() == "/usr/bin/gs"
    monkeypatch.delenv("LEAFWEAVING_TRUST_GHOSTSCRIPT")
    _gs_version(monkeypatch, "10.07.1")
    assert standards.ghostscript_for_untrusted_input() is None     # CVE-2026-39919 etc. fixed in 10.08.0
    _gs_version(monkeypatch, "10.08.0")
    assert standards.ghostscript_for_untrusted_input() == "/usr/bin/gs"
    assert standards.ghostscript_status()[2] == "ok"
    assert standards._version_tuple("gs10.05.1") > standards._version_tuple("gs9.56.1")


def test_outdated_ghostscript_is_flagged_and_too_old_is_named(sample_pdf, tmp_path, monkeypatch):
    fake = _FakeGs()
    monkeypatch.setattr(standards, "find_ghostscript", lambda: "/usr/bin/gs")

    def run(cmd, **kw):
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, ver[0] + "\n", "")
        return fake(cmd, **kw)

    ver = ["10.02.1"]
    monkeypatch.delenv("LEAFWEAVING_TRUST_GHOSTSCRIPT", raising=False)
    monkeypatch.setattr(standards.subprocess, "run", run)
    pdf = PdfDocument.open(sample_pdf)
    # Not trusted by the user: an outdated Ghostscript is NOT run on the document.
    res = standards.save_document(pdf, tmp_path / "a0.pdf", standards.SaveOptions(standard="pdfa-2b"))
    assert res.engine == "best-effort" and "security" in res.warnings[0] and not fake.cmds
    # Trusted (the UI asked first): run, but still warn.
    res = standards.save_document(pdf, tmp_path / "a.pdf",
                                  standards.SaveOptions(standard="pdfa-2b", allow_outdated_ghostscript=True))
    assert res.engine == "ghostscript" and "security" in res.warnings[0]
    ver[0] = "9.27"
    res = standards.save_document(pdf, tmp_path / "b.pdf",
                                  standards.SaveOptions(standard="pdfa-2b", allow_outdated_ghostscript=True))
    assert res.engine == "best-effort" and "security" in res.warnings[0]


def test_undecodable_file_name_title_does_not_crash():
    assert standards.ps_string("bad\udcffname").startswith("<FEFF")


# ------------------------------------------------------------ virtual printer
def _server(tmp_path, monkeypatch):
    monkeypatch.setattr(printserver, "inbox_dir", lambda: tmp_path)
    results, errors = [], []
    srv = printserver.PrintServer(results.append, errors.append, port=0)
    srv.start()
    return srv, results, errors


def _send(port, data):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(data)


def test_http_request_is_dropped_silently(sample_pdf, tmp_path, monkeypatch):
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        body = open(sample_pdf, "rb").read()
        _send(srv.port, b"POST / HTTP/1.1\r\nHost: 127.0.0.1:9100\r\nContent-Type: text/plain\r\n"
                        b"Content-Length: %d\r\n\r\n" % len(body) + body)
        time.sleep(1.0)
        assert not results and not errors          # no document, and no dialog to spam
        assert not list(tmp_path.glob("print_*"))
    finally:
        srv.stop()
    with pytest.raises(printserver.NotAPrintJob):
        printserver.convert_to_pdf(b"GET / HTTP/1.1\r\n\r\n%PDF-1.7", tmp_path / "x.pdf")


def test_tls_and_unknown_data_are_dropped_silently(tmp_path, monkeypatch):
    """A page loading https://127.0.0.1:9100/ sends a TLS ClientHello; neither it
    nor any other unrecognised data may raise a dialog (error callback)."""
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        _send(srv.port, bytes.fromhex("160301") + b"\x00\x40" + b"\x01" * 64)
        _send(srv.port, b"\x89PNG\r\n\x1a\n not a print job at all")
        time.sleep(1.0)
        assert not results and not errors
        assert not list(tmp_path.iterdir())
    finally:
        srv.stop()


def test_browser_noise_is_recognised_directly():
    noise = [b"GET / HTTP/1.1\r\n", b"post / http/1.1\r\n", b"\r\nPOST /x", b"PRI * HTTP/2.0\r\n",
             bytes.fromhex("160301") + b"\x00\x40"]
    for n in noise:
        assert printserver.looks_like_browser_noise(n), n
    for ok in (b"%PDF-1.7\n", b"%!PS-Adobe-3.0\n", b"PK\x03\x04", b"\x1b%-12345X@PJL\n"):
        assert not printserver.looks_like_browser_noise(ok), ok


def test_http_post_is_cut_off_early(tmp_path, monkeypatch):
    """A page POSTing a large body: the connection is closed as soon as the
    request line is seen, long before MAX_JOB_BYTES would be read."""
    monkeypatch.setattr(printserver, "MAX_JOB_BYTES", 64 * 1024 * 1024)
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        sent = 0
        try:
            with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as s:
                s.sendall(b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 50000000\r\n\r\n")
                chunk = b"%PDF-1.7 " * 7000
                for _ in range(800):            # ~50 MB if the server kept reading
                    s.sendall(chunk)
                    sent += len(chunk)
        except OSError:
            pass
        assert sent < 20 * 1024 * 1024, sent
        time.sleep(0.5)
        assert not results and not errors
    finally:
        srv.stop()


def test_complete_job_from_sender_that_never_closes_is_delivered(tmp_path, monkeypatch, sample_pdf):
    monkeypatch.setattr(printserver._Handler, "timeout", 1)
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as s:
            s.sendall(open(sample_pdf, "rb").read())     # whole file, connection kept open
            time.sleep(2.5)
        time.sleep(0.5)
        assert results and not errors
        with pymupdf.open(results[0]) as d:
            assert d.page_count == 3
    finally:
        srv.stop()


def test_looks_complete():
    pdf = open(__file__, "rb").read()[:0] + b"%PDF-1.7\n...\nstartxref\n9\n%%EOF\n"
    assert printserver.looks_complete(pdf) and not printserver.looks_complete(pdf[:-6])
    assert printserver.looks_complete(b"\x1b%-12345X@PJL\n" + pdf + b"\x1b%-12345X")
    assert printserver.looks_complete(b"%!PS-Adobe-3.0\nshowpage\n%%Trailer\n%%EOF\n")
    assert not printserver.looks_complete(b"%!PS-Adobe-3.0\nshowpage\n")
    assert printserver.looks_complete(b"PK\x03\x04" + b"x" * 100 + b"PK\x05\x06" + b"\x00" * 18)
    assert not printserver.looks_complete(b"PK\x03\x04" + b"x" * 100)


def test_incomplete_job_is_not_delivered(tmp_path, monkeypatch, sample_pdf):
    monkeypatch.setattr(printserver._Handler, "timeout", 1)
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as s:
            s.sendall(open(sample_pdf, "rb").read()[:300])
            time.sleep(2.5)                      # sender stalls without closing
        time.sleep(0.5)
        assert not results and errors and "ncomplete" in errors[0]
        assert not list(tmp_path.glob("print_*"))
    finally:
        srv.stop()


def test_oversized_job_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(printserver, "MAX_JOB_BYTES", 100_000)
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        try:
            _send(srv.port, b"%PDF-1.7\n" + b"0" * 400_000)
        except OSError:
            pass  # the server may close the connection while we are still sending
        deadline = time.time() + 10
        while time.time() < deadline and not errors:
            time.sleep(0.05)
        assert errors and not results
        assert not list(tmp_path.iterdir())
    finally:
        srv.stop()


def test_unknown_data_is_not_kept(tmp_path):
    with pytest.raises(printserver.NotAPrintJob):
        printserver.convert_to_pdf(b"\x89PNG not really a print job", tmp_path / "x.pdf")
    assert not list(tmp_path.iterdir())


def test_http_split_over_several_packets_is_still_dropped(tmp_path, monkeypatch):
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as s:
            s.sendall(b"PO")
            time.sleep(0.3)
            s.sendall(b"ST / HTTP/1.1\r\nHost: x\r\n\r\n%PDF-1.7\n")
        time.sleep(1.0)
        assert not results and not errors
    finally:
        srv.stop()


def test_pdf_wrapped_in_pjl_is_accepted(sample_pdf, tmp_path):
    data = b"\x1b%-12345X@PJL JOB\n@PJL ENTER LANGUAGE=PDF\n" + open(sample_pdf, "rb").read() + b"\x1b%-12345X"
    out = printserver.convert_to_pdf(data, tmp_path / "j.pdf")
    with pymupdf.open(str(out)) as d:
        assert d.page_count == 3


def test_postscript_job_needs_ghostscript_without_known_escapes(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAFWEAVING_TRUST_GHOSTSCRIPT", raising=False)
    _gs_version(monkeypatch, "10.06.0")
    monkeypatch.setattr(printserver, "find_ghostscript", lambda: "/usr/bin/gs")
    with pytest.raises(RuntimeError, match="10.08.0"):
        printserver.convert_to_pdf(b"%!PS-Adobe-3.0\nshowpage\n", tmp_path / "j.pdf")


def test_postscript_job_runs_ghostscript_sandboxed(tmp_path, monkeypatch):
    fake = _FakeGs()
    monkeypatch.setattr(standards, "find_ghostscript", lambda: "/usr/bin/gs")
    monkeypatch.setattr(printserver, "find_ghostscript", lambda: "/usr/bin/gs")
    monkeypatch.setattr(standards.subprocess, "run", fake)
    monkeypatch.setattr(printserver.subprocess, "run", fake)
    printserver.convert_to_pdf(b"%!PS-Adobe-3.0\n(%pipe%id) (w) file closefile\n", tmp_path / "j.pdf")
    assert "-dSAFER" in fake.cmds[0] and "-dNOSAFER" not in fake.cmds[0]


def test_too_many_connections_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(printserver, "MAX_CONNECTIONS", 1)
    srv, results, errors = _server(tmp_path, monkeypatch)
    try:
        hold = socket.create_connection(("127.0.0.1", srv.port), timeout=10)
        hold.sendall(b"%PDF-1.7\n")                # first job stays open
        time.sleep(0.3)
        with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as s2:
            s2.settimeout(5)
            assert s2.recv(1) == b""               # closed straight away
        hold.close()
    finally:
        srv.stop()


# ------------------------------------------------------------ redaction leftovers
def _streams_contain(path, needle: bytes) -> bool:
    hexed = needle.hex().encode()
    with pymupdf.open(path) as d:
        for x in range(1, d.xref_length()):
            try:
                data = d.xref_stream(x) or b""
            except Exception:
                continue
            if needle in data or hexed in data.lower():
                return True
    raw = Path(path).read_bytes()
    return needle in raw


@pytest.mark.parametrize("compress", [True, False])
def test_redacted_text_does_not_survive_any_save(sample_pdf, tmp_path, compress):
    pdf = PdfDocument.open(sample_pdf)
    for pno in range(3):
        redact.redact(pdf, pno, [pymupdf.Rect(60, 80, 300, 110)])
    out = tmp_path / f"r_{compress}.pdf"
    standards.save_document(pdf, out, standards.SaveOptions(compress=compress))
    assert not _streams_contain(str(out), b"Hello World")
    assert _streams_contain(str(out), b"Second line") or "Second line" in pymupdf.open(str(out))[0].get_text()


@pytest.mark.parametrize("opts", [standards.SaveOptions(), standards.SaveOptions(compress=False, pdf_version="1.7"),
                                  standards.SaveOptions(linearize=True),
                                  standards.SaveOptions(standard="pdfa-2b", prefer_ghostscript=False)])
def test_redaction_drops_pieceinfo_and_xmp_leftovers(sample_pdf, tmp_path, opts):
    """Illustrator/InDesign keep the editable artwork in /PieceInfo; Adobe XMP
    often carries a thumbnail of the first page.  Both must go with the redaction."""
    pdf = PdfDocument.open(sample_pdf)
    doc, page = pdf.doc, pdf.page(0)
    x = doc.get_new_xref()
    doc.update_object(x, "<< /Illustrator << /Private (PAGEPIECESECRET) >> >>")
    doc.xref_set_key(page.xref, "PieceInfo", f"{x} 0 R")
    m = doc.get_new_xref()
    doc.update_object(m, "<< /Type /Metadata /Subtype /XML >>")
    doc.update_stream(m, b"<x:xmpmeta>PAGEMETASECRET</x:xmpmeta>")
    doc.xref_set_key(page.xref, "Metadata", f"{m} 0 R")
    root = doc.pdf_catalog()
    y = doc.get_new_xref()
    doc.update_object(y, "<< /InDesign << /Private (DOCPIECESECRET) >> >>")
    doc.xref_set_key(root, "PieceInfo", f"{y} 0 R")
    dm = doc.get_new_xref()
    doc.update_object(dm, "<< /Type /Metadata /Subtype /XML >>")
    doc.update_stream(dm, b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description><dc:title>KEEPTITLE</dc:title>'
                          b'<xmp:Thumbnails><rdf:Alt><rdf:li><xmpGImg:image>THUMBSECRET</xmpGImg:image></rdf:li>'
                          b'</rdf:Alt></xmp:Thumbnails></rdf:Description></rdf:RDF></x:xmpmeta>')
    doc.xref_set_key(root, "Metadata", f"{dm} 0 R")
    redact.redact(pdf, 0, [pymupdf.Rect(60, 80, 300, 110)])
    out = tmp_path / "r.pdf"
    standards.save_document(pdf, out, opts)
    for secret in (b"PAGEPIECESECRET", b"PAGEMETASECRET", b"DOCPIECESECRET", b"THUMBSECRET"):
        assert not _streams_contain(str(out), secret), secret
    if opts.standard == "none":
        assert _streams_contain(str(out), b"KEEPTITLE")      # the rest of the XMP survives


def test_xmp_thumbnail_strip_is_linear_on_hostile_input():
    hostile = b"<xmp:Thumbnails>" * 5000 + b"x" * 2_000_000
    t = time.monotonic()
    out = redact._strip_xmp_thumbnails(hostile)
    assert time.monotonic() - t < 2.0
    assert out == hostile                                   # unclosed: left alone
    good = b"<a>KEEP</a><xmp:Thumbnails><rdf:Alt>SECRET</rdf:Alt></xmp:Thumbnails><b>KEEP2</b><xap:Thumbnails>S2</xap:Thumbnails>"
    assert redact._strip_xmp_thumbnails(good) == b"<a>KEEP</a><b>KEEP2</b>"
    assert redact._strip_xmp_thumbnails(b"<xmp:ThumbnailsX>K</xmp:ThumbnailsX>") == b"<xmp:ThumbnailsX>K</xmp:ThumbnailsX>"


def test_redaction_drops_page_thumbnail(sample_pdf, tmp_path):
    pdf = PdfDocument.open(sample_pdf)
    page = pdf.page(0)
    doc = pdf.doc
    thumb = doc.get_new_xref()
    doc.update_object(thumb, "<< /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 >>")
    doc.update_stream(thumb, b"\x00")
    doc.xref_set_key(page.xref, "Thumb", f"{thumb} 0 R")
    redact.redact(pdf, 0, [pymupdf.Rect(60, 80, 300, 110)])
    assert doc.xref_get_key(pdf.page(0).xref, "Thumb")[0] == "null"


# ------------------------------------------------------------ updater
def test_untrusted_urls_are_refused(monkeypatch):
    for bad in ("http://github.com/x", "https://evil.example/x", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(updater.UntrustedUrl):
            updater.check_url(bad)
    assert updater.check_url("https://github.com/whitewater-png/Leafweaving/releases/download/v1/x.dmg")
    assert updater.check_url("http://127.0.0.1:8000/x")
    # redirects: only https on GitHub hosts (or loopback) are followed
    h = updater._StrictRedirects()
    for bad in ("http://github.com/x", "https://evil.example/x"):
        with pytest.raises(updater.UntrustedUrl):
            h.redirect_request(urllib.request.Request("https://github.com/a"), None, 302, "", {}, bad)
    for good in ("https://objects.githubusercontent.com/x", "https://release-assets.githubusercontent.com/y",
                 "http://127.0.0.1:1/z"):
        assert h.redirect_request(urllib.request.Request("https://github.com/a"), None, 302, "", {}, good) is not None
    monkeypatch.setenv("LEAFWEAVING_UPDATE_URL", "http://evil.example/latest")
    with pytest.raises(updater.UntrustedUrl):
        updater.fetch_latest()
    rel = updater.parse_release({"tag_name": "v1", "html_url": "file:///Applications/Calculator.app", "assets": []})
    assert rel.page_url == updater.RELEASES_URL


@pytest.fixture
def release_server():
    payload = b"leafweaving package bytes" * 1000
    state = {"sum": hashlib.sha256(payload).hexdigest(), "with_sums": True}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/latest":
                assets = [{"name": "leafweaving-9.9.9-linux-x86_64.tar.gz", "browser_download_url": base + "/pkg",
                           "size": len(payload)}]
                if state["with_sums"]:
                    assets.append({"name": "SHA256SUMS.txt", "browser_download_url": base + "/sums", "size": 1})
                body = json.dumps({"tag_name": "v9.9.9", "body": "", "html_url": "", "assets": assets}).encode()
            elif self.path == "/sums":
                body = f"{state['sum']}  leafweaving-9.9.9-linux-x86_64.tar.gz\n".encode()
            else:
                body = payload
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", state
    srv.shutdown()


def test_download_is_verified_against_published_checksum(release_server, tmp_path):
    url, state = release_server
    rel = updater.fetch_latest(url + "/latest")
    asset = updater.pick_asset(rel, "linux", "x86_64")
    digest = updater.expected_sha256(rel, asset)
    path = updater.download(asset, tmp_path, sha256=digest)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    # same name again: the existing file is not overwritten
    path2 = updater.download(asset, tmp_path, sha256=digest)
    assert path2 != path and path.exists() and path2.name.endswith(" (1).tar.gz")
    # tampered package
    with pytest.raises(ValueError):
        updater.download(asset, tmp_path / "bad", sha256="0" * 64)
    assert not list((tmp_path / "bad").iterdir())
    # a stale .part from a crashed download never blocks the next one
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / (asset.name + ".part")).write_bytes(b"old")
    (stale / (asset.name + ".abc123.part")).write_bytes(b"old")
    p = updater.download(asset, stale, sha256=digest)
    assert p.name == asset.name and hashlib.sha256(p.read_bytes()).hexdigest() == digest
    assert not [q for q in stale.glob("*.part") if q.stat().st_size != 3]   # ours is cleaned up
    # a failure mid-download leaves nothing behind either
    def boom(req, timeout):
        raise OSError("connection reset")
    monkeypatch_open = updater._open
    updater._open = boom
    try:
        with pytest.raises(OSError):
            updater.download(asset, tmp_path / "fail")
    finally:
        updater._open = monkeypatch_open
    assert not list((tmp_path / "fail").iterdir())
    # no checksum file published -> refuse
    state["with_sums"] = False
    rel = updater.fetch_latest(url + "/latest")
    with pytest.raises(ValueError):
        updater.expected_sha256(rel, updater.pick_asset(rel, "linux", "x86_64"))


# ------------------------------------------------------------ licenses
def test_license_texts_are_collected_for_the_bundle(tmp_path):
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import collect_licenses as licenses
    finally:
        sys.path.remove(str(ROOT / "packaging"))
    out = licenses.collect(tmp_path / "LICENSES")
    names = {p.name for p in out.iterdir()}
    assert {"LICENSE.txt", "NOTICE.txt", "AGPL-3.0.txt", "LGPL-3.0.txt", "GPL-3.0.txt"} <= names
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (out / "AGPL-3.0.txt").read_text()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in (out / "LGPL-3.0.txt").read_text()
    third = {p.name.split("-")[0].lower() for p in (out / "third-party").iterdir()}
    assert {"pymupdf", "pikepdf", "pyside6_essentials", "shiboken6", "certifi", "mupdf"} <= third
    assert list((out / "third-party").rglob("qpdf*"))
    mu = out / "third-party" / "MuPDF-thirdparty"
    for lib in ("freetype", "harfbuzz", "libjpeg", "openjpeg", "jbig2dec", "lcms2", "zlib", "fonts"):
        assert any((mu / lib).iterdir()), lib
    assert "SIL OPEN FONT LICENSE" in (mu / "fonts" / "urw" / "OFL.txt").read_text()
    assert (mu / "fonts" / "droid" / "NOTICE").exists()
    assert "LGPL" in next((out / "third-party").glob("PySide6*/LICENSE-INFO.txt")).read_text()
    qt = out / "third-party" / "Qt-thirdparty"
    attributions = (qt / "ATTRIBUTIONS.txt").read_text()
    for comp in ("PCRE2", "double-conversion", "LibPNG", "HarfBuzz", "Freetype"):
        assert comp.lower() in attributions.lower(), comp
    assert (qt / "license-texts" / "BSD-3-Clause.txt").exists()
    assert "Jay Berkenbilt" in (out / "third-party" / "qpdf-NOTICE.md").read_text()
    assert (out / "third-party" / "CPython-deps" / "OpenSSL-LICENSE.txt").exists()
    assert "CPython 3." in (out / "third-party" / "CPython" / "VERSION.txt").read_text()
    notice = (out / "NOTICE.txt").read_text()
    for holder in ("Artifex Software", "The Qt Company", "Leafweaving contributors", "Independent JPEG Group",
                   "FreeType Project", "(URW)++"):
        assert holder in notice, holder


def test_bundle_binary_allowlist_covers_known_and_flags_unknown(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import build as build_mod
    finally:
        sys.path.remove(str(ROOT / "packaging"))
    known = ["leafweaving", "_internal/libmupdf.so.28.6", "_internal/pymupdf/_mupdf.so", "_internal/libqpdf-781b.so.30",
             "_internal/libQt6Core.so.6", "_internal/PySide6/Qt/plugins/platforms/libqxcb.so",
             "_internal/libpython3.12.so.1.0", "_internal/lib-dynload/_ssl.cpython-312-x86_64-linux-gnu.so",
             "_internal/libssl.so.3", "_internal/libstdc++.so.6", "_internal/python312.dll", "_internal/VCRUNTIME140.dll",
             "_internal/shiboken6/Shiboken.abi3.so", "_internal/PySide6/QtCore.abi3.so", "_internal/libicudata.so.73"]
    for rel in known:
        assert any(build_mod.re.search(rx, rel.lower()) for _, rx in build_mod.KNOWN_BINARIES), rel
    for rel in ("_internal/libgtk-3.so.0", "_internal/libglib-2.0.so.0", "_internal/libgnutls.so.30", "_internal/libsystemd.so.0"):
        assert not any(build_mod.re.search(rx, rel.lower()) for _, rx in build_mod.KNOWN_BINARIES), rel
    root = tmp_path / "dist"
    (root / "_internal").mkdir(parents=True)
    (root / "_internal" / "libgtk-3.so.0").write_bytes(b"x")
    (root / "_internal" / "libmupdf.so.28.6").write_bytes(b"x")
    monkeypatch.setattr(build_mod, "ROOT", tmp_path)
    (tmp_path / "build").mkdir()
    monkeypatch.delenv("LEAFWEAVING_ALLOW_UNKNOWN_BINARIES", raising=False)
    with pytest.raises(SystemExit, match="libgtk-3"):
        build_mod._check_binaries_known(root)
    assert "UNKNOWN" in (tmp_path / "build" / "BINARIES.txt").read_text()


def test_linux_runtime_package_list_is_shared_by_readme_and_workflow():
    pkgs = [l.strip() for l in (ROOT / "packaging" / "linux-runtime-packages.txt").read_text().splitlines()
            if l.strip() and not l.startswith("#")]
    assert "libxcb-cursor0" in pkgs and "libssl3" in pkgs and "libffi8" in pkgs
    readme = (ROOT / "README.md").read_text()
    assert "sudo apt install " + " ".join(pkgs) in readme
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "linux-runtime-packages.txt" in wf and "ubuntu:22.04" in wf
    assert "pattern: leafweaving-*" in wf


def test_source_archives_cover_the_copyleft_components():
    sys.path.insert(0, str(ROOT / "packaging"))
    try:
        import fetch_sources
    finally:
        sys.path.remove(str(ROOT / "packaging"))
    pins = fetch_sources.pinned()
    assert pins["pymupdf"] in fetch_sources.MUPDF_FOR_PYMUPDF   # bump the MuPDF mapping with PyMuPDF
    assert {"pymupdf", "pikepdf", "pyside6-essentials", "certifi"} <= set(pins)
