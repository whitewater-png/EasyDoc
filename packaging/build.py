#!/usr/bin/env python3
"""Build a ready-to-run leafweaving bundle for the current OS.

    python packaging/build.py            # -> release/leafweaving-<version>-<os>-<arch>.{zip,tar.gz,dmg}

Requires: pip install -e . pyinstaller
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from leafweaving import __version__  # noqa: E402

LICENSES = ROOT / "build" / "LICENSES"   # filled by leafweaving.spec (packaging/collect_licenses.py)

DIST = ROOT / "build" / "dist"
WORK = ROOT / "build" / "work"
RELEASE = ROOT / "release"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


REQUIRED = ("NOTICE.txt", "AGPL-3.0.txt", "LGPL-3.0.txt", "GPL-3.0.txt", "LICENSE.txt")

# Every native library in the bundle must belong to a component that NOTICE.txt
# covers.  An unknown one means a new dependency (or a system library leaking
# in) whose license we have not accounted for: the build fails.
import re  # noqa: E402

KNOWN_BINARIES = [
    # (component, regex on the path inside the bundle, "/"-separated, lower-case).
    # Specific components first: the CPython pattern for extension modules is
    # deliberately generic and must only catch what nothing else claims.
    ("Leafweaving", r"^(leafweaving(\.exe)?|leafweaving\.app/contents/macos/leafweaving)$"),
    ("PyInstaller bootloader/runtime", r"(^|/)(pyi_rth_.*|pyinstaller.*)"),
    ("PyMuPDF / MuPDF", r"(^|/)(pymupdf/.*|libmupdf.*|mupdf.*\.dll|_mupdf.*|_extra.*|_features.*|_tgif.*)"),
    ("pikepdf (qpdf, libjpeg-turbo, OpenSSL, zlib)", r"(^|/)(pikepdf/.*|pikepdf\.libs/.*|libqpdf.*|libjpeg.*|"
                                                     r"jpeg[0-9]*\.dll|qpdf[0-9]*\.dll)"),
    ("Qt / PySide6 / Shiboken6", r"(^|/)(pyside6/.*|shiboken6/.*|qt6.*|libqt6.*|qt[a-z0-9]+(\.framework/.*|\.dylib)?|"
                                 r"pyside6.*|libpyside6.*|shiboken6.*|libshiboken6.*|libicu.*|icu.*\.dll|"
                                 r"plugins/.*|libq[a-z0-9]+\.(so|dylib)|q[a-z0-9]+\.dll|libexec/.*)"),
    ("certifi", r"(^|/)certifi/.*"),
    ("CPython deps (OpenSSL, libffi, expat, bzip2, xz, sqlite, zlib, mpdecimal)",
     r"(^|/)(libssl.*|libcrypto.*|libffi.*|libexpat.*|libbz2.*|liblzma.*|libsqlite3.*|sqlite3\.dll|"
     r"libz\.|libmpdec.*|libintl.*|libtcl.*|libtk.*|tcl.*\.dll|tk.*\.dll|libcrypt.*|libuuid.*)"),
    ("Microsoft Visual C++ runtime / UCRT (Windows)",
     r"(^|/)(vcruntime.*|msvcp.*|concrt.*|ucrtbase.*|api-ms-win-.*|vcomp.*)\.dll$"),
    ("GCC runtime (Linux/Windows)", r"(^|/)(libgcc_s.*|libstdc\+\+.*|libgomp.*|libwinpthread.*|libatomic.*)"),
    ("CPython", r"(^|/)(python3[0-9]*(\.dll|\.so.*|\.dylib)?|libpython3.*|python\.exe|python3?$|"
                r"lib-dynload/.*|_[a-z0-9_]+(\.cpython-[^/]*)?\.(so|pyd|dylib)|[a-z]+\.pyd|"
                r"(math|array|select|binascii|zlib|pyexpat|unicodedata|resource|grp|termios|fcntl|mmap|"
                r"readline|syslog|xxlimited.*|cmath|audioop|nis|spwd|crypt|ossaudiodev)(\.cpython-[^/]*)?\.(so|pyd))$"),
]

NATIVE_SUFFIXES = (".so", ".dylib", ".dll", ".pyd", ".exe")


def _native_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        name = p.name.lower()
        is_native = name.endswith(NATIVE_SUFFIXES) or ".so." in name or ".dylib." in name
        if not is_native and sys.platform == "darwin" and p.parent.name in ("MacOS", "A") and "." not in name:
            is_native = True          # framework binaries and the launcher have no suffix on macOS
        if is_native:
            yield p


def _check_binaries_known(root: Path) -> None:
    """List every native library in the bundle (build/BINARIES.txt) and fail on
    any that no component in NOTICE.txt accounts for."""
    report, unknown = [], []
    for p in sorted(_native_files(root)):
        rel = str(p.relative_to(root)).replace("\\", "/").lower()
        comp = next((c for c, rx in KNOWN_BINARIES if re.search(rx, rel)), None)
        report.append(f"{comp or '!! UNKNOWN'}\t{p.relative_to(root)}")
        if comp is None:
            unknown.append(str(p.relative_to(root)))
    (ROOT / "build" / "BINARIES.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"{len(report)} native files listed in build/BINARIES.txt")
    if unknown:
        msg = "native libraries of unknown origin in the bundle (add their notices, or exclude them):\n  " + "\n  ".join(unknown)
        if os.environ.get("LEAFWEAVING_ALLOW_UNKNOWN_BINARIES") == "1":
            print("WARNING:", msg)
        else:
            raise SystemExit(msg)


def _check_licenses_inside(archive: Path) -> None:
    """Fail the build unless the finished archive itself carries the license texts."""
    if archive.suffix == ".dmg":
        names = [str(p.relative_to(WORK / "dmg")) for p in (WORK / "dmg").rglob("*")]
    elif archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
    else:
        with tarfile.open(archive) as tf:
            names = tf.getnames()
    found = {Path(n).name for n in names if "LICENSES" in Path(n).parts}
    missing = [r for r in REQUIRED if r not in found]
    if missing:
        raise SystemExit(f"{archive.name} is missing license files: {missing}")


def main() -> int:
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    RELEASE.mkdir(exist_ok=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(WORK), str(ROOT / "packaging" / "leafweaving.spec")])

    system = platform.system().lower()
    arch = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    stem = f"leafweaving-{__version__}-{system}-{arch}"

    if not (LICENSES / "NOTICE.txt").exists():
        raise SystemExit("license texts were not collected; the package must not ship without them")
    _check_binaries_known(DIST)

    if system == "darwin":
        app = DIST / "leafweaving.app"
        out = RELEASE / f"{stem}.dmg"
        if out.exists():
            out.unlink()
        # The disk image shows the app plus the license notices next to it.
        stage = WORK / "dmg"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        run(["ditto", str(app), str(stage / "leafweaving.app")])
        shutil.copytree(LICENSES, stage / "LICENSES")
        if shutil.which("hdiutil"):
            run(["hdiutil", "create", "-volname", "Leafweaving", "-srcfolder", str(stage), "-ov", "-format", "UDZO", str(out)])
        else:  # pragma: no cover
            out = RELEASE / f"{stem}.zip"
            run(["ditto", "-c", "-k", "--keepParent", str(stage), str(out)])
    elif system == "windows":
        out = RELEASE / f"{stem}.zip"
        shutil.copytree(LICENSES, DIST / "leafweaving" / "LICENSES", dirs_exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in (DIST / "leafweaving").rglob("*"):
                zf.write(p, p.relative_to(DIST))
    else:
        shutil.copytree(LICENSES, DIST / "leafweaving" / "LICENSES", dirs_exist_ok=True)
        out = RELEASE / f"{stem}.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            tf.add(DIST / "leafweaving", arcname="leafweaving")
    _check_licenses_inside(out)
    print(f"\nBuilt {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
