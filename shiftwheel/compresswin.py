"""Compress with a choice of levels (PDF, audio, ZIP / 7Z), each showing the size it will make
before anything is written. Estimates run in the background: PDFs are compressed in memory
(or from a sample of pages when big), audio is bitrate × duration, archives compress a sample
of every file."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QLabel, QRadioButton

from . import archive, imaging, media
from .tools import ToolWindow
from .util import file_size, human_size, keep, release


class _Sig(QObject):
    done = Signal(str, int, bool)       # level, bytes (-1 = failed), exact


class _Estimate(QRunnable):
    def __init__(self, level: str, fn):
        super().__init__()
        self.level, self.fn, self.sig = level, fn, _Sig()

    def run(self):
        try:
            size, exact = self.fn(self.level)
        except Exception:  # noqa: BLE001
            size, exact = -1, False
        try:
            self.sig.done.emit(self.level, int(size), bool(exact))
        except RuntimeError:            # the window was closed meanwhile
            pass


def describe(before: int, after: int, exact: bool) -> str:
    approx = "" if exact else "≈ "
    if after >= before * 0.98:
        return f"{approx}{human_size(after)} · no smaller"
    pct = round(100 * (1 - after / before))
    return f"{approx}{human_size(after)} · " + ("over 99% smaller" if pct > 99 else f"{pct}% smaller")


class LevelCompressWindow(ToolWindow):
    """`levels`: [(key, name, description)], `estimate(level) -> (bytes, exact)` for all files,
    `work(level) -> fn(progress=None) -> [outputs]`."""
    tool_name = "Compress"

    def __init__(self, title: str, paths, notify, kind: str, levels, estimate, work, default: str,
                 primary: str = "Compress", note: str = "", before: int | None = None):
        super().__init__(title, paths, notify, size=(600, 160 + 74 * len(levels) + (40 if note else 0)))
        self.kind, self.estimate_fn, self.work_fn = kind, estimate, work
        self.before = before if before is not None else sum(file_size(p) for p in self.paths)
        self._jobs = []
        remembered = str(QSettings("ShiftWheel", "ShiftWheel").value(f"compress_level/{kind}", default))
        if remembered not in [k for k, _, _ in levels]:
            remembered = default

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        self.group = QButtonGroup(self)
        self.est_labels: dict[str, QLabel] = {}
        self.keys = [k for k, _, _ in levels]
        for i, (key, name, blurb) in enumerate(levels):
            card = QFrame()
            card.setObjectName("card")
            g = QGridLayout(card)
            g.setContentsMargins(12, 8, 12, 8)
            rb = QRadioButton(name)
            rb.setChecked(key == remembered)
            self.group.addButton(rb, i)
            g.addWidget(rb, 0, 0)
            d = QLabel(blurb)
            d.setObjectName("dim")
            d.setWordWrap(True)
            g.addWidget(d, 1, 0)
            est = QLabel("calculating…")
            est.setObjectName("dim")
            g.addWidget(est, 0, 1, 2, 1)
            g.setColumnStretch(0, 1)
            self.est_labels[key] = est
            card.mousePressEvent = lambda _e, b=rb: b.setChecked(True)
            grid.addWidget(card, i, 0)
        self.body.addLayout(grid)
        if note:
            n = QLabel(note)
            n.setObjectName("warn")
            n.setWordWrap(True)
            self.body.addWidget(n)
        self.body.addStretch(1)
        self.body.addLayout(self.footer(primary, self.save))
        for key in self.keys:
            job = keep(_Estimate(key, self.estimate_fn))
            job.sig.done.connect(self._estimated)
            self._jobs.append(job)
            QThreadPool.globalInstance().start(job)

    def _estimated(self, level: str, size: int, exact: bool):
        for j in [j for j in self._jobs if j.level == level]:
            release(j)
        lab = self.est_labels.get(level)
        if lab is None:
            return
        lab.setText("—" if size < 0 else describe(self.before, size, exact))
        lab.setObjectName("good" if 0 <= size < self.before * 0.98 else "dim")
        lab.style().unpolish(lab)
        lab.style().polish(lab)

    def level(self) -> str:
        return self.keys[max(0, self.group.checkedId())]

    def save(self):
        level = self.level()
        QSettings("ShiftWheel", "ShiftWheel").setValue(f"compress_level/{self.kind}", level)
        self.run(self.work_fn(level), "Compressing…", self.group.checkedButton().text())


# ---------------------------------------------------------------- the three kinds
def pdf_window(paths, notify) -> LevelCompressWindow:
    paths = [str(p) for p in paths]

    def estimate(level):
        sizes = [imaging.estimate_pdf(p, level) for p in paths]
        return sum(s for s, _ in sizes), all(e for _, e in sizes)

    def work(level):
        return lambda progress=None: [imaging.compress_pdf(p, level=level) for p in paths]
    return LevelCompressWindow("Compress PDF", paths, notify, "pdf",
                               [(k, n, d) for k, n, d, _, _ in imaging.PDF_LEVELS], estimate, work, "balanced")


def audio_window(paths, notify) -> LevelCompressWindow:
    paths = [str(p) for p in paths]

    def estimate(level):
        return sum(media.estimate_audio(p, level) for p in paths), False

    def work(level):
        def run(progress=None):
            outs = []
            for i, p in enumerate(paths):
                sub = (lambda f, i=i: progress((i + f) / len(paths))) if progress else None
                outs.append(media.compress_audio(p, progress=sub, level=level))
            return outs
        return run
    return LevelCompressWindow("Compress audio", paths, notify, "audio",
                               [(k, n, d) for k, n, d, _, _ in media.AUDIO_LEVELS], estimate, work, "balanced",
                               note="Saved as MP3.")


def archive_window(paths, notify, fmt: str = "ZIP") -> LevelCompressWindow:
    paths = [str(p) for p in paths]
    before = sum(f.stat().st_size for f, _ in archive._walk(paths))
    packed = archive.packed_share(paths)
    note = ("Most of this is already compressed (photos, videos, PDFs, Office files): expect little saving. "
            "Store or Fast is quickest.") if packed > 0.6 else ""

    def estimate(level):
        return archive.estimate_archive(paths, fmt, level), level == "store"

    def work(level):
        return lambda progress=None: [archive.zip_paths(paths, fmt, level)]
    name = Path(paths[0]).name if len(paths) == 1 else f"{len(paths)} items"
    w = LevelCompressWindow(f"Create {fmt}", paths, notify, f"archive_{fmt.lower()}", archive.ARCHIVE_LEVELS,
                            estimate, work, "fast" if packed > 0.6 else "normal",
                            primary=f"Create {fmt}", note=note, before=before)
    w.tool_name = "Zip"
    w.subtitle.setText(f"{name}  ·  {human_size(before)}")
    return w
