"""Every slice on every ring, for every kind of file, through the real dispatcher.

A fake app runs background jobs synchronously and records opened windows, so this
catches wiring mistakes (wrong key, missing window, crash) that unit tests can't."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from shiftwheel import app as A
from shiftwheel.util import UserError


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class FakeToasts:
    def __init__(self):
        self.errors = []

    def error(self, title, detail):
        self.errors.append((title, detail))

    def info(self, *a, **k):
        pass


class FakeApp(A.ShiftWheelApp):
    def __init__(self):  # no tray, no watcher, no IPC
        from PySide6.QtCore import QObject
        QObject.__init__(self)
        self.toasts = FakeToasts()
        self.windows, self.results, self.failures = [], [], []

    def submit(self, action, srcs, fn, working="", extra=""):
        from shiftwheel.util import call_with_progress
        try:
            outs = call_with_progress(fn, lambda f: None) or []
            self.results.append((action, [Path(o) for o in outs]))
        except UserError as e:
            self.failures.append((action, str(e)))

    def open_window(self, w):
        self.windows.append(w)
        w.close()

    def notify(self, *a, **k):
        pass


def files(tmp_path, media_dir, card_photos, doc_photo) -> dict[str, list[str]]:
    from openpyxl import Workbook
    d = tmp_path
    img = d / "photo.png"
    Image.open(card_photos[0]).save(img)
    pdf = d / "doc.pdf"
    Image.open(doc_photo).convert("RGB").save(pdf)
    txt = d / "notes.txt"
    txt.write_text("hello\nworld")
    wb = Workbook()
    wb.active.append(["a", 1])
    xlsx = d / "book.xlsx"
    wb.save(xlsx)
    from docx import Document
    docx = d / "letter.docx"
    doc = Document()
    doc.add_paragraph("Dear ShiftWheel")
    doc.save(docx)
    z = d / "pack.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("x.txt", "x")
    folder = d / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    vid = d / "clip.mp4"
    shutil.copy(media_dir / "clip.mp4", vid)
    aud = d / "tone.wav"
    shutil.copy(media_dir / "tone.wav", aud)
    return {"image": [str(img)], "images×2": [str(card_photos[0]), str(card_photos[1])], "pdf": [str(pdf)],
            "text": [str(txt)], "sheet": [str(xlsx)], "docx": [str(docx)], "archive": [str(z)],
            "folder": [str(folder)], "video": [str(vid)], "audio": [str(aud)],
            "mixed": [str(img), str(txt)]}


WINDOW_SLICES = {"Crop", "Edit", "Annotate", "Redact", "Add BG", "Metadata", "Resize", "Protect", "Text",
                 "ID Card", "Passport", "Scan", "Print", "Trim", "GIF", "Snapshot", "Speed"}


def test_every_slice(tmp_path, media_dir, card_photos, doc_photo, monkeypatch):
    from shiftwheel import office
    if office.find_soffice() is None:
        pytest.skip("needs LibreOffice for docx/slides fidelity path")
    fs = files(tmp_path, media_dir, card_photos, doc_photo)
    app = FakeApp()
    tried = 0
    for kind, paths in fs.items():
        rings = app.build_rings(paths)
        assert rings and all(rings.values()), f"{kind}: empty wheel"
        for ring, items in rings.items():
            for it in items:
                before = (len(app.windows), len(app.results), len(app.failures), len(app.toasts.errors))
                app.run_item(it, list(paths))
                after = (len(app.windows), len(app.results), len(app.failures), len(app.toasts.errors))
                tried += 1
                label = f"{kind} / {ring} / {it.label}"
                assert after[3] == before[3], f"{label}: error toast {app.toasts.errors[-1:]}"
                assert after[2] == before[2], f"{label}: failed {app.failures[-1:]}"
                if after[0] > before[0]:
                    continue                                # a tool window opened
                if (kind == "video" and it.label == "Compress"):
                    continue
                assert after[1] > before[1], f"{label}: did nothing"
                action, outs = app.results[-1]
                assert outs and all(o.exists() for o in outs), f"{label}: no output"
    assert tried > 80


def test_result_texts(tmp_path, media_dir):
    from shiftwheel.report import summarize
    clip = tmp_path / "a.mp4"
    shutil.copy(media_dir / "clip.mp4", clip)
    assert summarize("tool:Merge", [clip, clip], [clip]).title == "Joined 2 clips"
    folder = tmp_path / "out"
    folder.mkdir()
    (folder / "x.txt").write_text("x")
    assert summarize("tool:Unpack", [clip], [folder]).detail == "1 file → out/"
    r = summarize("tool:ID Card", [clip], [clip], "card 85.6 × 54 mm")
    assert r.title == "ID card sheet ready" and r.good == "true size"
    assert summarize("tool:Print", [clip], [], "Sent 1 page to HP at 100% scale").title == "Print sent"
