"""Tool windows added to match Santra: Collage, Organize PDF pages, Crop / Split / Redact
video, audio Channels / Bleep / Visualizer, and metadata editing. Engines: extras.py."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox)

from . import extras as X
from . import media as M
from .convert import open_pdf, open_preview
from .glass import qimage_from_pil
from .mediawin import RangeBar
from .tools import CropView, ToolWindow, section, slider, slider_row, toggle_row
from .window import ImageView


def _frame_label(min_h: int = 300) -> QLabel:
    lab = QLabel()
    lab.setAlignment(Qt.AlignCenter)
    lab.setMinimumHeight(min_h)
    lab.setStyleSheet("background: rgba(0,0,0,0.25); border-radius: 10px;")
    return lab


# ================================================================ COLLAGE
class CollageWindow(ToolWindow):
    tool_name = "Collage"
    SIZES = [("Square", (2400, 2400)), ("Landscape", (3000, 2000)), ("Portrait", (2000, 3000)),
             ("Story 9:16", (1080, 1920)), ("Wide 16:9", (1920, 1080))]
    BGS = ["#ffffff", "#f4f4f4", "#000000", "#1f2229", "#ff5200", "transparent"]

    def __init__(self, paths, notify):
        super().__init__("Make a Collage", paths, notify, size=(980, 760))
        if len(self.paths) < 2:
            raise ValueError("Pick two or more images for a collage.")
        self.thumbs = [open_preview(p, 700) for p in self.paths]
        self.bg = self.BGS[0]
        self.view = _frame_label(380)
        self.body.addWidget(self.view, 1)
        g = QGridLayout()
        g.addWidget(QLabel("Layout"), 0, 0)
        row, self.layout_grp = toggle_row([n for _, n in X.COLLAGE_LAYOUTS])
        g.addLayout(row, 0, 1, 1, 2)
        g.addWidget(QLabel("Size"), 1, 0)
        row, self.size_grp = toggle_row([n for n, _ in self.SIZES])
        g.addLayout(row, 1, 1, 1, 2)
        self.spacing = slider(0, 120, 24)
        slider_row(g, 2, "Spacing", self.spacing, lambda v: f"{v} px")
        self.corners = slider(0, 120, 24)
        slider_row(g, 3, "Corners", self.corners, lambda v: f"{v} px")
        g.addWidget(QLabel("Background"), 4, 0)
        bg = QHBoxLayout()
        for c in self.BGS:
            b = QPushButton("" if c != "transparent" else "None")
            b.setObjectName("swatch" if c != "transparent" else "")
            if c != "transparent":
                b.setStyleSheet(f"background: {c};")
            b.clicked.connect(lambda _=False, c=c: self._bg(c))
            bg.addWidget(b)
        more = QPushButton("Custom…")
        more.clicked.connect(lambda: (lambda col: col.isValid() and self._bg(col.name()))(QColorDialog.getColor()))
        bg.addWidget(more)
        bg.addStretch(1)
        g.addLayout(bg, 4, 1, 1, 2)
        self.body.addLayout(g)
        self.order = QListWidget()
        self.order.setViewMode(QListWidget.IconMode)
        self.order.setIconSize(QSize(72, 72))
        self.order.setFixedHeight(104)
        self.order.setFlow(QListWidget.LeftToRight)
        self.order.setDragDropMode(QAbstractItemView.InternalMove)
        self.order.setMovement(QListWidget.Snap)
        for i, t in enumerate(self.thumbs):
            it = QListWidgetItem(QIcon(QPixmap.fromImage(qimage_from_pil(t.copy().convert("RGB")))), "")
            it.setData(Qt.UserRole, i)
            self.order.addItem(it)
        self.order.model().rowsMoved.connect(lambda *_: self.render())
        self.body.addWidget(section("Order (drag to rearrange)"))
        self.body.addWidget(self.order)
        for grp in (self.layout_grp, self.size_grp):
            grp.idClicked.connect(lambda *_: self.render())
        for s in (self.spacing, self.corners):
            s.valueChanged.connect(lambda *_: self._later.start())
        self._later = QTimer(self, singleShot=True, interval=120, timeout=self.render)
        self.body.addLayout(self.footer("Save Collage", self.save))
        QTimer.singleShot(30, self.render)

    def _bg(self, c):
        self.bg = c
        self.render()

    def _indices(self) -> list[int]:
        return [self.order.item(k).data(Qt.UserRole) for k in range(self.order.count())]

    def _params(self, scale: float = 1.0) -> dict:
        size = self.SIZES[self.size_grp.checkedId()][1]
        return dict(layout=X.COLLAGE_LAYOUTS[self.layout_grp.checkedId()][0],
                    size=(int(size[0] * scale), int(size[1] * scale)),
                    spacing=int(self.spacing.value() * scale), corners=int(self.corners.value() * scale),
                    background=self.bg)

    def render(self):
        size = self.SIZES[self.size_grp.checkedId()][1]
        scale = 720 / max(size)
        im = X.collage([self.thumbs[i] for i in self._indices()], **self._params(scale))
        pm = QPixmap.fromImage(qimage_from_pil(im))
        self.view.setPixmap(pm.scaled(self.view.width() - 16, self.view.height() - 16, Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation))

    def save(self):
        paths = [str(self.paths[i]) for i in self._indices()]
        params = self._params()
        n = len(paths)
        self.run(lambda: [X.save_collage(paths, **params)], "Making the collage…",
                 f"{n} images · {params['layout']}")


# ================================================================ ORGANIZE PDF
class OrganizePdfWindow(ToolWindow):
    tool_name = "Organize"

    def __init__(self, path, notify):
        super().__init__("Organize PDF Pages", path, notify, size=(980, 720))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(130, 170))
        self.list.setGridSize(QSize(160, 210))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setMovement(QListWidget.Snap)
        self.pages: list[QImage] = []
        with open_pdf(self.path) as doc:
            if doc.page_count > 400:
                raise ValueError("This PDF has too many pages to arrange here (400 max).")
            for i, page in enumerate(doc):
                pix = page.get_pixmap(dpi=40, alpha=False)
                self.pages.append(QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy())
                self._add(i, 0)
        self.body.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("⟲ Rotate left", lambda: self._rotate(-90)), ("Rotate right ⟳", lambda: self._rotate(90)),
                         ("Duplicate", self._duplicate), ("Remove", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        tip = QLabel("Drag pages to reorder · select several with Ctrl or Shift")
        tip.setObjectName("dim")
        row.addWidget(tip)
        self.body.addLayout(row)
        self.body.addLayout(self.footer("Save PDF", self.save, self.reset))

    def _add(self, idx: int, rot: int, at: int | None = None):
        pm = QPixmap.fromImage(self.pages[idx])
        if rot:
            from PySide6.QtGui import QTransform
            pm = pm.transformed(QTransform().rotate(rot))
        # a hairline and a soft shadow, so white pages stand out on any background
        framed = QPixmap(pm.width() + 6, pm.height() + 6)
        framed.fill(Qt.transparent)
        p = QPainter(framed)
        p.fillRect(QRectF(3, 4, pm.width(), pm.height()), QColor(0, 0, 0, 40))
        p.drawPixmap(2, 2, pm)
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.drawRect(QRectF(2, 2, pm.width() - 1, pm.height() - 1))
        p.end()
        pm = framed
        it = QListWidgetItem(QIcon(pm), f"Page {idx + 1}" + (f" · {rot % 360}°" if rot % 360 else ""))
        it.setData(Qt.UserRole, (idx, rot % 360))
        if at is None:
            self.list.addItem(it)
        else:
            self.list.insertItem(at, it)

    def _selected_rows(self) -> list[int]:
        return sorted(self.list.row(i) for i in self.list.selectedItems())

    def _rotate(self, d):
        for r in self._selected_rows():
            idx, rot = self.list.item(r).data(Qt.UserRole)
            self.list.takeItem(r)
            self._add(idx, rot + d, r)
            self.list.item(r).setSelected(True)

    def _duplicate(self):
        for k, r in enumerate(self._selected_rows()):
            idx, rot = self.list.item(r + k).data(Qt.UserRole)
            self._add(idx, rot, r + k + 1)

    def _remove(self):
        for r in reversed(self._selected_rows()):
            self.list.takeItem(r)

    def reset(self):
        self.list.clear()
        for i in range(len(self.pages)):
            self._add(i, 0)

    def save(self):
        pages = [self.list.item(k).data(Qt.UserRole) for k in range(self.list.count())]
        path = self.path
        self.run(lambda: [X.organize_pdf(path, pages)], "Saving pages…", f"{len(pages)} pages")


# ================================================================ VIDEO: CROP
class VideoCropWindow(ToolWindow):
    batch = True
    tool_name = "Crop"
    RATIOS = [("Free", None), ("1:1", 1.0), ("16:9", 16 / 9), ("9:16", 9 / 16), ("4:5", 0.8), ("4:3", 4 / 3)]

    def __init__(self, path, notify):
        super().__init__("Crop Video", path, notify, size=(900, 720))
        self.info = M.probe(self.path)
        if not self.info.has_video:
            raise ValueError("This needs a video.")
        frame = M.frame_image(self.path, min(1.0, self.info.duration / 3), 540) or Image.new("RGB", (960, 540))
        self.k = self.info.width / frame.width
        self.view = CropView(qimage_from_pil(frame), self.k)
        self.body.addWidget(self.view, 1)
        row, self.grp = toggle_row([n for n, _ in self.RATIOS])
        self.grp.idClicked.connect(lambda i: self.view.set_ratio(self.RATIOS[i][1]))
        self.body.addLayout(row)
        self.dims = QLabel("")
        self.dims.setObjectName("dim")
        self.body.addWidget(self.dims)
        self.view.changed.connect(self._dims)
        self._dims()
        self.body.addLayout(self.footer("Save Video", self.save, self.view.reset_sel))

    def _box(self):
        s = self.view.sel
        x, y = round(s.left() * self.k), round(s.top() * self.k)
        w, h = round(s.width() * self.k) // 2 * 2, round(s.height() * self.k) // 2 * 2
        r = self.view.ratio
        if r:                       # keep the chosen ratio exact after rounding to even pixels
            h = round(w / r) // 2 * 2
            if h > self.info.height:
                h = self.info.height // 2 * 2
                w = round(h * r) // 2 * 2
        # rounding can push the box a pixel past the frame: slide it back in, don't shrink it
        x = max(0, min(x, self.info.width - w))
        y = max(0, min(y, self.info.height - h))
        return x, y, w, h

    def _dims(self):
        x, y, w, h = self._box()
        self.dims.setText(f"Output {w // 2 * 2} × {h // 2 * 2} px · the sound is kept")

    def save(self):
        box, first, W, H = self._box(), self.path, self.info.width, self.info.height
        rel = (box[0] / W, box[1] / H, box[2] / W, box[3] / H)

        def crop(p, progress):
            if p == first:
                return X.crop_video(p, *box, progress=progress)
            i = M.probe(p)       # the same area of each video, whatever its size
            return X.crop_video(p, rel[0] * i.width, rel[1] * i.height, rel[2] * i.width, rel[3] * i.height,
                                progress=progress)
        self.run(_each(self.targets(), crop), "Cropping video…", f"{box[2]}×{box[3]}")


def _each(targets, fn):
    """Run fn(path, progress) for every file, spreading the progress bar over them."""
    def work(progress=None):
        outs = []
        for i, p in enumerate(targets):
            sub = (lambda f, i=i: progress((i + f) / len(targets))) if progress else None
            outs.append(fn(p, sub))
        return outs
    return work


# ================================================================ VIDEO / AUDIO: SPLIT
class SplitWindow(ToolWindow):
    tool_name = "Split"

    def __init__(self, path, notify):
        super().__init__("Split", path, notify, size=(900, 640))
        self.info = M.probe(self.path)
        d = self.info.duration
        self.frame = _frame_label(260 if self.info.has_video else 100)
        self.body.addWidget(self.frame, 1)
        self.bar = RangeBar(d, single=True)
        self.body.addWidget(self.bar)
        row, self.mode = toggle_row(["Equal parts", "Every …", "At my cut points"])
        self.body.addLayout(row)
        opts = QHBoxLayout()
        self.parts = QSpinBox()
        self.parts.setRange(2, 100)
        self.parts.setValue(2)
        self.every = QDoubleSpinBox()
        self.every.setRange(1, 36000)
        self.every.setValue(min(60.0, max(1.0, round(d / 3, 1))))
        self.every.setSuffix(" s")
        add = QPushButton("Add a cut here")
        add.clicked.connect(self._add_point)
        clear = QPushButton("Clear cuts")
        clear.clicked.connect(lambda: (self.points.clear(), self._preview()))
        for w in (QLabel("Parts"), self.parts, QLabel("Every"), self.every, add, clear):
            opts.addWidget(w)
        opts.addStretch(1)
        self.body.addLayout(opts)
        self.points: list[float] = []
        self.summary = QLabel("")
        self.summary.setObjectName("dim")
        self.summary.setWordWrap(True)
        self.body.addWidget(self.summary)
        for sig in (self.mode.idClicked, self.parts.valueChanged, self.every.valueChanged):
            sig.connect(lambda *_: self._preview())
        self.bar.released.connect(lambda _w, t: self._show(t))
        self.body.addLayout(self.footer("Split", self.save))
        QTimer.singleShot(30, self._visuals)
        self._preview()

    def _visuals(self):
        if self.info.has_video:
            self.bar.set_strip(M.filmstrip(self.path, 14, 72, self.info.duration))
            self._show(self.bar.start)
        else:
            self.bar.set_strip(M.waveform_image(self.path, 1400, 160, "0xffb06b"))

    def _show(self, t):
        if self.info.has_video:
            im = M.frame_image(self.path, t, 360)
            if im is not None:
                self.frame.setPixmap(QPixmap.fromImage(qimage_from_pil(im)).scaled(
                    self.frame.width() - 16, self.frame.height() - 16, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _add_point(self):
        self.points.append(round(self.bar.start, 2))
        self.mode.button(2).setChecked(True)
        self._preview()

    def _ranges(self):
        m = self.mode.checkedId()
        d = self.info.duration
        if m == 2:
            return X.split_points(d, points=self.points) if self.points else []
        return X.split_points(d, every=self.every.value()) if m == 1 else X.split_points(d, parts=self.parts.value())

    def _preview(self):
        r = self._ranges()
        self.summary.setText(f"{len(r)} pieces: " + ", ".join(f"{M.fmt_time(a)}–{M.fmt_time(b)}" for a, b in r[:8])
                             + (" …" if len(r) > 8 else "") if r else "Move the marker and press “Add a cut here”.")
        if self.primary_btn is not None:
            self.primary_btn.setEnabled(len(r) >= 2)

    def save(self):
        ranges, path = self._ranges(), self.path
        self.run(lambda progress=None: X.split_video(path, ranges, progress), "Splitting…", f"{len(ranges)} pieces")


# ================================================================ VIDEO: REDACT
class _BoxView(ImageView):
    def __init__(self, image: QImage, owner: "RedactVideoWindow"):
        super().__init__(image)
        self.owner = owner
        self._start: QPointF | None = None
        self._cur: QRectF | None = None
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, e):
        self._start = self.clamp_image(self.to_image(e.position()))

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self._cur = QRectF(self._start, self.clamp_image(self.to_image(e.position()))).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._cur is not None and self._cur.width() > 4 and self._cur.height() > 4:
            self.owner.add_box(self._cur)
        self._start, self._cur = None, None
        self.update()

    def paint_overlay(self, p, t):
        for k, (r, _s, _e) in enumerate(self.owner.boxes):
            p.setPen(QPen(QColor("#ff5200") if k == self.owner.current else QColor(255, 255, 255, 200), 2))
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRect(self.rect_to_widget(r))
        if self._cur is not None:
            p.setPen(QPen(QColor(255, 255, 255), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.rect_to_widget(self._cur))


class RedactVideoWindow(ToolWindow):
    tool_name = "Redact"

    def __init__(self, path, notify):
        super().__init__("Redact Video", path, notify, size=(960, 760))
        self.info = M.probe(self.path)
        if not self.info.has_video:
            raise ValueError("This needs a video.")
        frame = M.frame_image(self.path, min(1.0, self.info.duration / 3), 540) or Image.new("RGB", (960, 540))
        self.k = self.info.width / frame.width
        self.boxes: list[tuple[QRectF, float, float]] = []
        self.current = -1
        self.view = _BoxView(qimage_from_pil(frame), self)
        self.body.addWidget(self.view, 1)
        self.body.addWidget(section("Time range of the selected area"))
        self.bar = RangeBar(self.info.duration)
        self.body.addWidget(self.bar)
        self.bar.changed.connect(self._range)
        self.bar.released.connect(lambda _w, t: self._frame_at(t))
        row, self.style = toggle_row(["Blur", "Solid black"])
        undo = QPushButton("Remove selected area")
        undo.clicked.connect(self._remove)
        row.addWidget(undo)
        self.body.addLayout(row)
        tip = QLabel("Drag on the picture to cover an area. Each area has its own time range.")
        tip.setObjectName("dim")
        self.body.addWidget(tip)
        self.body.addLayout(self.footer("Save Video", self.save))
        QTimer.singleShot(30, lambda: self.bar.set_strip(M.filmstrip(self.path, 14, 72, self.info.duration)))

    def add_box(self, r: QRectF):
        self.boxes.append((r, 0.0, self.info.duration))
        self.current = len(self.boxes) - 1
        self.bar.set_range(0.0, self.info.duration)
        self.view.update()

    def _range(self, s, e):
        if 0 <= self.current < len(self.boxes):
            r, _, _ = self.boxes[self.current]
            self.boxes[self.current] = (r, s, e)

    def _frame_at(self, t):
        im = M.frame_image(self.path, t, 540)
        if im is not None:
            self.view.image = qimage_from_pil(im)
            self.view.pix = QPixmap.fromImage(self.view.image)
            self.view.update()

    def _remove(self):
        if 0 <= self.current < len(self.boxes):
            self.boxes.pop(self.current)
            self.current = len(self.boxes) - 1
            self.view.update()

    def save(self):
        blur = self.style.checkedId() == 0
        boxes = [X.Box(int(r.left() * self.k), int(r.top() * self.k), int(r.width() * self.k), int(r.height() * self.k),
                       s, e, blur) for r, s, e in self.boxes]
        path = self.path
        self.run(lambda progress=None: [X.redact_video(path, boxes, progress)], "Redacting video…",
                 f"{len(boxes)} area{'s' if len(boxes) != 1 else ''}")


# ================================================================ AUDIO: CHANNELS
class ChannelsWindow(ToolWindow):
    batch = True
    tool_name = "Channels"

    def __init__(self, path, notify):
        super().__init__("Audio Channels", path, notify, size=(620, 360))
        g = QGridLayout()
        g.addWidget(QLabel("Make it"), 0, 0)
        self.mode = QComboBox()
        for k, label in X.CHANNEL_MODES:
            self.mode.addItem(label, k)
        g.addWidget(self.mode, 0, 1, 1, 2)
        self.left = slider(0, 200, 100)
        slider_row(g, 1, "Left volume", self.left, lambda v: f"{v}%")
        self.right = slider(0, 200, 100)
        slider_row(g, 2, "Right volume", self.right, lambda v: f"{v}%")
        self.body.addLayout(g)
        self.body.addStretch(1)
        self.body.addLayout(self.footer("Save", self.save))

    def save(self):
        mode, l, r = self.mode.currentData(), self.left.value() / 100, self.right.value() / 100
        self.run(_each(self.targets(), lambda p, pr: X.channels(p, mode, l, r, pr)), "Converting channels…",
                 self.mode.currentText())


# ================================================================ AUDIO: BLEEP
class BleepWindow(ToolWindow):
    tool_name = "Bleep"

    def __init__(self, path, notify):
        super().__init__("Bleep", path, notify, size=(900, 560))
        self.info = M.probe(self.path)
        if not self.info.has_audio:
            raise ValueError("This file has no sound.")
        self.bar = RangeBar(self.info.duration)
        self.bar.set_range(0, min(self.info.duration, 1.0))
        self.body.addWidget(self.bar)
        row = QHBoxLayout()
        add = QPushButton("＋ Bleep this part")
        add.clicked.connect(self._add)
        rm = QPushButton("Remove selected")
        rm.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        self.freq = QComboBox()
        for f in (1000, 800, 440, 1500):
            self.freq.addItem(f"{f} Hz tone", f)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        row.addWidget(self.freq)
        self.body.addLayout(row)
        self.list = QListWidget()
        self.body.addWidget(self.list, 1)
        self.body.addLayout(self.footer("Save", self.save))
        QTimer.singleShot(30, lambda: self.bar.set_strip(M.waveform_image(self.path, 1400, 160, "0xffb06b")))

    def _add(self):
        a, b = self.bar.start, self.bar.end
        it = QListWidgetItem(f"{M.fmt_time(a)} – {M.fmt_time(b)}")
        it.setData(Qt.UserRole, (a, b))
        self.list.addItem(it)

    def save(self):
        ranges = [self.list.item(k).data(Qt.UserRole) for k in range(self.list.count())]
        if not ranges:
            self._add()
            ranges = [self.list.item(0).data(Qt.UserRole)]
        freq, path = self.freq.currentData(), self.path
        self.run(lambda progress=None: [X.bleep(path, ranges, freq, progress)], "Bleeping…",
                 f"{len(ranges)} part{'s' if len(ranges) != 1 else ''}")


# ================================================================ AUDIO: VISUALIZER
class VisualizerWindow(ToolWindow):
    batch = True
    tool_name = "Visualize"
    COLORS = ["#ff5200", "#ffffff", "#22c55e", "#3b82f6", "#ec4899", "#facc15"]

    def __init__(self, path, notify):
        super().__init__("Audio Visualizer", path, notify, size=(700, 420))
        self.color, self.image = self.COLORS[0], None
        g = QGridLayout()
        g.addWidget(QLabel("Shape"), 0, 0)
        row, self.layout_grp = toggle_row(["Landscape", "Portrait", "Square"])
        g.addLayout(row, 0, 1)
        g.addWidget(QLabel("Style"), 1, 0)
        row, self.style = toggle_row(["Waveform", "Spectrum bars", "Still image"])
        self.style.idClicked.connect(self._style)
        g.addLayout(row, 1, 1)
        g.addWidget(QLabel("Colour"), 2, 0)
        cr = QHBoxLayout()
        for c in self.COLORS:
            b = QPushButton()
            b.setObjectName("swatch")
            b.setStyleSheet(f"background: {c};")
            b.clicked.connect(lambda _=False, c=c: setattr(self, "color", c))
            cr.addWidget(b)
        cr.addStretch(1)
        g.addLayout(cr, 2, 1)
        g.addWidget(QLabel("Background"), 3, 0)
        self.bg = QComboBox()
        for name, hexv in (("Near black", "#101114"), ("White", "#ffffff"), ("Navy", "#0f172a"), ("Santra", "#ff5200")):
            self.bg.addItem(name, hexv)
        g.addWidget(self.bg, 3, 1)
        self.pick = QPushButton("Choose image…")
        self.pick.clicked.connect(self._pick)
        self.pick.setVisible(False)
        g.addWidget(self.pick, 4, 1)
        self.body.addLayout(g)
        self.body.addStretch(1)
        self.body.addLayout(self.footer("Make Video", self.save))

    def _style(self, i):
        self.pick.setVisible(i == 2)

    def _pick(self):
        f, _ = QFileDialog.getOpenFileName(self, "Picture for the video", str(self.path.parent),
                                           "Images (*.jpg *.jpeg *.png *.webp *.bmp)")
        if f:
            self.image = f
            self.pick.setText(Path(f).name)

    def save(self):
        layout = ["landscape", "portrait", "square"][self.layout_grp.checkedId()]
        style = ["wave", "bars", "image"][self.style.checkedId()]
        if style == "image" and not self.image:
            self._pick()
            if not self.image:
                return
        args = dict(layout=layout, style=style, color=self.color, background=self.bg.currentData(), image=self.image)
        self.run(_each(self.targets(), lambda p, pr: X.visualizer(p, progress=pr, **args)), "Making the video…",
                 f"{layout} · {style}")


# ================================================================ METADATA: EDIT
class MetadataEditWindow(ToolWindow):
    tool_name = "Metadata"

    def __init__(self, path, notify):
        super().__init__("Edit Metadata", path, notify, size=(620, 440))
        from .util import category
        cat = category(self.path)
        fields = X.PDF_FIELDS if cat == "pdf" else X.MEDIA_FIELDS if cat in ("video", "audio") else X.IMAGE_FIELDS
        values = X.read_fields(self.path)
        g = QGridLayout()
        self.edits: dict[str, QLineEdit] = {}
        for r, (key, label, _) in enumerate(fields):
            g.addWidget(QLabel(label), r, 0)
            e = QLineEdit(values.get(key, ""))
            e.setPlaceholderText("(empty: removed)")
            g.addWidget(e, r, 1)
            self.edits[key] = e
        self.body.addLayout(g)
        tip = QLabel("Saves an edited copy; the original keeps its metadata.")
        tip.setObjectName("dim")
        self.body.addWidget(tip)
        self.body.addStretch(1)
        self.body.addLayout(self.footer("Save Copy", self.save))

    def save(self):
        values = {k: e.text().strip() for k, e in self.edits.items()}
        path = self.path
        self.run(lambda progress=None: [X.write_fields(path, values, progress)], "Saving metadata…",
                 f"{sum(1 for v in values.values() if v)} fields set")
