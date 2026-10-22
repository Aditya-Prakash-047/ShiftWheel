"""ShiftWheel: Shift+drag any file to convert or edit it from a radial liquid-glass menu."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QDir, QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QPainter,
                           QPixmap)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon, QWidget

from . import (__version__, archive, convert, glass, imaging, media, mediawin, ocr, ocrwin, office, printwin,
               report, tools)
from .radial import Item, RadialMenu
from .settings import Settings, SettingsWindow, WelcomeWindow, TRIGGERS
from .toasts import ToastStack
from .trigger import ShiftWheelWatcher
from .util import UserError, call_with_progress, category, file_size, human_size, keep, release

APP_NAME = "ShiftWheel"
REPO_URL = "https://github.com/Aditya-prakash-047/ShiftWheel"
CREDITS_URL = "https://github.com/llamaboi55/DragShift"
VERSION = __version__
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
from .handoff import ipc_name
IPC_NAME = ipc_name()

GLYPHS = {"Compress": "⇲", "Metadata": "ⓘ", "Redact": "▮", "Crop": "⌗", "Edit": "☼",
          "Annotate": "✎", "Add BG": "▣", "Resize": "⤢", "Split": "✂", "Rotate": "⟳",
          "Merge": "⧉", "Protect": "⚿", "Extract": "⧈",
          "ID Card": "▤", "Passport": "☺", "Scan": "⬚", "Print": "⎙",
          "Text": "¶", "OCR": "¶", "Zip": "▦", "7Z": "▦",
          "Trim": "✂", "GIF": "◎", "Snapshot": "◫", "Mute": "⊘", "Speed": "»", "Normalize": "≋"}

HINTS = {
    "Compress": "Shrink file size", "Metadata": "View · remove GPS", "Redact": "Hide private info",
    "Crop": "Trim to a ratio", "Edit": "Light · colour · rotate", "Annotate": "Arrows · text · steps",
    "Add BG": "Gradient backdrop", "Resize": "Change dimensions", "Split": "One PDF per page",
    "Rotate": "Turn pages 90°", "Merge": "Join into one PDF", "Protect": "Add a password",
    "Extract": "Save embedded images",
    "ID Card": "Front + back, real size", "Passport": "35×45 photo sheet",
    "Scan": "Photo → clean PDF", "Print": "Exact size · N-up",
    "Trim": "Cut start / end", "GIF": "Clip → looping GIF", "Snapshot": "Save a frame as PNG",
    "Text": "Copy text from photo", "OCR": "Make it searchable", "Zip": "Compress into .zip",
    "7Z": "Smaller .7z archive",
    "Mute": "Remove the sound", "Speed": "0.25× – 4×", "Normalize": "Even out loudness",
}
FORMAT_HINTS = {"JPG": "Small, universal", "PNG": "Lossless · transparency", "WEBP": "Smallest for web",
                "HEIC": "iPhone format", "TIFF": "Print · archival", "AVIF": "Next-gen, tiny",
                "BMP": "Uncompressed", "PDF": "Document", "ICO": "Windows icon", "GIF": "Legacy web",
                "DOCX": "Editable Word", "TXT": "Plain text"}

IMAGE_TOOLS = ["Compress", "Resize", "Crop", "Edit", "Annotate", "Redact", "Add BG", "Metadata", "Text"]
PDF_TOOLS = ["Compress", "Split", "Rotate", "Protect", "Extract", "Metadata", "OCR"]
VIDEO_TOOLS = ["Compress", "Trim", "GIF", "Snapshot", "Rotate", "Mute", "Speed"]
AUDIO_TOOLS = ["Trim", "Compress", "Normalize", "Speed"]
MEDIA_HINTS = {"Compress": "Smaller MP4 · target size", "Rotate": "Turn 90° clockwise", "Merge": "Join in order"}
IMAGE_PRINT = ["ID Card", "Passport", "Scan", "Print"]
PDF_PRINT = ["Print", "ID Card", "Scan"]
PRINT_WINDOWS = {"ID Card": printwin.IDCardWindow, "Passport": printwin.PassportWindow,
                 "Scan": printwin.ScanWindow, "Print": printwin.PrintWindow}


# ---------------------------------------------------------------- background jobs
class _Sig(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float)


class Job(QRunnable):
    def __init__(self, action: str, srcs: list, fn, extra: str = ""):
        super().__init__()
        self.action, self.srcs, self.fn, self.extra = action, srcs, fn, extra
        self.sig = _Sig()

    def run(self):
        try:
            last = {"t": 0.0}

            def report_progress(f: float):
                now = time.monotonic()
                if f >= 1.0 or now - last["t"] > 0.25:   # throttle UI updates
                    last["t"] = now
                    try:
                        self.sig.progress.emit(float(f))
                    except RuntimeError:
                        pass
            outs = call_with_progress(self.fn, report_progress) or []
            self.sig.done.emit(report.summarize(self.action, self.srcs, outs, self.extra))
        except UserError as e:
            self.sig.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.sig.failed.emit(friendly_error(e))


def friendly_error(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    low = msg.lower()
    if isinstance(e, PermissionError) or "permission denied" in low:
        return "No permission to write next to this file. Try a folder you own, or set Settings → Save results → subfolder."
    if "cannot identify image" in low:
        return "This file doesn't look like an image ShiftWheel can read."
    if isinstance(e, FileNotFoundError):
        return "The file was moved or deleted."
    return msg


# ---------------------------------------------------------------- icon
def make_tray_icon() -> QIcon:
    """macOS menu bar wants a monochrome 'template' image; Windows gets the colour icon."""
    if not IS_MAC:
        return make_icon()
    pm = QPixmap(44, 44)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QPen
    p.setPen(QPen(QColor(0, 0, 0), 4.5))
    p.drawEllipse(QPointF(22, 22), 14, 14)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0))
    p.drawEllipse(QPointF(22, 22), 5, 5)
    for a in range(0, 360, 45):  # petal gaps
        import math
        x, y = 22 + 14 * math.cos(math.radians(a + 22.5)), 22 + 14 * math.sin(math.radians(a + 22.5))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    p.end()
    pm.setDevicePixelRatio(2.0)
    icon = QIcon(pm)
    icon.setIsMask(True)
    return icon


def make_icon() -> QIcon:
    ico = Path(__file__).with_name("assets") / "shiftwheel.ico"
    if ico.exists():
        return QIcon(str(ico))
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(glass.iridescent_pen(QPointF(32, 32), 7, 255))
    p.drawEllipse(QPointF(32, 32), 24, 24)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------- the app
class ShiftWheelApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.settings = Settings()
        self.settings.apply()
        self.pool = QThreadPool.globalInstance()
        self.windows: list[QWidget] = []
        self.toasts = ToastStack()
        self.menu = RadialMenu(self.build_rings, self.describe)
        self.menu.activated.connect(self.run_item)

        # the watcher only manages menus it opened (drag mode); click-mode menus (tray, right-click,
        # Send To) must not be closed just because no mouse button is held
        self.watcher = ShiftWheelWatcher(lambda: self.menu.isVisible() and not self.menu.click_mode,
                                        lambda: self.menu.got_drag, self)
        self.watcher.set_key(self.settings.get("trigger"))
        self.watcher.show_menu.connect(lambda pos: self.menu.popup(pos))
        self.watcher.toggle_ring.connect(self.menu.next_ring)
        self.watcher.hide_menu.connect(self.menu.close_menu)
        self.watcher.start()

        # files handed over by "Send to", the right-click menu, or a second launch
        self._pending: list[str] = []
        self._pending_timer = QTimer(self, singleShot=True, interval=280, timeout=self._flush_pending)
        self.server = QLocalServer(self)
        QLocalServer.removeServer(IPC_NAME)
        self.server.listen(IPC_NAME)
        self.server.newConnection.connect(self._ipc)

        self.tray = QSystemTrayIcon(make_tray_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} — press {self.trigger_label()} while dragging a file")
        m = QMenu()
        m.setStyleSheet(glass.QSS)
        self.act_enabled = QAction("Enabled", m, checkable=True, checked=True)
        self.act_enabled.toggled.connect(lambda on: setattr(self.watcher, "enabled", on))
        m.addAction(self.act_enabled)
        m.addAction("Open a file…", self.open_dialog)
        m.addSeparator()
        m.addAction("Settings…", self.open_settings)
        m.addAction("How to use", self.show_welcome)
        m.addAction("About / credits", lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        m.addSeparator()
        m.addAction(f"Quit {APP_NAME}", self.qapp.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

    def trigger_label(self) -> str:
        return dict(TRIGGERS).get(self.settings.get("trigger"), "Shift")

    # ------------------------------------------------------------ IPC
    def _ipc(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = {"v": False}

        def consume():
            if done["v"]:
                return
            try:
                buf.extend(bytes(sock.readAll()))
            except RuntimeError:
                pass
            try:
                data = json.loads(buf.decode("utf-8"))
            except Exception:
                return  # incomplete: wait for more
            done["v"] = True
            files = [f for f in data.get("files", []) if os.path.exists(f)]
            print(f"IPC: {len(files)} file(s) handed over", flush=True)
            if files:
                self.queue_files(files)
            elif data.get("show"):
                self.toasts.info("ShiftWheel is already running",
                                 f"Drag any file and press {self.trigger_label()}. It lives in the tray.")
            sock.disconnectFromServer()
            sock.deleteLater()

        # Windows pipes: the sender may already be gone, so read on every signal + a fallback timer
        sock.readyRead.connect(consume)
        sock.disconnected.connect(consume)
        for ms in (0, 50, 200, 600):
            QTimer.singleShot(ms, consume)

    def queue_files(self, files: list[str]):
        """Explorer's right-click menu launches once per file: gather them, then show one menu."""
        for f in files:
            if f not in self._pending:
                self._pending.append(f)
        self._pending_timer.start()

    def _flush_pending(self):
        files, self._pending = self._pending, []
        if files:
            self.show_click_menu(files)

    # ------------------------------------------------------------ menu contents
    def describe(self, paths: list[str]) -> str:
        if len(paths) > 1:
            return f"{len(paths)} files"
        return human_size(file_size(paths[0]))

    def build_rings(self, paths: list[str]) -> dict[str, list[Item]]:
        cat = category(paths[0])
        if cat is None or len({category(p) for p in paths}) > 1:
            # folders, unknown files, or a mixed selection: pack them
            label = f"{len(paths)} items" if len(paths) > 1 else "Pack"
            return {"Tools": [Item("Zip", GLYPHS["Zip"], key="pack:ZIP", hint=label),
                              Item("7Z", GLYPHS["7Z"], key="pack:7Z", hint=HINTS["7Z"])]}
        if cat in ("sheet", "slides", "worddoc"):
            ext_u = Path(paths[0]).suffix.lstrip(".").upper()
            targets = {"sheet": office.SHEET_TARGETS, "slides": office.SLIDE_TARGETS,
                       "worddoc": office.WORDDOC_TARGETS}[cat]
            return {"Convert": [Item(t, key=f"convert:{t}", hint=office.HINTS.get(t, "")) for t in targets
                                if t != ext_u],
                    "Tools": [Item("Zip", GLYPHS["Zip"], key="pack:ZIP", hint=HINTS["Zip"])]}
        if cat == "archive":
            k = archive.kind(paths[0])
            return {"Tools": [Item("Extract", GLYPHS["Extract"], key="archive:Extract", hint="Unpack here")] +
                    [Item(t, key=f"archive:{t}", hint=f"Convert to .{t.lower()}") for t in archive.ARCHIVE_TARGETS
                     if t.lower() != k]}
        ext = Path(paths[0]).suffix
        same = [p for p in paths if category(p) == cat]
        if cat in ("video", "audio"):
            cur = ext.lstrip(".").upper().replace("JPEG", "JPG")
            targets, hints = (media.VIDEO_TARGETS, media.VIDEO_HINTS) if cat == "video" else \
                (media.AUDIO_TARGETS, media.AUDIO_HINTS)
            names = (VIDEO_TOOLS if cat == "video" else AUDIO_TOOLS) + (["Merge"] if len(same) > 1 else [])
            return {"Convert": [Item(t, key=f"convert:{t}", hint=hints.get(t, "")) for t in targets if t != cur],
                    "Tools": [Item(n, GLYPHS[n], key=f"tool:{n}", hint=MEDIA_HINTS.get(n, HINTS.get(n, "")))
                              for n in names]}
        convert_items = []
        for t in convert.targets_for(cat, ext):
            hint = FORMAT_HINTS.get(t, "")
            if cat == "image" and t == "PDF" and len(same) > 1:
                hint = f"{len(same)} images → 1 PDF"
            convert_items.append(Item(t, key=f"convert:{t}", hint=hint))
        rings: dict[str, list[Item]] = {"Convert": convert_items}
        if cat == "image":
            rings["Tools"] = [Item(n, GLYPHS[n], key=f"tool:{n}", hint=HINTS[n]) for n in IMAGE_TOOLS]
        elif cat == "pdf":
            names = PDF_TOOLS[:3] + (["Merge"] if len(same) > 1 else []) + PDF_TOOLS[3:]
            rings["Tools"] = [Item(n, GLYPHS[n], key=f"tool:{n}", hint=HINTS[n]) for n in names]
        if cat in ("image", "pdf"):
            names = IMAGE_PRINT if cat == "image" else PDF_PRINT
            rings["Print"] = [Item(n, GLYPHS[n], key=f"print:{n}", hint=HINTS[n]) for n in names]
        return rings

    # ------------------------------------------------------------ actions
    def _open_tool(self, name: str, cls, paths: list[str]):
        try:
            self.open_window(cls(paths, self.notify))
        except (UserError, ValueError) as e:
            self.toasts.error(f"Couldn't open {name}", str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.toasts.error(f"Couldn't open {name}", friendly_error(e))

    def run_item(self, item: Item, paths: list[str]):
        self._all_paths = list(paths)
        cat = category(paths[0])
        paths = [p for p in paths if category(p) == cat]
        kind, name = item.key.split(":", 1)
        if kind == "pack":
            allp = self._all_paths
            self.submit("tool:Zip", allp, lambda: [archive.zip_paths(allp, name)], "Compressing…")
            return
        if kind == "archive":
            if name == "Extract":
                self.submit("tool:Unpack", paths, lambda: [archive.extract(p) for p in paths], "Unpacking…")
            else:
                self.submit(f"convert:{name}", paths, lambda: [archive.convert_archive(p, name) for p in paths],
                            f"Converting to {name}…")
            return
        if cat in ("sheet", "slides", "worddoc") and kind == "convert":
            fn = {"sheet": office.convert_sheet, "slides": office.convert_slides,
                  "worddoc": office.convert_worddoc}[cat]
            self.submit(f"convert:{name}", paths, lambda: [o for p in paths for o in fn(p, name)],
                        f"Converting to {name}…")
            return
        if name == "Text" and cat == "image":
            self._open_tool("Text", lambda ps, n: ocrwin.ExtractTextWindow(ps[0], n), paths)
            return
        if name == "OCR" and cat == "pdf":
            self.submit("tool:OCR", paths,
                        lambda progress=None: [ocr.make_searchable(p, progress=progress) for p in paths],
                        "Reading text…")
            return
        if kind == "print":
            # ID Card / Scan / Print take images and PDFs together (e.g. front.jpg + back.pdf)
            mixed = [p for p in self._all_paths if category(p) in ("image", "pdf")] or paths
            self._open_tool(name, PRINT_WINDOWS[name], mixed if name != "Passport" else paths[:1])
            return
        if cat in ("video", "audio"):
            self.run_media(kind, name, cat, paths)
            return
        if kind == "convert":
            if cat == "image" and name == "PDF" and len(paths) > 1:
                self.submit(f"convert:{name}", paths, lambda: convert.images_to_single_pdf(paths),
                            f"Combining {len(paths)} images…")
            else:
                verb = f"Converting to {name}…"
                self.submit(f"convert:{name}", paths,
                            lambda: [o for p in paths for o in convert.convert(p, cat, name)], verb)
            return
        if cat == "pdf":
            if name == "Merge":
                self.submit("tool:Merge", paths, lambda: [imaging.merge_pdfs(paths)], "Merging…")
            elif name == "Metadata":
                self.open_window(tools.MetadataWindow(paths[0], self.notify, is_pdf=True))
            elif name == "Protect":
                self.open_window(tools.ProtectWindow(paths[0], self.notify))
            else:
                fns = {"Compress": lambda p: [imaging.compress_pdf(p)], "Split": imaging.split_pdf,
                       "Rotate": lambda p: [imaging.rotate_pdf(p)], "Extract": imaging.extract_pdf_images}
                f = fns[name]
                self.submit(f"tool:{name}", paths, lambda: [o for p in paths for o in f(p)],
                            {"Compress": "Compressing…", "Split": "Splitting…", "Rotate": "Rotating…",
                             "Extract": "Extracting images…"}[name])
            return
        windows = {"Crop": tools.CropWindow, "Add BG": tools.AddBgWindow, "Annotate": tools.AnnotateWindow,
                   "Redact": tools.RedactWindow, "Edit": tools.EditWindow, "Metadata": tools.MetadataWindow}
        try:
            if name == "Compress":
                self.open_window(tools.CompressWindow(paths, self.notify))
            elif name == "Resize":
                self.open_window(tools.ResizeWindow(paths, self.notify))
            else:
                self.open_window(windows[name](paths[0], self.notify))
        except UserError as e:
            self.toasts.error(f"Couldn't open {name}", str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.toasts.error(f"Couldn't open {name}", friendly_error(e))

    def run_media(self, kind: str, name: str, cat: str, paths: list[str]):
        if kind == "convert":
            fn = media.convert_video if cat == "video" else media.convert_audio

            def work(progress=None):
                outs, n = [], len(paths)
                for k, p in enumerate(paths):
                    sub = (lambda f, k=k: progress((k + f) / n)) if progress else None
                    outs += fn(p, name, sub)
                return outs
            self.submit(f"convert:{name}", paths, work, f"Converting to {name}…")
            return
        quick = {"Rotate": (lambda p, progress=None: media.rotate_video(p, 90, progress), "Rotating…"),
                 "Mute": (media.mute, "Removing sound…"),
                 "Normalize": (media.normalize, "Evening out loudness…")}
        if name == "Merge":
            self.submit("tool:Merge", paths, lambda progress=None: [media.merge(paths, progress)],
                        f"Joining {len(paths)} files…")
        elif name in quick:
            f, verb = quick[name]

            def work(progress=None):
                outs, n = [], len(paths)
                for k, p in enumerate(paths):
                    sub = (lambda x, k=k: progress((k + x) / n)) if progress else None
                    outs.append(f(p, progress=sub))
                return outs
            self.submit(f"tool:{name}", paths, work, verb)
        elif name == "Compress":
            if cat == "audio":
                self.submit("tool:Compress", paths,
                            lambda progress=None: [media.compress_audio(p, 96, progress) for p in paths],
                            "Compressing audio…")
            else:
                self._open_tool(name, mediawin.VideoCompressWindow, paths)
        elif name in ("Trim", "GIF", "Snapshot"):
            mode = {"Trim": "trim", "GIF": "gif", "Snapshot": "snapshot"}[name]
            self._open_tool(name, lambda ps, n: mediawin.TrimWindow(ps[0], n, mode), paths)
        elif name == "Speed":
            self._open_tool(name, lambda ps, n: mediawin.SpeedWindow(ps[0], n), paths)

    def open_window(self, w: QWidget):
        if hasattr(w, "submit"):
            w.submit = self.submit
        self.windows.append(w)
        w.destroyed.connect(lambda *_: self.windows.remove(w) if w in self.windows else None)
        if hasattr(w, "present"):
            w.present()
        else:
            w.show()

    def submit(self, action: str, srcs: list, fn, working: str = "Working…", extra: str = ""):
        """Run in the background. A spinner card appears only if it takes > 150 ms."""
        state = {"card": None, "finished": False}
        names = Path(srcs[0]).name if len(srcs) == 1 else f"{len(srcs)} files"

        def show_spinner():
            if not state["finished"]:
                state["card"] = self.toasts.new()
                state["card"].working(working, names)

        QTimer.singleShot(150, show_spinner)
        job = Job(action, srcs, fn, extra)

        def done(r):
            release(job)
            state["finished"] = True
            card = state["card"] or self.toasts.new()
            card.done(r)

        def failed(msg):
            release(job)
            state["finished"] = True
            card = state["card"] or self.toasts.new()
            card.error("Couldn't finish", msg)

        def progress(f):
            if state["finished"]:
                return
            if state["card"] is None:
                state["card"] = self.toasts.new()
            state["card"].working(working, f"{names}  ·  {int(f * 100)}%")

        job.sig.done.connect(done)
        job.sig.failed.connect(failed)
        job.sig.progress.connect(progress)
        self.pool.start(keep(job))

    def notify(self, action: str, srcs: list, outs: list, extra: str = ""):
        """Called by tool windows after they save."""
        self.toasts.new().done(report.summarize(action, srcs, outs, extra))

    # ------------------------------------------------------------ misc
    def _tray_click(self, reason):
        # macOS: a click on the menu-bar icon shows the menu; Windows: click opens a file
        if not IS_MAC and reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.open_dialog()

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(None, "Choose file(s) for ShiftWheel", QDir.homePath())
        if files:
            self.show_click_menu(files)

    def show_click_menu(self, files: list[str]):
        g = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        pos = QCursor.pos() if g.contains(QCursor.pos()) else g.center()
        self.menu.popup(pos, files)
        self.menu.activateWindow()

    def open_settings(self):
        w = SettingsWindow(self.settings)
        w.changed.connect(self._settings_changed)
        self.open_window(w)

    def _settings_changed(self):
        self.watcher.set_key(self.settings.get("trigger"))
        self.tray.setToolTip(f"{APP_NAME} — press {self.trigger_label()} while dragging a file")

    def show_welcome(self):
        self.open_window(WelcomeWindow(self.settings, self.trigger_label()))


class ShiftWheelQApplication(QApplication):
    """macOS delivers files from Finder's "Open With", the Dock and `open -a` as FileOpen
    events (not argv)."""
    file_opened = Signal(str)

    def __init__(self, argv):
        super().__init__(argv)
        self.early_files: list[str] = []

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.FileOpen:
            f = e.file()
            if f:
                self.early_files.append(f)
                self.file_opened.emit(f)
            return True
        return super().event(e)


def mac_setup(qapp):
    # fonts: util.ui_family picks a real installed family. (Substituting the private
    # ".AppleSystemUIFont" made labels draw nothing on macOS 26.)
    try:
        from . import platform_mac
        platform_mac.become_accessory()
    except Exception:
        pass


def send_to_running(payload: dict) -> bool:
    s = QLocalSocket()
    s.connectToServer(IPC_NAME)
    if not s.waitForConnected(300):
        return False
    s.write(json.dumps(payload).encode("utf-8"))
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def setup_logging():
    """Errors go to %LOCALAPPDATA%\\ShiftWheel\\log.txt (pythonw / the .exe have no console)."""
    import faulthandler
    if IS_MAC:
        base = Path.home() / "Library" / "Logs" / "ShiftWheel"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "ShiftWheel"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "log.txt"
    if path.exists() and path.stat().st_size > 1_000_000:
        path.replace(base / "log.old.txt")
    f = open(path, "a", encoding="utf-8", buffering=1)
    f.write(f"\n==== ShiftWheel {VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
    if sys.stderr is None or getattr(sys, "frozen", False) or sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = f
    faulthandler.enable(f)

    def hook(t, v, tb):
        f.write("Unhandled: " + "".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = hook
    return path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    try:
        setup_logging()
    except Exception:
        pass
    if IS_WIN:
        try:  # crisp taskbar/tray icon grouping
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ShiftWheel.App")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = ShiftWheelQApplication(argv)
    if IS_MAC:
        mac_setup(qapp)
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(make_icon())

    if "--selftest" in argv:
        return selftest()
    files = [os.path.abspath(a) for a in argv[1:] if not a.startswith("-") and os.path.exists(a)]
    # already running? hand over and exit (instant: no second UI start-up)
    if send_to_running({"files": files} if files else {"show": "--quiet" not in argv}):
        return 0
    app = ShiftWheelApp(qapp)
    qapp.file_opened.connect(lambda f: app.queue_files([f]))
    if qapp.early_files:
        app.queue_files(list(qapp.early_files))
    if files:  # e.g. "Send to → ShiftWheel" or drag onto the .exe
        QTimer.singleShot(120, lambda: app.queue_files(files))
    elif not app.settings.get("welcomed"):
        QTimer.singleShot(300, app.show_welcome)
    elif "--quiet" not in argv:
        QTimer.singleShot(400, lambda: app.toasts.info(
            "ShiftWheel is running", f"Drag any file, then press {app.trigger_label()}."))
    return qapp.exec()


def check_text_renders():
    """Labels must really draw: paint text with the UI fonts and count the inked pixels."""
    from PySide6.QtGui import QImage, QPainter, QColor
    from .util import ui_font, ui_family
    for display in (True, False):
        img = QImage(200, 40, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setFont(ui_font(16, True, display))
        p.setPen(QColor(255, 255, 255))
        p.drawText(img.rect(), Qt.AlignCenter, "WEBP 43.8 KB")
        p.end()
        inked = sum(1 for y in range(0, 40, 2) for x in range(0, 200, 2) if img.pixelColor(x, y).alpha() > 60)
        print(f"font {ui_family(display)!r}: {inked} inked samples")
        if inked < 30:
            raise RuntimeError(f"text does not render with font {ui_family(display)!r}")


def selftest() -> int:
    """Used by CI on the frozen .exe: exercise every library and build the UI, then exit."""
    import tempfile
    from PIL import Image
    try:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "t.png"
            Image.new("RGBA", (64, 48), (255, 100, 80, 255)).save(src)
            for t in convert.targets_for("image", ".png"):
                convert.convert(src, "image", t)
            pdf = convert.convert(src, "image", "PDF")[0]
            for t in convert.PDF_TARGETS:
                convert.convert(pdf, "pdf", t)
            (Path(d) / "n.txt").write_text("hello")
            docx = convert.convert(Path(d) / "n.txt", "text", "DOCX")[0]
            convert.convert(docx, "docx", "TXT")
            imaging.add_background(convert.open_image(src), imaging.Background())
            imaging.compress_pdf(pdf)
            imaging.protect_pdf(pdf, "pw")
            from . import liquid
            liquid.render(Image.new("RGB", (80, 80)), liquid.sdf_circle(80, 80, 40, 40, 30))
            menu = RadialMenu(lambda p: {"Convert": [Item("PNG")]}, lambda p: "1 KB")
            menu._load([str(src)])
            n = lambda *a, **k: None
            for w in (tools.CropWindow(str(src), n), tools.AddBgWindow(str(src), n), tools.EditWindow(str(src), n),
                      tools.AnnotateWindow(str(src), n), tools.RedactWindow(str(src), n),
                      tools.MetadataWindow(str(src), n), tools.CompressWindow([str(src)], n),
                      tools.ResizeWindow([str(src)], n), tools.ProtectWindow(str(pdf), n)):
                w.close()
            ToastStack().info("ok", "ok").dismiss()
            check_text_renders()
            selftest_extras(Path(d), src, pdf)
        print("SELFTEST OK")
        return 0
    except Exception:
        traceback.print_exc()
        print("SELFTEST FAILED")
        return 1


def selftest_extras(d: Path, png: Path, pdf: Path) -> None:
    """ShiftWheel additions: proves FFmpeg, OpenCV, OCR models, Qt printing, spreadsheets and 7z
    are all packaged and working inside the frozen build."""
    import subprocess
    from PIL import Image, ImageDraw
    from . import archive, media, mediawin, ocr, ocrwin, office, printing, printwin
    n = lambda *a, **k: None

    # print ring: card detection + exact-size sheet + Qt print path
    card = Image.new("RGB", (1200, 900), (60, 50, 40))
    ImageDraw.Draw(card).rectangle([200, 220, 1056, 760], fill=(240, 240, 250))
    cp = d / "card.jpg"
    card.save(cp)
    q = printing.find_card(card)
    assert q is not None, "card detection (OpenCV) failed"
    sheet = printing.id_sheet([printing.warp_quad(card, q)], "A4")
    printing.print_pages(sheet, pdf_file=str(d / "printed.pdf"))
    print("print ring OK")

    # video & audio through the bundled FFmpeg
    exe = media.ffmpeg_exe()
    clip = d / "clip.mp4"
    subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x240:rate=15:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
                   check=True, creationflags=media.CREATE_NO_WINDOW)
    info = media.probe(clip)
    assert info.width == 320 and info.has_audio, "ffprobe parse failed"
    media.convert_video(clip, "WEBM")
    media.convert_video(clip, "GIF")
    mp3 = media.convert_video(clip, "MP3")[0]
    media.trim(clip, 0.2, 1.2)
    media.compress_video(clip, target_mb=0.05)
    assert media.filmstrip(clip, 4, 40) is not None
    print("media OK")

    # OCR (models bundled)
    if ocr.available():
        from PySide6.QtGui import QImage, QPainter, QColor
        from .util import ui_font
        qi = QImage(900, 140, QImage.Format_RGB32)
        qi.fill(QColor("white"))
        p = QPainter(qi)
        p.setFont(ui_font(44))
        p.setPen(QColor("black"))
        p.drawText(30, 90, "Selftest 2026 OK")
        p.end()
        tp = d / "text.png"
        qi.save(str(tp))
        txt = ocr.image_text(tp)
        assert "2026" in txt, f"OCR read {txt!r}"
        print(f"OCR OK: {txt!r}")

    # spreadsheets & archives
    csvp = d / "t.csv"
    csvp.write_text("a,b\n1,2\n")
    x = office.convert_sheet(csvp, "XLSX")[0]
    office.convert_sheet(x, "CSV")
    office.tables_to_pdf(office.read_table(x), d / "t-table.pdf")
    z = archive.zip_paths([csvp, x], "7Z")
    archive.extract(z)
    print("office/archive OK")

    for w in (printwin.IDCardWindow([str(cp)], n), printwin.PassportWindow([str(png)], n),
              printwin.ScanWindow([str(cp)], n), printwin.PrintWindow([str(pdf)], n),
              mediawin.TrimWindow(str(clip), n), mediawin.TrimWindow(str(mp3), n),
              mediawin.VideoCompressWindow([str(clip)], n), mediawin.SpeedWindow(str(clip), n),
              ocrwin.ExtractTextWindow(str(png), n)):
        w.close()
    print("windows OK")
