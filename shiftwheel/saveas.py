"""'Ask for a file name before saving': a small box that names (and places) a fresh result.

The result is already written under its automatic name, so closing the box or pressing Esc
simply keeps that name — nothing is ever lost."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .window import GlassWindow

BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def clean_name(name: str) -> str:
    """A name Windows accepts: no reserved characters, no trailing dots/spaces, not CON/NUL…"""
    name = BAD.sub("_", name).strip().rstrip(". ")
    if name.lower() in RESERVED:
        name = f"{name}_"
    return name[:200]


def move_result(src: Path, folder: Path, stem: str) -> Path:
    """Rename/move `src` to folder/stem+ext. Returns the new path (or `src` if unchanged)."""
    dst = Path(folder) / (stem + src.suffix)
    if dst == src:
        return src
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)             # same drive: atomic, replaces an existing file
    except OSError:
        shutil.move(str(src), str(dst))  # another drive
    return dst


class SaveAsWindow(GlassWindow):
    def __init__(self, path: str | Path, on_done):
        super().__init__("Save as", size=(560, 250))
        self.path = Path(path)
        self.folder = self.path.parent
        self.on_done = on_done
        self._finished = False
        self._confirm_replace = None

        row = QHBoxLayout()
        self.name = QLineEdit(self.path.stem)
        self.name.selectAll()
        self.name.returnPressed.connect(self.save)
        self.name.textEdited.connect(lambda _: self._clear_warning())
        row.addWidget(self.name, 1)
        ext = QLabel(self.path.suffix)
        ext.setObjectName("dim")
        row.addWidget(ext)
        self.body.addLayout(row)

        frow = QHBoxLayout()
        self.where = QLabel(str(self.folder))
        self.where.setObjectName("dim")
        self.where.setWordWrap(True)
        frow.addWidget(self.where, 1)
        change = QPushButton("Change folder…")
        change.clicked.connect(self.pick_folder)
        frow.addWidget(change)
        self.body.addLayout(frow)

        self.warning = QLabel("")
        self.warning.setObjectName("warn")
        self.warning.setWordWrap(True)
        self.body.addWidget(self.warning)
        self.body.addStretch(1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        keep = QPushButton(f"Keep “{self.path.name}”")
        keep.clicked.connect(self.close)
        foot.addWidget(keep)
        ok = QPushButton("Save")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.save)
        foot.addWidget(ok)
        self.body.addLayout(foot)
        self.name.setFocus(Qt.OtherFocusReason)

    def _clear_warning(self):
        self.warning.setText("")
        self._confirm_replace = None

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Save in…", str(self.folder))
        if d:
            self.folder = Path(d)
            self.where.setText(d)
            self._clear_warning()

    def save(self):
        stem = clean_name(self.name.text())
        if not stem:
            self.warning.setText("Type a name first.")
            return
        dst = self.folder / (stem + self.path.suffix)
        if dst != self.path and dst.exists() and self._confirm_replace != dst:
            self._confirm_replace = dst
            self.warning.setText(f"“{dst.name}” already exists there. Press Save again to replace it.")
            return
        try:
            new = move_result(self.path, self.folder, stem)
        except OSError as e:
            self.warning.setText(f"Couldn't save there: {e.strerror or e}")
            return
        self._finish(new)
        self.close()

    def _finish(self, path: Path):
        if not self._finished:
            self._finished = True
            self.on_done(path)

    def closeEvent(self, e):
        self._finish(self.path)          # closed / Esc / Keep: the automatic name stays
        super().closeEvent(e)
