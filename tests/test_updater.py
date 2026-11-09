import http.server
import json
import os
import threading

import pytest

from leafweaving.core import updater


def test_version_compare():
    assert updater.is_newer("v0.2.0", "0.1.0")
    assert updater.is_newer("1.0", "0.9.9")
    assert not updater.is_newer("0.1.0", "0.1.0")
    assert not updater.is_newer("v0.1", "0.1.0")
    assert not updater.is_newer("garbage", "0.1.0")


def _release():
    return updater.parse_release({
        "tag_name": "v0.3.0", "body": "notes", "html_url": "https://example/rel",
        "assets": [{"name": "leafweaving-0.3.0-windows-x86_64.zip", "browser_download_url": "u1", "size": 1},
                   {"name": "leafweaving-0.3.0-darwin-arm64.dmg", "browser_download_url": "u2", "size": 2},
                   {"name": "leafweaving-0.3.0-linux-x86_64.tar.gz", "browser_download_url": "u3", "size": 3}]})


def test_pick_asset_per_os():
    rel = _release()
    assert updater.pick_asset(rel, "darwin", "arm64").url == "u2"
    assert updater.pick_asset(rel, "windows", "x86_64").url == "u1"
    assert updater.pick_asset(rel, "linux", "x86_64").url == "u3"
    assert updater.pick_asset(rel, "darwin", "x86_64") is None


@pytest.fixture
def server(tmp_path):
    payload = b"x" * 200000

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/latest":
                body = json.dumps({"tag_name": "v9.9.9", "body": "n", "html_url": "h", "assets": [
                    {"name": "../evil/leafweaving-9.9.9-linux-x86_64.tar.gz",
                     "browser_download_url": f"http://127.0.0.1:{self.server.server_port}/pkg", "size": len(payload)}]}).encode()
            else:
                body = payload
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_check_and_download(server, tmp_path):
    rel = updater.check(current="0.1.0", url=server + "/latest")
    assert rel is not None and rel.version == "9.9.9"
    assert updater.check(current="9.9.9", url=server + "/latest") is None
    seen = []
    path = updater.download(rel.assets[0], tmp_path / "dl", lambda d, t: seen.append((d, t)))
    assert path.parent == tmp_path / "dl"                    # path traversal in the asset name is neutralised
    assert path.stat().st_size == 200000 and seen[-1][0] == 200000
    assert not list((tmp_path / "dl").glob("*.part"))


def test_check_failure_raises():
    with pytest.raises(Exception):
        updater.fetch_latest("http://127.0.0.1:9/none", timeout=1)
