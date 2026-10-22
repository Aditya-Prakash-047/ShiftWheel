"""Persistent settings + the Settings and Welcome windows."""
from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from . import __version__, themes
from .util import CONFIG
from .window import GlassWindow

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
APP = "ShiftWheel"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Apps where Shift+drag means something else (constrain, duplicate…): no wheel there.
DEFAULT_EXCLUDED = "Photoshop.exe, Illustrator.exe, InDesign.exe, AfterFX.exe, Figma.exe, blender.exe, Resolve.exe"

DEFAULTS = {
    # appearance
    "theme": themes.DEFAULT_THEME,
    "appearance": "system",
    "accent": "theme",
    "wheel_size": 100,
    # saving
    "output": "next",
    "output_folder": "",
    "ask_name": False,
    "on_conflict": "number",
    "after_save": "notify",
    "jpg_quality": 90,
    "pdf_dpi": 200,
    # behaviour
    "trigger": "shift",
    "excluded_apps": DEFAULT_EXCLUDED,
    "notifications": "all",
    "welcomed": False,
}

# allowed values: anything else stored (hand-edited registry, older versions) reads as the default
CHOICES = {
    "theme": set(themes.THEMES),
    "appearance": {k for k, _ in themes.MODES},
    "accent": {k for k, _, _ in themes.ACCENTS},
    "wheel_size": {85, 100, 115, 130},
    "output": {"next", "folder", "custom"},
    "on_conflict": {"number", "replace"},
    "after_save": {"notify", "open", "reveal"},
    "jpg_quality": set(range(60, 101)),
    "pdf_dpi": {150, 200, 300},
    "trigger": {"shift", "ctrl", "alt"},
    "notifications": {"all", "errors"},
}
RENAMED = {"theme": "wheel_style"}     # older key it can be migrated from


class Settings:
    def __init__(self, store: QSettings | None = None):
        self.q = store if store is not None else QSettings(APP, APP)   # tests pass an .ini store
        for new, old in RENAMED.items():
            if not self.q.contains(new) and self.q.contains(old):
                self.q.setValue(new, self.q.value(old))

    def get(self, key):
        d = DEFAULTS[key]
        v = self.q.value(key, d)
        if isinstance(d, bool):
            return v in (True, "true", "1", 1)
        if isinstance(d, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return d
        elif v is None:
            return d
        else:
            v = str(v)
        allowed = CHOICES.get(key)
        return v if allowed is None or v in allowed else d

    def set(self, key, value):
        self.q.setValue(key, value)
        self.apply()

    def reset(self):
        """Back to defaults. 'welcomed' is kept so the welcome window doesn't come back."""
        for key in DEFAULTS:
            if key != "welcomed":
                self.q.remove(key)
        self.apply()

    def apply(self):
        """Copy what worker threads need into plain values (see util.CONFIG)."""
        for k in ("output", "output_folder", "on_conflict", "jpg_quality", "pdf_dpi"):
            CONFIG[k] = self.get(k)

    def excluded_apps(self) -> set[str]:
        return {a.strip().lower() for a in self.get("excluded_apps").replace(";", ",").split(",") if a.strip()}

    def palette(self):
        return themes.palette(self.get("theme"), self.get("appearance"), self.get("accent"))


# ---------------------------------------------------------------- autostart (Windows)
def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --quiet'
    return f'"{sys.executable}" -m shiftwheel --quiet'


def autostart_enabled() -> bool:
    if IS_LINUX:
        from . import platform_linux
        return platform_linux.autostart_enabled()
    if IS_MAC:
        from . import platform_mac
        return platform_mac.autostart_enabled()
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
            return True
    except OSError:
        return False


def set_autostart(on: bool):
    if IS_LINUX:
        from . import platform_linux
        platform_linux.set_autostart(on)
        return
    if IS_MAC:
        from . import platform_mac
        platform_mac.set_autostart(on)
        return
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass


# ---------------------------------------------------------------- right-click menu (Windows)
# Same per-user keys the installer writes, so the portable .exe can add (and remove) it too.
MENU_KEYS = (r"Software\Classes\*\shell\ShiftWheel", r"Software\Classes\Directory\shell\ShiftWheel")


def open_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" -m shiftwheel "%1"'


def context_menu_enabled() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, MENU_KEYS[0] + r"\command").Close()
        return True
    except OSError:
        return False


def set_context_menu(on: bool):
    if not IS_WIN:
        return
    import winreg
    exe = sys.executable
    for key in MENU_KEYS:
        if on:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, "ShiftWheel…")
                winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, exe)
                winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, open_command())
        else:
            for sub in (key + r"\command", key):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except OSError:
                    pass


TRIGGERS = ([("shift", "Shift ⇧"), ("ctrl", "Control ⌃"), ("alt", "Option ⌥")] if IS_MAC
            else [("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt")])
OUTPUTS = [("next", "Next to the original"), ("folder", "In a “ShiftWheel” subfolder"),
           ("custom", "In a folder I choose")]
CONFLICTS = [("number", "Keep both: add (1), (2)…"), ("replace", "Replace the older file")]
AFTER_SAVE = [("notify", "Just show a notification"), ("open", "Open the new file"),
              ("reveal", "Show it in its folder")]
NOTIFICATIONS = [("all", "Every result"), ("errors", "Only when something goes wrong")]
DPIS = [(150, "150 dpi · small"), (200, "200 dpi · balanced"), (300, "300 dpi · print")]
SIZES = [(85, "Small"), (100, "Normal"), (115, "Large"), (130, "Extra large")]

SAMPLE = ["PNG", "WEBP", "HEIC", "TIFF", "AVIF", "BMP", "PDF", "GIF"]

# set on the card itself: a widget's own stylesheet beats the generic "checked button" look
CARD_QSS = """
QPushButton { border-radius: 16px; padding: 4px; background: rgba(@INK@,0.06); border: 1px solid rgba(@INK@,0.14); }
QPushButton:hover { background: rgba(@INK@,0.12); }
QPushButton:checked { background: rgba(@INK@,0.14); border: 2px solid @ACCENT@; }
"""


def combo(options, current):
    c = QComboBox()
    for v, label in options:
        c.addItem(label, v)
    values = [v for v, _ in options]
    c.setCurrentIndex(values.index(current) if current in values else 0)
    return c


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("dim")
    lab.setWordWrap(True)
    return lab


def swatch(color: QColor, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(color)
    return QIcon(pm)


def wallpaper(dark: bool, size: int = 400) -> QPixmap:
    """A soft wallpaper so frosted themes have something to frost in previews."""
    from . import glass
    from .imaging import gradient
    stops = ["#1b1f3a", "#3a1f4f", "#0f2b3d", "#26123a"] if dark else ["#f6d5c3", "#f3b6c6", "#c9c3f2", "#b8dcf5"]
    pm = QPixmap.fromImage(glass.qimage_from_pil(gradient((size, size), stops, 160).convert("RGB")))
    return glass.blur_pixmap(pm, 24)


def preview(theme: str, mode: str, accent: str, size: int, hover: int = -1) -> QPixmap:
    from .radial import Item, render_preview
    pal = themes.palette(theme, mode, accent)
    return render_preview(pal, [Item(t) for t in SAMPLE], hover, backdrop=wallpaper(pal.dark), size=size)


class ThemeCard(QPushButton):
    def __init__(self, key: str):
        super().__init__()
        self.key = key
        self.setObjectName("themecard")
        self.setCheckable(True)
        from . import glass
        ink = "255,255,255" if glass.is_dark() else ",".join(str(v) for v in glass.INK)
        accent = themes.THEMES[key].accent.name()
        self.setStyleSheet(CARD_QSS.replace("@INK@", ink).replace("@ACCENT@", accent))
        self.setFixedSize(138, 150)
        self.setToolTip(f"{themes.THEMES[key].blurb}\nInspired by: {themes.THEMES[key].credit}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(2)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.name = QLabel(themes.THEMES[key].name)
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setStyleSheet("font-weight: 600;")
        for w in (self.pic, self.name):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)

    def draw(self, mode: str, accent: str):
        self.pic.setPixmap(preview(self.key, mode, accent, 106))


class SettingsWindow(GlassWindow):
    changed = Signal()

    def __init__(self, settings: Settings):
        super().__init__("Settings", size=(800, 720))
        self.s = settings
        tabs = QHBoxLayout()
        self.tab_buttons = []
        for i, name in enumerate(("Appearance", "Saving", "Behaviour")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i: self.show_page(i))
            tabs.addWidget(b)
            self.tab_buttons.append(b)
        tabs.addStretch(1)
        self.body.addLayout(tabs)
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        about = QLabel(f"ShiftWheel {__version__}  ·  originals are never modified")
        about.setObjectName("dim")
        foot.addWidget(about)
        foot.addStretch(1)
        self.reset_btn = QPushButton("Reset to defaults")
        self.reset_btn.clicked.connect(self._reset)
        foot.addWidget(self.reset_btn)
        done = QPushButton("Done")
        done.setObjectName("primary")
        done.clicked.connect(self.close)
        foot.addWidget(done)
        self.body.addLayout(foot)
        self._build()
        self.show_page(0)

    # ------------------------------------------------------------ pages
    def _build(self):
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        for build in (self._appearance, self._saving, self._behaviour):
            page = QWidget()
            page.setObjectName("page")
            lay = QVBoxLayout(page)
            lay.setContentsMargins(2, 4, 8, 4)
            lay.setSpacing(10)
            build(lay)
            lay.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("QScrollArea, QWidget#qt_scrollarea_viewport, QWidget#page "
                                 "{ background: transparent; border: none; }")
            scroll.setWidget(page)
            self.stack.addWidget(scroll)

    def show_page(self, i: int):
        self.stack.setCurrentIndex(i)
        for k, b in enumerate(self.tab_buttons):
            b.setChecked(k == i)

    def _save(self, key, value):
        self.s.set(key, value)
        self.changed.emit()

    def _section(self, lay, text):
        lab = QLabel(text.upper())
        lab.setObjectName("section")
        lay.addWidget(lab)

    # ---- Appearance
    def _appearance(self, lay):
        self._section(lay, "Wheel theme")
        row = QHBoxLayout()
        grid = QGridLayout()
        grid.setSpacing(8)
        self.cards = []
        for i, key in enumerate(themes.THEMES):
            card = ThemeCard(key)
            card.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            grid.addWidget(card, i // 3, i % 3)
            self.cards.append(card)
        row.addLayout(grid)
        side = QVBoxLayout()
        self.big = QLabel()
        self.big.setAlignment(Qt.AlignCenter)
        self.big.setFixedSize(230, 230)
        side.addWidget(self.big, 0, Qt.AlignHCenter)
        self.about_theme = hint("")
        self.about_theme.setFixedWidth(230)
        side.addWidget(self.about_theme)
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row)

        self._section(lay, "Colours and size")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(QLabel("Light or dark"), 0, 0)
        self.mode = combo(themes.MODES, self.s.get("appearance"))
        self.mode.currentIndexChanged.connect(lambda _: self._look("appearance", self.mode.currentData()))
        g.addWidget(self.mode, 0, 1)
        g.addWidget(hint("“Match Windows” follows Settings → Personalisation → Colours, and switches "
                         "live. Also applies to ShiftWheel's windows and notifications."), 1, 1)
        g.addWidget(QLabel("Highlight colour"), 2, 0)
        self.accent = QComboBox()
        for key, label, hexv in themes.ACCENTS:
            col = themes.accent_color(self.s.get("theme"), key)
            self.accent.addItem(swatch(col), label, key)
        keys = [k for k, _, _ in themes.ACCENTS]
        self.accent.setCurrentIndex(keys.index(self.s.get("accent")))
        self.accent.currentIndexChanged.connect(lambda _: self._look("accent", self.accent.currentData()))
        g.addWidget(self.accent, 2, 1)
        g.addWidget(QLabel("Wheel size"), 3, 0)
        self.size_box = combo(SIZES, self.s.get("wheel_size"))
        self.size_box.currentIndexChanged.connect(lambda _: self._save("wheel_size", self.size_box.currentData()))
        g.addWidget(self.size_box, 3, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)
        self._refresh_previews()

    def _pick_theme(self, key):
        self._look("theme", key)

    def _look(self, key, value):
        self._save(key, value)
        self._refresh_previews()

    def _refresh_previews(self):
        theme, mode, accent = self.s.get("theme"), self.s.get("appearance"), self.s.get("accent")
        for card in self.cards:
            card.setChecked(card.key == theme)
            card.draw(mode, accent)
        self.big.setPixmap(preview(theme, mode, accent, 230, hover=2))
        t = themes.THEMES[theme]
        self.about_theme.setText(f"<b>{t.name}</b><br>{t.blurb}<br><i>Inspired by: {t.credit}</i>")
        if hasattr(self, "accent"):
            for i, (key, _, _) in enumerate(themes.ACCENTS):
                self.accent.setItemIcon(i, swatch(themes.accent_color(theme, key)))

    # ---- Saving
    def _saving(self, lay):
        self._section(lay, "Where results go")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(QLabel("Save results"), 0, 0)
        self.output = combo(OUTPUTS, self.s.get("output"))
        self.output.currentIndexChanged.connect(self._output_changed)
        g.addWidget(self.output, 0, 1)
        frow = QHBoxLayout()
        self.folder_label = hint(self.s.get("output_folder") or "No folder chosen yet")
        pick = QPushButton("Choose folder…")
        pick.clicked.connect(self._choose_folder)
        frow.addWidget(self.folder_label, 1)
        frow.addWidget(pick)
        self.folder_row = QWidget()
        self.folder_row.setLayout(frow)
        self.folder_row.setVisible(self.s.get("output") == "custom")
        g.addWidget(self.folder_row, 1, 1)

        self.ask = QCheckBox("Ask for a file name before saving")
        self.ask.setChecked(self.s.get("ask_name"))
        self.ask.toggled.connect(lambda on: self._save("ask_name", on))
        g.addWidget(self.ask, 2, 1)
        g.addWidget(hint("A box shows the suggested name; change it, pick another folder, or press Enter. "
                         "Jobs that make several files (PDF pages, split) keep their automatic names."), 3, 1)
        g.addWidget(QLabel("If the name is taken"), 4, 0)
        self.conflict = combo(CONFLICTS, self.s.get("on_conflict"))
        self.conflict.currentIndexChanged.connect(lambda _: self._save("on_conflict", self.conflict.currentData()))
        g.addWidget(self.conflict, 4, 1)
        g.addWidget(QLabel("After saving"), 5, 0)
        self.after = combo(AFTER_SAVE, self.s.get("after_save"))
        self.after.currentIndexChanged.connect(lambda _: self._save("after_save", self.after.currentData()))
        g.addWidget(self.after, 5, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)

        self._section(lay, "Quality")
        q = QGridLayout()
        q.setHorizontalSpacing(14)
        q.addWidget(QLabel("JPG / WebP quality"), 0, 0)
        row = QHBoxLayout()
        self.q = QSlider(Qt.Horizontal)
        self.q.setRange(60, 100)
        self.q.setValue(self.s.get("jpg_quality"))
        self.qv = QLabel(str(self.q.value()))
        self.qv.setObjectName("dim")
        self.qv.setFixedWidth(30)
        self.q.valueChanged.connect(lambda v: (self.qv.setText(str(v)), self._save("jpg_quality", v)))
        row.addWidget(self.q)
        row.addWidget(self.qv)
        q.addLayout(row, 0, 1)
        q.addWidget(QLabel("PDF → image resolution"), 1, 0)
        self.dpi = combo(DPIS, self.s.get("pdf_dpi"))
        self.dpi.currentIndexChanged.connect(lambda _: self._save("pdf_dpi", self.dpi.currentData()))
        q.addWidget(self.dpi, 1, 1)
        q.setColumnStretch(1, 1)
        lay.addLayout(q)

    def _output_changed(self, _):
        v = self.output.currentData()
        if v == "custom" and not self.s.get("output_folder"):
            if not self._choose_folder():
                self.output.setCurrentIndex([k for k, _ in OUTPUTS].index(self.s.get("output")))
                return
        self.folder_row.setVisible(v == "custom")
        self._save("output", v)

    def _choose_folder(self) -> bool:
        d = QFileDialog.getExistingDirectory(self, "Save ShiftWheel results in…", self.s.get("output_folder"))
        if not d:
            return False
        self._save("output_folder", d)
        self.folder_label.setText(d)
        return True

    # ---- Behaviour
    def _behaviour(self, lay):
        self._section(lay, "Opening the wheel")
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.addWidget(QLabel("Open the wheel with"), 0, 0)
        self.trigger = combo(TRIGGERS, self.s.get("trigger"))
        self.trigger.currentIndexChanged.connect(lambda _: self._save("trigger", self.trigger.currentData()))
        g.addWidget(self.trigger, 0, 1)
        g.addWidget(hint("…pressed while you’re dragging a file. Tap it again to switch rings."), 1, 1)
        g.addWidget(QLabel("Never open it in"), 2, 0)
        self.excl = QLineEdit(self.s.get("excluded_apps"))
        self.excl.setPlaceholderText("Photoshop.exe, Figma.exe")
        self.excl.editingFinished.connect(lambda: self._save("excluded_apps", self.excl.text().strip()))
        g.addWidget(self.excl, 2, 1)
        g.addWidget(hint("Program names, separated by commas. Use it for apps where Shift-dragging already "
                         "means something (constrain, duplicate, select)."), 3, 1)
        g.setColumnStretch(1, 1)
        lay.addLayout(g)

        self._section(lay, "Notifications and system")
        n = QGridLayout()
        n.setHorizontalSpacing(14)
        n.addWidget(QLabel("Notify me about"), 0, 0)
        self.notif = combo(NOTIFICATIONS, self.s.get("notifications"))
        self.notif.currentIndexChanged.connect(lambda _: self._save("notifications", self.notif.currentData()))
        n.addWidget(self.notif, 0, 1)
        r = 1
        if IS_WIN or IS_MAC or IS_LINUX:
            self.auto = QCheckBox("Start ShiftWheel with Windows" if IS_WIN else "Open ShiftWheel at login")
            self.auto.setChecked(autostart_enabled())
            self.auto.toggled.connect(set_autostart)
            n.addWidget(self.auto, r, 1)
            r += 1
        if IS_WIN:
            self.ctx = QCheckBox("Show “ShiftWheel…” when you right-click a file")
            self.ctx.setToolTip("Windows 11: under “Show more options”. No admin rights needed.")
            self.ctx.setChecked(context_menu_enabled())
            self.ctx.toggled.connect(set_context_menu)
            n.addWidget(self.ctx, r, 1)
            r += 1
        if IS_MAC:
            from . import platform_mac
            if not platform_mac.has_screen_recording():
                glass_btn = QPushButton("Enable full liquid glass…")
                glass_btn.setToolTip("Lets the glass refract the windows behind it (Screen Recording permission)")
                glass_btn.clicked.connect(platform_mac.request_screen_recording)
                n.addWidget(glass_btn, r, 1)
                r += 1
        n.setColumnStretch(1, 1)
        lay.addLayout(n)

    # ------------------------------------------------------------ reset
    def _reset(self):
        if self.reset_btn.text() != "Click again to reset":
            self.reset_btn.setText("Click again to reset")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, lambda: self.reset_btn.setText("Reset to defaults"))
            return
        self.reset_btn.setText("Reset to defaults")
        page = self.stack.currentIndex()
        self.s.reset()
        self.changed.emit()
        self._build()
        self.show_page(page)


class WelcomeWindow(GlassWindow):
    def __init__(self, settings: Settings, trigger_label: str = "Shift"):
        super().__init__("Welcome to ShiftWheel", size=(560, 490))
        self.s = settings
        steps = [
            ("1", "Start dragging any file", "in Finder or on the desktop" if IS_MAC else
             "in your file manager (Thunar, Nautilus…)" if IS_LINUX else "in File Explorer or on the desktop"),
            ("2", f"Press {trigger_label}", "the glass menu opens right under your cursor"),
            ("3", "Drop it on a slice", "the result is saved next to the original"),
            ("⇄", f"Tap {trigger_label} again", "to switch Convert → Tools → Print"),
            ("✦", "Works with almost anything", "photos, PDFs, video, audio, Office files, folders"),
        ]
        for n, head, sub in steps:
            row = QHBoxLayout()
            badge = QLabel(n)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(34, 34)
            badge.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #5ac8ff, stop:1 #2f7bff);"
                                "border-radius: 17px; font-weight: 700; font-size: 12pt;")
            row.addWidget(badge)
            col = QVBoxLayout()
            col.setSpacing(0)
            h = QLabel(head)
            h.setStyleSheet("font-size: 12pt; font-weight: 600;")
            d = QLabel(sub)
            d.setObjectName("dim")
            col.addWidget(h)
            col.addWidget(d)
            row.addSpacing(8)
            row.addLayout(col, 1)
            self.body.addLayout(row)
        self.body.addStretch(1)
        if IS_MAC:
            from . import platform_mac
            if not platform_mac.has_screen_recording():
                note = QLabel("Optional: allow Screen Recording so the glass can refract the windows "
                              "behind it (otherwise it shows your wallpaper). ShiftWheel never saves or sends it.")
                note.setObjectName("dim")
                note.setWordWrap(True)
                self.body.addWidget(note)
                b = QPushButton("Allow Screen Recording…")
                b.clicked.connect(platform_mac.request_screen_recording)
                self.body.addWidget(b, 0, Qt.AlignLeft)
        if IS_LINUX:
            from . import platform_linux
            if platform_linux.is_wayland():
                note = QLabel("You're on a Wayland session: the Shift-while-dragging trigger needs X11 (e.g. XFCE). "
                              "Right-click a file → Open With → ShiftWheel still works.")
                note.setObjectName("warn")
                note.setWordWrap(True)
                self.body.addWidget(note)
        foot = QHBoxLayout()
        if IS_WIN or IS_MAC or IS_LINUX:
            self.auto = QCheckBox("Start with Windows" if IS_WIN else "Open at login")
            self.auto.setChecked(True)
            foot.addWidget(self.auto)
        foot.addStretch(1)
        ok = QPushButton("Got it")
        ok.setObjectName("primary")
        ok.clicked.connect(self._done)
        foot.addWidget(ok)
        self.body.addLayout(foot)

    def _done(self):
        self.s.set("welcomed", True)
        if IS_WIN or IS_MAC or IS_LINUX:
            set_autostart(self.auto.isChecked())
        self.close()
