"""Video & audio tool windows: Trim (also GIF and Snapshot), Compress, Speed.

The trim bar shows a filmstrip (video) or waveform (audio); drag the two handles, the big
preview shows the frame under the handle you're moving. Optional playback uses Qt Multimedia
when it's available."""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QWidget)

from . import media as M
from .glass import qimage_from_pil
from .tools import ToolWindow, section, toggle_row
from .util import file_size, human_size


class RangeBar(QWidget):
    """Filmstrip/waveform strip with two draggable handles (or one, for snapshots)."""
    changed = Signal(float, float)       # start, end (seconds)
    moved = Signal(str, float)           # which handle ("start"/"end"/"at"), time
    released = Signal(str, float)

    def __init__(self, duration: float, single: bool = False):
        super().__init__()
        self.duration = max(duration, 0.01)
        self.single = single
        self.start, self.end = 0.0, self.duration
        if single:
            self.start = self.end = min(1.0, self.duration / 2)
        self.strip: QPixmap | None = None
        self.drag = ""
        self.playhead = -1.0
        self.setMinimumHeight(78)
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeHorCursor)

    def set_strip(self, im: Image.Image | None):
        self.strip = QPixmap.fromImage(qimage_from_pil(im)) if im is not None else None
        self.update()

    def track(self) -> QRectF:
        return QRectF(self.rect()).adjusted(12, 8, -12, -8)

    def x_of(self, t: float) -> float:
        r = self.track()
        return r.left() + r.width() * t / self.duration

    def t_of(self, x: float) -> float:
        r = self.track()
        return min(self.duration, max(0.0, (x - r.left()) / max(1.0, r.width()) * self.duration))

    def set_range(self, start: float, end: float):
        self.start, self.end = max(0.0, min(start, self.duration)), max(0.0, min(end, self.duration))
        if self.single:
            self.end = self.start
        elif self.end < self.start:
            self.start, self.end = self.end, self.start
        self.update()
        self.changed.emit(self.start, self.end)

    def mousePressEvent(self, e):
        x = e.position().x()
        if self.single:
            self.drag = "at"
        else:
            ds, de = abs(x - self.x_of(self.start)), abs(x - self.x_of(self.end))
            self.drag = "start" if ds <= de else "end"
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        if not self.drag:
            return
        t = self.t_of(e.position().x())
        if self.drag == "at":
            self.start = self.end = t
        elif self.drag == "start":
            self.start = min(t, self.end - 0.05)
        else:
            self.end = max(t, self.start + 0.05)
        self.update()
        self.changed.emit(self.start, self.end)
        self.moved.emit(self.drag, self.start if self.drag != "end" else self.end)

    def mouseReleaseEvent(self, e):
        if self.drag:
            which = self.drag
            self.drag = ""
            self.released.emit(which, self.start if which != "end" else self.end)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.track()
        clip = QPainterPath()
        clip.addRoundedRect(r, 8, 8)
        p.setClipPath(clip)
        p.fillRect(r, QColor(0, 0, 0, 90))
        if self.strip is not None:
            p.drawPixmap(r.toRect(), self.strip)
        if not self.single:  # dim outside the selection
            x0, x1 = self.x_of(self.start), self.x_of(self.end)
            p.fillRect(QRectF(r.left(), r.top(), x0 - r.left(), r.height()), QColor(0, 0, 0, 150))
            p.fillRect(QRectF(x1, r.top(), r.right() - x1, r.height()), QColor(0, 0, 0, 150))
        p.setClipping(False)
        accent = QColor(255, 120, 60)
        if self.single:
            x = self.x_of(self.start)
            p.setPen(QPen(accent, 3))
            p.drawLine(QPointF(x, r.top() - 4), QPointF(x, r.bottom() + 4))
        else:
            x0, x1 = self.x_of(self.start), self.x_of(self.end)
            p.setPen(QPen(accent, 3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x0, r.top(), x1 - x0, r.height()), 6, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            for x in (x0, x1):
                p.drawRoundedRect(QRectF(x - 5, r.top() + r.height() * 0.25, 10, r.height() * 0.5), 4, 4)
        if self.playhead >= 0:
            x = self.x_of(self.playhead)
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.end()


class TrimWindow(ToolWindow):
    """mode: 'trim' | 'gif' | 'snapshot'"""
    TITLES = {"trim": ("Trim", "Trim"), "gif": ("Make GIF", "GIF"), "snapshot": ("Save a Frame", "Snapshot")}

    def __init__(self, path, notify, mode: str = "trim"):
        title, self.tool_name = self.TITLES[mode]
        super().__init__(title, path, notify, size=(900, 680))
        self.mode = mode
        self.info = M.probe(self.path)
        self.video = self.info.has_video
        if mode != "trim" and not self.video:
            raise ValueError("This needs a video.")
        d = self.info.duration
        bits = [M.fmt_time(d)]
        if self.video:
            bits.insert(0, f"{self.info.width}×{self.info.height}")
        self.subtitle.setText(f"{self.path.name}  ·  {'  ·  '.join(bits)}  ·  {human_size(file_size(self.path))}")

        self.frame = QLabel()
        self.frame.setAlignment(Qt.AlignCenter)
        self.frame.setMinimumHeight(300 if self.video else 120)
        self.frame.setStyleSheet("background: rgba(0,0,0,0.25); border-radius: 10px;")
        self.body.addWidget(self.frame, 1)
        self.bar = RangeBar(d, single=(mode == "snapshot"))
        self.body.addWidget(self.bar)
        if mode == "gif":
            self.bar.set_range(0.0, min(d, 5.0))

        times = QHBoxLayout()
        self.s_spin, self.e_spin = QDoubleSpinBox(), QDoubleSpinBox()
        for sp in (self.s_spin, self.e_spin):
            sp.setRange(0.0, d)
            sp.setDecimals(2)
            sp.setSingleStep(0.1)
            sp.setSuffix(" s")
            sp.setFixedWidth(110)
        times.addWidget(QLabel("At" if mode == "snapshot" else "Start"))
        times.addWidget(self.s_spin)
        if mode != "snapshot":
            times.addWidget(QLabel("End"))
            times.addWidget(self.e_spin)
        self.len_label = QLabel("")
        self.len_label.setObjectName("dim")
        times.addWidget(self.len_label)
        times.addStretch(1)
        self.play_btn = QPushButton("▶ Play selection")
        self.play_btn.clicked.connect(self.toggle_play)
        import importlib.util
        self.play_btn.setVisible(importlib.util.find_spec("PySide6.QtMultimedia") is not None)
        times.addWidget(self.play_btn)
        self.body.addLayout(times)

        opts = QHBoxLayout()
        if mode == "trim":
            row, self.precise = toggle_row(["Precise cut", "Fast (lossless, keyframes)"])
            opts.addLayout(row)
        elif mode == "gif":
            self.fps = QComboBox()
            self.fps.addItems(["10 fps", "12 fps", "15 fps", "20 fps"])
            self.fps.setCurrentIndex(1)
            self.width_box = QComboBox()
            self.width_box.addItems(["320 px", "480 px", "640 px", "800 px"])
            self.width_box.setCurrentIndex(1)
            opts.addWidget(QLabel("Smoothness"))
            opts.addWidget(self.fps)
            opts.addWidget(QLabel("Width"))
            opts.addWidget(self.width_box)
            opts.addStretch(1)
        self.body.addLayout(opts)

        self.bar.changed.connect(self._range_changed)
        self.bar.released.connect(lambda which, t: self.show_frame(t))
        self.s_spin.editingFinished.connect(lambda: self.bar.set_range(self.s_spin.value(), self.e_spin.value()))
        self.e_spin.editingFinished.connect(lambda: self.bar.set_range(self.s_spin.value(), self.e_spin.value()))
        self._range_changed(self.bar.start, self.bar.end)
        primary = {"trim": "Save Trimmed", "gif": "Save GIF", "snapshot": "Save PNG"}[mode]
        self.body.addLayout(self.footer(primary, self.save, self.reset))

        self.player = None
        QTimer.singleShot(30, self._load_visuals)

    # ------------------------------------------------------------ visuals
    def _load_visuals(self):
        if self.video:
            self.bar.set_strip(M.filmstrip(self.path, 14, 72, self.info.duration))
            self.show_frame(self.bar.start)
        else:
            wave = M.waveform_image(self.path, 1400, 200, "0xffb06b")
            self.bar.set_strip(wave)
            if wave is not None:
                big = wave.copy()
                self.frame.setPixmap(QPixmap.fromImage(qimage_from_pil(big)).scaled(
                    self.frame.width() - 20, self.frame.height() - 20, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def show_frame(self, t: float):
        if not self.video:
            return
        im = M.frame_image(self.path, t, 480)
        if im is None:
            return
        pm = QPixmap.fromImage(qimage_from_pil(im))
        self.frame.setPixmap(pm.scaled(self.frame.width() - 16, self.frame.height() - 16, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))

    def _range_changed(self, s, e):
        for sp, v in ((self.s_spin, s), (self.e_spin, e)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        if self.mode == "snapshot":
            self.len_label.setText(M.fmt_time(s))
        else:
            self.len_label.setText(f"{M.fmt_time(s)} → {M.fmt_time(e)}  ·  {M.fmt_time(e - s)} selected")

    def reset(self):
        d = self.info.duration
        if self.mode == "snapshot":
            self.bar.set_range(min(1.0, d / 2), min(1.0, d / 2))
        else:
            self.bar.set_range(0.0, d if self.mode == "trim" else min(d, 5.0))
        self.show_frame(self.bar.start)

    # ------------------------------------------------------------ playback (optional)
    def toggle_play(self):
        try:
            if self.player is None:
                from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
                from PySide6.QtMultimediaWidgets import QVideoWidget
                self.player = QMediaPlayer(self)
                self.audio = QAudioOutput(self)
                self.player.setAudioOutput(self.audio)
                if self.video:
                    self.vw = QVideoWidget()
                    self.body.insertWidget(self.body.indexOf(self.frame), self.vw, 1)
                    self.player.setVideoOutput(self.vw)
                self.player.setSource(QUrl.fromLocalFile(str(self.path)))
                self.player.positionChanged.connect(self._pos)
            from PySide6.QtMultimedia import QMediaPlayer
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.player.pause()
                self.play_btn.setText("▶ Play selection")
                return
            if self.video:
                self.frame.hide()
                self.vw.show()
            self.player.setPosition(int(self.bar.start * 1000))
            self.player.play()
            self.play_btn.setText("❚❚ Pause")
        except Exception:  # noqa: BLE001 - playback is a nicety; frames still preview
            self.play_btn.setEnabled(False)
            self.play_btn.setToolTip("Playback isn't available on this system")

    def _pos(self, ms):
        t = ms / 1000
        self.bar.playhead = t
        self.bar.update()
        if self.mode != "snapshot" and t >= self.bar.end:
            self.player.pause()
            self.play_btn.setText("▶ Play selection")

    def closeEvent(self, e):
        if self.player is not None:
            self.player.stop()
        super().closeEvent(e)

    # ------------------------------------------------------------ save
    def save(self):
        s, e, path = self.bar.start, self.bar.end, self.path
        if self.mode == "trim":
            precise = self.precise.checkedId() == 0
            self.run(lambda progress=None: [M.trim(path, s, e, precise, progress)], "Trimming…",
                     f"{M.fmt_time(e - s)} kept")
        elif self.mode == "gif":
            fps = int(self.fps.currentText().split()[0])
            width = int(self.width_box.currentText().split()[0])
            self.run(lambda progress=None: [M.to_gif(path, None, s, e - s, fps, width, progress)], "Making GIF…",
                     f"{M.fmt_time(e - s)} · {fps} fps")
        else:
            self.run(lambda: [M.snapshot(path, s)], "Saving frame…", f"at {M.fmt_time(s)}")


class VideoCompressWindow(ToolWindow):
    tool_name = "Compress"
    HEIGHTS = [("Keep size", None), ("1080p", 1080), ("720p", 720), ("480p", 480)]

    def __init__(self, paths, notify):
        super().__init__("Compress Video", paths, notify, size=(620, 420))
        self.infos = [M.probe(p) for p in self.paths]
        self.body.addWidget(section("Quality"))
        row, self.q = toggle_row(["Smallest", "Balanced", "High quality", "Target size"], 1)
        self.body.addLayout(row)
        g = QGridLayout()
        self.res = QComboBox()
        for name, h in self.HEIGHTS:
            if h is None or h < max(x.height for x in self.infos):
                self.res.addItem(name, h)
        self.mb = QDoubleSpinBox()
        self.mb.setRange(0.1, 4000)
        self.mb.setDecimals(1)
        self.mb.setSuffix(" MB")
        total = sum(file_size(p) for p in self.paths) / len(self.paths) / 1048576
        self.mb.setValue(max(0.1, round(total * 0.3, 1)))
        presets = QHBoxLayout()
        for label, v in (("WhatsApp 16 MB", 16), ("Email 25 MB", 25), ("Discord 10 MB", 10)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, v=v: (self.q.button(3).click(), self.mb.setValue(v)))
            presets.addWidget(b)
        presets.addStretch(1)
        g.addWidget(QLabel("Resolution"), 0, 0)
        g.addWidget(self.res, 0, 1)
        g.addWidget(QLabel("Target"), 1, 0)
        g.addWidget(self.mb, 1, 1)
        self.body.addLayout(g)
        self.body.addLayout(presets)
        self.note = QLabel("")
        self.note.setObjectName("dim")
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self.body.addStretch(1)
        self.q.idClicked.connect(self._update)
        self.mb.valueChanged.connect(self._update)
        self.res.currentIndexChanged.connect(self._update)
        self.body.addLayout(self.footer("Compress", self.save))
        self._update()

    def _update(self, *_):
        target = self.q.checkedId() == 3
        self.mb.setEnabled(target)
        i = self.infos[0]
        self.note.setText(
            (f"Aims for about {self.mb.value():.1f} MB per video. " if target else "") +
            f"Saved as MP4 (H.264), plays everywhere. Source: {i.width}×{i.height}, {M.fmt_time(i.duration)}, "
            f"{human_size(file_size(self.paths[0]))}.")

    def save(self):
        qual = ["small", "balanced", "high", "balanced"][self.q.checkedId()]
        h = self.res.currentData()
        mb = self.mb.value() if self.q.checkedId() == 3 else None
        paths = list(self.paths)

        def work(progress=None):
            outs = []
            n = len(paths)
            for k, p in enumerate(paths):
                sub = (lambda f, k=k: progress((k + f) / n)) if progress else None
                outs.append(M.compress_video(p, qual, h, mb, sub))
            return outs
        self.run(work, "Compressing video…")


class SpeedWindow(ToolWindow):
    tool_name = "Speed"
    SPEEDS = [0.25, 0.5, 0.75, 1.25, 1.5, 2.0, 3.0, 4.0]

    def __init__(self, path, notify):
        super().__init__("Change Speed", path, notify, size=(560, 260))
        self.info = M.probe(self.path)
        self.body.addWidget(section("Speed"))
        row, self.grp = toggle_row([f"{s:g}×" for s in self.SPEEDS], 5)
        self.body.addLayout(row)
        self.note = QLabel("")
        self.note.setObjectName("dim")
        self.body.addWidget(self.note)
        self.grp.idClicked.connect(self._update)
        self.body.addStretch(1)
        self.body.addLayout(self.footer("Save", self.save))
        self._update()

    def _update(self, *_):
        f = self.SPEEDS[self.grp.checkedId()]
        self.note.setText(f"{M.fmt_time(self.info.duration)} → {M.fmt_time(self.info.duration / f)}  ·  "
                          "voice pitch is kept")

    def save(self):
        f, path = self.SPEEDS[self.grp.checkedId()], self.path
        self.run(lambda progress=None: [M.speed(path, f, progress)], "Changing speed…", f"{f:g}×")
