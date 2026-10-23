"""Shared fixtures: realistic synthetic inputs (a card photographed at an angle on a table,
a document page photographed with perspective, short video/audio clips)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _close_windows_after_each_test():
    """Tool windows start timers and background jobs (filmstrips, previews, OCR). Left open,
    they fire during later tests; finish the jobs and delete each test's windows instead."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    before = {id(w) for w in app.topLevelWidgets()} if app else set()
    yield
    app = QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    QThreadPool.globalInstance().waitForDone(60_000)
    app.processEvents()
    for w in app.topLevelWidgets():
        if id(w) not in before:
            w.close()
            w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def _paste_warped(bg: np.ndarray, src: np.ndarray, corners) -> np.ndarray:
    import cv2
    h, w = src.shape[:2]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
    H, W = bg.shape[:2]
    warped = cv2.warpPerspective(src, M, (W, H))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    bg[mask > 0] = warped[mask > 0]
    return bg


def make_card(label: str, color) -> Image.Image:
    im = Image.new("RGB", (1712, 1080), color)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, 1711, 1079], radius=60, outline=(40, 40, 40), width=6)
    d.rectangle([60, 60, 1652, 200], fill=(200, 80, 30))
    d.rectangle([80, 280, 480, 780], fill=(120, 120, 160))
    for i in range(6):
        d.rectangle([560, 300 + i * 90, 1500, 340 + i * 90], fill=(60, 60, 60))
    d.text((90, 100), label, fill="white")
    return im


@pytest.fixture
def card_photos(tmp_path) -> list[Path]:
    """Front and back of an ID card photographed at an angle with perspective on a wooden table."""
    out = []
    rng = np.random.default_rng(1)
    for name, color, ang in (("front", (235, 240, 250), 12), ("back", (250, 245, 230), -8)):
        card = np.array(make_card(name.upper(), color))
        bg = np.full((1500, 2000, 3), (92, 70, 55), np.uint8)
        bg = np.clip(bg.astype(int) + rng.integers(0, 25, bg.shape), 0, 255).astype(np.uint8)
        cx, cy, rad = 1000, 750, np.deg2rad(ang)
        pts = []
        for (x, y), k in zip([(-650, -410), (650, -410), (650, 410), (-650, 410)], [1, 0.92, 0.95, 1.04]):
            pts.append([cx + (x * np.cos(rad) - y * np.sin(rad)) * k, cy + (x * np.sin(rad) + y * np.cos(rad)) * k])
        Image.fromarray(_paste_warped(bg, card, pts)).save(tmp_path / f"IMG_{name}.jpg", quality=90)
        out.append(tmp_path / f"IMG_{name}.jpg")
    return out


@pytest.fixture
def doc_photo(tmp_path) -> Path:
    page = Image.new("RGB", (1240, 1754), (245, 242, 230))
    d = ImageDraw.Draw(page)
    for i in range(30):
        d.rectangle([120, 150 + i * 48, 1100 - (i % 4) * 120, 172 + i * 48], fill=(30, 30, 30))
    bg = np.full((2000, 1600, 3), (70, 80, 90), np.uint8)
    corners = [[260, 180], [1380, 240], [1450, 1860], [180, 1800]]
    p = tmp_path / "doc_photo.jpg"
    Image.fromarray(_paste_warped(bg, np.array(page), corners)).save(p, quality=90)
    return p


@pytest.fixture
def portrait(tmp_path) -> Path:
    im = Image.new("RGB", (900, 1200), (230, 235, 240))
    d = ImageDraw.Draw(im)
    d.ellipse([300, 250, 600, 600], fill=(200, 160, 130))
    d.rectangle([200, 650, 700, 1200], fill=(40, 60, 120))
    p = tmp_path / "portrait.jpg"
    im.save(p, quality=90)
    return p


def _ffmpeg(*args):
    import subprocess
    from shiftwheel.media import ffmpeg_exe
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    """4 s 640×360 H.264/AAC clip, a 2 s silent 320×240 clip, and a 5 s WAV tone."""
    d = tmp_path_factory.mktemp("media")
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(d / "clip.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", str(d / "silent.mov"))
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=5", "-c:a", "pcm_s16le", str(d / "tone.wav"))
    return d
