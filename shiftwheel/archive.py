"""Zip files/folders, extract archives (ZIP, 7Z, TAR, GZ, RAR…), convert between them.
Extraction refuses paths that would escape the destination folder (zip-slip)."""
from __future__ import annotations

import gzip
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from .util import UserError, output_dir, unique_path

ARCHIVE_TARGETS = ["ZIP", "7Z", "TAR", "GZIP"]
EXT = {"ZIP": "zip", "7Z": "7z", "TAR": "tar", "GZIP": "tar.gz"}
KIND_TARGET = {"zip": "ZIP", "7z": "7Z", "tar": "TAR", "tgz": "GZIP"}


def kind(path: str | Path) -> str:
    n = str(path).lower()
    if n.endswith(".zip"):
        return "zip"
    if n.endswith(".7z"):
        return "7z"
    if n.endswith((".tar.gz", ".tgz")):
        return "tgz"
    if n.endswith((".tar", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
        return "tar"
    if n.endswith(".rar"):
        return "rar"
    if n.endswith(".gz"):
        return "gz"
    return ""


def _stem(path: Path) -> str:
    n = path.name
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz", ".tar", ".zip", ".7z", ".gz", ".rar"):
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


# (key, name, what it means) · ZIP deflate level / 7z LZMA2 preset per level
ARCHIVE_LEVELS = [
    ("store", "Store", "No compression · instant, for photos and videos that are already compressed"),
    ("fast", "Fast", "Quick, a little bigger"),
    ("normal", "Normal", "The usual balance of size and speed"),
    ("maximum", "Maximum", "Smallest archive, slower"),
]
_ZIP_LEVEL = {"store": 0, "fast": 1, "normal": 6, "maximum": 9}
_7Z_PRESET = {"store": 0, "fast": 1, "normal": 5, "maximum": 9}
# already compressed: deflate/LZMA can't shrink these much
PACKED = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".gif", ".mp4", ".mov", ".mkv", ".webm",
          ".avi", ".m4a", ".mp3", ".aac", ".ogg", ".opus", ".flac", ".zip", ".7z", ".rar", ".gz", ".xz", ".bz2",
          ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub", ".pdf", ".jar", ".apk"}


def packed_share(paths) -> float:
    """Share of the bytes that are already-compressed formats (0..1)."""
    total = packed = 0
    for full, _ in _walk(paths):
        n = full.stat().st_size
        total += n
        if full.suffix.lower() in PACKED:
            packed += n
    return packed / total if total else 0.0


def estimate_archive(paths, fmt: str = "ZIP", level: str = "normal", sample_bytes: int = 6_000_000) -> int:
    """Expected archive size: compress up to `sample_bytes` taken evenly from every file and
    scale each file's ratio to its size (plus per-entry overhead)."""
    import lzma
    import zlib
    items = list(_walk(paths))
    total = sum(f.stat().st_size for f, _ in items) or 1
    out = 0
    for full, arc in items:
        size = full.stat().st_size
        take = max(4096, int(sample_bytes * size / total)) if size else 0
        overhead = 120 + 2 * len(arc.encode("utf-8"))
        if level == "store" or not size:
            out += size + overhead
            continue
        with open(full, "rb") as f:
            chunk = f.read(min(size, take))
        if fmt.upper() == "7Z":
            c = len(lzma.compress(chunk, format=lzma.FORMAT_RAW,
                                  filters=[{"id": lzma.FILTER_LZMA2, "preset": _7Z_PRESET[level]}]))
        else:
            c = len(zlib.compress(chunk, _ZIP_LEVEL[level]))
        ratio = min(1.0, c / max(1, len(chunk)))
        out += int(size * ratio) + overhead
    return out


def zip_paths(paths: list, fmt: str = "ZIP", level: str = "normal") -> Path:
    paths = [Path(p) for p in paths]
    first = paths[0]
    name = first.name if first.is_dir() else first.stem
    if len(paths) > 1:
        name = first.parent.name or "Archive"
    out = unique_path(output_dir(first) / f"{name}.{EXT.get(fmt.upper(), fmt.lower())}")
    items = list(_walk(paths))
    if not items:
        raise UserError("Nothing to compress.")
    tmp = out.with_name(f".~{out.name}.part")
    try:
        if fmt.upper() == "7Z":
            import py7zr
            filters = [{"id": py7zr.FILTER_COPY}] if level == "store" else                 [{"id": py7zr.FILTER_LZMA2, "preset": _7Z_PRESET.get(level, 5)}]
            with py7zr.SevenZipFile(tmp, "w", filters=filters) as z:
                for full, arc in items:
                    z.write(full, arc)
        elif fmt.upper() in ("TAR", "GZIP"):
            with tarfile.open(tmp, "w:gz" if fmt.upper() == "GZIP" else "w") as t:
                for full, arc in items:
                    t.add(full, arc)
        else:
            method = zipfile.ZIP_STORED if level == "store" else zipfile.ZIP_DEFLATED
            with zipfile.ZipFile(tmp, "w", method, compresslevel=None if level == "store"
                                 else _ZIP_LEVEL.get(level, 6)) as z:
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
        elif k == "rar":
            _extract_rar(path, dest)
        elif k in ("tar", "tgz"):
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
        final = unique_path(output_dir(path) / f"{_stem(Path(path))}.{EXT.get(target.upper(), target.lower())}")
        shutil.move(str(out), final)
        return final


def _extract_rar(path: Path, dest: Path) -> None:
    """RAR (read-only): Windows 10+ ships libarchive's tar.exe, which reads RAR 4 and 5 and,
    by default, refuses absolute paths and '..' (no zip-slip)."""
    import subprocess
    import sys
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if sys.platform != "win32" or not tar.exists():
        sevenzip = shutil.which("7z")
        if not sevenzip:
            raise UserError("Opening RAR files needs Windows 10 or later (or 7-Zip installed).")
        cmd = [sevenzip, "x", "-y", f"-o{dest}", str(path)]
    else:
        cmd = [str(tar), "-xf", str(path), "-C", str(dest)]
    r = subprocess.run(cmd, capture_output=True, creationflags=0x08000000 if sys.platform == "win32" else 0)
    if r.returncode != 0:
        msg = (r.stderr or b"").decode("utf-8", "replace").lower()
        raise UserError("This RAR is password-protected." if "passw" in msg or "encrypt" in msg
                        else "The archive is damaged or uses a RAR feature that can't be read.")
    for f in dest.rglob("*"):                 # belt and braces
        _safe(dest, str(f.relative_to(dest)))


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
