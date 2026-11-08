"""Update check against GitHub Releases, and download of the matching package."""
from __future__ import annotations

import json
import os
import platform
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .. import __version__

REPO = "whitewater-png/easydoc"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
TIMEOUT = 8


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page_url: str
    assets: list[Asset] = field(default_factory=list)


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2.3-beta' -> (1, 2, 3).  Unparseable -> ()."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if not a:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _os_tokens() -> tuple[str, tuple[str, ...]]:
    system = {"Darwin": "darwin", "Windows": "windows", "Linux": "linux"}.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64" if machine in ("x86_64", "amd64") else machine
    return system, (arch,)


def pick_asset(release: Release, system: Optional[str] = None, arch: Optional[str] = None) -> Optional[Asset]:
    """The package built for this OS / CPU (names look like easydoc-0.2.0-darwin-arm64.dmg)."""
    if system is None or arch is None:
        d_system, (d_arch,) = _os_tokens()
        system, arch = system or d_system, arch or d_arch
    for a in release.assets:
        n = a.name.lower()
        if system in n and arch in n and n.endswith((".dmg", ".zip", ".tar.gz")):
            return a
    return None


def _ssl_context() -> ssl.SSLContext:
    """TLS context with a CA bundle that also exists inside a frozen app.

    A PyInstaller build has no system OpenSSL cert directory, so the default
    context fails with CERTIFICATE_VERIFY_FAILED; certifi's bundle is shipped
    with the app instead (falls back to the system store when unavailable)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def fetch_latest(url: Optional[str] = None, timeout: float = TIMEOUT) -> Release:
    """Query the latest published release.  Raises on network / format errors."""
    url = url or os.environ.get("EASYDOC_UPDATE_URL") or API_URL
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"EasyDoc/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310 - fixed https endpoint
        data = json.loads(resp.read().decode("utf-8"))
    return parse_release(data)


def parse_release(data: dict) -> Release:
    tag = str(data.get("tag_name", ""))
    return Release(
        version=tag.lstrip("vV"), tag=tag, notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or RELEASES_URL),
        assets=[Asset(a["name"], a["browser_download_url"], int(a.get("size", 0))) for a in data.get("assets", [])
                if "name" in a and "browser_download_url" in a])


def check(current: str = __version__, url: Optional[str] = None) -> Optional[Release]:
    """Return the latest release if it is newer than ``current``, else None."""
    try:
        rel = fetch_latest(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:      # nothing published yet
            return None
        raise
    return rel if is_newer(rel.version, current) else None


def download(asset: Asset, dest_dir: str | Path, progress: Optional[Callable[[int, int], None]] = None,
             should_cancel: Optional[Callable[[], bool]] = None) -> Path:
    """Download ``asset`` into ``dest_dir`` (via a .part file); returns the final path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / Path(asset.name).name        # never trust path components from the network
    part = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(asset.url, headers={"User-Agent": f"EasyDoc/{__version__}"})
    done = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp, open(part, "wb") as fh:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or asset.size or 0)
        while True:
            if should_cancel and should_cancel():
                fh.close()
                part.unlink(missing_ok=True)
                raise InterruptedError("cancelled")
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    part.replace(target)
    return target
