"""The File ring: everyday file actions that work on anything (files, folders, mixed)."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from .util import UserError, sibling, unique_path


def reveal(path: str | Path) -> None:
    """Open the containing folder with the item selected."""
    p = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(f'explorer /select,"{p}"')     # one argument: explorer's own parser
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])


def duplicate(path: str | Path) -> Path:
    """'Report.pdf' → 'Report Copy.pdf' (folders too). Never overwrites."""
    p = Path(path)
    if p.is_dir():
        out = unique_path(p.with_name(p.name + " Copy"))
        shutil.copytree(p, out)
        return out
    out = sibling(p, "Copy")
    shutil.copy2(p, out)
    return out


def sha256(paths, progress=None) -> list[tuple[Path, str]]:
    """[(file, hex digest)] for every file (folders are skipped), streamed in 1 MB blocks."""
    files = [Path(p) for p in paths if Path(p).is_file()]
    if not files:
        raise UserError("Checksums are for files, not folders.")
    total = sum(f.stat().st_size for f in files) or 1
    done, out = 0, []
    for f in files:
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
                done += len(block)
                if progress:
                    progress(done / total)
        out.append((f, h.hexdigest()))
    return out


def checksum_text(results: list[tuple[Path, str]]) -> str:
    """One digest on its own, or 'digest  name' lines (the sha256sum format) for several."""
    if len(results) == 1:
        return results[0][1]
    return "\n".join(f"{d}  {f.name}" for f, d in results)


def move_to(paths, folder: str | Path) -> list[Path]:
    """Move files/folders into `folder` (names that are taken get (1), (2)…)."""
    from .util import unique_path
    folder = Path(folder)
    out = []
    for p in map(Path, paths):
        dst = unique_path(folder / p.name)
        if p.resolve() == dst.resolve() or folder.resolve() == p.parent.resolve():
            out.append(p)
            continue
        shutil.move(str(p), str(dst))
        out.append(dst)
    return out


def open_terminal(path: str | Path) -> None:
    """Windows Terminal if installed, else PowerShell, in the folder (or the file's folder)."""
    p = Path(path)
    folder = p if p.is_dir() else p.parent
    if sys.platform == "win32":
        wt = shutil.which("wt")
        if wt:
            subprocess.Popen([wt, "-d", str(folder)])
        else:
            subprocess.Popen(["powershell.exe", "-NoExit", "-Command", "Set-Location -LiteralPath '" + str(folder).replace("'", "''") + "'"],
                             creationflags=0x00000010)          # CREATE_NEW_CONSOLE
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Terminal", str(folder)])
    else:
        for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal"):
            if shutil.which(term):
                subprocess.Popen([term], cwd=str(folder))
                break
