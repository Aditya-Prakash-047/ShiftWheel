"""Extract Text: read the text in an image (offline OCR), edit it, copy it or save it."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton

from . import ocr
from .convert import open_preview
from .glass import qimage_from_pil
from .tools import ToolWindow
from .util import keep, release, sibling
from .window import ImageView


class _Sig(QObject):
    done = Signal(str)
    failed = Signal(str)


class _Read(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.sig = _Sig()

    def run(self):
        try:
            result, ok = ocr.image_text(self.path), True
        except Exception as e:  # noqa: BLE001
            result, ok = str(e), False
        try:   # the window may have been closed while we were reading
            (self.sig.done if ok else self.sig.failed).emit(result)
        except RuntimeError:
            pass


class ExtractTextWindow(ToolWindow):
    tool_name = "Text"

    def __init__(self, path, notify):
        super().__init__("Extract Text", path, notify, size=(980, 640))
        row = QHBoxLayout()
        self.view = ImageView(qimage_from_pil(open_preview(path, 1400)))
        row.addWidget(self.view, 1)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Reading text…")
        self.text.setReadOnly(True)
        row.addWidget(self.text, 1)
        self.body.addLayout(row, 1)
        self.status = QLabel("Reading text on this computer — nothing is uploaded.")
        self.status.setObjectName("dim")
        self.body.addWidget(self.status)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.copy)
        self.body.addLayout(self.footer("Save .txt", self.save, extra_buttons=[self.copy_btn]))
        self.primary_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.job = _Read(str(self.path))
        self.job.sig.done.connect(self._done)
        self.job.sig.failed.connect(self._failed)
        QThreadPool.globalInstance().start(keep(self.job))

    def _done(self, text: str):
        release(self.job)
        self.text.setReadOnly(False)
        if text.strip():
            self.text.setPlainText(text)
            words = len(text.split())
            self.status.setText(f"{words} word{'s' if words != 1 else ''} found. You can edit before copying.")
            self.primary_btn.setEnabled(True)
            self.copy_btn.setEnabled(True)
        else:
            self.text.setPlaceholderText("")
            self.status.setText("No text found in this image.")

    def _failed(self, msg: str):
        release(self.job)
        self.status.setText(f"Couldn't read text: {msg}")

    def copy(self):
        QGuiApplication.clipboard().setText(self.text.toPlainText())
        self.status.setText("Copied to the clipboard.")

    def save(self):
        text, out = self.text.toPlainText(), sibling(self.path, "Text", ".txt")

        def work():
            out.write_text(text, encoding="utf-8")
            return [out]
        self.run(work, "Saving text…")
