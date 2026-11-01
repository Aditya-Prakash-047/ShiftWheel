"""Interface sounds: a short tick when a slice lights up, plus open, ring
switch, drop, done and error.

Packs are synthesised here (no audio files to license or ship) and cached as WAV files.
Every event can be switched off or replaced with your own sound (any audio file; it is
converted to WAV with the bundled FFmpeg), and themes can bring their own sounds.

Playback uses Qt's QSoundEffect with the native Windows audio backend (low latency, several
overlapping voices, so a fast sweep across slices doesn't cut ticks short)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from .util import LazyModule

np = LazyModule("numpy")          # only when a sound pack is first generated

if sys.platform == "win32":                       # must be set before QGuiApplication exists
    os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

RATE = 48000
VERSION = 1
EVENTS = [("highlight", "Slice lights up"), ("open", "Wheel opens"), ("switch", "Ring changes"),
          ("select", "File dropped"), ("done", "Job finished"), ("error", "Something went wrong")]
EVENT_KEYS = [e for e, _ in EVENTS]
PACKS = [("santra", "Santra · soft tick"), ("soft", "Soft · wooden clicks"), ("glass", "Glass · bright pings"),
         ("pop", "Pop · bubbles"), ("arcade", "Arcade · 8-bit blips"), ("theme", "Match the theme")]
PACK_KEYS = [k for k, _ in PACKS]
VOICES = {"highlight": 6}                         # overlapping copies (fast sweeps)


# ---------------------------------------------------------------- synthesis
def _t(ms: float) -> np.ndarray:
    return np.arange(int(RATE * ms / 1000)) / RATE


def _env(t: np.ndarray, tau_ms: float, attack_ms: float = 0.4) -> np.ndarray:
    a = np.clip(t / (attack_ms / 1000), 0, 1)
    return a * np.exp(-t / (tau_ms / 1000))


def _tick(ms=60, bright=8200, amp=0.14, thump=0.006, thump_hz=105, seed=7, delay_ms=5.0) -> np.ndarray:
    """The highlight sound: silent for ~5 ms, then a
    bright transient (energy near 8–9 kHz) that falls from 0.14 to 0.02 within 5 ms, over a
    faint ~100 Hz body (≈0.005), 60 ms in all."""
    rng = np.random.default_rng(seed)
    t = _t(ms)
    tc = np.clip(t - delay_ms / 1000, 0, None)
    noise = _bandpass(rng.standard_normal(t.size), bright, q=1.4)
    click = noise * _env(tc, 2.0, 0.12) * (t >= delay_ms / 1000)
    click /= max(1e-9, np.abs(click).max())
    body = np.sin(2 * np.pi * thump_hz * tc) * _env(tc, 20, 1.5) * (t >= delay_ms / 1000)
    out = click * amp + body * thump
    return out.astype(np.float32)


def _bandpass(x: np.ndarray, f0: float, q: float = 1.0) -> np.ndarray:
    """RBJ biquad band-pass (constant 0 dB peak gain)."""
    w0 = 2 * np.pi * f0 / RATE
    alpha = np.sin(w0) / (2 * q)
    b0, b2 = alpha, -alpha
    a0, a1, a2 = 1 + alpha, -2 * np.cos(w0), 1 - alpha
    b0, b2, a1, a2 = b0 / a0, b2 / a0, a1 / a0, a2 / a0
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for n, xn in enumerate(x):
        yn = b0 * xn + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, xn, y1, yn
        y[n] = yn
    return y


def _tone(freqs, ms=110, tau=55, amp=0.12, partials=(1.0,), attack=2.0) -> np.ndarray:
    t = _t(ms)
    out = np.zeros(t.size)
    for f in freqs if isinstance(freqs, (list, tuple)) else [freqs]:
        for k, w in enumerate(partials, 1):
            out += w * np.sin(2 * np.pi * f * k * t)
    out *= _env(t, tau, attack)
    out /= max(1e-9, np.abs(out).max())
    return (out * amp).astype(np.float32)


def _seq(*parts, gap_ms=0) -> np.ndarray:
    gap = np.zeros(int(RATE * gap_ms / 1000), np.float32)
    out = []
    for i, p in enumerate(parts):
        out.append(p)
        if i < len(parts) - 1:
            out.append(gap)
    return np.concatenate(out)


def _sweep(f0, f1, ms=40, amp=0.13, tau=18) -> np.ndarray:
    t = _t(ms)
    f = np.linspace(f0, f1, t.size)
    out = np.sin(2 * np.pi * np.cumsum(f) / RATE) * _env(t, tau, 1.0)
    return (out / max(1e-9, np.abs(out).max()) * amp).astype(np.float32)


def _square(f, ms=40, amp=0.07, tau=30) -> np.ndarray:
    t = _t(ms)
    out = np.sign(np.sin(2 * np.pi * f * t)) * _env(t, tau, 0.5)
    return (out * amp).astype(np.float32)


def synth(pack: str, event: str) -> np.ndarray:
    if pack == "santra":
        return {"highlight": lambda: _tick(),
                "open": lambda: _tick(ms=70, bright=6000, amp=0.09, thump=0.02, thump_hz=90, seed=3),
                "switch": lambda: _seq(_tick(ms=30, amp=0.1), _tick(ms=60, amp=0.12, seed=9), gap_ms=18),
                "select": lambda: _tick(ms=80, amp=0.17, thump=0.03, thump_hz=120, seed=5),
                "done": lambda: _seq(_tone(1318.5, 90, 45, 0.08, (1, 0.25)), _tone(1760, 160, 80, 0.08, (1, 0.25))),
                "error": lambda: _seq(_tone(330, 90, 50, 0.1, (1, 0.5, 0.25)), _tone(262, 140, 70, 0.1, (1, 0.5, 0.25)),
                                      gap_ms=20)}[event]()
    if pack == "soft":
        return {"highlight": lambda: _tone(1900, 26, 6, 0.09, (1, 0.3), 0.3),
                "open": lambda: _tone(700, 60, 18, 0.08, (1, 0.4), 1.0),
                "switch": lambda: _seq(_tone(1500, 22, 6, 0.08), _tone(1900, 26, 6, 0.08), gap_ms=25),
                "select": lambda: _tone(1200, 50, 14, 0.12, (1, 0.5)),
                "done": lambda: _seq(_tone(880, 90, 40, 0.09, (1, 0.4, 0.2)), _tone(1320, 150, 70, 0.09, (1, 0.4, 0.2))),
                "error": lambda: _tone(200, 180, 80, 0.11, (1, 0.6, 0.4, 0.2))}[event]()
    if pack == "glass":
        return {"highlight": lambda: _tone(2600, 70, 25, 0.06, (1, 0.35), 0.5),
                "open": lambda: _seq(_tone(1568, 60, 30, 0.05, (1, 0.3)), _tone(2093, 120, 60, 0.05, (1, 0.3))),
                "switch": lambda: _tone(2349, 90, 35, 0.06, (1, 0.35)),
                "select": lambda: _tone(3136, 140, 60, 0.07, (1, 0.35, 0.1)),
                "done": lambda: _seq(_tone(2093, 120, 60, 0.06, (1, 0.3)), _tone(2637, 220, 110, 0.06, (1, 0.3))),
                "error": lambda: _seq(_tone(880, 110, 50, 0.07, (1, 0.5)), _tone(698, 160, 70, 0.07, (1, 0.5)))}[event]()
    if pack == "pop":
        return {"highlight": lambda: _sweep(380, 900, 34, 0.11, 12),
                "open": lambda: _sweep(250, 600, 60, 0.09, 25),
                "switch": lambda: _seq(_sweep(500, 1000, 30, 0.09, 10), _sweep(600, 1200, 30, 0.09, 10), gap_ms=20),
                "select": lambda: _sweep(300, 1100, 60, 0.14, 22),
                "done": lambda: _seq(_sweep(600, 1200, 60, 0.1, 25), _sweep(800, 1600, 90, 0.1, 40)),
                "error": lambda: _sweep(500, 180, 160, 0.12, 70)}[event]()
    if pack == "arcade":
        return {"highlight": lambda: _square(880, 30, 0.05, 25),
                "open": lambda: _seq(_square(523, 35, 0.05), _square(784, 45, 0.05)),
                "switch": lambda: _seq(_square(660, 30, 0.05), _square(990, 35, 0.05)),
                "select": lambda: _square(1320, 70, 0.06, 50),
                "done": lambda: _seq(_square(784, 60, 0.05), _square(988, 60, 0.05), _square(1319, 120, 0.05, 80)),
                "error": lambda: _seq(_square(220, 90, 0.06), _square(165, 160, 0.06, 90))}[event]()
    return np.zeros(int(RATE * 0.02), np.float32)


def write_wav(path: Path, data: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return path


def cache_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "ShiftWheel" / "sounds" / f"v{VERSION}"


def custom_dir() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / ".config") / "ShiftWheel" / "sounds"


def pack_file(pack: str, event: str) -> Path:
    p = cache_dir() / pack / f"{event}.wav"
    if not p.exists():
        write_wav(p, synth(pack, event))
    return p


def import_sound(src: str | Path, event: str) -> Path:
    """Copy a user's sound into the app's folder as a WAV (converting other formats, keeping
    at most 3 seconds) so it keeps working if the original is moved."""
    src = Path(src)
    dst = custom_dir() / f"{event}.wav"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".wav" and _wav_ok(src):
        shutil.copyfile(src, dst)
        return dst
    from .media import CREATE_NO_WINDOW, ffmpeg_exe
    tmp = dst.with_suffix(".part.wav")
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-t", "3",
                        "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(tmp)],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        from .util import UserError
        raise UserError("That file doesn't contain audio ShiftWheel can play.")
    os.replace(tmp, dst)
    return dst


def _wav_ok(p: Path) -> bool:
    try:
        with wave.open(str(p), "rb") as w:
            return w.getnframes() > 0 and w.getsampwidth() in (1, 2) and w.getnchannels() in (1, 2)
    except Exception:
        return False


# ---------------------------------------------------------------- playback
class Player:
    """Owns the QSoundEffect voices. configure() whenever settings or the theme change."""

    def __init__(self):
        self.enabled = True
        self.volume = 0.6
        self.on: dict[str, bool] = {e: True for e in EVENT_KEYS}
        self.files: dict[str, str] = {}
        self._voices: dict[str, list] = {}
        self._next: dict[str, int] = {}
        import importlib.util
        self.available = importlib.util.find_spec("PySide6.QtMultimedia") is not None

    def configure(self, enabled: bool, volume: int, pack: str, on: dict, custom: dict, theme_files: dict,
                  theme_pack: str = "santra"):
        self.enabled = bool(enabled)
        self.volume = max(0.0, min(1.0, volume / 100))
        self.on = {e: bool(on.get(e, True)) for e in EVENT_KEYS}
        use = theme_pack if pack == "theme" else pack
        if use not in PACK_KEYS or use == "theme":
            use = "santra"
        files = {}
        for e in EVENT_KEYS:
            if custom.get(e) and Path(custom[e]).is_file():
                files[e] = custom[e]
            elif pack == "theme" and theme_files.get(e) and Path(theme_files[e]).is_file():
                files[e] = theme_files[e]
            else:
                files[e] = str(pack_file(use, e))
        if files != self.files:
            self.files = files
            self._voices = {}
        for voices in self._voices.values():
            for v in voices:
                v.setVolume(self.volume)

    def _make(self, event: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QSoundEffect
        voices = []
        for _ in range(VOICES.get(event, 2)):
            s = QSoundEffect()
            s.setSource(QUrl.fromLocalFile(self.files[event]))
            s.setVolume(self.volume)
            voices.append(s)
        self._voices[event] = voices
        self._next[event] = 0
        return voices

    def release(self):
        """Free the loaded sounds (they reload at the next wheel)."""
        self._voices = {}
        self._next = {}

    def preload(self):
        """Decode every sound now, so the first tick isn't late."""
        if self.available:
            for e in EVENT_KEYS:
                if e in self.files and e not in self._voices:
                    self._make(e)

    def play(self, event: str, force: bool = False):
        if not self.available or event not in self.files:
            return
        if not force and (not self.enabled or not self.on.get(event, True) or self.volume <= 0):
            return
        try:
            voices = self._voices.get(event) or self._make(event)
            i = self._next.get(event, 0)
            self._next[event] = (i + 1) % len(voices)
            v = voices[i]
            v.stop()
            v.play()
        except Exception:
            pass
