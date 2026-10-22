"""Zip files/folders, extract archives (ZIP, 7Z, TAR, GZ…), convert between them.
Extraction refuses paths that would escape the destination folder (zip-slip)."""
from __future__ import annotations

import gzip
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from .util import UserError, output_dir, unique_path

ARCHIVE_TARGETS = ["ZIP", "7Z"]


def kind(path: str | Path) -> str:
    n = str(path).lower()
    if n.endswith(".zip"):
        return "zip"
    if n.endswith(".7z"):
        return "7z"
    if n.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return "tar"
    if n.endswith(".gz"):
        return "gz"
    return ""


def _stem(path: Path) -> str:
    n = path.name
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".tar", ".zip", ".7z", ".gz"):
        if n.lower().endswith(ext):
            return n[: -len(ext)]
    return path.stem


def _walk(paths):
    """(absolute file, name inside archive) for files and folders."""
    for p in map(Path, paths):
        if p.is_dir():
            for root, _, files in os.walk(p):
                for f in files:
                    full = Path(root) / f
                    yield full, str(Path(p.name) / full.relative_to(p))
        elif p.is_file():
            yield p, p.name


def zip_paths(paths: list, fmt: str = "ZIP") -> Path:
    paths = [Path(p) for p in paths]
    first = paths[0]
    name = first.name if first.is_dir() else first.stem
    if len(paths) > 1:
        name = first.parent.name or "Archive"
    out = unique_path(output_dir(first) / f"{name}.{fmt.lower()}")
    items = list(_walk(paths))
    if not items:
        raise UserError("Nothing to compress.")
    tmp = out.with_name(f".~{out.name}.part")
    try:
        if fmt.upper() == "7Z":
            import py7zr
            with py7zr.SevenZipFile(tmp, "w") as z:
                for full, arc in items:
                    z.write(full, arc)
        else:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                for full, arc in items:
                    z.write(full, arc)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out


def _safe(dest: Path, member: str) -> Path:
    target = (dest / member).resolve()
    if dest.resolve() not in target.parents and target != dest.resolve():
        raise UserError("This archive tries to write outside its folder; extraction was stopped.")
    return target


def extract(path) -> Path:
    path = Path(path)
    k = kind(path)
    dest = unique_path(output_dir(path) / _stem(path))
    dest.mkdir(parents=True)
    try:
        if k == "zip":
            with zipfile.ZipFile(path) as z:
                for m in z.infolist():
                    _safe(dest, m.filename)
                z.extractall(dest)
        elif k == "7z":
            import py7zr
            with py7zr.SevenZipFile(path) as z:
                for n in z.getnames():
                    _safe(dest, n)
                z.extractall(dest)
        elif k == "tar":
            with tarfile.open(path) as t:
                for m in t.getmembers():
                    _safe(dest, m.name)
                    if m.issym() or m.islnk():
                        _safe(dest, os.path.join(os.path.dirname(m.name), m.linkname))
                t.extractall(dest, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(dest)
        elif k == "gz":
            with gzip.open(path, "rb") as src, open(dest / _stem(path), "wb") as out:
                shutil.copyfileobj(src, out)
        else:
            raise UserError("Unknown archive type.")
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        if isinstance(e, UserError):
            raise
        raise UserError("The archive is damaged or password-protected.") from e
    except UserError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    # one top folder inside? lift it up so we don't get "x/x/…"
    inner = list(dest.iterdir())
    if len(inner) == 1 and inner[0].is_dir() and inner[0].name in (dest.name, _stem(path)):
        tmp = dest.with_name(dest.name + ".~lift")
        inner[0].rename(tmp)
        dest.rmdir()
        tmp.rename(dest)
    return dest


def convert_archive(path, target: str) -> Path:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        folder = extract_to(path, Path(td))
        out = zip_paths([p for p in folder.iterdir()], target) if any(folder.iterdir()) else None
        if out is None:
            raise UserError("The archive is empty.")
        final = unique_path(output_dir(path) / f"{_stem(Path(path))}.{target.lower()}")
        shutil.move(str(out), final)
        return final


def extract_to(path, base: Path) -> Path:
    import shiftwheel.util as U
    old = U.CONFIG.get("output")
    try:
        U.CONFIG["output"] = "next"
        copy = base / Path(path).name
        shutil.copy2(path, copy)
        return extract(copy)
    finally:
        U.CONFIG["output"] = old
