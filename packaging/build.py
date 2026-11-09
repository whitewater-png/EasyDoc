#!/usr/bin/env python3
"""Build a ready-to-run leafwright bundle for the current OS.

    python packaging/build.py            # -> release/leafwright-<version>-<os>-<arch>.{zip,tar.gz,dmg}

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
from leafwright import __version__  # noqa: E402

DIST = ROOT / "build" / "dist"
WORK = ROOT / "build" / "work"
RELEASE = ROOT / "release"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    RELEASE.mkdir(exist_ok=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(WORK), str(ROOT / "packaging" / "leafwright.spec")])

    system = platform.system().lower()
    arch = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
    stem = f"leafwright-{__version__}-{system}-{arch}"

    if system == "darwin":
        app = DIST / "leafwright.app"
        out = RELEASE / f"{stem}.dmg"
        if out.exists():
            out.unlink()
        if shutil.which("hdiutil"):
            run(["hdiutil", "create", "-volname", "Leafwright", "-srcfolder", str(app), "-ov", "-format", "UDZO", str(out)])
        else:  # pragma: no cover
            out = RELEASE / f"{stem}.zip"
            run(["ditto", "-c", "-k", "--keepParent", str(app), str(out)])
    elif system == "windows":
        out = RELEASE / f"{stem}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in (DIST / "leafwright").rglob("*"):
                zf.write(p, p.relative_to(DIST))
    else:
        out = RELEASE / f"{stem}.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            tf.add(DIST / "leafwright", arcname="leafwright")
    print(f"\nBuilt {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
