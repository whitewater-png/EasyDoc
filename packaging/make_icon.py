"""Render the Leafweaving logo to packaging/leafweaving.{png,ico,icns} (run once, commit the results).

    python packaging/make_icon.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from leafweaving.ui.logo import draw_logo  # noqa: E402

app = QGuiApplication.instance() or QGuiApplication([])
out = ROOT / "packaging"
draw_logo(1024).save(str(out / "leafweaving.png"))

# Windows .ico (PNG-compressed entries; the largest edge is 256).
from PySide6.QtGui import QImage  # noqa: E402

draw_logo(256).save(str(out / "leafweaving.ico"), "ICO")

# macOS .icns through iconutil (only available on macOS).
if shutil.which("iconutil"):
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "leafweaving.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            draw_logo(base).save(str(iconset / f"icon_{base}x{base}.png"))
            draw_logo(base * 2).save(str(iconset / f"icon_{base}x{base}@2x.png"))
        subprocess.check_call(["iconutil", "-c", "icns", str(iconset), "-o", str(out / "leafweaving.icns")])
print("wrote", [p.name for p in out.glob("leafweaving.*") if p.suffix in (".png", ".ico", ".icns")])
