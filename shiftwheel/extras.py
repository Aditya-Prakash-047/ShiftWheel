"""Engines for the tools ShiftWheel 1.0 didn't have: video crop / split / redact,
audio channels / bleep / visualizer / silence trim, image collage and QR codes, PDF page
organising, metadata editing. The windows live in tools2.py."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from . import media as M
from .convert import open_image, open_pdf
from .util import UserError, output_dir, sibling, unique_path

Progress = M.Progress


def _even(v: float) -> int:
    return max(2, int(v) // 2 * 2)


# ---------------------------------------------------------------- video
def crop_video(src, x: int, y: int, w: int, h: int, progress: Progress = None) -> Path:
    """Reframe a video; the audio is kept as it is."""
    info = M.probe(src)
    if not info.has_video:
        raise UserError("This needs a video.")
    x, y = max(0, int(x)) // 2 * 2, max(0, int(y)) // 2 * 2      # positions may be 0; sizes stay ≥ 2
    w, h = _even(w), _even(h)
    w, h = min(w, _even(info.width - x)), min(h, _even(info.height - y))
    if w < 16 or h < 16:
        raise UserError("The crop is too small.")
    out = sibling(src, "Cropped", ".mp4")
    M.run(["-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-vf", f"crop={w}:{h}:{x}:{y}",
           *M._video_codec_args("MP4", crf=19), "-c:a", "copy", str(out)], info.duration, progress, out)
    return out


def split_points(duration: float, parts: int | None = None, every: float | None = None,
                 points: list[float] | None = None) -> list[tuple[float, float]]:
    """[(start, end)] for equal parts, fixed-length pieces, or custom cut points."""
    if points:
        cuts = sorted({round(p, 3) for p in points if 0.05 < p < duration - 0.05})
    elif every:
        if every <= 0.2:
            raise UserError("Pieces must be longer than 0.2 s.")
        cuts = [every * k for k in range(1, math.ceil(duration / every)) if every * k < duration - 0.05]
    else:
        n = max(2, int(parts or 2))
        cuts = [duration * k / n for k in range(1, n)]
    edges = [0.0, *cuts, duration]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b - a > 0.05]


def split_video(src, ranges: list[tuple[float, float]], progress: Progress = None) -> list[Path]:
    """Every piece re-encoded (frame-accurate) into one '<name> parts' folder."""
    info = M.probe(src)
    src = Path(src)
    folder = unique_path(output_dir(src) / f"{src.stem} parts")
    folder.mkdir(parents=True)
    ext = ".mp4" if info.has_video else src.suffix.lower()
    outs = []
    total = sum(b - a for a, b in ranges) or 1
    done = 0.0
    for k, (a, b) in enumerate(ranges, 1):
        out = folder / f"{src.stem} part {k}{ext}"
        enc = (["-map", "0:v:0", "-map", "0:a?", *M._video_codec_args("MP4", crf=18), "-c:a", "aac", "-b:a", "192k"]
               if info.has_video else ["-vn"])
        sub = (lambda f, d=done, n=b - a: progress((d + f * n) / total)) if progress else None
        M.run(["-ss", f"{a:.3f}", "-i", str(src), "-t", f"{b - a:.3f}", *enc, str(out)], b - a, sub, out)
        outs.append(out)
        done += b - a
    return outs


@dataclass
class Box:
    """A redaction rectangle in video pixels, active from start to end (seconds)."""
    x: int
    y: int
    w: int
    h: int
    start: float = 0.0
    end: float = 1e9
    blur: bool = True


def redact_video(src, boxes: list[Box], progress: Progress = None) -> Path:
    """Cover areas with blur or solid black, each for its own time range."""
    info = M.probe(src)
    if not boxes:
        raise UserError("Draw at least one area to cover.")
    chain, last = [], "0:v"
    for k, b in enumerate(boxes):
        x, y = max(0, int(b.x)), max(0, int(b.y))
        w, h = max(4, min(int(b.w), info.width - x)), max(4, min(int(b.h), info.height - y))
        when = f"between(t,{b.start:.3f},{min(b.end, info.duration + 1):.3f})"
        if b.blur:
            r = max(4, min(w, h) // 6)
            chain.append(f"[{last}]split[b{k}][o{k}];[o{k}]crop={w}:{h}:{x}:{y},boxblur={r}:3[bl{k}];"
                         f"[b{k}][bl{k}]overlay={x}:{y}:enable='{when}'[v{k}]")
        else:
            chain.append(f"[{last}]drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill:enable='{when}'[v{k}]")
        last = f"v{k}"
    out = sibling(src, "Redacted", ".mp4")
    M.run(["-i", str(src), "-filter_complex", ";".join(chain), "-map", f"[{last}]", "-map", "0:a?",
           *M._video_codec_args("MP4", crf=19), "-c:a", "copy", str(out)], info.duration, progress, out)
    return out


# ---------------------------------------------------------------- audio
CHANNEL_MODES = [("mono", "Mono (both sides mixed)"), ("stereo", "Stereo"), ("left", "Left channel only"),
                 ("right", "Right channel only"), ("swap", "Swap left and right")]


def _audio_out(src, label: str) -> tuple[Path, list[str]]:
    p = Path(src)
    info = M.probe(src)
    if info.has_video:
        return sibling(src, label, ".mp4"), ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    t = {".mp3": "MP3", ".m4a": "M4A", ".aac": "M4A", ".ogg": "OGG", ".flac": "FLAC", ".opus": "OPUS",
         ".wav": "WAV"}.get(p.suffix.lower(), "MP3")
    return sibling(src, label, "." + t.lower()), list(M.AUDIO_CODEC[t])


def channels(src, mode: str = "mono", left: float = 1.0, right: float = 1.0, progress: Progress = None) -> Path:
    info = M.probe(src)
    if not info.has_audio:
        raise UserError("This file has no sound.")
    pan = {"mono": f"pan=mono|c0={0.5 * left:.3f}*c0+{0.5 * right:.3f}*c1",     # one gain per term
           "stereo": f"pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1",
           "left": f"pan=stereo|c0={left:.3f}*c0|c1={left:.3f}*c0",
           "right": f"pan=stereo|c0={right:.3f}*c1|c1={right:.3f}*c1",
           "swap": f"pan=stereo|c0={left:.3f}*c1|c1={right:.3f}*c0"}[mode]
    out, enc = _audio_out(src, {"mono": "Mono", "stereo": "Stereo", "left": "Left", "right": "Right",
                                "swap": "Swapped"}[mode])
    M.run(["-i", str(src), "-map", "0:v?", "-map", "0:a:0", "-af", pan, *enc, str(out)], info.duration, progress, out)
    return out


def bleep(src, ranges: list[tuple[float, float]], freq: int = 1000, progress: Progress = None) -> Path:
    """Replace each range with a bleep tone (the original sound is silenced there)."""
    info = M.probe(src)
    if not info.has_audio:
        raise UserError("This file has no sound.")
    ranges = [(max(0.0, a), min(info.duration, b)) for a, b in ranges if b - a > 0.02]
    if not ranges:
        raise UserError("Mark at least one part to bleep.")
    on = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in ranges)
    graph = (f"[0:a:0]volume=0:enable='{on}'[quiet];"
             f"sine=frequency={freq}:sample_rate=48000:duration={info.duration:.3f},volume=0.35,"
             f"volume=0:enable='not({on})'[tone];[quiet][tone]amix=inputs=2:normalize=0:duration=first[a]")
    out, enc = _audio_out(src, "Bleeped")
    M.run(["-i", str(src), "-filter_complex", graph, "-map", "0:v?", "-map", "[a]", *enc, str(out)],
          info.duration, progress, out)
    return out


def trim_silence(src, threshold_db: int = -45, progress: Progress = None) -> Path:
    """Remove silence from the beginning and the end only (never from the middle)."""
    info = M.probe(src)
    f = (f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_silence=0.1,areverse,"
         f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_silence=0.1,areverse")
    out, enc = _audio_out(src, "Trimmed")
    if info.has_video:
        raise UserError("Silence trimming is for audio files.")
    M.run(["-i", str(src), "-vn", "-af", f, *enc, str(out)], info.duration, progress, out)
    return out


VISUAL_SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}


def visualizer(src, layout: str = "landscape", style: str = "wave", color: str = "#ff5200",
               background: str = "#101114", image: str | None = None, progress: Progress = None) -> Path:
    """An MP4 of the audio with an animated waveform (or spectrum bars), or a still image."""
    info = M.probe(src)
    if not info.has_audio:
        raise UserError("This file has no sound.")
    W, H = VISUAL_SIZES.get(layout, VISUAL_SIZES["landscape"])
    col = color.lstrip("#")
    bg = background.lstrip("#")
    out = sibling(src, "Visualizer", ".mp4")
    if style == "image" and image:
        args = ["-loop", "1", "-i", str(image), "-i", str(src), "-filter_complex",
                f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x{bg},"
                f"format=yuv420p[v]", "-map", "[v]", "-map", "1:a:0", "-shortest", "-r", "2"]
    else:
        wh = H // 3
        if style == "bars":
            viz = f"showfreqs=s={W}x{wh}:mode=bar:fscale=log:colors=0x{col}:win_size=2048"
        else:
            viz = f"showwaves=s={W}x{wh}:mode=cline:rate=30:colors=0x{col}"
        args = ["-f", "lavfi", "-i", f"color=c=0x{bg}:s={W}x{H}:r=30", "-i", str(src), "-filter_complex",
                f"[1:a:0]{viz},format=rgba[w];[0:v][w]overlay=0:(H-h)/2:shortest=1,format=yuv420p[v]",
                "-map", "[v]", "-map", "1:a:0", "-shortest", "-r", "30"]
    M.run([*args, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", str(out)], info.duration, progress, out)
    return out


# ---------------------------------------------------------------- images
COLLAGE_LAYOUTS = [("grid", "Grid"), ("row", "Row"), ("column", "Column"), ("featured", "Featured")]


def _fill(im: Image.Image, w: int, h: int) -> Image.Image:
    """Cover a w×h cell (crop the overflow), like object-fit: cover."""
    k = max(w / im.width, h / im.height)
    r = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def collage_cells(n: int, layout: str, W: int, H: int, gap: int) -> list[tuple[int, int, int, int]]:
    """(x, y, w, h) for each image."""
    if layout == "row":
        w = (W - gap * (n + 1)) / n
        return [(round(gap + k * (w + gap)), gap, round(w), H - 2 * gap) for k in range(n)]
    if layout == "column":
        h = (H - gap * (n + 1)) / n
        return [(gap, round(gap + k * (h + gap)), W - 2 * gap, round(h)) for k in range(n)]
    if layout == "featured" and n >= 2:
        big_w = (W - 3 * gap) * 0.62
        small_w = W - 3 * gap - big_w
        m = n - 1
        h = (H - gap * (m + 1)) / m
        return [(gap, gap, round(big_w), H - 2 * gap)] + [
            (round(2 * gap + big_w), round(gap + k * (h + gap)), round(small_w), round(h)) for k in range(m)]
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    w = (W - gap * (cols + 1)) / cols
    h = (H - gap * (rows + 1)) / rows
    return [(round(gap + (k % cols) * (w + gap)), round(gap + (k // cols) * (h + gap)), round(w), round(h))
            for k in range(n)]


def collage(images: list[Image.Image], layout: str = "grid", size: tuple[int, int] = (2400, 2400),
            spacing: int = 24, corners: int = 24, background: str = "#ffffff") -> Image.Image:
    W, H = size
    bg = Image.new("RGBA", (W, H), background)
    if background.lower() in ("transparent", "none"):
        bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for im, (x, y, w, h) in zip(images, collage_cells(len(images), layout, W, H, spacing)):
        tile = _fill(im.convert("RGBA"), w, h)
        mask = None
        if corners:
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=min(corners, w // 2, h // 2), fill=255)
            mask = Image.composite(tile.getchannel("A"), Image.new("L", (w, h), 0), mask)
        bg.paste(tile, (x, y), mask if mask is not None else tile)
    return bg


def save_collage(paths: list, **kw) -> Path:
    im = collage([open_image(p) for p in paths], **kw)
    out = sibling(paths[0], "Collage", ".png" if im.getchannel("A").getextrema()[0] < 255 else ".jpg")
    if out.suffix == ".jpg":
        im.convert("RGB").save(out, "JPEG", quality=92)
    else:
        im.save(out, "PNG")
    return out


def read_qr(src) -> list[str]:
    """Text of every QR code in a photo or screenshot (OpenCV, offline)."""
    import cv2
    import numpy as np
    im = open_image(src).convert("RGB")
    arr = np.asarray(im)[:, :, ::-1].copy()
    det = cv2.QRCodeDetector()
    found = []
    for scale in (1.0, 0.5, 2.0):            # small or huge codes decode better at another size
        img = arr if scale == 1.0 else cv2.resize(arr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                                                   if scale < 1 else cv2.INTER_CUBIC)
        ok, texts, _, _ = det.detectAndDecodeMulti(img)
        if ok:
            found += [t for t in texts if t and t not in found]
        if found:
            break
    return found


def qr_to_txt(src) -> Path:
    texts = read_qr(src)
    if not texts:
        raise UserError("No QR code found in this image.")
    out = sibling(src, "QR", ".txt")
    out.write_text("\n".join(texts) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- PDF pages
def organize_pdf(src, pages: list[tuple[int, int]]) -> Path:
    """A new PDF with `pages` = [(original page index, extra rotation in degrees)] in that order
    (pages can repeat, which duplicates them, or be left out, which removes them)."""
    import fitz
    if not pages:
        raise UserError("Keep at least one page.")
    out = sibling(src, "Organized", ".pdf")
    with open_pdf(src) as doc:
        new = fitz.open()
        for idx, rot in pages:
            new.insert_pdf(doc, from_page=idx, to_page=idx)
            pg = new[-1]
            pg.set_rotation((pg.rotation + rot) % 360)
        new.save(out, garbage=3, deflate=True)
    return out


# ---------------------------------------------------------------- metadata editing
IMAGE_FIELDS = [("title", "Title", 0x010E), ("author", "Author", 0x013B), ("copyright", "Copyright", 0x8298),
                ("camera", "Camera", 0x0110), ("date", "Date taken (YYYY:MM:DD HH:MM:SS)", 0x9003)]
PDF_FIELDS = [("title", "Title", "title"), ("author", "Author", "author"), ("subject", "Subject", "subject"),
              ("keywords", "Keywords", "keywords")]
MEDIA_FIELDS = [("title", "Title", "title"), ("artist", "Artist", "artist"), ("album", "Album", "album"),
                ("date", "Year", "date"), ("comment", "Comment", "comment")]


def read_fields(src) -> dict[str, str]:
    from .util import category
    cat = category(src)
    if cat == "pdf":
        with open_pdf(src) as doc:
            md = doc.metadata or {}
        return {k: md.get(key) or "" for k, _, key in PDF_FIELDS}
    if cat in ("video", "audio"):
        import subprocess
        exe = M.ffmpeg_exe()
        r = subprocess.run([exe, "-hide_banner", "-i", str(src), "-f", "ffmetadata", "-"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", creationflags=M.CREATE_NO_WINDOW)
        tags = {}
        for line in r.stdout.splitlines():
            if "=" in line and not line.startswith(";"):
                k, v = line.split("=", 1)
                tags[k.lower()] = v
        return {k: tags.get(key, "") for k, _, key in MEDIA_FIELDS}
    with Image.open(src) as im:
        exif = im.getexif()
        ifd = exif.get_ifd(0x8769)
    return {k: str((ifd if tag == 0x9003 else exif).get(tag, "") or "").strip("\x00 ") for k, _, tag in IMAGE_FIELDS}


def write_fields(src, values: dict[str, str], progress: Progress = None) -> Path:
    """A copy with the given fields changed (empty = removed); the original stays untouched."""
    from .util import category
    cat = category(src)
    if cat == "pdf":
        out = sibling(src, "Edited", ".pdf")
        with open_pdf(src) as doc:
            md = dict(doc.metadata or {})
            for k, _, key in PDF_FIELDS:
                if k in values:
                    md[key] = values[k]
            doc.set_metadata(md)
            doc.save(out, garbage=3, deflate=True)
        return out
    if cat in ("video", "audio"):
        info = M.probe(src)
        out = sibling(src, "Edited")
        meta = []
        for k, _, key in MEDIA_FIELDS:
            if k in values:
                meta += ["-metadata", f"{key}={values[k]}"]
        M.run(["-i", str(src), "-map", "0", "-c", "copy", *meta, str(out)], info.duration, progress, out)
        return out
    from .imaging import save_like
    with Image.open(src) as raw:
        exif = raw.getexif()
    im = open_image(src)
    for k, _, tag in IMAGE_FIELDS:
        if k not in values:
            continue
        target = exif.get_ifd(0x8769) if tag == 0x9003 else exif
        if values[k]:
            target[tag] = values[k]
        elif tag in target:
            del target[tag]
    exif[0x0112] = 1                                  # orientation is baked in by open_image
    out = save_like(im, src, "Edited")
    _save_with_exif(im, out, exif)
    return out


def _save_with_exif(im: Image.Image, out: Path, exif) -> None:
    fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".tif": "TIFF", ".tiff": "TIFF"}.get(
        out.suffix.lower())
    if fmt is None:
        return
    kw = {"exif": exif.tobytes()}
    if fmt == "JPEG":
        kw["quality"] = 95
        im = im.convert("RGB")
    im.save(out, fmt, **kw)


def compress_percent(src, percent: int, to_webp: bool = False) -> Path:
    """Make an image about `percent` % smaller."""
    from .imaging import compress_to, lossy_target, plan_target_size
    from .util import file_size
    size = file_size(src)
    goal = max(1024, int(size * (1 - percent / 100)))
    target = lossy_target(src, to_webp)
    q, side = plan_target_size(open_image(src), target, goal)
    return compress_to(src, q, side, target)
