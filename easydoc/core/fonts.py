"""Font discovery and matching.

Any TrueType / OpenType font installed on the host (Windows, macOS, Linux) is
discovered by scanning the usual font directories.  Font family names are read
with PyMuPDF itself so no extra dependency is needed.  Results are cached on
disk so the scan only costs time once.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pymupdf

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}

# PyMuPDF built-in (Base-14 + CJK fallback) fonts: display name -> pymupdf name.
BUILTIN_FONTS: dict[str, str] = {
    "Helvetica": "helv",
    "Helvetica Bold": "hebo",
    "Helvetica Italic": "heit",
    "Helvetica Bold Italic": "hebi",
    "Times Roman": "tiro",
    "Times Bold": "tibo",
    "Times Italic": "tiit",
    "Times Bold Italic": "tibi",
    "Courier": "cour",
    "Courier Bold": "cobo",
    "Courier Italic": "coit",
    "Courier Bold Italic": "cobi",
    "CJK Fallback (Droid Sans Fallback)": "cjk",
}


@dataclass(frozen=True)
class FontInfo:
    name: str          # human readable, e.g. "Noto Sans CJK JP Bold"
    path: Optional[str]  # file path, or None for built-ins
    builtin: Optional[str]  # pymupdf built-in name, or None
    bold: bool = False
    italic: bool = False
    serif: bool = False
    mono: bool = False

    def load(self) -> pymupdf.Font:
        if self.builtin:
            return pymupdf.Font(self.builtin)
        return pymupdf.Font(fontfile=self.path)


def system_font_dirs() -> list[Path]:
    dirs: list[Path] = []
    home = Path.home()
    if sys.platform.startswith("win"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs += [windir / "Fonts", home / "AppData/Local/Microsoft/Windows/Fonts"]
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
                 home / ".fonts", home / ".local/share/fonts"]
        xdg = os.environ.get("XDG_DATA_DIRS", "")
        for d in xdg.split(os.pathsep):
            if d:
                dirs.append(Path(d) / "fonts")
    extra = os.environ.get("EASYDOC_FONT_DIRS", "")
    for d in extra.split(os.pathsep):
        if d:
            dirs.append(Path(d))
    seen, out = set(), []
    for d in dirs:
        if d.is_dir() and d.resolve() not in seen:
            seen.add(d.resolve())
            out.append(d)
    return out


def _cache_file() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "easydoc" / "fonts.json"


def _normalize(name: str) -> str:
    name = re.sub(r"^[A-Z]{6}\+", "", name)  # strip subset prefix ABCDEF+
    name = name.replace("-", " ").replace("_", " ").replace(",", " ")
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)  # CamelCase -> words
    return re.sub(r"\s+", " ", name).strip().lower()


_CJK_MARKERS = ("gothic", "mincho", "ipa", "hiragino", "meiryo", "yugo", "yumin", "kozuka", "kozgo",
                "kozmin", "msgothic", "mspgothic", "msmincho", "notosanscjk", "notoserifcjk", "sansjp",
                "serifjp", "sourcehan", "cjk", "simsun", "simhei", "songti", "heiti", "pingfang",
                "malgun", "batang", "gulim", "microsoftyahei", "mingliu", "kaiti", "fangsong", "takao",
                "vlgothic", "ricoh", "morisawa", "hgp", "hgs", "hgm", "idgothic", "tsukushi", "osaka")


def _is_cjk_font(lowered: str) -> bool:
    return any(m in lowered for m in _CJK_MARKERS)


def _base14_family(lowered: str) -> Optional[str]:
    """Family of a Base-14 look-alike ('Helvetica', 'Times' or 'Courier') or None."""
    if lowered.startswith(("nimbussans", "helvetica", "arial", "liberationsans")):
        return "Helvetica"
    if lowered.startswith(("nimbusroman", "timesnewroman", "times", "liberationserif")):
        return "Times"
    if lowered.startswith(("nimbusmono", "courier", "liberationmono")):
        return "Courier"
    return None


class FontRegistry:
    """Thread-safe registry of built-in and installed fonts."""

    def __init__(self, scan: bool = True, use_cache: bool = True):
        self._lock = threading.Lock()
        self._fonts: dict[str, FontInfo] = {}
        self._scanned = False
        self._use_cache = use_cache
        for name, code in BUILTIN_FONTS.items():
            lower = name.lower()
            self._fonts[name] = FontInfo(
                name=name, path=None, builtin=code,
                bold="bold" in lower, italic="italic" in lower,
                serif="times" in lower, mono="courier" in lower,
            )
        if scan:
            self.scan()

    # --------------------------------------------------------------- scanning
    def scan(self, force: bool = False) -> None:
        with self._lock:
            if self._scanned and not force:
                return
            cache: dict[str, dict] = {}
            cache_path = _cache_file()
            if self._use_cache and cache_path.exists() and not force:
                try:
                    cache = json.loads(cache_path.read_text("utf-8"))
                except Exception:
                    cache = {}
            new_cache: dict[str, dict] = {}
            for d in system_font_dirs():
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        if Path(f).suffix.lower() not in FONT_EXTENSIONS:
                            continue
                        p = os.path.join(root, f)
                        try:
                            mtime = os.path.getmtime(p)
                        except OSError:
                            continue
                        entry = cache.get(p)
                        if entry is None or entry.get("mtime") != mtime:
                            entry = self._probe(p, mtime)
                            if entry is None:
                                continue
                        new_cache[p] = entry
                        info = FontInfo(name=entry["name"], path=p, builtin=None,
                                        bold=bool(entry.get("bold")), italic=bool(entry.get("italic")),
                                        serif=bool(entry.get("serif")), mono=bool(entry.get("mono")))
                        self._fonts.setdefault(info.name, info)
            if self._use_cache:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps(new_cache), "utf-8")
                except OSError:
                    pass
            self._scanned = True

    @staticmethod
    def _probe(path: str, mtime: float) -> Optional[dict]:
        try:
            font = pymupdf.Font(fontfile=path)
        except Exception:
            return None
        name = font.name or Path(path).stem
        flags = font.flags or {}
        return {
            "name": name, "mtime": mtime,
            "bold": bool(flags.get("bold")), "italic": bool(flags.get("italic")),
            "serif": bool(flags.get("serif")), "mono": bool(flags.get("mono")),
        }

    # ---------------------------------------------------------------- queries
    def names(self) -> list[str]:
        with self._lock:
            builtins = [n for n, f in self._fonts.items() if f.builtin]
            system = sorted(n for n, f in self._fonts.items() if not f.builtin)
            return builtins + system

    def get(self, name: str) -> Optional[FontInfo]:
        with self._lock:
            return self._fonts.get(name)

    def add_file(self, path: str) -> Optional[FontInfo]:
        """Register an arbitrary font file chosen by the user."""
        entry = self._probe(path, os.path.getmtime(path))
        if entry is None:
            return None
        info = FontInfo(name=entry["name"], path=path, builtin=None,
                        bold=entry["bold"], italic=entry["italic"], serif=entry["serif"], mono=entry["mono"])
        with self._lock:
            self._fonts[info.name] = info
        return info

    def match_pdf_font(self, pdf_fontname: str, flags: int = 0) -> FontInfo:
        """Best effort mapping of a font name found in a PDF to an available font.

        ``flags`` is the PyMuPDF span flag bit field (1=superscript, 2=italic,
        4=serif, 8=mono, 16=bold).
        """
        italic = bool(flags & 2)
        serif = bool(flags & 4)
        mono = bool(flags & 8)
        bold = bool(flags & 16)
        target = _normalize(pdf_fontname)
        lowered = target.replace(" ", "")
        # Fonts easydoc itself writes with (and what MuPDF reports for the Base-14
        # substitutes) must map back to the very same font; otherwise every move
        # changes the typeface (MuPDF also flags NimbusSans as "serif").
        if "droid sans fallback" in target or _is_cjk_font(lowered):
            return self._fonts["CJK Fallback (Droid Sans Fallback)"]
        base = _base14_family(lowered)
        if base:
            bold = bold or "bold" in lowered
            italic = italic or "italic" in lowered or "oblique" in lowered
            key = {(False, False): base, (True, False): base + " Bold",
                   (False, True): base + " Italic", (True, True): base + " Bold Italic"}
            if base == "Times":
                key = {(False, False): "Times Roman", (True, False): "Times Bold",
                       (False, True): "Times Italic", (True, True): "Times Bold Italic"}
            return self._fonts[key[(bold, italic)]]
        if "bold" in lowered:
            bold = True
        if "italic" in lowered or "oblique" in lowered:
            italic = True
        with self._lock:
            candidates = list(self._fonts.values())
        # 1) exact normalized name match
        for f in candidates:
            if _normalize(f.name) == target:
                return f
        # 2) same family (first word) and matching style flags
        family = target.split(" ")[0] if target else ""
        best: Optional[FontInfo] = None
        best_score = -1
        for f in candidates:
            fam = _normalize(f.name)
            if family and fam.startswith(family):
                score = 1 + (f.bold == bold) + (f.italic == italic)
                if score > best_score:
                    best, best_score = f, score
        if best is not None and best_score >= 2:
            return best
        # 3) base-14 fallback by style
        if mono:
            key = {(False, False): "Courier", (True, False): "Courier Bold",
                   (False, True): "Courier Italic", (True, True): "Courier Bold Italic"}
        elif serif:
            key = {(False, False): "Times Roman", (True, False): "Times Bold",
                   (False, True): "Times Italic", (True, True): "Times Bold Italic"}
        else:
            key = {(False, False): "Helvetica", (True, False): "Helvetica Bold",
                   (False, True): "Helvetica Italic", (True, True): "Helvetica Bold Italic"}
        return self._fonts[key[(bold, italic)]]


_default_registry: Optional[FontRegistry] = None
_default_lock = threading.Lock()


def default_registry(scan: bool = True) -> FontRegistry:
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = FontRegistry(scan=scan)
        return _default_registry
