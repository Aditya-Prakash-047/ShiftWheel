"""Updates from GitHub Releases: check, download, verify, install, restart.

* Check: the latest release from the GitHub API (at most once a day in the background, or when
  asked). Pre-releases and drafts are ignored; "Skip this version" is remembered.
* Download: the asset that fits this copy (installer for an installed copy, the portable .exe
  for a portable one, the right .dmg on a Mac) into a temp folder, with progress.
* Verify: the size, and the SHA-256 GitHub publishes for every release asset. A file that
  doesn't match is deleted and never run.
* Install: a small detached script waits for ShiftWheel to quit, then runs the installer
  silently (Windows), swaps the portable .exe, or replaces the .app (macOS), and starts the
  new version. Settings, themes and sounds are kept: they live outside the program folder.

SHIFTWHEEL_UPDATE_FEED overrides the release URL (tests, or a mirror)."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__
from .util import UserError

# the source repository is private; builds and release notes are published to a public one
REPO = "Aditya-Prakash-047/ShiftWheel-releases"
FEED = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
CHECK_EVERY = 24 * 3600          # automatic checks: at most once a day
CREATE_NO_WINDOW = 0x08000000


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0
    sha256: str = ""


@dataclass
class Release:
    version: str
    notes: str = ""
    page: str = RELEASES_PAGE
    assets: list[Asset] = field(default_factory=list)

    def asset(self, name: str) -> Asset | None:
        return next((a for a in self.assets if a.name == name), None)


# ---------------------------------------------------------------- versions
def parse_version(v: str) -> tuple[int, ...]:
    """'v1.10.2' → (1, 10, 2); anything after the numbers (-beta…) is ignored."""
    nums = re.findall(r"\d+", v.split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


# ---------------------------------------------------------------- what this copy is
def install_kind() -> str:
    """'installed' (Windows, via the installer), 'portable' (Windows single .exe), 'mac-app',
    or 'source' (run from Python: updates mean `git pull`, so we only point to the page)."""
    if not getattr(sys, "frozen", False):
        return "source"
    exe = Path(sys.executable)
    if sys.platform == "darwin":
        return "mac-app"
    if sys.platform == "win32":
        programs = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "ShiftWheel"
        if (exe.parent / "unins000.exe").exists() or exe.parent == programs:
            return "installed"
        return "portable"
    return "source"


def asset_name(kind: str | None = None) -> str | None:
    kind = kind or install_kind()
    if kind == "installed":
        return "ShiftWheel-Setup.exe"
    if kind == "portable":
        return "ShiftWheel.exe"
    if kind == "mac-app":
        arm = platform.machine().lower() in ("arm64", "aarch64")
        return "ShiftWheel-mac-apple-silicon.dmg" if arm else "ShiftWheel-mac-intel.dmg"
    return None


# ---------------------------------------------------------------- check
def _get(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": f"ShiftWheel/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_latest(feed: str | None = None) -> Release:
    """The latest published release. Raises UserError with a readable reason."""
    feed = feed or os.environ.get("SHIFTWHEEL_UPDATE_FEED") or FEED
    try:
        with _get(feed) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UserError("No published release found yet.") from e
        if e.code in (403, 429):
            raise UserError("GitHub is limiting requests right now. Try again in an hour.") from e
        raise UserError(f"The update server answered {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UserError("Couldn't reach the update server. Check your internet connection.") from e
    except ValueError as e:
        raise UserError("The update server sent something unexpected.") from e
    if data.get("draft") or data.get("prerelease"):
        raise UserError("No stable release found.")
    assets = []
    for a in data.get("assets") or []:
        digest = str(a.get("digest") or "")
        assets.append(Asset(a.get("name", ""), a.get("browser_download_url", ""), int(a.get("size") or 0),
                            digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""))
    return Release(version=str(data.get("tag_name") or data.get("name") or "0").lstrip("vV"),
                   notes=str(data.get("body") or "").strip(), page=data.get("html_url") or RELEASES_PAGE,
                   assets=assets)


def check(feed: str | None = None, skip: str = "") -> Release | None:
    """The release to offer, or None when this copy is up to date (or that version was skipped)."""
    rel = fetch_latest(feed)
    if not is_newer(rel.version) or (skip and rel.version == skip):
        return None
    return rel


def due(last_check: float, now: float | None = None) -> bool:
    return (now or time.time()) - float(last_check or 0) >= CHECK_EVERY


# ---------------------------------------------------------------- download + verify
def download(asset: Asset, folder: Path | None = None,
             progress: Callable[[float], None] | None = None) -> Path:
    """Download to a temp folder and check size and SHA-256. Returns the verified file."""
    folder = Path(folder or tempfile.mkdtemp(prefix="ShiftWheel-update-"))
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / asset.name
    part = out.with_name(out.name + ".part")
    h = hashlib.sha256()
    got = 0
    try:
        with _get(asset.url, timeout=30) as r, open(part, "wb") as f:
            total = asset.size or int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress and total:
                    progress(min(1.0, got / total))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        part.unlink(missing_ok=True)
        raise UserError("The download stopped. Check your connection and try again.") from e
    if asset.size and got != asset.size:
        part.unlink(missing_ok=True)
        raise UserError("The download was incomplete. Try again.")
    if asset.sha256 and h.hexdigest() != asset.sha256:
        part.unlink(missing_ok=True)
        raise UserError("The downloaded file didn't match its published checksum, so it wasn't installed.")
    os.replace(part, out)
    return out


# ---------------------------------------------------------------- install
def install_script(kind: str, downloaded: Path, pid: int, target: Path) -> tuple[Path, list[str]]:
    """Write the script that finishes the update after ShiftWheel quits; returns (script, command).
    `target`: the running program (exe, or the .app bundle on a Mac)."""
    folder = downloaded.parent
    if kind in ("installed", "portable"):
        lines = ["@echo off", "setlocal",
                 # wait (up to a minute) for ShiftWheel to quit; Windows' own tools by full path
                 # (a Unix 'find' earlier on PATH would break the wait)
                 r'set "SYS=%SystemRoot%\System32"',
                 "for /l %%i in (1,1,120) do (",
                 rf'  "%SYS%\tasklist.exe" /fi "PID eq {pid}" /nh | "%SYS%\findstr.exe" /c:" {pid} " >nul || goto :go',
                 r'  "%SYS%\ping.exe" -n 2 127.0.0.1 >nul',
                 ")", ":go"]
        if kind == "installed":
            lines += [f'"{downloaded}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS '
                      f'/LOG="{folder / "install.log"}"']
        else:
            lines += [f'move /y "{target}" "{target}.old" >nul',
                      f'move /y "{downloaded}" "{target}" >nul || move /y "{target}.old" "{target}" >nul']
        lines += [f'start "" "{target}"', f'del "{target}.old" 2>nul', "endlocal"]
        script = folder / "finish-update.cmd"
        script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        return script, ["cmd.exe", "/c", str(script)]
    if kind == "mac-app":
        lines = ["#!/bin/bash", "set -u",
                 f"for i in $(seq 120); do kill -0 {pid} 2>/dev/null || break; sleep 0.5; done",
                 'MNT="$(mktemp -d)"',
                 f'hdiutil attach "{downloaded}" -mountpoint "$MNT" -nobrowse -quiet || exit 1',
                 f'rm -rf "{target}.old"; mv "{target}" "{target}.old"',
                 f'ditto "$MNT/ShiftWheel.app" "{target}" || mv "{target}.old" "{target}"',
                 'hdiutil detach "$MNT" -quiet',
                 f'xattr -dr com.apple.quarantine "{target}" 2>/dev/null',
                 f'rm -rf "{target}.old"', f'open "{target}"']
        script = folder / "finish-update.sh"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)
        return script, ["/bin/bash", str(script)]
    raise UserError("This copy runs from source: update it with git pull.")


def current_target(kind: str) -> Path:
    exe = Path(sys.executable)
    if kind == "mac-app":
        for p in exe.parents:                 # …/ShiftWheel.app/Contents/MacOS/ShiftWheel
            if p.suffix == ".app":
                return p
    return exe


def launch_install(downloaded: Path, kind: str | None = None) -> None:
    """Start the finishing script, detached. The caller then quits the app."""
    kind = kind or install_kind()
    script, cmd = install_script(kind, downloaded, os.getpid(), current_target(kind))
    if sys.platform == "win32":
        flags = CREATE_NO_WINDOW | 0x00000008 | 0x00000200      # no window, detached, new group
        subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=str(script.parent))
    else:
        subprocess.Popen(cmd, start_new_session=True, close_fds=True, cwd=str(script.parent))
