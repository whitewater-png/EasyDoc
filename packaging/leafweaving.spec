# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for leafweaving.  Build with:  pyinstaller packaging/leafweaving.spec"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))
from leafweaving import __version__  # noqa: E402
import collect_licenses as _licenses  # noqa: E402  (packaging/collect_licenses.py)

# License texts that must travel with the bundle (AGPL/LGPL/MPL/Apache notices).
LICENSES_DIR = _licenses.collect(ROOT / "build" / "LICENSES")
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Only the PyMuPDF modules leafweaving uses.  ``pymupdf.layout`` (a 50 MB ONNX
# model) and ``pymupdf.table`` (numpy/pandas) are optional extras we never import.
hiddenimports = ["pymupdf", "pymupdf.mupdf", "pymupdf.utils", "pymupdf.extra", "pymupdf._extra",
                 "pymupdf._features", "pymupdf.features", "pymupdf.tgif", "pymupdf._tgif", "pymupdf._wxcolors",
                 "pymupdf.table", "pymupdf._table_headers", "pymupdf._table_refine", "pymupdf._table_spans",
                 "pymupdf._table_union", "pymupdf._apply_pages"] \
    + collect_submodules("pikepdf") + ["PySide6.QtPrintSupport"]

HEAVY_PREFIXES = ("pymupdf/layout", "pymupdf/mupdf-devel", "PySide6/Qt/translations",
                  "PySide6/translations", "pymupdf\\layout", "pymupdf\\mupdf-devel")


def _slim(entries):
    return [e for e in entries if not str(e[1]).replace("\\", "/").startswith(
        tuple(h.replace("\\", "/") for h in HEAVY_PREFIXES))]


binaries = _slim(collect_dynamic_libs("pymupdf") + collect_dynamic_libs("pikepdf"))
datas = _slim(collect_data_files("pymupdf") + collect_data_files("pikepdf"))
datas += [(str(f), str(Path("LICENSES") / f.relative_to(LICENSES_DIR).parent))
          for f in LICENSES_DIR.rglob("*") if f.is_file()]

icon = None
if IS_WIN and (ROOT / "packaging" / "leafweaving.ico").exists():
    icon = str(ROOT / "packaging" / "leafweaving.ico")
elif IS_MAC and (ROOT / "packaging" / "leafweaving.icns").exists():
    icon = str(ROOT / "packaging" / "leafweaving.icns")

a = Analysis(
    [str(ROOT / "leafweaving" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Qt modules the app does not use - keeps the bundle small.
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtRemoteObjects",
        "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtWebChannel",
        "PySide6.QtWebSockets", "PySide6.QtHttpServer", "PySide6.QtLocation", "PySide6.QtSpatialAudio",
        "tkinter", "unittest", "pydoc", "doctest", "pytest",
        # optional PyMuPDF extras and their heavy dependencies
        "pymupdf.layout",
        "onnxruntime", "numpy", "pandas", "PIL", "pillow", "lxml", "yaml", "scipy", "matplotlib", "cv2",
    ],
    noarchive=False,
)
# Drop anything the Analysis still pulled in under the heavy prefixes.
a.binaries = _slim(a.binaries)
a.datas = _slim(a.datas)

if sys.platform.startswith("linux"):
    # Do not bundle the distribution's own shared libraries (glib, GTK, gnutls,
    # OpenSSL, systemd, ...).  They are LGPL/Apache/... works of their own whose
    # notices and source we would otherwise have to ship; the user's system
    # provides them (see README, "Linux").  Only libraries that come from Python
    # packages (PySide6/Qt, PyMuPDF, pikepdf, the interpreter) stay in.
    SYSTEM_LIB_DIRS = ("/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/", "/usr/local/lib/")
    a.binaries = [b for b in a.binaries if not str(b[1]).startswith(SYSTEM_LIB_DIRS)]
    # The GTK platform theme plugin is what drags the whole GTK stack in.
    a.binaries = [b for b in a.binaries if "platformthemes/libqgtk3" not in str(b[0]).replace("\\", "/")]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="leafweaving",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no terminal window
    icon=icon,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="leafweaving",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="leafweaving.app",
        icon=icon,
        bundle_identifier="io.github.whitewater-png.leafweaving",
        info_plist={
            "CFBundleName": "Leafweaving",
            "CFBundleDisplayName": "Leafweaving",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHumanReadableCopyright": "Copyright (C) 2026 Leafweaving contributors (MIT). Includes MuPDF, "
                                        "Copyright (C) Artifex Software, Inc., and Qt, Copyright (C) The Qt Company "
                                        "Ltd.; this package is distributed under the GNU AGPL-3.0 - see LICENSES.",
            "NSHighResolutionCapable": True,
            # pikepdf only publishes macOS 15+ wheels for Apple Silicon.
            "LSMinimumSystemVersion": "15.0",
            "NSPrincipalClass": "NSApplication",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF document",
                "CFBundleTypeRole": "Editor",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["com.adobe.pdf"],
            }],
        },
    )
