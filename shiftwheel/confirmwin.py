"""Asks before a job that would create a lot of files: says how many, why and where, and lets
you back out (or, for a PDF split, make fewer) before any work is done."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSpinBox

from .window import GlassWindow


class ConfirmManyWindow(GlassWindow):
    """`pages`: set for a PDF split, adds 'one file for every N pages'; on_yes then receives N."""

    def __init__(self, title: str, count: int, why: str, where: str, on_yes: Callable[[int], None],
                 pages: int = 0):
        super().__init__(title, size=(540, 300 if pages else 260))
        self.count, self.pages, self.on_yes = count, pages, on_yes
        self.head = QLabel()
        self.head.setObjectName("big")
        self.body.addWidget(self.head)
        reason = QLabel(why)
        reason.setWordWrap(True)
        self.body.addWidget(reason)
        self.every = None
        if pages:
            row = QHBoxLayout()
            row.addWidget(QLabel("One file for every"))
            self.every = QSpinBox()
            self.every.setRange(1, max(1, pages))
            self.every.setValue(1)
            self.every.valueChanged.connect(self._update)
            row.addWidget(self.every)
            row.addWidget(QLabel("pages"))
            row.addStretch(1)
            self.body.addLayout(row)
        place = QLabel(where)
        place.setObjectName("dim")
        place.setWordWrap(True)
        self.body.addWidget(place)
        self.body.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        foot.addWidget(cancel)
        self.yes = QPushButton()
        self.yes.setObjectName("primary")
        self.yes.clicked.connect(self._accept)
        foot.addWidget(self.yes)
        self.body.addLayout(foot)
        self._update()

    def files(self) -> int:
        if self.every is None:
            return self.count
        return -(-self.pages // self.every.value())

    def _update(self, *_):
        n = self.files()
        self.head.setText(f"This will create {n:,} file{'s' if n != 1 else ''}")
        self.yes.setText(f"Create {n:,} file{'s' if n != 1 else ''}")

    def _accept(self):
        every = self.every.value() if self.every is not None else 1
        self.close()
        self.on_yes(every)
