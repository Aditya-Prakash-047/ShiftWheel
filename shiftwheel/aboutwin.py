"""About ShiftWheel: the creator and links, what's new (release notes, inside the app), and
credits for the projects and libraries it is built on. Same look as Settings."""
from __future__ import annotations

import platform
import sys
import urllib.parse
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from . import __version__, glass
from .window import GlassWindow

RELEASES = "https://github.com/Aditya-Prakash-047/ShiftWheel"

CREATOR = {
    "name": "Aditya Prakash",
    "role": "Creator & developer",
    "bio": "Engineering undergraduate building cross-platform applications and exploring backend systems.",
    "place": "Kanpur, India",
}
# (label, url): shown as buttons under the creator
LINKS = [
    ("GitHub", "https://github.com/Aditya-Prakash-047"),
]
APP_LINKS = [
    ("Downloads", f"{RELEASES}/releases/latest"),
    ("All releases", f"{RELEASES}/releases"),
]
PRIVACY = ("Your files stay on your computer: every conversion runs locally and nothing is uploaded. ShiftWheel "
           "connects to the internet only to check GitHub for updates, which you can turn off in "
           "Settings → Behaviour.")

# (name, what it gives ShiftWheel, licence, url)
CREDITS = [
    ("DragShift", "The original Shift-drag wheel, glass rendering, image and PDF tools", "MIT",
     "https://github.com/llamaboi55/DragShift"),
    ("Qt for Python (PySide6)", "Windows, the wheel, sounds", "LGPL-3.0", "https://doc.qt.io/qtforpython-6/"),
    ("FFmpeg", "Video and audio conversion (via imageio-ffmpeg)", "GPL", "https://ffmpeg.org"),
    ("PyMuPDF", "PDF reading, writing and compression", "AGPL-3.0", "https://pymupdf.readthedocs.io"),
    ("RapidOCR / PP-OCR", "Offline text recognition", "Apache-2.0", "https://github.com/RapidAI/RapidOCR"),
    ("ONNX Runtime", "Runs the OCR models", "MIT", "https://onnxruntime.ai"),
    ("OpenCV", "Card and document edge detection", "Apache-2.0", "https://opencv.org"),
    ("Pillow · pillow-heif", "Images, HEIC and AVIF", "MIT-CMU · BSD", "https://python-pillow.org"),
    ("NumPy", "Image and sound maths", "BSD-3-Clause", "https://numpy.org"),
    ("python-docx · python-pptx · openpyxl", "Word, PowerPoint and Excel files", "MIT", "https://github.com/python-openxml"),
    ("py7zr", "7z archives", "LGPL-2.1", "https://github.com/miurahr/py7zr"),
    ("Python-Markdown", "Markdown documents", "BSD-3-Clause", "https://python-markdown.github.io"),
    ("Segoe Fluent Icons", "Tool icons (from Windows)", "Microsoft", "https://learn.microsoft.com/windows/apps/design/style/segoe-fluent-icons-font"),
]


def release_notes() -> str:
    """This version's notes (RELEASE_NOTES.md, bundled with the app)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    for p in (base / "RELEASE_NOTES.md", Path(__file__).resolve().parents[1] / "RELEASE_NOTES.md"):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return "- Release notes aren't included in this copy."


def system_info() -> str:
    """What a bug report needs. Nothing personal: no user name, no file names."""
    from . import updater
    kind = {"installed": "installed", "portable": "portable", "mac-app": "macOS app"}.get(
        updater.install_kind(), "from source")
    release = platform.release()
    build = platform.version()
    if sys.platform == "win32" and release == "10" and int(build.rsplit(".", 1)[-1] or 0) >= 22000:
        release = "11"                  # Windows 11 still calls itself 10 to older Python versions
    return (f"ShiftWheel {__version__} ({kind})\n"
            f"{platform.system()} {release} ({platform.machine()}, build {build})\n"
            f"Python {platform.python_version()} · Qt {qVersion()}")


def report_url() -> str:
    body = f"**What happened?**\n\n\n**What did you expect?**\n\n\n**System**\n```\n{system_info()}\n```\n"
    return f"{RELEASES}/issues/new?" + urllib.parse.urlencode({"body": body})


def licence_text() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    names = ("NOTICE", "LICENSE", "LICENSES/DragShift-MIT.txt", "THIRD-PARTY-NOTICES.md")
    parts = [(base / n).read_text(encoding="utf-8") for n in names if (base / n).exists()]
    return "\n\n".join(parts) or "GNU AGPL-3.0-or-later. See the LICENSE file."


def _link_button(label: str, url: str, primary: bool = False) -> QPushButton:
    b = QPushButton(label)
    if primary:
        b.setObjectName("primary")
    b.setToolTip(url)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
    return b


def _section(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("section")
    return lab


class AboutWindow(GlassWindow):
    PAGES = ("About", "What's new", "Credits", "Licence")

    def __init__(self, updates=None, page: int = 0):
        super().__init__("About ShiftWheel", size=(760, 740))
        self.updates = updates          # updatectl.UpdateController, or None
        tabs = QHBoxLayout()
        self.tab_buttons = []
        for i, name in enumerate(self.PAGES):
            b = QPushButton(name)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.show_page(i))
            tabs.addWidget(b)
            self.tab_buttons.append(b)
        tabs.addStretch(1)
        self.body.addLayout(tabs)
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, 1)
        for build in (self._about, self._whats_new, self._credits, self._licence):
            page_w = QWidget()
            page_w.setObjectName("page")
            page_w.setStyleSheet("QWidget#page { background: transparent; }")
            lay = QVBoxLayout(page_w)
            lay.setContentsMargins(2, 6, 2, 4)
            lay.setSpacing(10)
            build(lay)
            self.stack.addWidget(page_w)
        foot = QHBoxLayout()
        note = QLabel(f"© 2026 {CREATOR['name']}  ·  GNU AGPL-3.0 licence")
        note.setObjectName("dim")
        foot.addWidget(note)
        foot.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("primary")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        self.body.addLayout(foot)
        self.show_page(page)
        if updates is not None:
            updates.status_changed.connect(self._update_status)
            self._update_status(updates.status)

    def show_page(self, i: int):
        self.stack.setCurrentIndex(i)
        for k, b in enumerate(self.tab_buttons):
            b.setChecked(k == i)

    # ------------------------------------------------------------ About
    def _about(self, lay):
        head = QHBoxLayout()
        icon = QLabel()
        pm = QPixmap(str(Path(__file__).with_name("assets") / "shiftwheel.png"))
        if not pm.isNull():
            icon.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("ShiftWheel")
        title.setObjectName("big")
        col.addWidget(title)
        tag = QLabel("Drag any file, tap a key, drop it on the wheel: convert, edit, print or share it, "
                     "right where you are. Everything stays on your computer.")
        tag.setObjectName("dim")
        tag.setWordWrap(True)
        col.addWidget(tag)
        ver = QLabel(f"Version {__version__}")
        col.addWidget(ver)
        head.addSpacing(10)
        head.addLayout(col, 1)
        lay.addLayout(head)

        lay.addWidget(_section("Made by"))
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(14, 12, 14, 12)
        badge = QLabel("".join(w[0] for w in CREATOR["name"].split()[:2]).upper())
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(52, 52)
        badge.setStyleSheet(f"background: {glass.accent().name()}; color: #ffffff; border-radius: 26px; "
                            "font-weight: 700; font-size: 15pt;")
        g.addWidget(badge, 0, 0, 3, 1, Qt.AlignTop)
        name = QLabel(CREATOR["name"])
        name.setStyleSheet("font-size: 13pt; font-weight: 700;")
        g.addWidget(name, 0, 1)
        role = QLabel(f"{CREATOR['role']}  ·  {CREATOR['place']}")
        role.setObjectName("dim")
        g.addWidget(role, 1, 1)
        bio = QLabel(CREATOR["bio"])
        bio.setWordWrap(True)
        g.addWidget(bio, 2, 1)
        links = QHBoxLayout()
        for label, url in LINKS:
            links.addWidget(_link_button(label, url))
        links.addStretch(1)
        g.addLayout(links, 3, 1)
        g.setColumnStretch(1, 1)
        g.setHorizontalSpacing(14)
        lay.addWidget(card)

        lay.addWidget(_section("ShiftWheel"))
        row = QHBoxLayout()
        for label, url in APP_LINKS:
            row.addWidget(_link_button(label, url))
        row.addWidget(_link_button("Report a problem", report_url()))
        row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_section("Updates"))
        urow = QHBoxLayout()
        self.upd_status = QLabel(f"Version {__version__}")
        self.upd_status.setObjectName("dim")
        self.upd_status.setWordWrap(True)
        urow.addWidget(self.upd_status, 1)
        self.upd_check = QPushButton("Check for updates")
        self.upd_check.setEnabled(self.updates is not None)
        if self.updates is not None:
            self.upd_check.clicked.connect(lambda: self.updates.check(quiet=False))
        urow.addWidget(self.upd_check)
        self.upd_install = QPushButton("Install update")
        self.upd_install.setObjectName("primary")
        self.upd_install.setVisible(False)
        if self.updates is not None:
            self.upd_install.clicked.connect(lambda: self.updates.install())
        urow.addWidget(self.upd_install)
        lay.addLayout(urow)

        lay.addWidget(_section("Privacy"))
        privacy = QLabel(PRIVACY)
        privacy.setObjectName("dim")
        privacy.setWordWrap(True)
        lay.addWidget(privacy)

        lay.addWidget(_section("System"))
        srow = QHBoxLayout()
        info = QLabel(system_info())
        info.setObjectName("dim")
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        srow.addWidget(info, 1)
        self.copy_btn = QPushButton("Copy details")
        self.copy_btn.clicked.connect(self._copy_info)
        srow.addWidget(self.copy_btn, 0, Qt.AlignTop)
        lay.addLayout(srow)
        lay.addStretch(1)

    def _copy_info(self):
        QGuiApplication.clipboard().setText(system_info())
        self.copy_btn.setText("Copied ✓")
        QTimer.singleShot(1400, lambda: self.copy_btn.setText("Copy details"))

    # ------------------------------------------------------------ Licence
    def _licence(self, lay):
        view = self._notes_view()
        view.setPlainText(licence_text())
        lay.addWidget(view, 1)

    def _update_status(self, text: str):
        try:
            self.upd_status.setText(text)
            rel = self.updates.available if self.updates else None
            for b in (self.upd_install, self.new_install):
                b.setVisible(rel is not None)
                if rel is not None:
                    b.setText(f"Install {rel.version}")
            if rel is not None:
                self.new_head.setText(f"ShiftWheel {rel.version} is available")
                self.new_notes.setMarkdown(rel.notes or "No notes for this release.")
                self.new_box.setVisible(True)
        except RuntimeError:            # window closed
            pass

    # ------------------------------------------------------------ What's new
    def _whats_new(self, lay):
        self.new_box = QFrame()
        self.new_box.setObjectName("card")
        nb = QVBoxLayout(self.new_box)
        nb.setContentsMargins(14, 10, 14, 12)
        top = QHBoxLayout()
        self.new_head = QLabel("")
        self.new_head.setStyleSheet("font-size: 12pt; font-weight: 700;")
        top.addWidget(self.new_head, 1)
        self.new_install = QPushButton("Install update")
        self.new_install.setObjectName("primary")
        if self.updates is not None:
            self.new_install.clicked.connect(lambda: self.updates.install())
        top.addWidget(self.new_install)
        nb.addLayout(top)
        self.new_notes = self._notes_view()
        self.new_notes.setMaximumHeight(170)
        nb.addWidget(self.new_notes)
        self.new_box.setVisible(False)
        lay.addWidget(self.new_box)

        lay.addWidget(_section(f"In version {__version__}"))
        notes = self._notes_view()
        notes.setMarkdown(release_notes())
        lay.addWidget(notes, 1)
        row = QHBoxLayout()
        row.addWidget(_link_button("All release notes", f"{RELEASES}/releases"))
        row.addStretch(1)
        lay.addLayout(row)

    @staticmethod
    def _notes_view() -> QTextBrowser:
        v = QTextBrowser()
        v.setOpenExternalLinks(True)
        v.setFrameShape(QFrame.NoFrame)
        v.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        return v

    # ------------------------------------------------------------ Credits
    def _credits(self, lay):
        intro = QLabel("ShiftWheel stands on the work of these projects. Thank you.")
        intro.setObjectName("dim")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setFrameShape(QFrame.NoFrame)
        view.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        acc = glass.accent().name()
        rows = "".join(
            f"<tr><td style='padding:6px 14px 6px 0'><a href='{url}' style='color:{acc}; text-decoration:none'>"
            f"<b>{name}</b></a></td><td style='padding:6px 14px 6px 0'>{what}</td>"
            f"<td style='padding:6px 0; opacity:0.7'>{lic}</td></tr>"
            for name, what, lic, url in CREDITS)
        view.setHtml(f"<table cellspacing='0'>{rows}</table>"
                     "<p style='margin-top:14px'>ShiftWheel's own code is MIT-licensed. The bundled FFmpeg, "
                     "PyMuPDF and Qt keep their own licences (GPL, AGPL, LGPL).</p>")
        lay.addWidget(view, 1)
