"""Float: a small always-on-top shelf that holds files so you can drag them into another app
later (Santra's Float). Drop more files on it, drag any tile out, pin it to a screen edge."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDrag, QGuiApplication
from PySide6.QtWidgets import (QFileIconProvider, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton,
                               QWidget)
from PySide6.QtCore import QFileInfo

from .window import GlassWindow


class Tile(QToolButton):
    remove = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIcon(QFileIconProvider().icon(QFileInfo(path)))
        self.setIconSize(QSize(40, 40))
        name = Path(path).name
        self.setText(name if len(name) <= 16 else name[:13] + "…")
        self.setToolTip(f"{path}\nDrag it out · right-click to remove")
        self.setFixedSize(96, 84)
        self.setStyleSheet("QToolButton { border: none; border-radius: 10px; background: transparent; }"
                           "QToolButton:hover { background: rgba(127,127,127,0.18); }")
        self._press: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.remove.emit(self.path)
            return
        self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 6:
            return
        self._press = None
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(self.path)])
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(self.icon().pixmap(40, 40))
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

    def mouseReleaseEvent(self, e):
        self._press = None


class FloatShelf(GlassWindow):
    """One shelf for the whole app; `add()` brings it up with more files."""

    def __init__(self):
        super().__init__("Float", size=(440, 220))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setAcceptDrops(True)
        self.paths: list[str] = []
        self.hint = QLabel("Drop files here, or drag them out into any app.")
        self.hint.setObjectName("dim")
        self.body.addWidget(self.hint)
        self.row = QHBoxLayout()
        self.row.setSpacing(4)
        self.row.addStretch(1)
        holder = QWidget()
        holder.setObjectName("page")
        holder.setLayout(self.row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setStyleSheet("QScrollArea, QWidget#qt_scrollarea_viewport, QWidget#page "
                             "{ background: transparent; border: none; }")
        scroll.setFixedHeight(100)
        self.body.addWidget(scroll)
        foot = QHBoxLayout()
        for text, edge in (("◧ Pin left", "left"), ("Pin right ◨", "right")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, e=edge: self.pin(e))
            foot.addWidget(b)
        foot.addStretch(1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        foot.addWidget(clear)
        self.body.addLayout(foot)

    def add(self, paths: list[str]):
        for p in paths:
            if p not in self.paths and Path(p).exists():
                self.paths.append(p)
                t = Tile(p)
                t.remove.connect(self.remove)
                self.row.insertWidget(self.row.count() - 1, t)
        self._update_hint()

    def remove(self, path: str):
        if path in self.paths:
            i = self.paths.index(path)
            self.paths.pop(i)
            w = self.row.itemAt(i).widget()
            if w is not None:
                w.deleteLater()
        self._update_hint()

    def clear(self):
        for p in list(self.paths):
            self.remove(p)

    def _update_hint(self):
        n = len(self.paths)
        self.hint.setText("Drop files here, or drag them out into any app." if not n else
                          f"{n} file{'s' if n != 1 else ''} · drag out into any app · right-click to remove")

    def pin(self, edge: str):
        scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        x = scr.left() + 8 if edge == "left" else scr.right() - self.width() - 8
        self.move(x, scr.center().y() - self.height() // 2)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def closeEvent(self, e):
        self.paths.clear()
        super().closeEvent(e)
