"""Video and audio, powered by the FFmpeg that ships inside ShiftWheel (imageio-ffmpeg).

Every function writes next to the source (never overwriting), never changes the original,
and reports progress (0..1) through an optional callback so the notification can show %."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .util import UserError, sibling

Progress = Callable[[float], None] | None
# no console window, below-normal priority: encoding never takes the machine from what you're doing
CREATE_NO_WINDOW = 0x08000000 | 0x00004000 if sys.platform == "win32" else 0

VIDEO_TARGETS = ["MP4", "MOV", "MKV", "WEBM", "AVI", "GIF", "MP3", "WAV"]
AUDIO_TARGETS = ["MP3", "M4A", "WAV", "OGG", "FLAC", "OPUS"]
VIDEO_HINTS = {"MP4": "Plays everywhere", "MOV": "Apple / editing", "MKV": "Keeps every track",
               "WEBM": "Web, small", "AVI": "Old players", "GIF": "Loop for chats",
               "MP3": "Audio only", "WAV": "Audio, lossless"}
AUDIO_HINTS = {"MP3": "Plays everywhere", "M4A": "Apple / AAC", "WAV": "Uncompressed",
               "OGG": "Open format", "FLAC": "Lossless, smaller", "OPUS": "Tiny voice notes"}


def ffmpeg_exe() -> str:
    env = os.environ.get("SHIFTWHEEL_FFMPEG")
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        from shutil import which
        found = which("ffmpeg")
        if found:
            return found
        raise UserError("FFmpeg is missing from this build.") from e


# ---------------------------------------------------------------- probe
@dataclass
class Info:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str = ""
    acodec: str = ""
    rotation: int = 0
    bitrate_kbps: int = 0
    streams: list[str] = field(default_factory=list)

    @property
    def has_video(self) -> bool:
        return bool(self.vcodec) and self.vcodec not in ("mjpeg", "png")  # cover art isn't video

    @property
    def has_audio(self) -> bool:
        return bool(self.acodec)


def probe(path: str | Path) -> Info:
    """Parse `ffmpeg -i` (ffprobe isn't bundled)."""
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    err = r.stderr
    info = Info()
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        info.duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"bitrate: (\d+) kb/s", err)
    if m:
        info.bitrate_kbps = int(m[1])
    for line in err.splitlines():
        if "Stream #" not in line:
            continue
        info.streams.append(line.strip())
        if "Video:" in line and not info.vcodec:
            if "attached pic" in line:
                continue
            info.vcodec = re.search(r"Video: (\w+)", line)[1]
            m = re.search(r", (\d{2,5})x(\d{2,5})", line)
            if m:
                info.width, info.height = int(m[1]), int(m[2])
            m = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
            if m:
                info.fps = float(m[1])
        elif "Audio:" in line and not info.acodec:
            info.acodec = re.search(r"Audio: (\w+)", line)[1]
    m = re.search(r"rotate\s*:\s*(-?\d+)", err) or re.search(r"rotation of (-?[\d.]+) degrees", err)
    if m:
        info.rotation = int(float(m[1])) % 360
    if info.rotation in (90, 270):
        info.width, info.height = info.height, info.width
    if not info.streams:
        raise UserError("This file doesn't look like audio or video ShiftWheel can read.")
    return info


# ---------------------------------------------------------------- running ffmpeg
def run(args: list[str], duration: float = 0.0, progress: Progress = None, out: Path | None = None) -> None:
    """Run ffmpeg; write to a temp name and rename at the end (Explorer never sees half a file)."""
    tmp = None
    if out is not None:
        out = Path(out)
        tmp = out.with_name(f".~{out.stem}.part{out.suffix}")
        args = [a if a != str(out) else str(tmp) for a in args]
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1",
           "-nostats", *args]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", creationflags=CREATE_NO_WINDOW)
    try:
        assert p.stdout is not None
        for line in p.stdout:
            if progress and duration > 0 and line.startswith("out_time_us="):
                try:
                    progress(min(1.0, max(0.0, int(line.split("=", 1)[1]) / 1e6 / duration)))
                except ValueError:
                    pass
        err = p.stderr.read() if p.stderr else ""
        code = p.wait()
        if code != 0:
            raise UserError(_ffmpeg_error(err))
        if tmp is not None:
            os.replace(tmp, out)
        if progress:
            progress(1.0)
    finally:
        if p.poll() is None:
            p.kill()
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _ffmpeg_error(err: str) -> str:
    lines = [l for l in err.strip().splitlines() if l.strip()]
    tail = lines[-1] if lines else "FFmpeg failed"
    low = err.lower()
    if "invalid data found" in low or "moov atom not found" in low:
        return "The file is damaged or incomplete."
    if "no such file" in low:
        return "The file was moved or deleted."
    if "does not contain any stream" in low or "output file is empty" in low:
        return "Nothing to write — the file has no matching audio/video."
    return tail[:300]


# ---------------------------------------------------------------- encoders
def _video_codec_args(target: str, crf: int | None = None, height: int | None = None) -> list[str]:
    t = target.upper()
    if t in ("MP4", "MOV", "MKV"):
        return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf or 21), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k"] + (["-movflags", "+faststart"] if t in ("MP4", "MOV") else [])
    if t == "WEBM":
        return ["-c:v", "libvpx-vp9", "-crf", str(crf or 33), "-b:v", "0", "-row-mt", "1", "-deadline", "good",
                "-cpu-used", "4", "-c:a", "libopus", "-b:a", "128k"]
    if t == "AVI":
        return ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-b:a", "192k"]
    raise ValueError(t)


AUDIO_CODEC = {
    "MP3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "M4A": ["-c:a", "aac", "-b:a", "192k"],
    "WAV": ["-c:a", "pcm_s16le"],
    "OGG": ["-c:a", "libvorbis", "-q:a", "5"],
    "FLAC": ["-c:a", "flac"],
    "OPUS": ["-c:a", "libopus", "-b:a", "96k"],
}
REMUX_OK = {"MP4": {"h264", "hevc", "mpeg4", "av1"}, "MOV": {"h264", "hevc", "mpeg4", "prores", "av1"},
            "MKV": None}  # None = anything
REMUX_AUDIO_OK = {"MP4": {"aac", "mp3", "ac3", "alac", "opus"}, "MOV": {"aac", "mp3", "alac", "pcm_s16le"}}


def _can_remux(info: Info, target: str) -> bool:
    t = target.upper()
    if t not in REMUX_OK:
        return False
    v_ok = REMUX_OK[t] is None or info.vcodec in REMUX_OK[t]
    a_ok = not info.has_audio or t == "MKV" or info.acodec in REMUX_AUDIO_OK.get(t, set())
    return v_ok and a_ok


# ---------------------------------------------------------------- conversions
def convert_video(src, target: str, progress: Progress = None) -> list[Path]:
    t = target.upper()
    info = probe(src)
    if t in AUDIO_CODEC:
        return extract_audio(src, t, progress)
    out = sibling(src, ext="." + t.lower())
    if t == "GIF":
        return [to_gif(src, out=out, progress=progress)]
    if not info.has_video:
        raise UserError("There's no video in this file.")
    if _can_remux(info, t):  # same streams, new container: instant and lossless
        try:
            run(["-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-c", "copy"] +
                (["-movflags", "+faststart"] if t in ("MP4", "MOV") else []) + [str(out)],
                info.duration, progress, out)
            return [out]
        except UserError:
            pass
    run(["-i", str(src), "-map", "0:v:0", "-map", "0:a?", *_video_codec_args(t), str(out)],
        info.duration, progress, out)
    return [out]


def to_gif(src, out=None, start: float = 0.0, length: float | None = None, fps: int = 12, width: int = 480,
           progress: Progress = None) -> Path:
    info = probe(src)
    out = out or sibling(src, ext=".gif")
    width = min(width, info.width or width)
    length = length if length is not None else min(info.duration, 30.0)  # GIFs get huge: cap at 30 s
    vf = (f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
          f"[b][p]paletteuse=dither=bayer:bayer_scale=4")
    run(["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src), "-filter_complex", vf, "-loop", "0",
         str(out)], length, progress, out)
    return out


def extract_audio(src, target: str = "MP3", progress: Progress = None) -> list[Path]:
    t = target.upper()
    info = probe(src)
    if not info.has_audio:
        raise UserError("This file has no sound.")
    out = sibling(src, ext="." + t.lower())
    run(["-i", str(src), "-vn", "-map", "0:a:0", *AUDIO_CODEC[t], str(out)], info.duration, progress, out)
    return [out]


def convert_audio(src, target: str, progress: Progress = None) -> list[Path]:
    return extract_audio(src, target, progress)


# ---------------------------------------------------------------- video tools
def compress_video(src, quality: str = "balanced", max_height: int | None = None,
                   target_mb: float | None = None, progress: Progress = None) -> Path:
    """quality: 'small' | 'balanced' | 'high'. target_mb: aim for a size (bitrate-based)."""
    info = probe(src)
    if not info.has_video:
        return compress_audio(src, progress=progress)
    out = sibling(src, "Compressed", ".mp4")
    vf = []
    if max_height and info.height > max_height:
        vf = ["-vf", f"scale=-2:{max_height}"]
    aud = ["-c:a", "aac", "-b:a", "96k" if quality == "small" or target_mb else "128k"] if info.has_audio else ["-an"]
    if target_mb:
        return _two_pass(src, out, info, target_mb, vf, aud, progress)
    crf = {"small": 30, "balanced": 26, "high": 22}[quality]
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
    run(["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *vf, *enc, *aud, "-movflags", "+faststart", str(out)],
        info.duration, progress, out)
    return out


def estimate_video(src, quality: str = "balanced", max_height: int | None = None,
                   target_mb: float | None = None, samples: int = 3, seconds: float = 2.0) -> int:
    """Expected size of compress_video: encode a few short samples spread through the video with
    the same settings and scale to the full length (how encoders' size previews work)."""
    info = probe(src)
    if target_mb:
        return int(target_mb * 1048576)
    if not info.has_video:
        return estimate_audio(src, "small")
    audio_k = (96 if quality == "small" else 128) if info.has_audio else 0
    vf = ["-vf", f"scale=-2:{max_height}"] if max_height and info.height > max_height else []
    crf = {"small": 30, "balanced": 26, "high": 22}[quality]
    dur = max(info.duration, 0.1)
    if dur <= samples * seconds * 1.5:
        spots, seg = [0.0], dur
    else:
        spots, seg = [dur * (i + 1) / (samples + 1) - seconds / 2 for i in range(samples)], seconds
    total = 0
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(spots):
            out = Path(td) / f"s{i}.mp4"
            run(["-ss", f"{max(0.0, t):.2f}", "-t", f"{seg:.2f}", "-i", str(src), "-map", "0:v:0", *vf,
                 "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-an", str(out)])
            total += out.stat().st_size
    video_bps = total / (seg * len(spots))
    return int((video_bps + audio_k * 125) * dur * 1.01)


def _two_pass(src, out: Path, info: Info, target_mb: float, vf: list, aud: list, progress: Progress) -> Path:
    """Two-pass x264 aimed at a file size; one corrective re-encode if it still lands over."""
    audio_k = 96 if info.has_audio else 0
    budget_k = target_mb * 8192 / max(info.duration, 0.1)        # kbit/s for the whole file
    video_k = max(40, int(budget_k * 0.95 - audio_k))           # 5% for the container
    null = "NUL" if sys.platform == "win32" else "/dev/null"
    for attempt in range(2):
        with tempfile.TemporaryDirectory() as td:
            log = os.path.join(td, "x264")
            enc = ["-c:v", "libx264", "-preset", "medium", "-b:v", f"{video_k}k", "-pix_fmt", "yuv420p",
                   "-passlogfile", log]
            p1 = (lambda f: progress(f * 0.45)) if progress else None
            p2 = (lambda f: progress(0.45 + f * 0.55)) if progress else None
            run(["-i", str(src), "-map", "0:v:0", *vf, *enc, "-pass", "1", "-an", "-f", "mp4", null],
                info.duration, p1)
            run(["-i", str(src), "-map", "0:v:0", "-map", "0:a:0?", *vf, *enc, "-pass", "2", *aud,
                 "-movflags", "+faststart", str(out)], info.duration, p2, out)
        size_mb = out.stat().st_size / 1048576
        if size_mb <= target_mb * 1.02 or video_k <= 40:
            break
        video_k = max(40, int(video_k * target_mb / size_mb * 0.97))
        out.unlink()
    return out


def trim(src, start: float, end: float, precise: bool = True, progress: Progress = None) -> Path:
    info = probe(src)
    start = max(0.0, start)
    end = min(info.duration or end, end)
    if end - start < 0.05:
        raise UserError("The selection is too short.")
    out = sibling(src, "Trimmed")
    length = end - start
    if precise:
        if info.has_video:
            ext = out.suffix.lower()
            if ext in (".webm",):
                enc = _video_codec_args("WEBM")
            elif ext in (".avi",):
                enc = _video_codec_args("AVI")
            else:
                enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-b:a", "192k"]
                if ext not in (".mp4", ".mov", ".mkv", ".m4v"):
                    out = out.with_suffix(".mp4")
            args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}", "-map", "0:v:0", "-map", "0:a?",
                    *enc, str(out)]
        else:
            t = {".mp3": "MP3", ".m4a": "M4A", ".aac": "M4A", ".ogg": "OGG", ".flac": "FLAC", ".opus": "OPUS",
                 ".wav": "WAV"}.get(out.suffix.lower(), "MP3")
            if out.suffix.lower() not in (".mp3", ".m4a", ".ogg", ".flac", ".opus", ".wav"):
                out = out.with_suffix("." + t.lower())
            args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}", "-vn", *AUDIO_CODEC[t], str(out)]
    else:  # instant, lossless; cuts land on the nearest keyframe
        args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{length:.3f}", "-map", "0", "-c", "copy",
                "-avoid_negative_ts", "make_zero", str(out)]
    run(args, length, progress, out)
    return out


def resize_video(src, height: int, progress: Progress = None) -> Path:
    info = probe(src)
    out = sibling(src, f"{height}p", ".mp4")
    run(["-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-vf", f"scale=-2:{height}:flags=lanczos",
         *_video_codec_args("MP4", crf=20), str(out)], info.duration, progress, out)
    return out


def rotate_video(src, degrees: int = 90, progress: Progress = None) -> Path:
    info = probe(src)
    vf = {90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}[degrees % 360]
    out = sibling(src, "Rotated", ".mp4")
    run(["-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-vf", vf, *_video_codec_args("MP4", crf=19), str(out)],
        info.duration, progress, out)
    return out


def mute(src, progress: Progress = None) -> Path:
    info = probe(src)
    out = sibling(src, "Muted")
    run(["-i", str(src), "-map", "0:v", "-c", "copy", "-an", str(out)], info.duration, progress, out)
    return out


def speed(src, factor: float, progress: Progress = None) -> Path:
    info = probe(src)
    out = sibling(src, f"{factor:g}x", ".mp4" if info.has_video else None)
    atempo = []
    f = factor
    while f > 2.0:   # atempo only accepts 0.5..2 per stage
        atempo.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        atempo.append("atempo=0.5")
        f /= 0.5
    atempo.append(f"atempo={f:.4f}")
    args = ["-i", str(src)]
    if info.has_video:
        args += ["-filter:v", f"setpts=PTS/{factor}"]
        args += ["-filter:a", ",".join(atempo)] if info.has_audio else ["-an"]
        args += _video_codec_args("MP4", crf=20)
    else:
        args += ["-filter:a", ",".join(atempo)]
    run([*args, str(out)], info.duration / factor, progress, out)
    return out


def snapshot(src, at: float, out: Path | None = None) -> Path:
    out = out or sibling(src, f"Frame {at:.1f}s", ".png")
    run(["-ss", f"{max(0.0, at):.3f}", "-i", str(src), "-frames:v", "1", "-update", "1", str(out)], out=out)
    return out


def frame_image(src, at: float, height: int = 360):
    """A PIL frame for previews (in memory)."""
    from PIL import Image
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, at):.3f}", "-i", str(src),
           "-frames:v", "1", "-vf", f"scale=-2:{height}", "-f", "image2pipe", "-c:v", "png", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        return None
    import io
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def waveform_image(src, width: int = 1200, height: int = 160, color: str = "0xffffff"):
    from PIL import Image
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(src), "-filter_complex",
           f"aformat=channel_layouts=mono,showwavespic=s={width}x{height}:colors={color}", "-frames:v", "1",
           "-f", "image2pipe", "-c:v", "png", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        return None
    import io
    return Image.open(io.BytesIO(r.stdout)).convert("RGBA")


def merge(srcs: list, progress: Progress = None) -> Path:
    """Join clips in order. Same format → lossless concat; otherwise re-encode to a common size."""
    infos = [probe(s) for s in srcs]
    total = sum(i.duration for i in infos)
    video = any(i.has_video for i in infos)
    first = Path(srcs[0])
    if video:
        out = sibling(first, "Merged", ".mp4")
        same = len({(i.vcodec, i.width, i.height, i.acodec) for i in infos}) == 1
        if same:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                for s in srcs:
                    f.write("file '" + str(Path(s).resolve()).replace("'", "'\\''") + "'\n")
                lst = f.name
            try:
                run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", str(out)],
                    total, progress, out)
                return out
            except UserError:
                pass
            finally:
                os.unlink(lst)
        W = max(i.width for i in infos if i.has_video) // 2 * 2
        H = max(i.height for i in infos if i.has_video) // 2 * 2
        args, chains, n = [], [], len(srcs)
        for k, (s, i) in enumerate(zip(srcs, infos)):
            args += ["-i", str(s)]
            if not i.has_audio:
                args += ["-f", "lavfi", "-t", f"{i.duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        idx = 0
        for k, i in enumerate(infos):
            v, a = f"{idx}:v", (f"{idx}:a" if i.has_audio else f"{idx + 1}:a")
            chains.append(f"[{v}]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
                          f"setsar=1,fps=30,format=yuv420p[v{k}];[{a}]aformat=sample_rates=48000:channel_layouts=stereo[a{k}]")
            idx += 1 if i.has_audio else 2
        fc = ";".join(chains) + ";" + "".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        run([*args, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *_video_codec_args("MP4"), str(out)],
            total, progress, out)
        return out
    out = sibling(first, "Merged", ".mp3" if first.suffix.lower() not in (".wav", ".flac", ".m4a") else first.suffix)
    t = {".wav": "WAV", ".flac": "FLAC", ".m4a": "M4A"}.get(out.suffix.lower(), "MP3")
    args = []
    for s in srcs:
        args += ["-i", str(s)]
    fc = "".join(f"[{k}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{k}];" for k in range(len(srcs)))
    fc += "".join(f"[a{k}]" for k in range(len(srcs))) + f"concat=n={len(srcs)}:v=0:a=1[a]"
    run([*args, "-filter_complex", fc, "-map", "[a]", *AUDIO_CODEC[t], str(out)], total, progress, out)
    return out


# ---------------------------------------------------------------- audio tools
# (key, name, description, kbps, mono)
AUDIO_LEVELS = [
    ("high", "High", "192 kbps stereo · hard to tell from the original", 192, False),
    ("balanced", "Balanced", "128 kbps stereo · good for music", 128, False),
    ("small", "Small", "96 kbps stereo · podcasts and casual listening", 96, False),
    ("voice", "Voice", "48 kbps mono · speech, lectures, voice notes", 48, True),
]


def _audio_level(level: str) -> tuple[int, bool]:
    for key, _, _, kbps, mono in AUDIO_LEVELS:
        if key == level:
            return kbps, mono
    return 96, False


def compress_audio(src, kbps: int = 96, progress: Progress = None, level: str | None = None) -> Path:
    mono = False
    if level:
        kbps, mono = _audio_level(level)
    info = probe(src)
    out = sibling(src, "Compressed", ".mp3")
    args = ["-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", f"{kbps}k"]
    if mono:
        args += ["-ac", "1"]
    run([*args, str(out)], info.duration, progress, out)
    return out


def estimate_audio(src, level: str) -> int:
    """MP3 at a constant bitrate: bitrate × duration, plus the ID3 header."""
    kbps, _ = _audio_level(level)
    return int(probe(src).duration * kbps * 1000 / 8) + 4096


def normalize(src, progress: Progress = None) -> Path:
    """Even out loudness (EBU R128, -14 LUFS like streaming services)."""
    info = probe(src)
    out = sibling(src, "Normalized")
    ext = out.suffix.lower()
    codec = {".mp3": AUDIO_CODEC["MP3"], ".m4a": AUDIO_CODEC["M4A"], ".wav": AUDIO_CODEC["WAV"],
             ".flac": AUDIO_CODEC["FLAC"], ".ogg": AUDIO_CODEC["OGG"], ".opus": AUDIO_CODEC["OPUS"]}.get(ext)
    if info.has_video:
        args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:a", "aac", "-b:a", "192k"]
        if ext not in (".mp4", ".mov", ".mkv", ".m4v"):
            out = out.with_suffix(".mp4")
    else:
        if codec is None:
            out, codec = out.with_suffix(".mp3"), AUDIO_CODEC["MP3"]
        args = ["-i", str(src), "-vn", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000" if ext == ".opus" else "44100",
                *codec]
    run([*args, str(out)], info.duration, progress, out)
    return out


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"


def filmstrip(src, count: int = 12, height: int = 64, duration: float | None = None):
    """One ffmpeg call: `count` evenly spaced frames tiled side by side (for the trim bar)."""
    from PIL import Image
    import io
    duration = duration or probe(src).duration or 1.0
    rate = max(count / max(duration, 0.1), 0.01)
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", str(src), "-vf",
           f"fps={rate:.5f},scale=-2:{height},tile={count}x1", "-frames:v", "1", "-f", "image2pipe",
           "-c:v", "png", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        return None
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")
