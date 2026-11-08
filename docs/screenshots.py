"""Regenerates the images in docs/ from the current code, so they never go out of date.

    python docs/screenshots.py

Run it on Windows or macOS (the offscreen platform has no fonts). Windows are rendered
without appearing on screen, and nothing on the computer is changed."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"          # 1:1 pixels whatever the screen scale

import numpy as np                                      # noqa: E402
from PIL import Image                                   # noqa: E402
from PySide6.QtCore import QRectF, QSettings, Qt, QThreadPool  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

app = QApplication([])

from conftest import _paste_warped, make_card           # noqa: E402

from shiftwheel import glass, themes                    # noqa: E402
from shiftwheel import settings as S                    # noqa: E402
from shiftwheel.media import ffmpeg_exe                 # noqa: E402
from shiftwheel.util import ui_family                   # noqa: E402

OUT = ROOT / "docs"
TMP = Path(tempfile.mkdtemp(prefix="shiftwheel-docs-"))


def use(theme: str, mode: str):
    look = themes.resolve(theme, {"mode": mode})
    glass.set_mode(look.dark)
    glass.set_ui(look.ui, look.dark)
    return look


def settle(seconds: float = 2.0):
    """Let background jobs (filmstrips, previews, card detection) finish and paint."""
    end = time.time() + seconds
    while time.time() < end:
        QThreadPool.globalInstance().waitForDone(100)
        app.processEvents()


def shoot(w, name: str, seconds: float = 2.0):
    w.setAttribute(Qt.WA_DontShowOnScreen)
    w.show()
    settle(seconds)
    w.grab().save(str(OUT / name))
    w.close()
    print("wrote", name)


def notify(*_a, **_k):
    pass


def theme_sheet():
    cell, bar = 210, 30
    builtin = themes.BUILTIN
    img = QImage(cell * len(builtin), bar + 2 * cell, QImage.Format_ARGB32)
    img.fill(QColor("#0d1117"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    f = QFont(ui_family(True))
    f.setPixelSize(14)
    f.setBold(True)
    for i, t in enumerate(builtin):
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(i * cell, 0, cell, bar), Qt.AlignCenter, t.name)
        for row, mode in enumerate(("light", "dark")):
            x, y = i * cell, bar + row * cell
            p.drawPixmap(x, y, S.wallpaper(mode == "dark", cell))
            p.drawPixmap(x + 5, y + 5, S.preview(t.key, {"mode": mode}, cell - 10, hover=2))
    p.end()
    img.save(str(OUT / "themes.png"))
    print("wrote themes.png")


def settings_window():
    use("santra", "light")
    store = S.Settings(QSettings(str(TMP / "s.ini"), QSettings.IniFormat))
    store.set("theme", "santra")
    store.set_custom("santra", {"mode": "light"})
    shoot(S.SettingsWindow(store), "settings.png")


def trim_window():
    from shiftwheel.mediawin import TrimWindow
    use("santra", "dark")
    clip = TMP / "clip.mp4"
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
    w = TrimWindow(str(clip), notify, "trim")
    w._load_visuals()
    w.bar.set_range(0.8, 3.1)
    shoot(w, "trim.png", 3.0)


def id_card_window():
    from shiftwheel.printwin import IDCardWindow
    use("santra", "light")
    paths = []
    rng = np.random.default_rng(1)
    for name, color, ang in (("front", (235, 240, 250), 12), ("back", (250, 245, 230), -8)):
        card = np.array(make_card(name.upper(), color))
        bg = np.full((1500, 2000, 3), (92, 70, 55), np.uint8)
        bg = np.clip(bg.astype(int) + rng.integers(0, 25, bg.shape), 0, 255).astype(np.uint8)
        cx, cy, rad = 1000, 750, np.deg2rad(ang)
        pts = [[cx + (x * np.cos(rad) - y * np.sin(rad)) * k, cy + (x * np.sin(rad) + y * np.cos(rad)) * k]
               for (x, y), k in zip([(-650, -410), (650, -410), (650, 410), (-650, 410)], [1, 0.92, 0.95, 1.04])]
        f = TMP / f"IMG_{name}.jpg"
        Image.fromarray(_paste_warped(bg, card, pts)).save(f, quality=90)
        paths.append(str(f))
    shoot(IDCardWindow(paths, notify), "id-card.png", 4.0)


if __name__ == "__main__":
    theme_sheet()
    settings_window()
    trim_window()
    id_card_window()
