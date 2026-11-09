#!/usr/bin/env python3
"""Download the source code of the copyleft components bundled in the packages.

    python packaging/fetch_sources.py <dest>

The ready-to-run packages contain PyMuPDF/MuPDF (AGPL-3.0) and Qt / Qt for
Python (LGPL-3.0).  Distributing their object code means offering the
*corresponding source* "from the same place", so the release workflow attaches
these archives to every GitHub release next to the packages.

Versions come from packaging/constraints.txt; PyPI archives are checked
against the SHA-256 digests PyPI publishes.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONSTRAINTS = ROOT / "packaging" / "constraints.txt"

# PyMuPDF builds against one fixed MuPDF release (``version_mupdf`` in its setup.py).
MUPDF_FOR_PYMUPDF = {"2.1": "1.28.6"}
# SHA-256 of the archives that have no PyPI digest.  Qt's come from the .sha256
# files published next to the archives on download.qt.io; MuPDF's was taken from
# a download over TLS from mupdf.com.  Update these together with the versions.
SHA256 = {
    "mupdf-1.28.6-source.tar.gz": "dc85000640a45d90ca9b77b061f6ca67cce0c4d4fbecf8819647baf573eef101",
    "qt-everywhere-src-6.12.0.tar.xz": "98ff4f44bac6ec3e1e62ee2a4316ae0e3d15badb015d753cc0268a20db52f165",
    "pyside-setup-everywhere-src-6.12.0.tar.xz": "099c1a597cf33c1b000e11cf68a0b82d216fb802bf81726efc720394f10c7751",
}
PYPI_SDISTS = ["pymupdf", "pikepdf", "certifi"]   # PySide6 has no sdist: see pyside-setup below


def pinned() -> dict[str, str]:
    out = {}
    for line in CONSTRAINTS.read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)", line.strip())
        if m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def fetch(url: str, dest: Path, sha256: str | None = None) -> Path:
    print(f"  {url}", flush=True)
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "leafweaving-release"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:  # noqa: S310 - fixed hosts
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
            h.update(chunk)
    if sha256 and h.hexdigest() != sha256:
        dest.unlink()
        raise SystemExit(f"checksum mismatch for {url}")
    return dest


def sources(versions: dict[str, str]) -> list[tuple[str, str | None, str]]:
    """(url, sha256 or None, file name) for every archive to attach."""
    items = []
    for name in PYPI_SDISTS:
        ver = versions[name]
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=60) as r:  # noqa: S310
            info = json.load(r)
        sdist = next(u for u in info["urls"] if u["packagetype"] == "sdist")
        items.append((sdist["url"], sdist["digests"]["sha256"], sdist["filename"]))
    mupdf = MUPDF_FOR_PYMUPDF.get(versions["pymupdf"])
    if mupdf is None:
        raise SystemExit(f"update MUPDF_FOR_PYMUPDF for PyMuPDF {versions['pymupdf']}")
    qt = versions["pyside6-essentials"]
    major_minor = ".".join(qt.split(".")[:2])
    for url, name in [
        (f"https://mupdf.com/downloads/archive/mupdf-{mupdf}-source.tar.gz", f"mupdf-{mupdf}-source.tar.gz"),
        (f"https://download.qt.io/archive/qt/{major_minor}/{qt}/single/qt-everywhere-src-{qt}.tar.xz",
         f"qt-everywhere-src-{qt}.tar.xz"),
        (f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{qt}-src/"
         f"pyside-setup-everywhere-src-{qt}.tar.xz", f"pyside-setup-everywhere-src-{qt}.tar.xz"),
    ]:
        if name not in SHA256:
            raise SystemExit(f"no SHA-256 recorded for {name}: add it to SHA256 in {__file__}")
        items.append((url, SHA256[name], name))
    return items


def leafweaving_archive(dest: Path) -> Path:
    """Leafweaving's own source at the current commit, as a release asset of its
    own (GitHub's automatic "Source code" links are not release assets and are
    not covered by SHA256SUMS.txt)."""
    import subprocess
    from leafweaving import __version__  # noqa: PLC0415

    out = dest / f"leafweaving-{__version__}-src.tar.gz"
    subprocess.run(["git", "archive", "--format=tar.gz", f"--prefix=leafweaving-{__version__}/", "-o", str(out), "HEAD"],
                   check=True, cwd=ROOT)
    return out


def main() -> int:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "sources")
    dest.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    print(f"  {leafweaving_archive(dest)}")
    for url, digest, name in sources(pinned()):
        fetch(url, dest / name, digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
