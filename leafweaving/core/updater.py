"""Update check against GitHub Releases, and download of the matching package.

Downloads are checked against the ``SHA256SUMS.txt`` published with every
release (this catches corruption and tampering on the way, not a compromised
release itself), and only https URLs on github.com are followed (plain http
is allowed for loopback addresses only, which the tests use).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .. import __version__

REPO = "whitewater-png/Leafweaving"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
TIMEOUT = 8
CHECKSUMS = "SHA256SUMS.txt"
TRUSTED_HOSTS = ("github.com", "api.github.com")
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


class UntrustedUrl(ValueError):
    pass


class _StrictRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to https on GitHub's hosts (loopback http for tests):
    urllib itself would happily follow an https -> http downgrade."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)
        host = (u.hostname or "").lower()
        ok = (host in _LOOPBACK and u.scheme in ("http", "https")) or (
            u.scheme == "https" and (host in TRUSTED_HOSTS or host.endswith(".githubusercontent.com")))
        if not ok:
            raise UntrustedUrl(f"refusing redirect to {newurl!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(req, timeout: float):
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl_context()), _StrictRedirects())
    return opener.open(req, timeout=timeout)


def check_url(url: str, hosts: tuple[str, ...] = TRUSTED_HOSTS) -> str:
    """Return ``url`` if it is https on one of ``hosts`` (or a loopback test server)."""
    u = urllib.parse.urlsplit(url or "")
    host = (u.hostname or "").lower()
    if host in _LOOPBACK and u.scheme in ("http", "https"):
        return url
    if u.scheme == "https" and host in hosts:
        return url
    raise UntrustedUrl(f"refusing untrusted URL: {url!r}")


def safe_page_url(url: str) -> str:
    """Release page to open in the browser: github.com only, else the default page."""
    try:
        return check_url(url, ("github.com",))
    except UntrustedUrl:
        return RELEASES_URL


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
    """The package built for this OS / CPU (names look like leafweaving-0.2.0-darwin-arm64.dmg)."""
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
    url = check_url(url or os.environ.get("LEAFWEAVING_UPDATE_URL") or API_URL)
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"Leafweaving/{__version__}"})
    with _open(req, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_release(data)


def parse_release(data: dict) -> Release:
    tag = str(data.get("tag_name", ""))
    return Release(
        version=tag.lstrip("vV"), tag=tag, notes=str(data.get("body") or ""),
        page_url=safe_page_url(str(data.get("html_url") or RELEASES_URL)),
        assets=[Asset(a["name"], a["browser_download_url"], int(a.get("size", 0))) for a in data.get("assets", [])
                if "name" in a and "browser_download_url" in a])


def checksum_asset(release: Release) -> Optional[Asset]:
    for a in release.assets:
        if a.name == CHECKSUMS:
            return a
    return None


def parse_checksums(text: str) -> dict[str, str]:
    """``sha256sum`` output -> {file name: hex digest}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S.*)$", line.strip())
        if m:
            out[Path(m.group(2).strip()).name] = m.group(1).lower()
    return out


def expected_sha256(release: Release, asset: Asset, timeout: float = TIMEOUT) -> str:
    """The published SHA-256 of ``asset``.  Raises when it is not published."""
    sums = checksum_asset(release)
    if sums is None:
        raise ValueError(f"{CHECKSUMS} is missing from the release; download it from the release page instead.")
    req = urllib.request.Request(check_url(sums.url), headers={"User-Agent": f"Leafweaving/{__version__}"})
    with _open(req, timeout) as resp:
        table = parse_checksums(resp.read(1 << 20).decode("utf-8", "replace"))
    digest = table.get(Path(asset.name).name)
    if not digest:
        raise ValueError(f"{asset.name} is not listed in {CHECKSUMS}.")
    return digest


def _free_name(target: Path) -> Path:
    """``target``, or ``name (1).ext`` etc. if a file of that name already exists."""
    if not target.exists():
        return target
    name = target.name
    stem, ext = (name[:-7], ".tar.gz") if name.endswith(".tar.gz") else (target.stem, target.suffix)
    i = 1
    while True:
        cand = target.with_name(f"{stem} ({i}){ext}")
        if not cand.exists():
            return cand
        i += 1


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
             should_cancel: Optional[Callable[[], bool]] = None, sha256: Optional[str] = None) -> Path:
    """Download ``asset`` into ``dest_dir`` (via a .part file); returns the final path.

    With ``sha256`` the file is kept only if its digest matches.  An existing
    file of the same name is never overwritten."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    import tempfile

    target = _free_name(dest_dir / Path(asset.name).name)   # never trust path components from the network
    req = urllib.request.Request(check_url(asset.url), headers={"User-Agent": f"Leafweaving/{__version__}"})
    h = hashlib.sha256()
    done = 0
    # A fresh, uniquely named temp file every time: a .part left behind by a
    # crash or a dropped connection can never block later downloads.
    fd, part_name = tempfile.mkstemp(dir=dest_dir, prefix=target.name + ".", suffix=".part")
    part = Path(part_name)
    fh = os.fdopen(fd, "wb")          # owned before the request: it must be closed before any unlink (Windows)
    try:
        with fh, _open(req, TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or asset.size or 0)
            while True:
                if should_cancel and should_cancel():
                    raise InterruptedError("cancelled")
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if sha256 is not None and h.hexdigest() != sha256.lower():
            raise ValueError(f"checksum mismatch for {asset.name}: the download was discarded.")
        target = _free_name(target)          # re-check right before the rename
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return target
