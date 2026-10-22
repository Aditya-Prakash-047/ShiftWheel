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

from . import glass, themes
from .themes import Palette
from .util import resolve_shortcuts, ui_family


@dataclass
class Item:
    label: str
    glyph: str = ""
    run: Callable[[list[str]], None] | None = None
    key: str = ""
    hint: str = ""


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
    def __init__(self, serial: int, n: int, backdrop):
        super().__init__()
        self.serial, self.n, self.backdrop = serial, n, backdrop
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
            img, light = liquid.render(self.backdrop, sdf, liquid.GlassStyle())
            sh = liquid.shadow(sdf, spread=26, opacity=0.42 if light else 0.30, offset=(0, 8))
            sh.alpha_composite(img)
            try:
                self.sig.done.emit(self.serial, self.n, glass.qimage_from_pil(sh), light)
            except RuntimeError:
                pass
        except Exception:  # pragma: no cover - fall back to the painted glass
            import traceback
            traceback.print_exc()


class RadialMenu(QWidget):
    activated = Signal(object, list)     # Item, paths
    dismissed = Signal()

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
        self.pal: Palette = themes.palette(themes.DEFAULT_THEME)
        self.k = 1.0             # wheel size (1 = SIZE logical pixels)
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
        self.show()
        self.raise_()
        self.anim.start()
        self.frame.start()
        if self.click_mode:
            # behave like a popup: a click anywhere outside dismisses it
            QTimer.singleShot(0, self.grabMouse)

    @property
    def win_size(self) -> int:
        return int(round(SIZE * self.k))

    def set_look(self, pal: Palette, scale: float = 1.0):
        """Theme palette and wheel size; takes effect from the next popup (or now, if shown)."""
        self.pal = pal
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
        if n <= 0 or n in self.liquid or self._raw_backdrop is None or not self.pal.glass:
            return                        # only the liquid-glass theme uses the refraction
        self.liquid[n] = QImage()  # placeholder: in flight
        job = _RenderJob(self._serial, n, self._raw_backdrop)
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
        self.ring_idx = 0
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

    def next_ring(self):
        if len(self.ring_names) > 1:
            self.ring_idx = (self.ring_idx + 1) % len(self.ring_names)
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

    def hit(self, pos: QPointF) -> int:
        c = QPointF(SIZE / 2, SIZE / 2)
        dx, dy = pos.x() - c.x(), c.y() - pos.y()
        d = math.hypot(dx, dy)
        if d <= R_HUB + 4:
            return -2
        if d > R_OUT + 30 or not self.items:
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
        if e.key() == Qt.Key_Escape:
            self.close_menu()
        elif e.key() in (Qt.Key_Tab, Qt.Key_Shift):
            self.next_ring()

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
            img = self.liquid.get(n) if n else (self.liquid.get(4) or self.liquid.get(7))
            if img is not None and not img.isNull():
                p.drawImage(0, 0, img)
            else:
                img = None
                self._paint_fallback(p, c, n)
        else:
            self._paint_disc(p, c, n)

        fg, fg_dim, shadow_col = self._text_colors()
        rot = (1 - self._swap) * -22
        for i, it in enumerate(items):
            a0, a1 = angles(n, i, self._gap())
            h = self.spring[i] if i < len(self.spring) else 0.0
            if h > 0.001:
                self._paint_hover(p, c, a0, a1, h, img)
            lift = h * 4 if pal.pop or pal.glass else 0.0
            self._petal_label(p, c, it, (a0 + a1) / 2 + rot, (R_IN + R_OUT) / 2 + lift, h, fg, shadow_col)
        if not n and self.paths:
            self._paint_unsupported(p, c, fg, fg_dim, shadow_col)

        self._paint_hub(p, c, fg, fg_dim, shadow_col)

    def _gap(self) -> float:
        return GAP_DEG if self.pal.glass else self.pal.gap

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
        hub = QPainterPath()
        hub.addEllipse(c, R_HUB, R_HUB)
        glass.paint_glass(p, hub, self.backdrop, QPointF(0, 0), tint=QColor(22, 18, 34, 80),
                          rainbow_alpha=150, highlight=1.3)
        for i in range(n):
            a0, a1 = angles(n, i)
            glass.paint_glass(p, sector_path(c, R_IN, R_OUT, a0, a1), self.backdrop, QPointF(0, 0),
                              tint=QColor(22, 18, 34, 62), rainbow_alpha=140)

    def _paint_disc(self, p: QPainter, c: QPointF, n: int):
        """Every non-glass theme: shadow and halo, the disc (frosted or solid), the slices,
        dividers, and the hub plate. All colours come from the palette."""
        pal = self.pal
        R = R_OUT + pal.rim
        p.save()
        p.setPen(Qt.NoPen)
        if pal.shadow is not None:
            sh = QRadialGradient(QPointF(c.x(), c.y() + 8), R + 22)
            col = QColor(pal.shadow)
            sh.setColorAt((R - 8) / (R + 22), col)
            col.setAlpha(0)
            sh.setColorAt(1.0, col)
            p.setBrush(sh)
            p.drawEllipse(QPointF(c.x(), c.y() + 8), R + 22, R + 22)
        if pal.glow is not None:
            halo = QRadialGradient(c, R + 20)
            col = QColor(pal.glow)
            halo.setColorAt(R / (R + 20) * 0.96, col)
            col.setAlpha(0)
            halo.setColorAt(1.0, col)
            p.setBrush(halo)
            p.drawEllipse(c, R + 20, R + 20)
        disc = QPainterPath()
        disc.addEllipse(c, R, R)
        if pal.frost and self.backdrop is not None:
            p.save()
            p.setClipPath(disc)
            p.drawPixmap(0, 0, self.backdrop)
            p.restore()
        if pal.base is not None:
            p.fillPath(disc, pal.base)
        if pal.base_edge is not None:
            self._stroke(p, lambda: p.drawEllipse(c, R - 0.5, R - 0.5), pal.base_edge, 1.2, pal.neon)

        gap = self._gap()
        slices = [sector_path(c, R_IN, R_OUT, *angles(n, i, gap)) for i in range(n)]
        if not n:
            ring = QPainterPath()
            ring.addEllipse(c, R_OUT, R_OUT)
            hole = QPainterPath()
            hole.addEllipse(c, R_IN, R_IN)
            slices.append(ring.subtracted(hole))
        shade = QRadialGradient(c, R_OUT)
        shade.setColorAt(R_IN / R_OUT, pal.slice_in)
        shade.setColorAt(1.0, pal.slice_out)
        p.setBrush(shade)
        p.setPen(QPen(pal.slice_edge, 1) if pal.slice_edge is not None else Qt.NoPen)
        for path in slices:
            p.drawPath(path)

        if pal.divider is not None and n > 1:
            def lines():
                for i in range(n):
                    a = math.radians(angles(n, i, 0)[0])
                    p.drawLine(QPointF(c.x() + R_IN * math.cos(a), c.y() - R_IN * math.sin(a)),
                               QPointF(c.x() + (R_OUT + 0.5) * math.cos(a), c.y() - (R_OUT + 0.5) * math.sin(a)))
            self._stroke(p, lines, pal.divider, pal.divider_w, pal.neon, cap=Qt.FlatCap)
        if pal.divider is not None and pal.inner_ring:
            self._stroke(p, lambda: p.drawEllipse(c, R_IN, R_IN), pal.divider, pal.divider_w, False)

        if pal.hub is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(pal.hub)
            p.drawEllipse(c, R_HUB, R_HUB)
        if pal.hub_edge is not None:
            self._stroke(p, lambda: p.drawEllipse(c, R_HUB - 0.5, R_HUB - 0.5), pal.hub_edge, 1.5, pal.neon)
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

    def _paint_hover(self, p: QPainter, c: QPointF, a0: float, a1: float, h: float, img: QImage | None):
        pal = self.pal
        mid = math.radians((a0 + a1) / 2)
        r_mid = (R_IN + R_OUT) / 2
        pc = QPointF(c.x() + r_mid * math.cos(mid), c.y() - r_mid * math.sin(mid))
        lift = pal.pop or pal.glass
        k = 1 + 0.07 * h if lift else 1.0     # elastic "pop" towards the cursor
        push = 6 * h if lift else 0.0
        off = QPointF(push * math.cos(mid), -push * math.sin(mid))
        path = sector_path(c, R_IN - 1, R_OUT + 1, a0, a1) if lift else sector_path(c, R_IN, R_OUT, a0, a1)
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
        g = QLinearGradient(c, QPointF(c.x() + R_OUT * math.cos(mid), c.y() - R_OUT * math.sin(mid)))
        a, b = QColor(pal.hover_in), QColor(pal.hover_out)
        a.setAlphaF(a.alphaF() * h * pal.hover_alpha)
        b.setAlphaF(b.alphaF() * h * pal.hover_alpha)
        g.setColorAt(0.0, a)
        g.setColorAt(1.0, b)
        p.fillPath(path, g)
        if pal.neon:
            self._stroke(p, lambda: p.drawPath(path), QColor(pal.hover_in), 1.4, True)
        p.restore()
        if pal.arc is not None:
            # a short accent arc on the rim, the "you are here" marker
            col = QColor(pal.arc)
            col.setAlphaF(col.alphaF() * h)
            r = R_OUT + max(2.0, pal.rim / 2)
            box = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            p.save()
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, int((a0 + 2) * 16), int((a1 - a0 - 4) * 16))
            p.restore()

    def _paint_hub(self, p: QPainter, c: QPointF, fg: QColor, fg_dim: QColor, shadow_col: QColor | None):
        pal = self.pal
        if pal.glass:
            p.setPen(glass.iridescent_pen(c, 1.2, 150, angle=60))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, R_HUB - 0.5, R_HUB - 0.5)
        elif pal.pill is not None:
            pill = QRectF(c.x() - R_HUB + 6, c.y() - 23, 2 * R_HUB - 12, 46)
            g = QLinearGradient(pill.topLeft(), pill.bottomLeft())
            g.setColorAt(0.0, pal.pill[0])
            g.setColorAt(1.0, pal.pill[1])
            p.setPen(QPen(QColor(255, 255, 255, 170), 1))
            p.setBrush(g)
            p.drawRoundedRect(pill, 23, 23)
        if pal.hub_text is not None:
            fg = pal.hub_text
            fg_dim = QColor(fg.red(), fg.green(), fg.blue(), 175)
            shadow_col = None

        items = self.items
        hov = items[self.hover] if 0 <= self.hover < len(items) else None
        if hov is not None:
            top, sub = hov.label if not hov.glyph else hov.label.title(), hov.hint or ""
        else:
            ring_name = self.ring_names[self.ring_idx] if self.ring_names else ""
            top = self.hub_text
            if len(self.ring_names) > 1:
                other = self.ring_names[(self.ring_idx + 1) % len(self.ring_names)]
                sub = f"⇧ {other.upper()}"
            else:
                sub = ring_name.upper()
        f = QFont(ui_family(True))
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        rect_top = QRectF(c.x() - R_HUB + 4, c.y() - 21, 2 * R_HUB - 8, 20)
        self._text(p, rect_top, top, fg, shadow_col)
        f.setPixelSize(10)
        f.setBold(False)
        p.setFont(f)
        self._text(p, QRectF(c.x() - R_HUB + 6, c.y() + 2, 2 * R_HUB - 12, 28), sub, fg_dim, None,
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
        rad = math.radians(ang)
        push = 6 * h if self.pal.pop or self.pal.glass else 0.0
        pt = QPointF(c.x() + (r + push) * math.cos(rad), c.y() - (r + push) * math.sin(rad))
        p.save()
        p.setOpacity(p.opacity() * (0.25 + 0.75 * self._swap))
        lit = h > 0.5
        col = (QColor(255, 255, 255) if self.pal.glass else self.pal.hover_text) if lit else fg
        shadow = None if lit and not self.pal.glass else shadow_col
        f = QFont(ui_family(True))
        if it.glyph:
            f.setPixelSize(int(18 + 3 * h))
            p.setFont(f)
            self._text(p, QRectF(pt.x() - 30, pt.y() - 24, 60, 24), it.glyph, col, shadow,
                       Qt.AlignHCenter | Qt.AlignBottom)
            f.setPixelSize(10)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.7)
            p.setFont(f)
            self._text(p, QRectF(pt.x() - 42, pt.y() + 1, 84, 16), it.label.upper(), col, shadow)
        else:
            f.setPixelSize(int(14 + 2 * h))
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.9)
            p.setFont(f)
            self._text(p, QRectF(pt.x() - 42, pt.y() - 12, 84, 24), it.label, col, shadow)
        p.restore()


def render_preview(pal: Palette, items: list[Item], hover: int = -1, hub_text: str = "1.2 MB",
                   rings: tuple[str, ...] = ("Convert", "Tools"), backdrop: QPixmap | None = None,
                   size: int = 200) -> QPixmap:
    """A still of the wheel in `pal` (Settings → theme gallery, docs)."""
    from PySide6.QtGui import QGuiApplication
    m = RadialMenu(lambda ps: {}, lambda ps: hub_text)
    m.pal = pal
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
