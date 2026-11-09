"""The radial drop menu that pops up under the cursor while you Shift+drag a file.

Rendering: the moment the menu opens we snapshot the screen behind it; a worker thread then
refracts that snapshot through the menu's shape (see liquid.py). Until that's ready (~60 ms)
a cheap frosted version is drawn, so the menu still appears instantly."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (QEasingCurve, QObject, QPoint, QPointF, QRectF, QRunnable, Qt,
                            QThreadPool, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from . import glass, themes, wheelshape
from .themes import Look, Palette
from .util import resolve_shortcuts, ui_family


@dataclass
class Item:
    label: str
    glyph: str = ""
    icon: str = ""          # Segoe Fluent Icons character (line icons)

    def __post_init__(self):
        if self.glyph and not self.icon:
            self.icon = FLUENT.get(self.label, "")
    run: Callable[[list[str]], None] | None = None
    key: str = ""
    hint: str = ""


# Segoe Fluent Icons / MDL2 code points for each tool (line-icon style)
FLUENT = {name: chr(cp) for name, cp in {
    "Compress": 0xE73F, "Resize": 0xE740, "Crop": 0xE7A8, "Edit": 0xE706, "Annotate": 0xE70F, "Redact": 0xED1A,
    "Add BG": 0xE91B, "Metadata": 0xE946, "Text": 0xE8D2, "OCR": 0xE8D2, "Split": 0xE8C6, "Trim": 0xE8C6,
    "Rotate": 0xE7AD, "Merge": 0xE81E, "Protect": 0xE72E, "Extract": 0xE896, "ID Card": 0xE779,
    "Passport": 0xE77B, "Scan": 0xEE6F, "Print": 0xE749, "Zip": 0xE7B8, "7Z": 0xE7B8, "GIF": 0xF4A9,
    "Snapshot": 0xE722, "Mute": 0xE74F, "Speed": 0xEC4A, "Normalize": 0xE9E9, "Copy path": 0xE71B,
    "Show": 0xE838, "SHA-256": 0xE928, "Duplicate": 0xF413, "Copy": 0xE8C8, "Move": 0xE8DE,
    "Terminal": 0xE756, "Float": 0xE718, "Share": 0xE72D, "QR code": 0xED14, "Collage": 0xF0E2,
    "Channels": 0xE995, "Bleep": 0xE767, "Organize": 0xE8A9, "Visualize": 0xE8D6, "Join": 0xE81E,
    "Create PDF": 0xE8A5, "Silence": 0xE8C6}.items()}

SIZE = 400          # window size (room for shadow + hover pop)
R_OUT = 158         # outer radius of petals
R_IN = 60           # inner radius of petals
R_HUB = 50          # hub radius
GAP_DEG = 3.2
CORNER = 10
SCALES = (0.85, 1.0, 1.15, 1.3)     # wheel size setting


def sector_path(c: QPointF, r0: float, r1: float, a0: float, a1: float) -> QPainterPath:
    """Annular sector between angles a0..a1 (degrees, Qt convention: 0 = 3 o'clock, CCW)."""
    path = QPainterPath()
    outer = QRectF(c.x() - r1, c.y() - r1, 2 * r1, 2 * r1)
    inner = QRectF(c.x() - r0, c.y() - r0, 2 * r0, 2 * r0)
    path.arcMoveTo(outer, a0)
    path.arcTo(outer, a0, a1 - a0)
    path.arcTo(inner, a1, -(a1 - a0))
    path.closeSubpath()
    return path


def angles(n: int, i: int, gap: float = GAP_DEG) -> tuple[float, float]:
    span = 360.0 / n
    start = 90 + span / 2 - (i + 1) * span   # first petal centred at 12 o'clock, clockwise
    return start + gap / 2, start + span - gap / 2


# ---------------------------------------------------------------- background render
class _RenderSig(QObject):
    done = Signal(int, int, QImage, bool)   # serial, petal count, image, is_light


class _RenderJob(QRunnable):
    def __init__(self, serial: int, n: int, backdrop, opacity: float = 0.65):
        super().__init__()
        self.serial, self.n, self.backdrop, self.opacity = serial, n, backdrop, opacity
        self.sig = _RenderSig()

    def run(self):
        try:
            from . import liquid
            c = SIZE / 2
            fields = [liquid.sdf_circle(SIZE, SIZE, c, c, R_HUB)]
            for i in range(self.n):
                a0, a1 = angles(self.n, i)
                fields.append(liquid.sdf_ring_sector(SIZE, SIZE, c, c, R_IN, R_OUT, a0, a1, CORNER))
            sdf = liquid.union(*fields)
            blur, tint = themes.frost(self.opacity)
            img, light = liquid.render(self.backdrop, sdf, liquid.GlassStyle(blur=blur, saturation=1.7, tint=tint))
            sh = liquid.shadow(sdf, spread=26, opacity=0.42 if light else 0.30, offset=(0, 8))
            sh.alpha_composite(img)
            try:
                self.sig.done.emit(self.serial, self.n, glass.qimage_from_pil(sh), light)
            except RuntimeError:
                pass
        except Exception:  # pragma: no cover - fall back to the painted glass
            import traceback
            traceback.print_exc()


ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")


def icon_family() -> str | None:
    from PySide6.QtGui import QFontDatabase
    fams = set(QFontDatabase.families())
    return next((f for f in ICON_FONTS if f in fams), None)


class RadialMenu(QWidget):
    activated = Signal(object, list)     # Item, paths
    dismissed = Signal()
    highlighted = Signal(int)            # a slice lit up (sounds)
    ring_changed = Signal(str)

    def __init__(self, build_rings: Callable[[list[str]], dict[str, list[Item]]],
                 describe: Callable[[list[str]], str]):
        super().__init__(None)
        self.build_rings = build_rings
        self.describe = describe
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint |
                            Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.resize(SIZE, SIZE)

        self.paths: list[str] = []
        self.rings: dict[str, list[Item]] = {}
        self.ring_names: list[str] = []
        self.ring_idx = 0
        self.hover = -1          # petal index, -2 = hub, -1 = none
        self.cursor_pos = QPointF(SIZE / 2, SIZE / 2)
        self.hub_text = ""
        self.backdrop: QPixmap | None = None     # blurred, for the instant fallback
        self._raw_backdrop = None                 # PIL image for the liquid renderer
        self.liquid: dict[int, QImage] = {}       # petal count -> rendered glass
        self.is_light = False
        self._serial = 0
        self.got_drag = False
        self.hub_armed = False
        self.click_mode = False  # opened from tray/menu instead of a drag
        self.look: Look = themes.resolve(themes.DEFAULT_THEME)
        self.pal: Palette = self.look.pal
        self.k = 1.0             # wheel size (1 = SIZE logical pixels)
        self.want_ring = ""      # ring to show first (the key that opened the menu)
        self.ring_hint = lambda name: ""   # e.g. "Ctrl", shown under the hub
        self._t = 1.0            # pop-in animation 0..1
        self._swap = 1.0         # ring-swap animation 0..1
        self.spring: list[float] = []   # per-petal hover amount 0..1 (eased every frame)
        self.hub_spring = 0.0

        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=190,
                                      easingCurve=QEasingCurve.OutBack)
        self.anim.valueChanged.connect(self._set_t)
        self.swap_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=220,
                                           easingCurve=QEasingCurve.OutCubic)
        self.swap_anim.valueChanged.connect(self._set_swap)
        self.hub_timer = QTimer(self, singleShot=True, interval=420, timeout=self.next_ring)
        self.frame = QTimer(self, interval=16, timeout=self._tick)   # 60 fps springs

    # ------------------------------------------------------------ show / hide
    def popup(self, pos: QPoint | None = None, paths: list[str] | None = None):
        pos = pos or QCursor.pos()
        S = self.win_size
        tl = pos - QPoint(S // 2, S // 2)
        scr = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        tl.setX(min(max(tl.x(), g.left()), g.right() - S))
        tl.setY(min(max(tl.y(), g.top()), g.bottom() - S))
        # snapshot what's underneath *before* we appear
        self._serial += 1
        self.liquid = {}
        try:
            if sys.platform == "darwin":
                # macOS captures "below the drag window": the drag picture never gets in
                raw = glass.grab_screen(tl.x(), tl.y(), S, S)
                if raw is None:
                    raise RuntimeError("capture failed")
                raw = raw.resize((SIZE, SIZE))
                from . import platform_mac
                print("menu: mac windows at cursor:", "; ".join(platform_mac.LAST_SWEEP), flush=True)
                if self.got_drag or paths is None:
                    # belt and braces: Finder's drag picture (icon + name label) sits on the
                    # cursor; erase that area — it ends up under the hub, blurred anyway
                    cx, cy = (pos.x() - tl.x()) / self.k, (pos.y() - tl.y()) / self.k
                    raw = glass.inpaint_rects(raw, [(cx - 70, cy - 64, cx + 70, cy + 64)])
                shot = QPixmap.fromImage(glass.qimage_from_pil(raw))
            else:
                with glass.hidden_drag_images() as hid:
                    shot = scr.grabWindow(0, tl.x() - g.left(), tl.y() - g.top(), S, S)
                if hid.hwnds:
                    print(f"menu: hid {len(hid.hwnds)} drag image(s) during capture: {'; '.join(hid.info)}", flush=True)
                elif hid.info:
                    print(f"menu: drag-image sweep: {'; '.join(hid.info)}", flush=True)
                raw = glass.pil_from_qimage(
                    shot.toImage().scaled(SIZE, SIZE, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                if sys.platform.startswith("linux") and paths is None:
                    # X11 drag icons (Thunar/GTK) sit on the cursor: erase that patch
                    cx, cy = pos.x() - tl.x(), pos.y() - tl.y()
                    hid.rects = [(pos.x() - 60, pos.y() - 60, pos.x() + 60, pos.y() + 60)]
                if hid.rects:
                    # belt and braces: erase where the drag picture was, in case it was captured anyway
                    k = SIZE / max(1, shot.width())
                    local = [(int((x0 - tl.x()) * k), int((y0 - tl.y()) * k), int((x1 - tl.x()) * k), int((y1 - tl.y()) * k))
                             for (x0, y0, x1, y1) in hid.rects]
                    raw = glass.inpaint_rects(raw, local)
                    shot = QPixmap.fromImage(glass.qimage_from_pil(raw))
            self._raw_backdrop = raw
            # always SIZE×SIZE logical pixels, like everything else the painter draws
            self.backdrop = glass.blur_pixmap(QPixmap.fromImage(glass.qimage_from_pil(raw)), 24)
        except Exception:
            self.backdrop = None
            self._raw_backdrop = None
        self.move(tl)
        self.hover = -1
        self.got_drag = False
        self.hub_armed = False  # drags start on the hub; don't flip until they leave it
        self.click_mode = paths is not None
        early = []
        if paths is None and sys.platform == "darwin":
            from . import platform_mac
            early = platform_mac.drag_files()
            if early:
                print(f"menu: {len(early)} file(s) from the drag pasteboard", flush=True)
        if paths is not None:
            self._load(paths)
        elif early:
            self._load(early)           # slices show at once; drop still comes via dragEnter
        else:
            self.paths, self.rings, self.ring_names = [], {}, []
            self.hub_text = "Drop here"
            for n in (4, 7):  # most common rings: render speculatively
                self._render(n)
        self._t = 0.0
        self._shape()
        # while dragging the menu must never take focus from Explorer; opened by click or
        # shortcut it takes the keyboard (arrows, Enter, 1–9, Esc)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, not self.click_mode)
        self.setAttribute(Qt.WA_ShowWithoutActivating, not self.click_mode)
        self.show()
        self.raise_()
        self.anim.start()
        self.frame.start()
        if self.click_mode:
            self.activateWindow()
            self.setFocus(Qt.ActiveWindowFocusReason)
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
            # behave like a popup: a click anywhere outside dismisses it
            QTimer.singleShot(0, self.grabMouse)

    @property
    def win_size(self) -> int:
        return int(round(SIZE * self.k))

    def set_look(self, look: Look | Palette, scale: float = 1.0):
        """Theme and wheel size; takes effect from the next popup (or now, if shown)."""
        if isinstance(look, Palette):       # a bare palette: keep the current shape
            look = themes.Look(self.look.theme, look, self.look.shape, self.look.ui, look.dark, self.look.accent,
                               self.look.opacity)
        if getattr(self, "look", None) is not None and self.look.opacity != look.opacity:
            self.liquid = {}                  # rendered at the old opacity
        self.look = look
        self.pal = look.pal
        self.k = min(1.6, max(0.6, float(scale)))
        self.resize(self.win_size, self.win_size)
        self.update()

    def _local(self, pos) -> QPointF:
        """Window position → the painter's SIZE×SIZE space."""
        return QPointF(pos.x() / self.k, pos.y() / self.k)

    def close_menu(self):
        if self.isVisible():
            self.hide()
            self.frame.stop()
            self.hub_timer.stop()
            self.dismissed.emit()

    def hideEvent(self, e):
        self.frame.stop()
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        super().hideEvent(e)

    def _render(self, n: int):
        if n <= 0 or n in self.liquid or self._raw_backdrop is None or not self._round_glass():
            return                        # only the round liquid-glass wheel uses the refraction
        self.liquid[n] = QImage()  # placeholder: in flight
        job = _RenderJob(self._serial, n, self._raw_backdrop, self.look.opacity)
        from .util import keep, release
        job.sig.done.connect(lambda *a, j=job: (release(j), self._rendered(*a)))
        QThreadPool.globalInstance().start(keep(job))

    def _rendered(self, serial: int, n: int, img: QImage, light: bool):
        if serial == self._serial:
            self.liquid[n] = img
            self.is_light = light
            self.update()

    def _load(self, paths: list[str]):
        paths = resolve_shortcuts(paths)
        self.paths = paths
        self.rings = {k: v for k, v in self.build_rings(paths).items() if v}
        self.ring_names = list(self.rings)
        self.ring_idx = self.ring_names.index(self.want_ring) if self.want_ring in self.ring_names else 0
        self.hub_text = self.describe(paths)
        for items in self.rings.values():
            self._render(len(items))
        self.spring = [0.0] * len(self.items)
        self._shape()
        self.update()

    def _shape(self):
        """No compositor (XFCE etc.): cut the window to the menu's outline."""
        if not glass.no_compositor():
            return
        c = QPointF(SIZE / 2, SIZE / 2)
        path = QPainterPath()
        path.addEllipse(c, R_HUB + 2, R_HUB + 2)
        n = len(self.items) or 0
        if n:
            for i in range(n):
                a0, a1 = angles(n, i)
                path = path.united(sector_path(c, R_IN - 2, R_OUT + 14, a0 - 1, a1 + 1))
        else:
            outer = QPainterPath()
            outer.addEllipse(c, R_OUT + 14, R_OUT + 14)
            path = path.united(outer)       # united, not added: odd-even fill would punch a hole
        if self.k != 1.0:
            from PySide6.QtGui import QTransform
            path = QTransform.fromScale(self.k, self.k).map(path)
        glass.apply_shape(self, path)

    def set_ring(self, name: str):
        """Jump to a ring by name (its key was pressed). Before the drag arrives, remember it."""
        self.want_ring = name
        if name in self.ring_names and self.ring_names[self.ring_idx] != name:
            self.ring_idx = self.ring_names.index(name) - 1
            self.next_ring()

    def next_ring(self):
        if len(self.ring_names) > 1:
            self.ring_idx = (self.ring_idx + 1) % len(self.ring_names)
            self.want_ring = self.ring_names[self.ring_idx]
            self.ring_changed.emit(self.want_ring)
            self.hover = -1
            self.spring = [0.0] * len(self.items)
            self._swap = 0.0
            self.swap_anim.start()
            self._shape()
            self.update()

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def _set_swap(self, v):
        self._swap = float(v)
        self.update()

    def _tick(self):
        moved = False
        for i in range(len(self.spring)):
            target = 1.0 if i == self.hover else 0.0
            v = self.spring[i]
            nv = v + (target - v) * 0.32
            if abs(nv - target) < 0.003:
                nv = target
            if nv != v:
                self.spring[i] = nv
                moved = True
        ht = 1.0 if self.hover == -2 else 0.0
        nh = self.hub_spring + (ht - self.hub_spring) * 0.3
        if abs(nh - ht) < 0.003:
            nh = ht
        if nh != self.hub_spring:
            self.hub_spring = nh
            moved = True
        if moved:
            self.update()

    # ------------------------------------------------------------ geometry
    @property
    def items(self) -> list[Item]:
        if not self.ring_names:
            return []
        return self.rings[self.ring_names[self.ring_idx]]

    def _angles(self, n: int, i: int) -> tuple[float, float]:
        return angles(n, i)

    def geom(self) -> tuple[float, float, float]:
        """(inner, outer, hub) radii for the current theme."""
        if self.pal.glass:
            return R_IN, R_OUT, R_HUB
        r_in = R_OUT * self.look.shape.inner
        return r_in, R_OUT, min(R_HUB, r_in - 8)

    def hit(self, pos: QPointF) -> int:
        c = QPointF(SIZE / 2, SIZE / 2)
        dx, dy = pos.x() - c.x(), c.y() - pos.y()
        d = math.hypot(dx, dy)
        r_in, r_out, r_hub = self.geom()
        if d <= r_hub + 4:
            return -2
        outline = self.look.shape.outline
        if not self.items:
            return -1
        if outline == "circle":
            if d > r_out + 30:
                return -1
        elif not wheelshape.inside(outline, c, r_out + 30, pos):
            return -1
        ang = math.degrees(math.atan2(dy, dx)) % 360
        n = len(self.items)
        rel = (90 + 180.0 / n - ang) % 360
        return int(rel // (360.0 / n)) % n

    def _set_hover(self, h: int, pos: QPointF | None = None):
        if pos is not None:
            self.cursor_pos = QPointF(pos)
        if h != self.hover:
            self.hover = h
            if h >= 0:
                self.hub_armed = True  # visited a petal: hovering the hub may now flip rings
                self.highlighted.emit(h)
            if h == -2 and self.hub_armed and len(self.ring_names) > 1:
                self.hub_timer.start()
            else:
                self.hub_timer.stop()
        self.update()

    # ------------------------------------------------------------ drag & drop
    @staticmethod
    def _local_paths(md) -> list[str]:
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and u.toLocalFile()]

    def dragEnterEvent(self, e):
        paths = self._local_paths(e.mimeData())
        if not paths:
            e.ignore()
            return
        self.got_drag = True
        if resolve_shortcuts(paths) != self.paths:
            self._load(paths)
        e.setDropAction(Qt.CopyAction)  # never let a Shift(=move) drop delete the source
        e.accept()

    def dragMoveEvent(self, e):
        pos = self._local(e.position())
        self._set_hover(self.hit(pos), pos)
        e.setDropAction(Qt.CopyAction)
        e.accept()

    def dragLeaveEvent(self, e):
        self._set_hover(-1)

    def dropEvent(self, e):
        idx = self.hit(self._local(e.position()))
        items = self.items
        if 0 <= idx < len(items):
            e.setDropAction(Qt.CopyAction)
            e.accept()
            item, paths = items[idx], list(self.paths)
            self.hide()
            # return to Explorer's drag loop immediately; do the work after
            QTimer.singleShot(0, lambda: self.activated.emit(item, paths))
        else:
            e.ignore()
            self.close_menu()

    # ------------------------------------------------------------ click mode
    def mouseMoveEvent(self, e):
        if self.click_mode:
            pos = self._local(e.position())
            self._set_hover(self.hit(pos), pos)

    def mouseReleaseEvent(self, e):
        if not self.click_mode:
            return
        if e.button() == Qt.RightButton:
            self.close_menu()
            return
        idx = self.hit(self._local(e.position()))
        if idx == -2:
            self.next_ring()
        elif 0 <= idx < len(self.items):
            item, paths = self.items[idx], list(self.paths)
            self.hide()
            QTimer.singleShot(0, lambda: self.activated.emit(item, paths))
        else:
            self.close_menu()

    def keyPressEvent(self, e):
        """Keyboard: arrows choose, Enter/Space apply, 1–9 pick directly, Tab switches ring,
        Esc cancels."""
        k, n = e.key(), len(self.items)
        if k == Qt.Key_Escape:
            self.close_menu()
        elif k in (Qt.Key_Tab, Qt.Key_Shift, Qt.Key_Backtab):
            self.next_ring()
        elif n and k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up):
            step = 1 if k in (Qt.Key_Right, Qt.Key_Down) else -1
            self._set_hover((self.hover + step) % n if self.hover >= 0 else (0 if step > 0 else n - 1))
        elif n and k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and 0 <= self.hover < n:
            self._activate(self.hover)
        elif n and Qt.Key_1 <= k <= Qt.Key_9 and k - Qt.Key_1 < n:
            self._activate(k - Qt.Key_1)

    def _activate(self, idx: int):
        item, paths = self.items[idx], list(self.paths)
        self.hide()
        QTimer.singleShot(0, lambda: self.activated.emit(item, paths))

    def leaveEvent(self, e):
        if self.click_mode:
            self._set_hover(-1)

    # ------------------------------------------------------------ painting
    def _text_colors(self) -> tuple[QColor, QColor, QColor | None]:
        pal = self.pal
        if pal.glass:                       # glass: whatever reads on the backdrop behind it
            if self.is_light:
                return QColor(28, 20, 44), QColor(28, 20, 44, 170), QColor(255, 255, 255, 120)
            return QColor(255, 255, 255), QColor(255, 255, 255, 190), QColor(0, 0, 0, 110)
        return pal.text, pal.text_dim, pal.text_shadow

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.scale(self.k, self.k)
        c = QPointF(SIZE / 2, SIZE / 2)
        t = self._t
        p.setOpacity(min(1.0, max(0.0, t * 1.5)))
        p.translate(c)
        s = 0.80 + 0.20 * t
        p.scale(s, s)
        p.translate(-c)
        self.paint_wheel(p)

    def paint_wheel(self, p: QPainter):
        """Everything inside the SIZE×SIZE square (also used for the Settings previews)."""
        pal = self.pal
        c = QPointF(SIZE / 2, SIZE / 2)
        items = self.items
        n = len(items)
        img = None
        if pal.glass:
            img = (self.liquid.get(n) if n else (self.liquid.get(4) or self.liquid.get(7))) if self._round_glass() else None
            if img is not None and not img.isNull():
                p.drawImage(0, 0, img)
            else:
                img = None
                self._paint_fallback(p, c, n)
        else:
            p.save()
            p.setOpacity(self.look.opacity)
            self._paint_disc(p, c, n)
            p.restore()

        fg, fg_dim, shadow_col = self._text_colors()
        rot = (1 - self._swap) * -22
        r_in, r_out, _ = self.geom()
        label_r = (R_IN + R_OUT) / 2 if pal.glass else r_in + (r_out - r_in) * self.look.shape.label_r
        for i, it in enumerate(items):
            h = self.spring[i] if i < len(self.spring) else 0.0
            if h > 0.001:
                self._paint_hover(p, c, n, i, h, img)
            lift = h * 4 if self._lifts() else 0.0
            ang = math.degrees(wheelshape.center_angle(n, i))
            self._petal_label(p, c, it, ang + rot, label_r + lift, h, fg, shadow_col)
        if not n and self.paths:
            self._paint_unsupported(p, c, fg, fg_dim, shadow_col)

        self._paint_hub(p, c, fg, fg_dim, shadow_col)

    def _lifts(self) -> bool:
        return self.pal.glass or self.look.shape.lift

    def _round_glass(self) -> bool:
        return self.pal.glass and self.look.shape.outline == "circle"

    def _glass_slice(self, n: int, i: int, grow: float = 0.0) -> QPainterPath:
        """A Liquid glass slice: round sectors, or the chosen outline's slices."""
        c = QPointF(SIZE / 2, SIZE / 2)
        if self._round_glass():
            a0, a1 = angles(n, i)
            return sector_path(c, R_IN - grow, R_OUT + grow, a0, a1)
        return wheelshape.slices(self.look.shape.outline, n, c, R_IN, R_OUT, 4.0, 10.0)[i]

    def _slices(self, n: int) -> list[QPainterPath]:
        sh = self.look.shape
        r_in, r_out, _ = self.geom()
        return wheelshape.slices(sh.outline, n, QPointF(SIZE / 2, SIZE / 2), r_in, r_out, sh.gap, sh.corner)

    def _paint_unsupported(self, p: QPainter, c: QPointF, fg: QColor, fg_dim: QColor,
                           shadow_col: QColor | None):
        """Nothing to offer: say so in the top band, clear of the cursor and the drag image."""
        ext = Path(self.paths[0]).suffix.lower() or "this file"
        f = QFont(ui_family(True))
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        r_mid = (R_IN + R_OUT) / 2
        self._text(p, QRectF(c.x() - R_OUT, c.y() - r_mid - 18, 2 * R_OUT, 18),
                   f"Can't convert {ext}", fg, shadow_col)
        f.setPixelSize(10)
        f.setBold(False)
        p.setFont(f)
        self._text(p, QRectF(c.x() - R_OUT, c.y() - r_mid + 1, 2 * R_OUT, 16),
                   "Images · PDF · Word · Text", fg_dim, None)

    def _paint_fallback(self, p: QPainter, c: QPointF, n: int):
        """The glass disc without a captured backdrop. It doesn't change while the wheel is open
        (hover effects are drawn on top), so it is rendered once and reused: ~10 ms → <1 ms a frame."""
        dev = p.device()
        dpr = dev.devicePixelRatioF() if dev is not None else 1.0
        key = (n, self.backdrop.cacheKey() if self.backdrop is not None else 0, id(self.look), round(dpr, 2))
        if getattr(self, "_fallback_key", None) != key:
            pm = QPixmap(int(SIZE * dpr), int(SIZE * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.setRenderHint(QPainter.SmoothPixmapTransform)
            self._paint_fallback_layer(q, c, n)
            q.end()
            self._fallback, self._fallback_key = pm, key
        p.drawPixmap(0, 0, self._fallback)

    def _paint_fallback_layer(self, p: QPainter, c: QPointF, n: int):
        hub = QPainterPath()
        hub.addEllipse(c, R_HUB, R_HUB)
        _, tint = themes.frost(self.look.opacity)
        glass.paint_glass(p, hub, self.backdrop, QPointF(0, 0), tint=QColor(22, 18, 34, int(80 + 200 * (tint - 0.385))),
                          rainbow_alpha=150, highlight=1.3)
        for i in range(n):
            glass.paint_glass(p, self._glass_slice(n, i), self.backdrop, QPointF(0, 0),
                              tint=QColor(22, 18, 34, int(62 + 200 * (tint - 0.385))), rainbow_alpha=140)

    def _paint_disc(self, p: QPainter, c: QPointF, n: int):
        """Every non-glass theme: shadow and halo, the backing (frosted or solid), the slices,
        dividers, and the hub. Colours from the palette, geometry from the shape."""
        pal, sh = self.pal, self.look.shape
        r_in, r_out, r_hub = self.geom()
        R = r_out + sh.rim
        backing = wheelshape.outline(sh.outline, c, R)
        p.save()
        p.setPen(Qt.NoPen)
        if pal.shadow is not None:
            p.save()
            p.translate(0, 6)
            for grow, a in ((10, 0.35), (5, 0.6), (1, 1.0)):
                col = QColor(pal.shadow)
                col.setAlphaF(col.alphaF() * a * 0.55)
                p.fillPath(wheelshape.outline(sh.outline, c, R + grow), col)
            p.restore()
        if pal.glow is not None:
            for grow, a in ((16, 0.25), (9, 0.5), (4, 1.0)):
                col = QColor(pal.glow)
                col.setAlphaF(col.alphaF() * a)
                p.fillPath(wheelshape.outline(sh.outline, c, R + grow), col)
        if pal.frost and self.backdrop is not None:
            p.save()
            p.setClipPath(backing)
            p.drawPixmap(0, 0, self.backdrop)
            p.restore()
        if pal.base is not None:
            p.fillPath(backing, pal.base)
        if pal.base_edge is not None:
            self._stroke(p, lambda: p.drawPath(wheelshape.outline(sh.outline, c, R - 0.5)), pal.base_edge, 1.0,
                         pal.neon)

        slices = self._slices(n)
        if not n:
            slices = [wheelshape.ring(sh.outline, c, r_in, r_out)]
        whole = QRadialGradient(c, r_out)
        whole.setColorAt(r_in / r_out, pal.slice_in)
        if pal.slice_mid is not None:
            whole.setColorAt(r_in / r_out + (1 - r_in / r_out) * 0.68, pal.slice_mid)
        whole.setColorAt(1.0, pal.slice_out)
        edge = QPen(pal.slice_edge, pal.slice_edge_w) if pal.slice_edge is not None else Qt.NoPen
        for path in slices:
            if pal.tile_gradient:          # glossy tiles: each slice lit from its own centre
                b = path.boundingRect()
                g = QRadialGradient(b.center(), max(b.width(), b.height()) / 2)
                g.setColorAt(0.0, pal.slice_in)
                if pal.slice_mid is not None:
                    g.setColorAt(0.68, pal.slice_mid)
                g.setColorAt(1.0, pal.slice_out)
                p.setBrush(g)
            else:
                p.setBrush(whole)
            p.setPen(edge)
            p.drawPath(path)

        if pal.divider is not None and n > 1 and sh.gap <= 0:
            def lines():
                for i in range(n):
                    a = wheelshape.center_angle(n, i) + math.pi / n
                    far = r_out * (1.0 if sh.outline == "circle" else 1.45)
                    p.drawLine(QPointF(c.x() + r_in * math.cos(a), c.y() - r_in * math.sin(a)),
                               QPointF(c.x() + far * math.cos(a), c.y() - far * math.sin(a)))
            p.save()
            p.setClipPath(wheelshape.outline(sh.outline, c, r_out + 0.5))
            self._stroke(p, lines, pal.divider, pal.divider_w, pal.neon, cap=Qt.FlatCap)
            p.restore()
        if pal.divider is not None and pal.inner_ring:
            self._stroke(p, lambda: p.drawEllipse(c, r_in, r_in), pal.divider, pal.divider_w, False)

        if pal.hub is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(pal.hub)
            p.drawEllipse(c, r_hub, r_hub)
        if pal.hub_edge is not None:
            self._stroke(p, lambda: p.drawEllipse(c, r_hub - 0.5, r_hub - 0.5), pal.hub_edge, 1.5, pal.neon)
        p.restore()

    @staticmethod
    def _stroke(p: QPainter, draw, col: QColor, width: float, glow: bool, cap=Qt.RoundCap):
        """Draw with `col`; neon themes get a soft bloom underneath."""
        p.save()
        p.setBrush(Qt.NoBrush)
        if glow:
            for w, a in ((width + 7, 0.10), (width + 3.5, 0.22)):
                bloom = QColor(col)
                bloom.setAlphaF(col.alphaF() * a)
                p.setPen(QPen(bloom, w, Qt.SolidLine, cap))
                draw()
        p.setPen(QPen(col, width, Qt.SolidLine, cap))
        draw()
        p.restore()

    def _paint_hover(self, p: QPainter, c: QPointF, n: int, i: int, h: float, img: QImage | None):
        pal = self.pal
        mid = wheelshape.center_angle(n, i)
        r_in, r_out, _ = self.geom()
        r_mid = (r_in + r_out) / 2
        pc = QPointF(c.x() + r_mid * math.cos(mid), c.y() - r_mid * math.sin(mid))
        lift = self._lifts()
        k = 1 + 0.07 * h if lift else 1.0     # elastic "pop" towards the cursor
        push = 6 * h if lift else 0.0
        off = QPointF(push * math.cos(mid), -push * math.sin(mid))
        if pal.glass:
            path = self._glass_slice(n, i, grow=1.0)
        else:
            path = self._slices(n)[i]
        p.save()
        p.translate(pc + off)
        p.scale(k, k)
        p.translate(-pc)
        if pal.glass:
            # the slice's own refraction, enlarged
            if img is not None:
                p.save()
                p.setClipPath(path)
                p.drawImage(0, 0, img)
                p.restore()
            else:
                glass.paint_glass(p, path, self.backdrop, QPointF(0, 0), tint=QColor(22, 18, 34, 62),
                                  rainbow_alpha=140)
        # lit in the highlight colour, so it's obvious which slice the file will land on
        # (the drag picture covers part of it)
        g = QLinearGradient(c, QPointF(c.x() + r_out * math.cos(mid), c.y() - r_out * math.sin(mid)))
        a, b = QColor(pal.hover_in), QColor(pal.hover_out)
        a.setAlphaF(a.alphaF() * h * pal.hover_alpha)
        b.setAlphaF(b.alphaF() * h * pal.hover_alpha)
        g.setColorAt(0.0, a)
        g.setColorAt(1.0, b)
        p.fillPath(path, g)
        if pal.hover_edge is not None:
            col = QColor(pal.hover_edge)
            col.setAlphaF(col.alphaF() * h)
            p.setPen(QPen(col, pal.slice_edge_w))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        if pal.neon:
            self._stroke(p, lambda: p.drawPath(path), QColor(pal.hover_in), 1.4, True)
        p.restore()
        if pal.arc is not None and self.look.shape.outline == "circle":
            # a short accent arc on the rim, the "you are here" marker
            col = QColor(pal.arc)
            col.setAlphaF(col.alphaF() * h)
            rim = 7.0 if pal.glass else self.look.shape.rim
            r = r_out + max(2.0, rim / 2)
            box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            span = 360.0 / n
            a0 = math.degrees(mid) - span / 2
            p.save()
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, int((a0 + 3) * 16), int((span - 6) * 16))
            p.restore()

    def _hub_lines(self) -> tuple[str, str]:
        items = self.items
        hov = items[self.hover] if 0 <= self.hover < len(items) else None
        if hov is not None:
            return (hov.label.upper() if hov.glyph or hov.icon else hov.label), (hov.hint or "")
        top = self.hub_text
        if len(self.ring_names) > 1:
            other = self.ring_names[(self.ring_idx + 1) % len(self.ring_names)]
            key = self.ring_hint(other)
            return top, f"{key} · {other.upper()}" if key else f"→ {other.upper()}"
        return top, (self.ring_names[self.ring_idx].upper() if self.ring_names else "")

    def _paint_hub(self, p: QPainter, c: QPointF, fg: QColor, fg_dim: QColor, shadow_col: QColor | None):
        pal, sh = self.pal, self.look.shape
        _, _, r_hub = self.geom()
        top, sub = self._hub_lines()
        if pal.glass:
            p.setPen(glass.iridescent_pen(c, 1.2, 150, angle=60))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r_hub - 0.5, r_hub - 0.5)
        if pal.hub_text is not None:
            fg = pal.hub_text
            fg_dim = QColor(fg.red(), fg.green(), fg.blue(), 165)
            shadow_col = None
        f = QFont(sh.font or ui_family(True))
        if not pal.glass and sh.hub_label == "pill" and pal.pill is not None:
            # Centre label: a small frosted capsule with one line of text
            f.setPixelSize(15 if not (self.hover >= 0 and self.items[self.hover].glyph) else 12)
            f.setWeight(QFont.DemiBold)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
            p.setFont(f)
            fm = p.fontMetrics()
            text = fm.elidedText(top, Qt.ElideRight, int(2 * r_hub - 26))
            w = min(2 * r_hub - 8, max(92.0, fm.horizontalAdvance(text) + 26))
            pill = QRectF(c.x() - w / 2, c.y() - 21, w, 42)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 14))
            p.drawRoundedRect(pill.translated(0, 2), 21, 21)
            p.setBrush(pal.pill)
            p.setPen(QPen(pal.pill_edge, 1) if pal.pill_edge is not None else Qt.NoPen)
            p.drawRoundedRect(pill, 21, 21)
            self._text(p, pill, text, fg, None)
            if sub and self.hover < 0:
                f.setPixelSize(9)
                f.setWeight(QFont.Medium)
                p.setFont(f)
                self._text(p, QRectF(c.x() - r_hub, pill.bottom() + 2, 2 * r_hub, 14), sub, fg_dim, None)
            return
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        rect_top = QRectF(c.x() - r_hub + 4, c.y() - 21, 2 * r_hub - 8, 20)
        self._text(p, rect_top, top, fg, shadow_col)
        f.setPixelSize(10)
        f.setBold(False)
        p.setFont(f)
        self._text(p, QRectF(c.x() - r_hub + 6, c.y() + 2, 2 * r_hub - 12, 28), sub, fg_dim, None,
                   Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap)

    @staticmethod
    def _text(p: QPainter, r: QRectF, text: str, col: QColor, shadow: QColor | None,
              flags=Qt.AlignCenter):
        if shadow is not None:
            p.setPen(shadow)
            p.drawText(r.translated(0, 1), flags, text)
        p.setPen(col)
        p.drawText(r, flags, text)

    def _petal_label(self, p: QPainter, c: QPointF, it: Item, ang: float, r: float,
                     h: float, fg: QColor, shadow_col: QColor | None):
        sh = self.look.shape
        rad = math.radians(ang)
        push = 6 * h if self._lifts() else 0.0
        pt = QPointF(c.x() + (r + push) * math.cos(rad), c.y() - (r + push) * math.sin(rad))
        p.save()
        p.setOpacity(p.opacity() * (0.25 + 0.75 * self._swap))
        lit = h > 0.5
        col = (QColor(255, 255, 255) if self.pal.glass else self.pal.hover_text) if lit else fg
        shadow = None if lit and not self.pal.glass else shadow_col
        family = sh.font or ui_family(True)
        icon_font = icon_family() if (it.icon and sh.icons == "fluent" and not self.pal.glass) else None
        if it.glyph or icon_font:
            if icon_font:
                fi = QFont(icon_font)
                fi.setPixelSize(int(sh.icon_px + 2 * h))
                p.setFont(fi)
                self._text(p, QRectF(pt.x() - 30, pt.y() - sh.icon_px - 6, 60, sh.icon_px + 4), it.icon, col,
                           None, Qt.AlignHCenter | Qt.AlignBottom)
            else:
                f = QFont(family)
                f.setPixelSize(int(18 + 3 * h))
                p.setFont(f)
                self._text(p, QRectF(pt.x() - 30, pt.y() - 24, 60, 24), it.glyph, col, shadow,
                           Qt.AlignHCenter | Qt.AlignBottom)
            f = QFont(family)
            f.setPixelSize(sh.tool_px if not self.pal.glass else 10)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
            p.setFont(f)
            self._text(p, QRectF(pt.x() - 46, pt.y() + 1, 92, 18), it.label.upper(), col, shadow)
        else:
            f = QFont(family)
            px = 14 if self.pal.glass else sh.label_px
            f.setPixelSize(int(px + 2 * h * (1 if self._lifts() else 0)))
            f.setWeight(QFont.DemiBold if not self.pal.glass else QFont.Bold)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
            p.setFont(f)
            self._text(p, QRectF(pt.x() - 46, pt.y() - 14, 92, 28), it.label, col, shadow)
        p.restore()


def render_preview(look, items: list[Item], hover: int = -1, hub_text: str = "1.2 MB",
                   rings: tuple[str, ...] = ("Convert", "Tools"), backdrop: QPixmap | None = None,
                   size: int = 200) -> QPixmap:
    """A still of the wheel (Settings → theme gallery, docs). `look`: a Look or a Palette."""
    from PySide6.QtGui import QGuiApplication
    m = RadialMenu(lambda ps: {}, lambda ps: hub_text)
    m.set_look(look)
    m.rings = {name: (items if i == 0 else [Item("·")]) for i, name in enumerate(rings)}
    m.ring_names = list(m.rings)
    m.hub_text = hub_text
    m.hover = hover
    m.spring = [1.0 if i == hover else 0.0 for i in range(len(items))]
    m.backdrop = backdrop
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.scale(size / SIZE, size / SIZE)
    m.paint_wheel(p)
    p.end()
    m.deleteLater()
    return pm
