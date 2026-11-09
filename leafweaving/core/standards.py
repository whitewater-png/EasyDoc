"""Saving to a specific PDF version or ISO standard (PDF/A, PDF/X).

Two engines are used:

* **Ghostscript** (if installed) performs a real conversion to PDF/A-1b/2b/3b
  or PDF/X-3, including colour conversion, font embedding and the output
  intent.  This is the recommended path.
* **Best-effort** (pikepdf only) is used when Ghostscript is missing.  It sets
  the PDF version, embeds an sRGB output intent, writes the required XMP
  identification and removes encryption, then reports anything it could not
  fix (e.g. non-embedded fonts).  Files produced this way should be verified
  with a validator such as veraPDF before being relied upon.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pikepdf
import pymupdf

from .document import PdfDocument

PDF_VERSIONS = ["1.4", "1.5", "1.6", "1.7", "2.0"]

# key -> (label, ghostscript flags, pdfaid part, conformance, pdf version, xmp kind)
STANDARDS: dict[str, dict] = {
    "none": {"label": "PDF (no standard)", "gs": None, "version": None},
    "pdfa-1b": {"label": "PDF/A-1b (ISO 19005-1)", "gs": ["-dPDFA=1"], "part": "1", "conf": "B", "version": "1.4", "kind": "a"},
    "pdfa-2b": {"label": "PDF/A-2b (ISO 19005-2)", "gs": ["-dPDFA=2"], "part": "2", "conf": "B", "version": "1.7", "kind": "a"},
    "pdfa-2u": {"label": "PDF/A-2u (ISO 19005-2, Unicode)", "gs": ["-dPDFA=2"], "part": "2", "conf": "U", "version": "1.7", "kind": "a"},
    "pdfa-3b": {"label": "PDF/A-3b (ISO 19005-3)", "gs": ["-dPDFA=3"], "part": "3", "conf": "B", "version": "1.7", "kind": "a"},
    "pdfx-3": {"label": "PDF/X-3:2003 (ISO 15930-6)", "gs": ["-dPDFX"], "version": "1.4", "kind": "x", "xver": "PDF/X-3:2003"},
    "pdfx-4": {"label": "PDF/X-4 (ISO 15930-7) *best effort only*", "gs": None, "version": "1.6", "kind": "x", "xver": "PDF/X-4"},
}


@dataclass
class SaveOptions:
    standard: str = "none"            # key of STANDARDS
    pdf_version: Optional[str] = None  # e.g. "1.7"; None keeps the current one
    linearize: bool = False           # "fast web view"
    compress: bool = True             # garbage collect + deflate
    prefer_ghostscript: bool = True
    # A Ghostscript with known security bugs is only used when the caller (the
    # UI, after asking the user) says the document is trusted.
    allow_outdated_ghostscript: bool = False
    title: Optional[str] = None
    author: Optional[str] = None


@dataclass
class SaveResult:
    path: str
    engine: str                      # "pymupdf" | "pikepdf" | "ghostscript" | "best-effort"
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- ghostscript
MIN_GS_VERSION = (9, 50)  # first release with the hardened -dSAFER and --permit-file-*
# Oldest release without publicly known security bugs reachable from a hostile
# PDF/PostScript (sandbox escapes and memory corruption in pdfwrite/pdfmark/
# JPEG 2000): CVE-2023-36664, CVE-2024-29510, CVE-2024-33871, CVE-2024-46951..56,
# CVE-2025-27830..37 (10.05.0), CVE-2025-59798..801 (10.06.0), CVE-2026-19547,
# CVE-2026-39919, CVE-2026-103226, CVE-2026-110133, CVE-2026-112922 (10.08.0).
# Raise this with every Ghostscript security release
# (https://www.ghostscript.com/releases/cve/index.html).  Linux distributions
# often backport the fixes to older version numbers; LEAFWEAVING_TRUST_GHOSTSCRIPT=1
# accepts such a Ghostscript.
GS_WITHOUT_KNOWN_BUGS = (10, 8, 0)


def find_ghostscript() -> Optional[str]:
    names = ["gs"]
    if sys.platform.startswith("win"):
        names = ["gswin64c", "gswin32c", "gs"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    if sys.platform.startswith("win"):
        for base in (r"C:\Program Files\gs", r"C:\Program Files (x86)\gs"):
            if os.path.isdir(base):
                # "gs10.05.1" must beat "gs9.56.1": compare version numbers, not strings
                for d in sorted(os.listdir(base), key=lambda n: _version_tuple(n) or (0,), reverse=True):
                    exe = os.path.join(base, d, "bin", "gswin64c.exe")
                    if os.path.exists(exe):
                        return exe
    return None


def _version_tuple(text: str) -> Optional[tuple[int, ...]]:
    import re

    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups(default="0")) if m else None


def ghostscript_version(gs: str) -> Optional[tuple[int, ...]]:
    try:
        out = subprocess.run([gs, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:  # noqa: BLE001
        return None
    return _version_tuple(out)


def safe_ghostscript(minimum: tuple[int, ...] = MIN_GS_VERSION) -> Optional[str]:
    """Ghostscript, only if it is at least ``minimum`` (it always runs under -dSAFER)."""
    gs = find_ghostscript()
    if gs is None:
        return None
    ver = ghostscript_version(gs)
    if ver is None or ver < minimum:
        return None
    return gs


def ghostscript_for_untrusted_input() -> Optional[str]:
    """Ghostscript for data we did not make ourselves (print jobs anyone on this
    computer can send; PDFs received from others): only a version without
    publicly known security bugs, unless the user vouches for a patched
    distribution build with LEAFWEAVING_TRUST_GHOSTSCRIPT=1."""
    if os.environ.get("LEAFWEAVING_TRUST_GHOSTSCRIPT") == "1":
        return safe_ghostscript()
    return safe_ghostscript(GS_WITHOUT_KNOWN_BUGS)


def ghostscript_status() -> tuple[Optional[str], Optional[tuple[int, ...]], str]:
    """(path, version, state) with state "ok" | "outdated" | "old" | "missing" for the UI."""
    gs = find_ghostscript()
    if gs is None:
        return None, None, "missing"
    ver = ghostscript_version(gs)
    if ver is None or ver < MIN_GS_VERSION:
        return gs, ver, "old"
    return gs, ver, "outdated" if ver < GS_WITHOUT_KNOWN_BUGS and not os.environ.get(
        "LEAFWEAVING_TRUST_GHOSTSCRIPT") == "1" else "ok"


def ps_string(data: str | bytes) -> str:
    """A PostScript string literal that is safe for any input.

    Text goes in as a UTF-16BE hex string with a BOM (what pdfmark expects for
    non-Latin titles); bytes (file names) as a literal string with every
    delimiter and non-printable byte escaped.  Either way nothing in ``data``
    can close the string and inject PostScript.
    """
    if isinstance(data, str):
        # errors="replace": a file-name title may hold undecodable bytes (surrogates)
        return "<FEFF" + data.encode("utf-16-be", "replace").hex().upper() + ">"
    out = []
    for b in data:
        if 0x20 <= b < 0x7F and b not in (0x28, 0x29, 0x5C):  # not ( ) \
            out.append(chr(b))
        else:
            out.append("\\%03o" % b)
    return "(" + "".join(out) + ")"


def srgb_icc_profile() -> bytes:
    """Return an sRGB ICC profile.  Qt can synthesise one; otherwise look for a
    system profile."""
    try:
        from PySide6.QtGui import QColorSpace  # type: ignore

        data = bytes(QColorSpace(QColorSpace.NamedColorSpace.SRgb).iccProfile())
        if data:
            return data
    except Exception:
        pass
    candidates = [
        "/usr/share/color/icc/colord/sRGB.icc",
        "/usr/share/color/icc/sRGB.icc",
        "/usr/share/color/icc/ghostscript/srgb.icc",
        "/System/Library/ColorSync/Profiles/sRGB Profile.icc",
        r"C:\Windows\System32\spool\drivers\color\sRGB Color Space Profile.icm",
    ]
    for c in candidates:
        if os.path.exists(c):
            return Path(c).read_bytes()
    raise RuntimeError("no sRGB ICC profile available")


def _pdfa_def_ps(icc_path: str, title: str, kind: str, xver: str = "") -> str:
    icc = ps_string(os.fsencode(icc_path.replace("\\", "/")))
    title = ps_string(title)
    if kind == "x":
        return f"""%!
% PDF/X definition file (generated by leafweaving)
/ICCProfile {icc} def
[ /GTS_PDFXVersion ({xver}) /Title {title} /Trapped /False /DOCINFO pdfmark
[/_objdef {{icc_PDFX}} /type /stream /OBJ pdfmark
[{{icc_PDFX}} <</N 3>> /PUT pdfmark
[{{icc_PDFX}} ICCProfile (r) file /PUT pdfmark
[/_objdef {{OutputIntent_PDFX}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFX}} <<
  /Type /OutputIntent /S /GTS_PDFX
  /OutputCondition (sRGB IEC61966-2.1)
  /OutputConditionIdentifier (sRGB IEC61966-2.1)
  /RegistryName (http://www.color.org)
  /DestOutputProfile {{icc_PDFX}}
>> /PUT pdfmark
[{{Catalog}} <</OutputIntents [ {{OutputIntent_PDFX}} ]>> /PUT pdfmark
"""
    return f"""%!
% PDF/A definition file (generated by leafweaving)
/ICCProfile {icc} def
[ /Title {title} /DOCINFO pdfmark
[/_objdef {{icc_PDFA}} /type /stream /OBJ pdfmark
[{{icc_PDFA}} <</N 3>> /PUT pdfmark
[{{icc_PDFA}} ICCProfile (r) file /PUT pdfmark
[/_objdef {{OutputIntent_PDFA}} /type /dict /OBJ pdfmark
[{{OutputIntent_PDFA}} <<
  /Type /OutputIntent /S /GTS_PDFA1
  /OutputCondition (sRGB IEC61966-2.1)
  /OutputConditionIdentifier (sRGB IEC61966-2.1)
  /RegistryName (http://www.color.org)
  /Info (sRGB IEC61966-2.1)
  /DestOutputProfile {{icc_PDFA}}
>> /PUT pdfmark
[{{Catalog}} <</OutputIntents [ {{OutputIntent_PDFA}} ]>> /PUT pdfmark
"""


def _run_ghostscript(gs: str, src: str, dst: str, spec: dict, title: str) -> list[str]:
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        icc_path = os.path.join(tmp, "srgb.icc")
        Path(icc_path).write_bytes(srgb_icc_profile())
        def_path = os.path.join(tmp, "def.ps")
        Path(def_path).write_text(_pdfa_def_ps(icc_path, title, spec["kind"], spec.get("xver", "")), "ascii")
        # -dSAFER: the input PDF is untrusted.  The definition file only needs to
        # read the ICC profile, which lives in our private temporary directory.
        cmd = [gs, "-dBATCH", "-dNOPAUSE", "-dQUIET", "-dSAFER",
               f"--permit-file-read={icc_path}", f"--permit-file-read={icc_path.replace(chr(92), '/')}",
               "-sDEVICE=pdfwrite", *spec["gs"],
               f"-dCompatibilityLevel={spec['version']}",
               "-dPDFACompatibilityPolicy=1",
               "-sColorConversionStrategy=RGB",
               "-dEmbedAllFonts=true", "-dSubsetFonts=true",
               f"-sOutputFile={dst}", def_path, src]
        if spec["kind"] == "x":
            cmd.insert(cmd.index("-sColorConversionStrategy=RGB"), "-dProcessColorModel=/DeviceRGB")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            raise RuntimeError(f"Ghostscript failed ({proc.returncode}): {proc.stderr.strip()[:800]}")
        for line in (proc.stderr or "").splitlines():
            if "warning" in line.lower() or "PDFA" in line or "PDFX" in line:
                warnings.append(line.strip())
    return warnings


# ---------------------------------------------------------------- best effort
def _xmp(spec: dict, title: str, author: str) -> bytes:
    kind = spec.get("kind")
    ident = ""
    if kind == "a":
        ident = (f'<rdf:Description rdf:about="" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">'
                 f'<pdfaid:part>{spec["part"]}</pdfaid:part><pdfaid:conformance>{spec["conf"]}</pdfaid:conformance>'
                 f'</rdf:Description>')
    elif kind == "x":
        ident = (f'<rdf:Description rdf:about="" xmlns:pdfxid="http://www.npes.org/pdfx/ns/id/" '
                 f'xmlns:pdfx="http://ns.adobe.com/pdfx/1.3/">'
                 f'<pdfxid:GTS_PDFXVersion>{spec["xver"]}</pdfxid:GTS_PDFXVersion>'
                 f'<pdfx:GTS_PDFXVersion>{spec["xver"]}</pdfx:GTS_PDFXVersion></rdf:Description>')

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    xml = ('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
           '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
           f'{ident}'
           '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{esc(title)}</rdf:li></rdf:Alt></dc:title>'
           f'<dc:creator><rdf:Seq><rdf:li>{esc(author)}</rdf:li></rdf:Seq></dc:creator>'
           '</rdf:Description>'
           '<rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/">'
           '<pdf:Producer>leafweaving</pdf:Producer></rdf:Description>'
           '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>')
    return xml.encode("utf-8")


def non_embedded_fonts(doc: pymupdf.Document) -> list[str]:
    missing: set[str] = set()
    for page in doc:
        for f in page.get_fonts(full=True):
            # (xref, ext, type, basefont, name, encoding, referencer)
            xref, ext, ftype, basefont = f[0], f[1], f[2], f[3]
            if ftype == "Type3":
                continue
            if ext == "n/a":
                missing.add(basefont)
    return sorted(missing)


def _best_effort(src: str, dst: str, spec: dict, opts: SaveOptions, title: str, author: str) -> list[str]:
    warnings: list[str] = []
    pdf = pikepdf.open(src)
    try:
        if pdf.is_encrypted:
            warnings.append("Encryption was removed (not allowed by PDF/A or PDF/X).")
        # Output intent
        icc = pdf.make_stream(srgb_icc_profile(), N=3, Alternate=pikepdf.Name.DeviceRGB)
        subtype = "/GTS_PDFA1" if spec.get("kind") == "a" else "/GTS_PDFX"
        intent = pikepdf.Dictionary(
            Type=pikepdf.Name.OutputIntent,
            S=pikepdf.Name(subtype),
            OutputCondition="sRGB IEC61966-2.1",
            OutputConditionIdentifier="sRGB IEC61966-2.1",
            RegistryName="http://www.color.org",
            Info="sRGB IEC61966-2.1",
            DestOutputProfile=icc,
        )
        pdf.Root.OutputIntents = pikepdf.Array([pdf.make_indirect(intent)])
        # Mark info required by PDF/X
        if spec.get("kind") == "x":
            pdf.docinfo["/GTS_PDFXVersion"] = spec["xver"]
            pdf.docinfo["/Trapped"] = pikepdf.Name("/False")
            pdf.docinfo["/Title"] = title
        # XMP
        pdf.Root.Metadata = pdf.make_stream(_xmp(spec, title, author), Type=pikepdf.Name.Metadata,
                                            Subtype=pikepdf.Name.XML)
        with pikepdf.open(src) as probe:  # noqa: F841 - keep for symmetry
            pass
        mu = pymupdf.open(src)
        missing = non_embedded_fonts(mu)
        mu.close()
        if missing:
            warnings.append("Fonts not embedded (standard requires embedding): " + ", ".join(missing))
        pdf.save(dst, force_version=spec["version"], linearize=opts.linearize,
                 object_stream_mode=pikepdf.ObjectStreamMode.disable,
                 compress_streams=True, fix_metadata_version=True, preserve_pdfa=False)
    finally:
        pdf.close()
    warnings.insert(0, "Ghostscript not found: file was prepared on a best-effort basis and is NOT "
                       "guaranteed to validate. Install Ghostscript for a real conversion.")
    return warnings


# --------------------------------------------------------------------- public
def save_document(pdf: PdfDocument, dst: str | Path, opts: Optional[SaveOptions] = None) -> SaveResult:
    opts = opts or SaveOptions()
    dst = str(dst)
    spec = STANDARDS.get(opts.standard, STANDARDS["none"])
    meta = pdf.doc.metadata or {}
    title = opts.title if opts.title is not None else (meta.get("title") or Path(dst).stem)
    author = opts.author if opts.author is not None else (meta.get("author") or "")
    if opts.title is not None or opts.author is not None:
        pdf.doc.set_metadata({**meta, "title": title, "author": author})

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work.pdf")
        if opts.compress:
            # Fonts added by text edits (notably the CJK fallback) are embedded in
            # full; subsetting keeps the file small.
            try:
                pdf.doc.subset_fonts()
            except Exception:  # pragma: no cover - best effort
                pass
        # Always drop unreferenced objects: otherwise content removed by
        # redaction (or deleted pages) would survive as orphans in the file.
        pdf.doc.save(work, garbage=3 if opts.compress else 1, deflate=opts.compress, clean=False)

        # Plain PDF -------------------------------------------------------
        if opts.standard == "none":
            if not opts.pdf_version and not opts.linearize:
                shutil.copyfile(work, dst)
                _finish(pdf, dst)
                return SaveResult(dst, "pymupdf")
            with pikepdf.open(work) as p:
                p.save(dst, force_version=opts.pdf_version or "", linearize=opts.linearize,
                       object_stream_mode=pikepdf.ObjectStreamMode.generate if opts.compress
                       else pikepdf.ObjectStreamMode.preserve)
            _finish(pdf, dst)
            return SaveResult(dst, "pikepdf")

        # Standards -------------------------------------------------------
        gs = None
        if opts.prefer_ghostscript:
            gs = safe_ghostscript() if opts.allow_outdated_ghostscript else ghostscript_for_untrusted_input()
        if gs and spec.get("gs"):
            tmp_out = os.path.join(tmp, "out.pdf")
            warnings = _run_ghostscript(gs, work, tmp_out, spec, title)
            ver = ghostscript_version(gs)
            if ver is not None and ver < GS_WITHOUT_KNOWN_BUGS:
                warnings.insert(0, "Ghostscript %s has publicly known security bugs; please update it (%s or newer)."
                                % (".".join(map(str, ver)), ".".join(map(str, GS_WITHOUT_KNOWN_BUGS))))
            if opts.linearize:
                with pikepdf.open(tmp_out) as p:
                    p.save(dst, linearize=True, preserve_pdfa=True)
            else:
                shutil.copyfile(tmp_out, dst)
            _finish(pdf, dst)
            return SaveResult(dst, "ghostscript", warnings)

        warnings = _best_effort(work, dst, spec, opts, title, author)
        if opts.prefer_ghostscript and find_ghostscript() and spec.get("gs"):
            warnings[0] = ("Ghostscript was not used because its version has known security bugs (%s or newer "
                           "is required): file was prepared on a best-effort basis and is NOT guaranteed to "
                           "validate." % ".".join(map(str, GS_WITHOUT_KNOWN_BUGS)))
        if spec.get("gs") is None and opts.standard != "none":
            warnings.append(f"{spec['label']}: no converter available, identification metadata only.")
        _finish(pdf, dst)
        return SaveResult(dst, "best-effort", warnings)


def _finish(pdf: PdfDocument, dst: str) -> None:
    pdf.path = dst
    pdf.dirty = False
    pdf.notify()


def verify_standard_claim(path: str | Path) -> Optional[str]:
    """Return the standard a file *claims* in its XMP (quick sanity check)."""
    try:
        with pikepdf.open(str(path)) as p:
            with p.open_metadata() as m:
                part = m.get("pdfaid:part")
                conf = m.get("pdfaid:conformance")
                if part:
                    return f"PDF/A-{part}{(conf or '').lower()}"
                x = m.get("pdfxid:GTS_PDFXVersion")
                if x:
                    return str(x)
    except Exception:
        return None
    return None
