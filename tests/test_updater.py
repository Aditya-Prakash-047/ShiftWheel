"""Updates: version maths, the release feed, verified downloads, and the hand-over scripts."""
from __future__ import annotations

import hashlib
import http.server
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath

import pytest

from shiftwheel import __version__, updater
from shiftwheel.util import UserError


# ---------------------------------------------------------------- a tiny release server
class Feed:
    def __init__(self, tmp: Path):
        self.files: dict[str, bytes] = {}
        self.release: dict = {}
        self.status = 200
        feed = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if feed.status != 200:
                    self.send_response(feed.status)
                    self.end_headers()
                    return
                if self.path == "/latest":
                    body = json.dumps(feed.release).encode()
                elif self.path.lstrip("/") in feed.files:
                    body = feed.files[self.path.lstrip("/")]
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def publish(self, version: str, files: dict[str, bytes], notes="- Faster\n- Share works", good_sha=True):
        self.files = files
        self.release = {"tag_name": f"v{version}", "body": notes, "html_url": f"{self.url}/page",
                        "draft": False, "prerelease": False,
                        "assets": [{"name": n, "browser_download_url": f"{self.url}/{n}", "size": len(b),
                                    "digest": "sha256:" + (hashlib.sha256(b).hexdigest() if good_sha else "0" * 64)}
                                   for n, b in files.items()]}


@pytest.fixture
def feed(tmp_path, monkeypatch):
    f = Feed(tmp_path)
    monkeypatch.setenv("SHIFTWHEEL_UPDATE_FEED", f.url + "/latest")
    yield f
    f.httpd.shutdown()


# ---------------------------------------------------------------- versions
def test_version_order():
    assert updater.is_newer("1.1.0", "1.0.0") and updater.is_newer("v1.10", "1.9.9")
    assert updater.is_newer("2", "1.99.99") and updater.is_newer("1.0.1", "1.0")
    assert not updater.is_newer("1.0.0", "1.0.0") and not updater.is_newer("1.0", "1.0.0")
    assert not updater.is_newer("0.9.9", "1.0.0") and not updater.is_newer("1.1.0-beta", "1.1.0")


def test_versions_agree_everywhere():
    """The app, the installer, the Windows file version and the Mac bundle say the same."""
    root = Path(__file__).resolve().parents[1]
    v = __version__
    assert f'#define AppVersion "{v}"' in (root / "installer/ShiftWheel.iss").read_text(encoding="utf-8")
    info = (root / "installer/version_info.txt").read_text(encoding="utf-8")
    assert f"'FileVersion', '{v}'" in info and f"filevers=({v.replace('.', ', ')}, 0)" in info
    spec = (root / "ShiftWheel.spec").read_text(encoding="utf-8")
    assert f'"CFBundleShortVersionString": "{v}"' in spec


# ---------------------------------------------------------------- check
def test_check_offers_a_newer_release(feed):
    feed.publish("9.0.0", {"ShiftWheel-Setup.exe": b"x" * 10})
    rel = updater.check()
    assert rel.version == "9.0.0" and rel.asset("ShiftWheel-Setup.exe").size == 10
    assert rel.asset("ShiftWheel-Setup.exe").sha256 == hashlib.sha256(b"x" * 10).hexdigest()
    assert updater.check(skip="9.0.0") is None                       # "Skip this version"


def test_check_says_up_to_date(feed):
    feed.publish(__version__, {})
    assert updater.check() is None


def test_check_explains_failures(feed):
    feed.status = 404
    with pytest.raises(UserError, match="No published release"):
        updater.check()
    feed.status = 403
    with pytest.raises(UserError, match="limiting"):
        updater.check()
    with pytest.raises(UserError, match="internet"):
        updater.check(feed="http://127.0.0.1:9/latest")


def test_check_ignores_prereleases(feed):
    feed.publish("9.0.0", {})
    feed.release["prerelease"] = True
    with pytest.raises(UserError):
        updater.check()


def test_daily_schedule():
    now = time.time()
    assert updater.due(0, now) and updater.due(now - 25 * 3600, now)
    assert not updater.due(now - 3600, now)


# ---------------------------------------------------------------- download
def test_download_is_verified(feed, tmp_path):
    data = b"new build " * 5000
    feed.publish("9.0.0", {"ShiftWheel.exe": data})
    seen = []
    out = updater.download(updater.check().asset("ShiftWheel.exe"), tmp_path / "dl", seen.append)
    assert out.read_bytes() == data and seen[-1] == 1.0
    assert not list((tmp_path / "dl").glob("*.part"))


def test_download_refuses_a_bad_checksum(feed, tmp_path):
    feed.publish("9.0.0", {"ShiftWheel.exe": b"tampered"}, good_sha=False)
    with pytest.raises(UserError, match="checksum"):
        updater.download(updater.check().asset("ShiftWheel.exe"), tmp_path / "dl")
    assert not any((tmp_path / "dl").iterdir())                      # nothing left to run


def test_asset_for_each_kind():
    assert updater.asset_name("installed") == "ShiftWheel-Setup.exe"
    assert updater.asset_name("portable") == "ShiftWheel.exe"
    assert updater.asset_name("mac-app").startswith("ShiftWheel-mac-")
    assert updater.asset_name("source") is None and updater.install_kind() == "source"


# ---------------------------------------------------------------- hand-over scripts
def test_installer_script(tmp_path):
    dl = tmp_path / "ShiftWheel-Setup.exe"
    dl.write_bytes(b"")
    script, cmd = updater.install_script("installed", dl, 4242, Path(r"C:\Apps\ShiftWheel\ShiftWheel.exe"))
    text = script.read_text(encoding="utf-8")
    assert "/VERYSILENT" in text and "/SUPPRESSMSGBOXES" in text and 'PID eq 4242' in text
    assert 'start "" "C:\\Apps\\ShiftWheel\\ShiftWheel.exe"' in text and cmd[0] == "cmd.exe"


def test_mac_script_is_valid_bash(tmp_path):
    dl = tmp_path / "ShiftWheel-mac-intel.dmg"
    dl.write_bytes(b"")
    script, cmd = updater.install_script("mac-app", dl, 4242, PurePosixPath("/Applications/ShiftWheel.app"))
    text = script.read_text(encoding="utf-8")
    assert "hdiutil attach" in text and 'ditto "$MNT/ShiftWheel.app" "/Applications/ShiftWheel.app"' in text
    bash = shutil.which("bash")
    if bash:
        assert subprocess.run([bash, "-n", str(script)]).returncode == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows hand-over")
def test_portable_update_swaps_the_exe_after_the_app_quits(tmp_path):
    """Really run the script: it waits for the 'app' to exit, swaps the exe, starts it."""
    sysdir = Path(r"C:\Windows\System32")
    target = tmp_path / "app" / "ShiftWheel.exe"
    target.parent.mkdir()
    shutil.copy(sysdir / "whoami.exe", target)                       # the "old version"
    dl = tmp_path / "dl" / "ShiftWheel.exe"
    dl.parent.mkdir()
    shutil.copy(sysdir / "hostname.exe", dl)                         # the "new version"
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    script, cmd = updater.install_script("portable", dl, app.pid, target)
    t = time.time()
    subprocess.run(cmd, timeout=60, creationflags=updater.CREATE_NO_WINDOW)
    assert time.time() - t >= 1.0                                    # it waited for the app to quit
    assert target.read_bytes() == (sysdir / "hostname.exe").read_bytes()
    assert not dl.exists() and not target.with_name("ShiftWheel.exe.old").exists()
    app.wait()
