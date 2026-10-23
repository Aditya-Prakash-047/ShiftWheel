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

from . import (__version__, archive, convert, extras, fileops, glass, hotkey, imaging, media, mediawin, ocr,
               ocrwin, office, printwin, report, saveas, sounds, themes, tools, tools2)
from .radial import Item, RadialMenu
from .settings import KEY_LABEL, KEY_VK, Settings, SettingsWindow, WelcomeWindow
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

GLYPHS = {"QR code": "▦", "Collage": "▚", "Organize": "▤", "Channels": "◐", "Bleep": "♪", "Visualize": "∿",
          "Silence": "✂", "Compress": "⇲", "Metadata": "ⓘ", "Redact": "▮", "Crop": "⌗", "Edit": "☼",
          "Annotate": "✎", "Add BG": "▣", "Resize": "⤢", "Split": "✂", "Rotate": "⟳",
          "Merge": "⧉", "Protect": "⚿", "Extract": "⧈",
          "ID Card": "▤", "Passport": "☺", "Scan": "⬚", "Print": "⎙",
          "Text": "¶", "OCR": "¶", "Zip": "▦", "7Z": "▦",
          "Trim": "✂", "GIF": "◎", "Snapshot": "◫", "Mute": "⊘", "Speed": "»", "Normalize": "≋",
          "Copy path": "⎘", "Show": "⌕", "SHA-256": "#", "Duplicate": "❐", "Copy": "⧉", "Move": "➜",
          "Terminal": ">_", "Share": "⇪", "Float": "◳"}

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
    "QR code": "Read it · copy the text", "Collage": "Grid, row, featured…", "Organize": "Reorder · rotate · remove",
    "Channels": "Mono · stereo · L/R", "Bleep": "Hide words", "Visualize": "Audio → MP4",
    "Silence": "Trim quiet start / end",
    "Copy path": "Path as text", "Show": "Open its folder", "SHA-256": "Checksum → clipboard",
    "Duplicate": "Make a copy", "Copy": "Paste it anywhere", "Move": "To another folder",
    "Terminal": "Open a terminal here", "Share": "Windows share", "Float": "Keep it handy",
}
# Santra's Actions wheel (AirDrop → Windows Share), plus ShiftWheel's extras
FILE_ACTIONS = ["Share", "Float", "Copy", "Move", "Copy path", "Terminal", "Show", "SHA-256", "Duplicate"]
FORMAT_HINTS = {"JPG": "Small, universal", "PNG": "Lossless · transparency", "WEBP": "Smallest for web",
                "HEIC": "iPhone format", "TIFF": "Print · archival", "AVIF": "Next-gen, tiny",
                "BMP": "Uncompressed", "PDF": "Document", "ICO": "Windows icon", "GIF": "Legacy web",
                "DOCX": "Editable Word", "TXT": "Plain text", "MD": "Markdown", "HTML": "Web page",
                "EPUB": "E-book", "XLSX": "Tables → Excel", "PPTX": "Pages → slides", "SRT": "SubRip subtitles",
                "VTT": "Web subtitles", "SVG": "Vector"}

# clockwise from 12 o'clock in Santra's order, then ShiftWheel's extras
IMAGE_TOOLS = ["Compress", "Metadata", "Edit", "Annotate", "Add BG", "Crop", "Redact", "Resize", "Text", "QR code"]
PDF_TOOLS = ["Compress", "Split", "Rotate", "Organize", "Protect", "Extract", "Metadata", "OCR"]
VIDEO_TOOLS = ["Compress", "Trim", "Crop", "Split", "Snapshot", "Speed", "Mute", "Redact", "Rotate", "Metadata"]
AUDIO_TOOLS = ["Trim", "Compress", "Normalize", "Speed", "Channels", "Bleep", "Visualize", "Silence", "Metadata"]
MEDIA_HINTS = {"Compress": "Smaller MP4 · target size", "Rotate": "Turn 90° clockwise", "Merge": "Join in order",
               "Crop": "Reframe · keeps sound", "Split": "Equal parts or cut points", "Redact": "Blur or cover areas",
               "Metadata": "Title · artist · year"}
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
        for problem in themes.load_user_themes():         # imported themes, before settings read "theme"
            print("theme skipped:", problem, flush=True)
        self.settings = Settings()
        self.settings.apply()
        self.pool = QThreadPool.globalInstance()
        self.windows: list[QWidget] = []
        self.toasts = ToastStack()
        self.menu = RadialMenu(self.build_rings, self.describe)
        self.sounds = sounds.Player()
        self.menu.activated.connect(lambda *_: self.sounds.play("select"))
        self.menu.activated.connect(self.run_item)
        self.menu.highlighted.connect(lambda *_: self.sounds.play("highlight"))
        self.menu.ring_changed.connect(lambda *_: self.sounds.play("switch"))
        self.menu.ring_hint = self._ring_key_label

        # the watcher only manages menus it opened (drag mode); click-mode menus (tray, right-click,
        # Send To) must not be closed just because no mouse button is held
        self.watcher = ShiftWheelWatcher(lambda: self.menu.isVisible() and not self.menu.click_mode,
                                        lambda: self.menu.got_drag, self)
        self._apply_keys()
        self.watcher.show_menu.connect(self._drag_popup)
        self.watcher.switch_ring.connect(self._switch_ring)
        self.watcher.hide_menu.connect(self.menu.close_menu)
        self.watcher.start()
        self.hotkey = hotkey.GlobalHotkey(qapp, self)
        self.hotkey.pressed.connect(self._hotkey_pressed)
        if not self.hotkey.set(self.settings.get("open_hotkey")):
            QTimer.singleShot(1200, lambda: self.toasts.error(
                "Shortcut unavailable", f"{self.settings.get('open_hotkey')} is used by another app. "
                                        "Pick another in Settings → Keys."))

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
        self.apply_look()
        # "Match Windows": follow light/dark live
        self.qapp.styleHints().colorSchemeChanged.connect(lambda *_: self.apply_look())
        QTimer.singleShot(1500, self.sounds.preload)       # decode sounds off the start-up path
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_click)
        self.tray.show()

    def apply_look(self):
        """Theme (with its customisations), light/dark and size → the wheel, every window,
        the notifications, the tray menu and the sounds."""
        s = self.settings
        look = s.look()
        self.menu.set_look(look, s.get("wheel_size") / 100)
        glass.set_mode(look.dark, look.accent if s.custom(s.get("theme")).get("accent") else None)
        glass.set_ui(look.ui, look.dark)
        self.tray_menu.setStyleSheet(glass.QSS)
        s.configure_sounds(self.sounds)

    def _apply_keys(self):
        self.watcher.set_bindings(self.settings.ring_keys(), KEY_VK)
        self.watcher.excluded = self.settings.excluded_apps()

    def _ring_key_label(self, ring: str) -> str:
        key = self.settings.ring_keys().get(ring)
        cur = self.menu.ring_names[self.menu.ring_idx] if self.menu.ring_names else ""
        if key is None and self.settings.get("cycle_rings"):
            key = self.settings.ring_keys().get(cur)       # the same key again cycles
        return KEY_LABEL.get(key, "") if key else ""

    def _drag_popup(self, pos, ring: str = ""):
        self.apply_look()        # picks up a Windows accent/mode change since last time
        self.menu.want_ring = ring
        self.menu.popup(pos)
        self.sounds.play("open")

    def _switch_ring(self, ring: str):
        m = self.menu
        cur = m.ring_names[m.ring_idx] if m.ring_names else ""
        if ring == cur or ring not in m.ring_names:
            if self.settings.get("cycle_rings") or ring not in m.ring_names:
                m.next_ring()
        else:
            m.set_ring(ring)

    def _hotkey_pressed(self):
        files = [f for f in hotkey.selected_paths() if os.path.exists(f)]
        if files:
            self.show_click_menu(files)
            self.sounds.play("open")

    def trigger_label(self) -> str:
        keys = self.settings.ring_keys()
        return KEY_LABEL.get(keys.get("Convert") or next(iter(keys.values()), "shift"), "Shift")

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
        """Convert → Tools → Print (what fits the file), then the Actions ring for anything."""
        rings = ShiftWheelApp._file_rings(self, paths)
        rings["Actions"] = [Item(n, GLYPHS[n], key=f"file:{n}", hint=HINTS[n]) for n in FILE_ACTIONS]
        return rings

    def _file_rings(self, paths: list[str]) -> dict[str, list[Item]]:
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
                    [Item(t, key=f"archive:{t}", hint=f"Convert to .{archive.EXT[t]}") for t in archive.ARCHIVE_TARGETS
                     if t != archive.KIND_TARGET.get(k)]}
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
            names = IMAGE_TOOLS + (["Collage"] if len(same) > 1 else [])
            rings["Tools"] = [Item(n, GLYPHS[n], key=f"tool:{n}", hint=HINTS[n]) for n in names]
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
        if kind == "file":
            self.run_file_action(name, self._all_paths)
            return
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
        if name == "QR code" and cat == "image":
            found = {}

            def read(progress=None):
                found["t"] = [t for p in paths for t in extras.read_qr(p)]
                if not found["t"]:
                    raise UserError("No QR code found in this image.")
                return []

            def show(_r):
                text = "\n".join(found["t"])
                QGuiApplication.clipboard().setText(text)
                self.toasts.info("QR code copied" if len(found["t"]) == 1 else f"{len(found['t'])} QR codes copied",
                                 text[:300])
            self.submit("tool:QR", paths, read, "Reading QR code…", on_done=show)
            return
        if name == "Collage" and cat == "image":
            self._open_tool(name, tools2.CollageWindow, paths)
            return
        if name == "Organize" and cat == "pdf":
            self._open_tool(name, lambda ps, n: tools2.OrganizePdfWindow(ps[0], n), paths)
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
        elif name in ("Crop", "Split", "Redact", "Metadata", "Channels", "Bleep", "Visualize"):
            cls = {"Crop": tools2.VideoCropWindow, "Split": tools2.SplitWindow, "Redact": tools2.RedactVideoWindow,
                   "Metadata": tools2.MetadataEditWindow, "Channels": tools2.ChannelsWindow,
                   "Bleep": tools2.BleepWindow, "Visualize": tools2.VisualizerWindow}[name]
            self._open_tool(name, lambda ps, n: cls(ps[0], n), paths)
        elif name == "Silence":
            self.submit("tool:Silence", paths,
                        lambda progress=None: [extras.trim_silence(p, progress=progress) for p in paths],
                        "Trimming silence…")

    def run_file_action(self, name: str, paths: list[str]):
        if name == "Copy path":
            text = "\n".join(str(Path(p)) for p in paths)
            QGuiApplication.clipboard().setText(text)
            self.toasts.info("Path copied", text if len(paths) == 1 else f"{len(paths)} paths, one per line")
        elif name == "Show":
            fileops.reveal(paths[0])
        elif name == "Copy":
            # files on the clipboard: paste them in Explorer, Mail, chat apps…
            from PySide6.QtCore import QMimeData
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
            md.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b"\x01\x00\x00\x00")
            QGuiApplication.clipboard().setMimeData(md)
            self.toasts.info("Copied", f"{len(paths)} item{'s' if len(paths) != 1 else ''} · paste anywhere")
        elif name == "Move":
            folder = QFileDialog.getExistingDirectory(None, "Move to…", str(Path(paths[0]).parent))
            if folder:
                self.submit("tool:Move", paths, lambda: fileops.move_to(paths, folder), "Moving…",
                            extra=f"to {folder}")
        elif name == "Terminal":
            fileops.open_terminal(paths[0])
        elif name == "Share":
            try:
                fileops.share(paths[0])
            except Exception as e:  # noqa: BLE001
                self.toasts.error("Couldn't open Share", friendly_error(e))
        elif name == "Float":
            from .shelf import FloatShelf
            shelf = getattr(self, "_shelf", None)
            try:
                alive = shelf is not None and shelf.isVisible()
            except RuntimeError:
                alive = False
            if not alive:
                shelf = self._shelf = FloatShelf()
                self.open_window(shelf)
                shelf.pin("right")
            shelf.add(paths)
            shelf.raise_()
        elif name == "Duplicate":
            self.submit("tool:Duplicate", paths, lambda: [fileops.duplicate(p) for p in paths], "Duplicating…")
        elif name == "SHA-256":
            sums = {}

            def work(progress=None):
                sums["r"] = fileops.sha256(paths, progress)
                return []

            def copied(text):
                QGuiApplication.clipboard().setText(text)
                self.toasts.info("SHA-256 copied", text if len(sums["r"]) == 1 else f"{len(sums['r'])} files")
            self.submit("tool:SHA-256", paths, work, "Hashing…",
                        on_done=lambda _r: copied(fileops.checksum_text(sums["r"])))

    def open_window(self, w: QWidget):
        if hasattr(w, "submit"):
            w.submit = self.submit
        self.windows.append(w)
        w.destroyed.connect(lambda *_: self.windows.remove(w) if w in self.windows else None)
        if hasattr(w, "present"):
            w.present()
        else:
            w.show()

    def submit(self, action: str, srcs: list, fn, working: str = "Working…", extra: str = "", on_done=None):
        """Run in the background. A spinner card appears only if it takes > 150 ms.
        on_done(result) replaces the usual 'done' card (for results that aren't files)."""
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
            if on_done is not None:
                if state["card"] is not None:
                    state["card"].dismiss()
                on_done(r)
                return
            self.deliver(r, action, srcs, extra, state["card"])

        def failed(msg):
            release(job)
            state["finished"] = True
            self.sounds.play("error")
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
        self.deliver(report.summarize(action, srcs, outs, extra), action, srcs, extra, None)

    def deliver(self, r, action: str, srcs: list, extra: str, card):
        """A job finished: offer to name it (Settings → Saving), then open / reveal / notify."""
        outs = [Path(o) for o in r.outs]
        if self.settings.get("ask_name") and len(outs) == 1 and outs[0].is_file():
            def named(new: Path):
                r2 = r if new == outs[0] else report.summarize(action, srcs, [new], extra)
                self._finish(r2, card)
            self.open_window(saveas.SaveAsWindow(outs[0], named))
            return
        self._finish(r, card)

    def _finish(self, r, card):
        self.sounds.play("done")
        after = self.settings.get("after_save")
        if r.outs and Path(r.outs[0]).exists():
            if after == "open":
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(r.outs[0])))
            elif after == "reveal":
                fileops.reveal(r.outs[0])
        if self.settings.get("notifications") == "errors":
            if card is not None:
                card.dismiss()
            return
        (card or self.toasts.new()).done(r)

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
        w = SettingsWindow(self.settings, self.sounds)
        w.changed.connect(self._settings_changed)
        self.open_window(w)

    def _settings_changed(self):
        self._apply_keys()
        self.apply_look()
        if not self.hotkey.set(self.settings.get("open_hotkey")) and self.settings.get("open_hotkey"):
            self.toasts.error("Shortcut unavailable",
                              f"{self.settings.get('open_hotkey')} is used by another app. Pick another in Settings → Keys.")
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
            textpdf = Path(d) / "text.pdf"
            tdoc = convert.fitz.open()
            tdoc.new_page().insert_text((72, 72), "Selftest heading", fontsize=20)
            tdoc.save(textpdf)
            for t in convert.PDF_TARGETS:          # needs real text: XLSX / EPUB / MD refuse picture-only PDFs
                convert.convert(textpdf, "pdf", t)
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
        # drawn with Pillow's bundled font: Qt's offscreen platform (CI) has no real fonts
        from PIL import ImageFont
        im = Image.new("RGB", (900, 140), "white")
        ImageDraw.Draw(im).text((30, 40), "Selftest 2026 OK", fill="black", font=ImageFont.load_default(56))
        tp = d / "text.png"
        im.save(tp)
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

    # themes, wheel shapes, sounds (QtMultimedia packaged), new documents & tools
    from . import docs, extras, sounds as snd, tools2, wheelshape
    from .radial import Item, render_preview
    for key in themes.THEMES:
        for mode in ("light", "dark"):
            render_preview(themes.resolve(key, {"mode": mode}), [Item(t) for t in ("PNG", "PDF", "JPG")], 1, size=80)
    for outline in themes.OUTLINES:
        assert len(wheelshape.slices(outline, 7, QPointF(200, 200), 64, 158, 5, 12)) == 7
    player = snd.Player()
    assert player.available, "QtMultimedia missing from the build"
    player.configure(True, 0, "santra", {}, {}, {})
    player.preload()
    srt = d / "s.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n", encoding="utf-8")
    docs.subtitles_to(srt, "VTT")
    md = d / "b.md"
    md.write_text("# Book\n\nText", encoding="utf-8")
    docs.epub_to(docs.document_to(md, "EPUB")[0], "PDF")
    docs.pdf_to_pptx(pdf)
    extras.collage([Image.new("RGB", (40, 30), "red")] * 3, size=(200, 200))
    print("themes/sounds/docs OK")

    for w in (printwin.IDCardWindow([str(cp)], n), printwin.PassportWindow([str(png)], n),
              printwin.ScanWindow([str(cp)], n), printwin.PrintWindow([str(pdf)], n),
              mediawin.TrimWindow(str(clip), n), mediawin.TrimWindow(str(mp3), n),
              mediawin.VideoCompressWindow([str(clip)], n), mediawin.SpeedWindow(str(clip), n),
              ocrwin.ExtractTextWindow(str(png), n), tools2.ChannelsWindow(str(clip), n),
              tools2.SplitWindow(str(clip), n), tools2.VideoCropWindow(str(clip), n),
              tools2.MetadataEditWindow(str(png), n)):
        w.close()
    print("windows OK")
