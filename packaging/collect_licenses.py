"""Gather the license texts that must ship with the ready-to-run packages.

    python packaging/collect_licenses.py <dest>     # used by leafweaving.spec and build.py

Copies Leafweaving's own LICENSE, NOTICE.txt, the GNU license texts kept in
packaging/licenses/, and every license file that the installed third-party
distributions ship in their metadata (pikepdf also carries qpdf, OpenSSL,
libjpeg-turbo, zlib, ...).
"""
from __future__ import annotations

import importlib.metadata as md
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "packaging" / "licenses"
DISTS = ["pymupdf", "pikepdf", "PySide6-Essentials", "shiboken6", "certifi", "pyinstaller", "pyinstaller-hooks-contrib"]
_KEYS = ("licen", "copying", "notice", "authors")
_QT_NOTE = """
Leafweaving uses Qt for Python under the GNU LGPL-3.0 (see LGPL-3.0.txt and
GPL-3.0.txt in the parent LICENSES folder).  The Qt libraries are separate
shared libraries in this package and can be replaced by a compatible build.
Qt itself contains third-party code; its attributions for this Qt version are
listed at https://doc.qt.io/qt-6/licenses-used-in-qt.html .
Source code: see NOTICE.txt (Qt / PySide6 rows).
"""


def collect(dest: str | Path) -> Path:
    dest = Path(dest)
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", dest / "LICENSE.txt")
    for f in HERE.glob("*.txt"):
        shutil.copyfile(f, dest / f.name)
    third = dest / "third-party"
    # Libraries built into MuPDF (FreeType, HarfBuzz, libjpeg, OpenJPEG, ...):
    # the PyMuPDF wheel does not ship their notices, so they are kept here,
    # taken from the MuPDF source release that PyMuPDF is built from.
    shutil.copytree(HERE / "mupdf-thirdparty", third / "MuPDF-thirdparty")
    # Third-party code inside the Qt libraries (the PySide6 wheel ships no notices).
    shutil.copytree(HERE / "qt-thirdparty", third / "Qt-thirdparty")
    # Libraries linked into the bundled CPython interpreter.
    shutil.copytree(HERE / "cpython-deps", third / "CPython-deps")
    # qpdf's NOTICE (Apache-2.0 §4(d)); the pikepdf wheel carries only the license text.
    shutil.copyfile(HERE / "qpdf-NOTICE.md", third / "qpdf-NOTICE.md")
    for name in DISTS:
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        sub = third / f"{dist.metadata['Name']}-{dist.version}"
        sub.mkdir(parents=True, exist_ok=True)
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see project"
        home = dist.metadata.get("Home-page") or next(
            (u.split(",", 1)[1].strip() for u in dist.metadata.get_all("Project-URL") or [] if "," in u), "")
        # Some wheels (PySide6, shiboken6) carry no license file, only this field.
        (sub / "LICENSE-INFO.txt").write_text(
            f"{dist.metadata['Name']} {dist.version}\nLicense: {lic}\nProject: {home}\n"
            + (_QT_NOTE if dist.metadata["Name"].lower().startswith(("pyside6", "shiboken6")) else ""),
            encoding="utf-8")
        for f in dist.files or []:
            parts = [p.lower() for p in f.parts]
            if not parts[0].endswith(".dist-info") or not any(k in q for q in parts[1:] for k in _KEYS):
                continue
            src = Path(dist.locate_file(f))
            if src.is_file():
                out = sub.joinpath(*f.parts[1:])
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, out)
    py_license = Path(sys.base_prefix) / ("LICENSE.txt" if sys.platform.startswith("win") else
                                          f"lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt")
    if py_license.exists():
        (third / "CPython").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(py_license, third / "CPython" / "LICENSE.txt")
    (third / "CPython").mkdir(parents=True, exist_ok=True)
    (third / "CPython" / "VERSION.txt").write_text(
        f"CPython {sys.version.split()[0]} ({sys.platform})\nLicense: PSF License (LICENSE.txt)\n"
        f"Source: https://www.python.org/downloads/source/  (Python-{sys.version.split()[0]}.tar.xz)\n"
        "Linked libraries: see ../CPython-deps/README.txt\n", encoding="utf-8")
    return dest


if __name__ == "__main__":
    out = collect(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "LICENSES")
    print("\n".join(str(p.relative_to(out)) for p in sorted(out.rglob("*")) if p.is_file()))
