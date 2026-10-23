"""Persistent settings + the Settings and Welcome windows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSlider, QStackedWidget, QVBoxLayout, QWidget)

from . import __version__, sounds, themes
from .util import CONFIG
from .window import GlassWindow

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
APP = "ShiftWheel"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Apps where Shift+drag means something else (constrain, duplicate…): no wheel there.
DEFAULT_EXCLUDED = "Photoshop.exe, Illustrator.exe, InDesign.exe, AfterFX.exe, Figma.exe, blender.exe, Resolve.exe"

# Keys that can open a ring while you drag (virtual-key codes for the watcher)
KEYS = [("none", "—  (not set)", 0), ("shift", "Shift", 0x10), ("ctrl", "Ctrl", 0x11), ("alt", "Alt", 0x12),
        ("space", "Space", 0x20), ("tab", "Tab", 0x09), ("capslock", "Caps Lock", 0x14), ("backquote", "` (backtick)", 0xC0)]
KEY_LABEL = {k: label.split("  ")[0] for k, label, _ in KEYS}
KEY_VK = {k: vk for k, _, vk in KEYS}
RINGS = [("Convert", "key_convert"), ("Tools", "key_tools"), ("Print", "key_print"), ("Actions", "key_actions")]

DEFAULTS = {
    # appearance (colours, mode and shape are per theme: see Settings.custom)
    "theme": themes.DEFAULT_THEME,
    "wheel_size": 100,
    # keys (Santra: Shift converts, Command opens tools, Control file actions)
    "key_convert": "shift",
    "key_tools": "ctrl",
    "key_print": "none",
    "key_actions": "alt",
    "cycle_rings": True,
    "open_hotkey": "Ctrl+Alt+W",            # W for wheel (Ctrl+Alt+Space is often taken, e.g. by Claude)
    # sounds
    "sounds_on": True,
    "sound_volume": 60,
    "sound_pack": "santra",
    "sound_events": "{}",
    "sound_custom": "{}",
    # saving
    "output": "next",
    "output_folder": "",
    "ask_name": False,
    "on_conflict": "number",
    "after_save": "notify",
    "jpg_quality": 90,
    "pdf_dpi": 200,
    # behaviour
    "excluded_apps": DEFAULT_EXCLUDED,
    "notifications": "all",
    "welcomed": False,
}

# allowed values: anything else stored (hand-edited registry, older versions) reads as the default
CHOICES = {
    "wheel_size": {85, 100, 115, 130},
    "key_convert": set(KEY_VK), "key_tools": set(KEY_VK), "key_print": set(KEY_VK), "key_actions": set(KEY_VK),
    "sound_volume": set(range(0, 101)),
    "sound_pack": set(sounds.PACK_KEYS),
    "output": {"next", "folder", "custom"},
    "on_conflict": {"number", "replace"},
    "after_save": {"notify", "open", "reveal"},
    "jpg_quality": set(range(60, 101)),
    "pdf_dpi": {150, 200, 300},
    "notifications": {"all", "errors"},
}
RENAMED = {"theme": "wheel_style", "key_convert": "trigger"}     # older keys they're migrated from


class Settings:
    def __init__(self, store: QSettings | None = None):
        self.q = store if store is not None else QSettings(APP, APP)   # tests pass an .ini store
        for new, old in RENAMED.items():
            if not self.q.contains(new) and self.q.contains(old):
                self.q.setValue(new, self.q.value(old))
        # 1.1 kept light/dark and accent globally: they become the current theme's own
        if self.q.contains("appearance") or self.q.contains("accent"):
            key = self.get("theme")
            custom = self.custom(key)
            for old, new in (("appearance", "mode"), ("accent", "accent")):
                if self.q.contains(old):
                    custom.setdefault(new, str(self.q.value(old)))
                    self.q.remove(old)
            self.set_custom(key, custom)

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
        if key == "theme" and v not in themes.THEMES:
            return d
        allowed = CHOICES.get(key)
        return v if allowed is None or v in allowed else d

    def set(self, key, value):
        self.q.setValue(key, value)
        self.apply()

    def get_json(self, key) -> dict:
        try:
            v = json.loads(self.get(key))
            return v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            return {}

    def set_json(self, key, value: dict):
        self.set(key, json.dumps(value))

    # ---- per-theme customisation: {"mode", "accent", "colors": {...}, "shape": {...}}
    def custom(self, theme_key: str) -> dict:
        try:
            v = json.loads(self.q.value(f"custom/{theme_key}", "{}"))
            return v if isinstance(v, dict) else {}
        except (TypeError, ValueError):
            return {}

    def set_custom(self, theme_key: str, value: dict):
        clean = {k: v for k, v in value.items() if v not in (None, "", {}, [])}
        if clean:
            self.q.setValue(f"custom/{theme_key}", json.dumps(clean))
        else:
            self.q.remove(f"custom/{theme_key}")

    def look(self):
        key = self.get("theme")
        return themes.resolve(key, self.custom(key))

    def palette(self):
        return self.look().pal

    def ring_keys(self) -> dict[str, str]:
        """{ring name: key} for the rings that have a key."""
        return {ring: self.get(k) for ring, k in RINGS if self.get(k) != "none"}

    def reset(self):
        """Back to defaults. 'welcomed' is kept so the welcome window doesn't come back."""
        for key in DEFAULTS:
            if key != "welcomed":
                self.q.remove(key)
        for key in self.q.allKeys():
            if key.startswith("custom/"):
                self.q.remove(key)
        self.apply()

    def apply(self):
        """Copy what worker threads need into plain values (see util.CONFIG)."""
        for k in ("output", "output_folder", "on_conflict", "jpg_quality", "pdf_dpi"):
            CONFIG[k] = self.get(k)

    def excluded_apps(self) -> set[str]:
        return {a.strip().lower() for a in self.get("excluded_apps").replace(";", ",").split(",") if a.strip()}

    def configure_sounds(self, player: "sounds.Player"):
        t = themes.THEMES.get(self.get("theme")) or themes.THEMES[themes.DEFAULT_THEME]
        player.configure(self.get("sounds_on"), self.get("sound_volume"), self.get("sound_pack"),
                         self.get_json("sound_events"), self.get_json("sound_custom"), t.sound_files, t.sounds)


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


OUTPUTS = [("next", "Next to the original"), ("folder", "In a “ShiftWheel” subfolder"),
           ("custom", "In a folder I choose")]
CONFLICTS = [("number", "Keep both: add (1), (2)…"), ("replace", "Replace the older file")]
AFTER_SAVE = [("notify", "Just show a notification"), ("open", "Open the new file"),
              ("reveal", "Show it in its folder")]
NOTIFICATIONS = [("all", "Every result"), ("errors", "Only when something goes wrong")]
DPIS = [(150, "150 dpi · small"), (200, "200 dpi · balanced"), (300, "300 dpi · print")]
SIZES = [(85, "Small"), (100, "Normal"), (115, "Large"), (130, "Extra large")]
OUTLINE_NAMES = [("circle", "Circle"), ("squircle", "Squircle"), ("square", "Rounded square"),
                 ("hexagon", "Hexagon"), ("octagon", "Octagon")]

SAMPLE = ["PNG", "WEBP", "HEIC", "TIFF", "AVIF", "BMP", "PDF", "GIF"]

# set on the card itself: a widget's own stylesheet beats the generic "checked button" look
CARD_QSS = """
QPushButton {{ border-radius: 16px; padding: 4px; background: {bg}; border: 1px solid {border}; }}
QPushButton:hover {{ background: {hover}; }}
QPushButton:checked {{ background: {hover}; border: 2px solid {accent}; }}
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
    stops = ["#1b1f3a", "#3a1f4f", "#0f2b3d", "#26123a"] if dark else ["#d5dde1", "#eef1f3", "#e1e7ea", "#f6f6f6"]
    pm = QPixmap.fromImage(glass.qimage_from_pil(gradient((size, size), stops, 160).convert("RGB")))
    return glass.blur_pixmap(pm, 24)


def preview(theme: str, custom: dict | None, size: int, hover: int = -1) -> QPixmap:
    from .radial import Item, render_preview
    look = themes.resolve(theme, custom or {})
    return render_preview(look, [Item(t) for t in SAMPLE], hover, backdrop=wallpaper(look.dark), size=size)


def _tok():
    from . import glass
    return glass.tokens()


class ThemeCard(QPushButton):
    def __init__(self, key: str):
        super().__init__()
        self.key = key
        t = themes.THEMES[key]
        self.setObjectName("themecard")
        self.setCheckable(True)
        self.setFixedSize(132, 146)
        self.setToolTip(f"{t.blurb}\nBy / inspired by: {t.credit}")
        ui = _tok()
        if ui is not None:
            css = CARD_QSS.format(bg=ui.surface.name(), border=ui.border.name(), hover=ui.hover.name(),
                                  accent=ui.accent.name())
        else:
            css = CARD_QSS.format(bg="rgba(255,255,255,0.06)", border="rgba(255,255,255,0.14)",
                                  hover="rgba(255,255,255,0.14)", accent=t.accent.name())
        self.setStyleSheet(css)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(2)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.name = QLabel(t.name + ("" if t.builtin else "  ★"))
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setStyleSheet("font-weight: 600; background: transparent; border: none;")
        for w in (self.pic, self.name):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            lay.addWidget(w)

    def draw(self, custom: dict | None):
        self.pic.setPixmap(preview(self.key, custom, 100))


class ColorButton(QPushButton):
    """A swatch that opens a colour picker; right-click / the ↺ button clears it."""
    picked = Signal(object)          # QColor or None

    def __init__(self, label: str):
        super().__init__(label)
        self.color: QColor | None = None
        self.clicked.connect(self._pick)

    def set_color(self, c: QColor | None, fallback: QColor):
        self.color = c
        self.setIcon(swatch(c or fallback, 16))

    def _pick(self):
        c = QColorDialog.getColor(self.color or QColor("#ffffff"), None, f"{self.text()} colour",
                                  QColorDialog.ShowAlphaChannel)
        if c.isValid():
            self.picked.emit(c)


class SettingsWindow(GlassWindow):
    changed = Signal()
    PAGES = ("Appearance", "Keys", "Sounds", "Saving", "Behaviour")

    def __init__(self, settings: Settings, player: "sounds.Player | None" = None):
        super().__init__("Settings", size=(860, 760))
        self.s = settings
        self.player = player
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

        foot = QHBoxLayout()
        about = QLabel(f"ShiftWheel {__version__}  ·  originals are never modified")
        about.setObjectName("dim")
        foot.addWidget(about)
        foot.addStretch(1)
        self.reset_btn = QPushButton("Reset all settings")
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
        for build in (self._appearance, self._keys, self._sounds, self._saving, self._behaviour):
            page = QWidget()
            page.setObjectName("page")
            lay = QVBoxLayout(page)
            lay.setContentsMargins(2, 4, 10, 4)
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

    @staticmethod
    def _grid():
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)
        g.setColumnStretch(1, 1)
        return g

    # ================================================================ Appearance
    def _appearance(self, lay):
        self._section(lay, "Theme")
        row = QHBoxLayout()
        self.gallery = QGridLayout()
        self.gallery.setSpacing(8)
        row.addLayout(self.gallery)
        side = QVBoxLayout()
        self.big = QLabel()
        self.big.setAlignment(Qt.AlignCenter)
        self.big.setFixedSize(250, 250)
        side.addWidget(self.big, 0, Qt.AlignHCenter)
        self.about_theme = hint("")
        self.about_theme.setFixedWidth(250)
        side.addWidget(self.about_theme)
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row)
        files = QHBoxLayout()
        for text, fn in (("Import theme…", self._import), ("Export…", self._export),
                         ("Save as new theme…", self._save_as)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            files.addWidget(b)
        self.delete_btn = QPushButton("Delete theme")
        self.delete_btn.clicked.connect(self._delete_theme)
        files.addWidget(self.delete_btn)
        files.addStretch(1)
        lay.addLayout(files)
        self.save_as_row = QWidget()
        sa = QHBoxLayout(self.save_as_row)
        sa.setContentsMargins(0, 0, 0, 0)
        self.save_as_name = QLineEdit()
        self.save_as_name.setPlaceholderText("Name for your theme")
        self.save_as_name.returnPressed.connect(self._save_as_confirm)
        ok = QPushButton("Save")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save_as_confirm)
        sa.addWidget(self.save_as_name, 1)
        sa.addWidget(ok)
        self.save_as_row.setVisible(False)
        lay.addWidget(self.save_as_row)
        self.theme_msg = hint("")
        self.theme_msg.setObjectName("warn")
        self.theme_msg.setVisible(False)
        lay.addWidget(self.theme_msg)

        self.custom_title = QLabel("")
        self.custom_title.setObjectName("section")
        lay.addWidget(self.custom_title)
        g = self._grid()
        r = 0
        g.addWidget(QLabel("Light or dark"), r, 0)
        self.mode = combo(themes.MODES, "system")
        self.mode.currentIndexChanged.connect(lambda _: self._custom("mode", self.mode.currentData()))
        g.addWidget(self.mode, r, 1)
        r += 1
        g.addWidget(hint("“Match Windows” follows Settings → Personalisation → Colours and switches live, "
                         "for the wheel, windows and notifications."), r, 1)
        r += 1
        g.addWidget(QLabel("Highlight colour"), r, 0)
        hl = QHBoxLayout()
        self.accent = QComboBox()
        for key, label, _ in themes.ACCENTS:
            self.accent.addItem(label, key)
        self.accent.addItem("Custom…", "custom")
        self.accent.currentIndexChanged.connect(self._accent_changed)
        hl.addWidget(self.accent, 1)
        g.addLayout(hl, r, 1)
        r += 1
        g.addWidget(QLabel("Colours"), r, 0)
        cl = QHBoxLayout()
        self.color_buttons = {}
        for role, label in themes.COLOR_ROLES[1:]:
            b = ColorButton(label)
            b.picked.connect(lambda c, role=role: self._color(role, c))
            cl.addWidget(b)
            self.color_buttons[role] = b
        clear = QPushButton("Reset colours")
        clear.clicked.connect(self._reset_colors)
        cl.addWidget(clear)
        cl.addStretch(1)
        g.addLayout(cl, r, 1)
        r += 1
        g.addWidget(QLabel("Shape"), r, 0)
        self.outline = combo(OUTLINE_NAMES, "circle")
        self.outline.currentIndexChanged.connect(lambda _: self._shape("outline", self.outline.currentData()))
        g.addWidget(self.outline, r, 1)
        r += 1
        self.sliders = {}
        for key, label, lo, hi, scale in (("corner", "Corner roundness", 0, 40, 1), ("gap", "Gap between slices", 0, 14, 1),
                                          ("inner", "Ring thickness", 25, 60, 100)):
            g.addWidget(QLabel(label), r, 0)
            row2 = QHBoxLayout()
            sl = QSlider(Qt.Horizontal)
            sl.setRange(lo, hi)
            val = QLabel("")
            val.setObjectName("dim")
            val.setFixedWidth(40)
            sl.valueChanged.connect(lambda v, k=key, sc=scale, lab=val: (lab.setText(f"{v}" if sc == 1 else f"{100 - v}%"),
                                                                          None))
            sl.sliderReleased.connect(lambda k=key, sl=sl, sc=scale: self._shape(k, sl.value() / sc))
            row2.addWidget(sl, 1)
            row2.addWidget(val)
            g.addLayout(row2, r, 1)
            self.sliders[key] = (sl, val, scale)
            r += 1
        self.lift = QCheckBox("Lift the highlighted slice towards the cursor")
        self.lift.toggled.connect(lambda on: self._shape("lift", on))
        g.addWidget(self.lift, r, 1)
        r += 1
        reset_theme = QPushButton("Reset this theme")
        reset_theme.clicked.connect(self._reset_theme)
        g.addWidget(reset_theme, r, 1, Qt.AlignLeft)
        r += 1
        g.addWidget(QLabel("Wheel size"), r, 0)
        self.size_box = combo(SIZES, self.s.get("wheel_size"))
        self.size_box.currentIndexChanged.connect(lambda _: self._save("wheel_size", self.size_box.currentData()))
        g.addWidget(self.size_box, r, 1)
        lay.addLayout(g)
        self._fill_gallery()
        self._load_custom()

    def _fill_gallery(self):
        while self.gallery.count():
            w = self.gallery.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.cards = []
        for i, key in enumerate(themes.THEMES):
            card = ThemeCard(key)
            card.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            self.gallery.addWidget(card, i // 3, i % 3)
            self.cards.append(card)
        self._refresh_previews()

    def _theme(self) -> str:
        return self.s.get("theme")

    def _pick_theme(self, key):
        self._save("theme", key)
        self._load_custom()
        self._refresh_previews()

    def _load_custom(self):
        """Fill the Customise panel from the selected theme's saved customisation."""
        key = self._theme()
        t = themes.THEMES[key]
        c = self.s.custom(key)
        look = themes.resolve(key, c)
        self.custom_title.setText(f"CUSTOMISE {t.name.upper()}")
        widgets = [self.mode, self.accent, self.outline, self.lift] + [s for s, _, _ in self.sliders.values()]
        for w in widgets:
            w.blockSignals(True)
        self.mode.setCurrentIndex([k for k, _ in themes.MODES].index(c.get("mode", "system"))
                                  if c.get("mode", "system") in [k for k, _ in themes.MODES] else 0)
        self.mode.setEnabled(not t.dark_only)
        acc = c.get("accent", "theme")
        keys = [k for k, _, _ in themes.ACCENTS]
        self.accent.setCurrentIndex(keys.index(acc) if acc in keys else len(keys))
        for i, k in enumerate(keys):
            self.accent.setItemIcon(i, swatch(themes.accent_color(key, k)))
        self.accent.setItemIcon(len(keys), swatch(look.accent))
        colors = c.get("colors") or {}
        fallback = {"slices": look.pal.slice_out, "ring": look.pal.base or QColor("#888888"), "text": look.pal.text}
        for role, b in self.color_buttons.items():
            b.set_color(themes._color(colors.get(role)), fallback[role])
        glass_theme = look.pal.glass
        self.outline.setCurrentIndex([k for k, _ in OUTLINE_NAMES].index(look.shape.outline))
        self.outline.setEnabled(not glass_theme)
        for k, (sl, val, scale) in self.sliders.items():
            v = getattr(look.shape, k)
            sl.setValue(int(round(v * scale)))
            val.setText(f"{sl.value()}" if scale == 1 else f"{100 - sl.value()}%")
            sl.setEnabled(not glass_theme)
        self.lift.setChecked(look.shape.lift)
        self.lift.setEnabled(not glass_theme)
        for w in widgets:
            w.blockSignals(False)
        self.delete_btn.setVisible(not t.builtin)

    def _custom(self, key, value):
        theme = self._theme()
        c = self.s.custom(theme)
        if value in (None, "", "theme", "system") and key in ("mode", "accent"):
            c.pop(key, None)
        else:
            c[key] = value
        self.s.set_custom(theme, c)
        self.changed.emit()
        self._refresh_previews()

    def _accent_changed(self, _):
        v = self.accent.currentData()
        if v == "custom":
            cur = themes.resolve(self._theme(), self.s.custom(self._theme())).accent
            col = QColorDialog.getColor(cur, None, "Highlight colour")
            if not col.isValid():
                self._load_custom()
                return
            v = col.name()
        self._custom("accent", v)
        self._load_custom()

    def _color(self, role, color):
        theme = self._theme()
        c = self.s.custom(theme)
        colors = dict(c.get("colors") or {})
        colors[role] = themes.color_text(color)
        c["colors"] = colors
        self.s.set_custom(theme, c)
        self.changed.emit()
        self._load_custom()
        self._refresh_previews()

    def _reset_colors(self):
        theme = self._theme()
        c = self.s.custom(theme)
        c.pop("colors", None)
        if c.get("accent", "").startswith("#"):
            c.pop("accent", None)
        self.s.set_custom(theme, c)
        self.changed.emit()
        self._load_custom()
        self._refresh_previews()

    def _shape(self, key, value):
        theme = self._theme()
        c = self.s.custom(theme)
        shape = dict(c.get("shape") or {})
        file_key = {v: k for k, v in themes.SHAPE_KEYS.items()}[key]
        shape[file_key] = value
        c["shape"] = shape
        self.s.set_custom(theme, c)
        self.changed.emit()
        self._refresh_previews()

    def _reset_theme(self):
        self.s.set_custom(self._theme(), {})
        self.changed.emit()
        self._load_custom()
        self._refresh_previews()

    def _refresh_previews(self):
        theme = self._theme()
        # every card previewed in the current light/dark, unless that theme has its own mode
        mode = "dark" if themes.resolve(theme, self.s.custom(theme)).dark else "light"
        for card in self.cards:
            card.setChecked(card.key == theme)
            c = self.s.custom(card.key)
            card.draw(c if "mode" in c else dict(c, mode=mode))
        self.big.setPixmap(preview(theme, self.s.custom(theme), 250, hover=2))
        t = themes.THEMES[theme]
        self.about_theme.setText(f"<b>{t.name}</b><br>{t.blurb}<br><i>{'Inspired by' if t.builtin else 'By'}: "
                                 f"{t.credit}</i>")

    # ---- theme files
    def _show_msg(self, text: str, warn: bool = True):
        self.theme_msg.setObjectName("warn" if warn else "good")
        self.theme_msg.setStyleSheet(self.theme_msg.styleSheet())
        self.theme_msg.setText(text)
        self.theme_msg.setVisible(bool(text))

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(self, "Import a ShiftWheel theme", "",
                                           "ShiftWheel themes (*.swtheme *.json);;All files (*)")
        if not f:
            return
        try:
            t, warn = themes.install_theme(f)
        except themes.ThemeError as e:
            self._show_msg(f"Couldn't import: {e}")
            return
        self._save("theme", t.key)
        self._fill_gallery()
        self._load_custom()
        self._show_msg(f"Imported “{t.name}”." + (f" {len(warn)} value(s) were ignored: " + "; ".join(warn[:4])
                                                    if warn else ""), warn=bool(warn))

    def _export(self):
        theme = self._theme()
        t = themes.THEMES[theme]
        default = str(Path.home() / "Desktop" / f"{themes.slug(t.name)}.swtheme")
        f, _ = QFileDialog.getSaveFileName(self, "Export theme", default, "ShiftWheel theme (*.swtheme)")
        if not f:
            return
        custom_sounds = {e: p for e, p in self.s.get_json("sound_custom").items() if Path(p).is_file()}
        themes.export_theme(t, f, self.s.custom(theme), custom_sounds)
        self._show_msg(f"Exported to {f} (includes your colours, shape and custom sounds).", warn=False)

    def _save_as(self):
        self.save_as_row.setVisible(True)
        self.save_as_name.setText(f"My {themes.THEMES[self._theme()].name}")
        self.save_as_name.selectAll()
        self.save_as_name.setFocus()

    def _save_as_confirm(self):
        name = self.save_as_name.text().strip()
        if not name:
            return
        from dataclasses import replace
        base = themes.THEMES[self._theme()]
        baked = themes.bake(base, self.s.custom(base.key))
        custom_sounds = {e: p for e, p in self.s.get_json("sound_custom").items() if Path(p).is_file()}
        t = themes.save_user_theme(replace(baked, key=themes.slug(name), name=name, credit="You",
                                           blurb=f"Based on {base.name}."), custom_sounds)
        self.save_as_row.setVisible(False)
        self._save("theme", t.key)
        self._fill_gallery()
        self._load_custom()
        self._show_msg(f"Saved “{name}”. It's in your theme list and can be exported.", warn=False)

    def _delete_theme(self):
        key = self._theme()
        if themes.THEMES[key].builtin:
            return
        if self.delete_btn.text() != "Click again to delete":
            self.delete_btn.setText("Click again to delete")
            QTimer.singleShot(3000, lambda: self.delete_btn.setText("Delete theme"))
            return
        self.delete_btn.setText("Delete theme")
        themes.delete_user_theme(key)
        self.s.set_custom(key, {})
        self._save("theme", themes.DEFAULT_THEME)
        self._fill_gallery()
        self._load_custom()

    # ================================================================ Keys
    def _keys(self, lay):
        self._section(lay, "While dragging a file, tap…")
        g = self._grid()
        self.key_boxes = {}
        for r, (ring, setting) in enumerate(RINGS):
            g.addWidget(QLabel(f"{ring} wheel"), r, 0)
            box = combo([(k, label) for k, label, _ in KEYS], self.s.get(setting))
            box.currentIndexChanged.connect(lambda _=0, s=setting, b=box: self._key_changed(s, b))
            g.addWidget(box, r, 1)
            self.key_boxes[setting] = box
        lay.addLayout(g)
        self.key_msg = hint("")
        self.key_msg.setObjectName("warn")
        lay.addWidget(self.key_msg)
        self.cycle = QCheckBox("Tap the same key again to go to the next wheel")
        self.cycle.setChecked(self.s.get("cycle_rings"))
        self.cycle.toggled.connect(lambda on: self._save("cycle_rings", on))
        lay.addWidget(self.cycle)
        lay.addWidget(hint("Defaults follow Santra: Shift converts, Ctrl (Command on a Mac) opens tools, "
                           "Alt (Control on a Mac) opens file actions. Release the key and keep dragging; the "
                           "wheel stays open until you drop or press Esc."))

        self._section(lay, "Without dragging")
        g2 = self._grid()
        g2.addWidget(QLabel("Open the wheel for the\nselected file"), 0, 0)
        row = QHBoxLayout()
        self.hotkey = QKeySequenceEdit(QKeySequence(self.s.get("open_hotkey")))
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey.editingFinished.connect(self._hotkey_changed)
        row.addWidget(self.hotkey, 1)
        clear = QPushButton("Turn off")
        clear.clicked.connect(lambda: (self.hotkey.clear(), self._hotkey_changed()))
        row.addWidget(clear)
        g2.addLayout(row, 0, 1)
        g2.addWidget(hint("Select a file in File Explorer or on the desktop and press this shortcut: the wheel "
                          "opens at the mouse."), 1, 1)
        lay.addLayout(g2)

        self._section(lay, "In the wheel")
        lay.addWidget(hint("Arrow keys choose a slice · Enter or Space applies · 1–9 pick a slice directly · "
                           "Tab switches wheel · Esc cancels"))

    def _key_changed(self, setting, box):
        value = box.currentData()
        if value != "none":
            for other, b in self.key_boxes.items():
                if other != setting and self.s.get(other) == value:
                    ring = next(r for r, s in RINGS if s == other)
                    self.key_msg.setText(f"{KEY_LABEL[value]} already opens the {ring} wheel; "
                                         f"that one is now unset.")
                    self.s.set(other, "none")
                    b.blockSignals(True)
                    b.setCurrentIndex(0)
                    b.blockSignals(False)
        if not any(self.s.get(s) != "none" for _, s in RINGS if s != setting) and value == "none":
            self.key_msg.setText("At least one wheel needs a key.")
            box.blockSignals(True)
            box.setCurrentIndex([k for k, _, _ in KEYS].index(self.s.get(setting)))
            box.blockSignals(False)
            return
        self._save(setting, value)

    def _hotkey_changed(self):
        seq = self.hotkey.keySequence().toString(QKeySequence.PortableText)
        self._save("open_hotkey", seq)

    # ================================================================ Sounds
    def _sounds(self, lay):
        self._section(lay, "Sounds")
        g = self._grid()
        self.snd_on = QCheckBox("Play sounds")
        self.snd_on.setChecked(self.s.get("sounds_on"))
        self.snd_on.toggled.connect(lambda on: self._snd("sounds_on", on))
        g.addWidget(self.snd_on, 0, 1)
        g.addWidget(QLabel("Volume"), 1, 0)
        row = QHBoxLayout()
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(self.s.get("sound_volume"))
        vl = QLabel(f"{self.vol.value()}%")
        vl.setObjectName("dim")
        vl.setFixedWidth(40)
        self.vol.valueChanged.connect(lambda v: vl.setText(f"{v}%"))
        self.vol.sliderReleased.connect(lambda: (self._snd("sound_volume", self.vol.value()), self._play("highlight")))
        row.addWidget(self.vol, 1)
        row.addWidget(vl)
        g.addLayout(row, 1, 1)
        g.addWidget(QLabel("Sound pack"), 2, 0)
        self.pack = combo(sounds.PACKS, self.s.get("sound_pack"))
        self.pack.currentIndexChanged.connect(lambda _: (self._snd("sound_pack", self.pack.currentData()),
                                                         self._play("highlight")))
        g.addWidget(self.pack, 2, 1)
        g.addWidget(hint("Santra's tick is recreated from the sound on the reference design (measured, not "
                         "copied). “Match the theme” uses each theme's own pack, or the sounds inside an "
                         "imported theme."), 3, 1)
        lay.addLayout(g)

        self._section(lay, "Each sound")
        e = self._grid()
        e.setColumnStretch(1, 0)
        e.setColumnStretch(2, 1)
        on = self.s.get_json("sound_events")
        custom = self.s.get_json("sound_custom")
        self.event_rows = {}
        for r, (ev, label) in enumerate(sounds.EVENTS):
            cb = QCheckBox(label)
            cb.setChecked(on.get(ev, True))
            cb.toggled.connect(lambda v, ev=ev: self._event_on(ev, v))
            e.addWidget(cb, r, 0)
            play = QPushButton("▶")
            play.setToolTip("Play")
            play.setFixedWidth(40)
            play.clicked.connect(lambda _=False, ev=ev: self._play(ev))
            e.addWidget(play, r, 1)
            src = QLabel(Path(custom[ev]).name if custom.get(ev) else "Pack sound")
            src.setObjectName("dim")
            e.addWidget(src, r, 2)
            choose = QPushButton("Choose…")
            choose.clicked.connect(lambda _=False, ev=ev: self._choose_sound(ev))
            e.addWidget(choose, r, 3)
            reset = QPushButton("Reset")
            reset.clicked.connect(lambda _=False, ev=ev: self._reset_sound(ev))
            e.addWidget(reset, r, 4)
            self.event_rows[ev] = src
        lay.addLayout(e)
        lay.addWidget(hint("Your own sounds can be any audio file (the first 3 seconds are kept). They're saved "
                           "with ShiftWheel and included when you export a theme."))

    def _snd(self, key, value):
        self._save(key, value)

    def _play(self, ev):
        if self.player is not None:
            self.s.configure_sounds(self.player)
            self.player.play(ev, force=True)

    def _event_on(self, ev, on):
        d = self.s.get_json("sound_events")
        d[ev] = bool(on)
        self.s.set_json("sound_events", d)
        self.changed.emit()

    def _choose_sound(self, ev):
        f, _ = QFileDialog.getOpenFileName(self, "Choose a sound", "",
                                           "Audio (*.wav *.mp3 *.m4a *.ogg *.flac *.aac *.opus);;All files (*)")
        if not f:
            return
        try:
            dst = sounds.import_sound(f, ev)
        except Exception as e:  # noqa: BLE001
            self.event_rows[ev].setText(f"Couldn't use it: {e}")
            return
        d = self.s.get_json("sound_custom")
        d[ev] = str(dst)
        self.s.set_json("sound_custom", d)
        self.event_rows[ev].setText(Path(f).name)
        self.changed.emit()
        self._play(ev)

    def _reset_sound(self, ev):
        d = self.s.get_json("sound_custom")
        d.pop(ev, None)
        self.s.set_json("sound_custom", d)
        self.event_rows[ev].setText("Pack sound")
        self.changed.emit()

    # ================================================================ Saving
    def _saving(self, lay):
        self._section(lay, "Where results go")
        g = self._grid()
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
        lay.addLayout(g)

        self._section(lay, "Quality")
        q = self._grid()
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

    # ================================================================ Behaviour
    def _behaviour(self, lay):
        self._section(lay, "Where the wheel opens")
        g = self._grid()
        g.addWidget(QLabel("Never open it in"), 0, 0)
        self.excl = QLineEdit(self.s.get("excluded_apps"))
        self.excl.setPlaceholderText("Photoshop.exe, Figma.exe")
        self.excl.editingFinished.connect(lambda: self._save("excluded_apps", self.excl.text().strip()))
        g.addWidget(self.excl, 0, 1)
        g.addWidget(hint("Program names, separated by commas. Use it for apps where Shift-dragging already "
                         "means something (constrain, duplicate, select)."), 1, 1)
        lay.addLayout(g)

        self._section(lay, "Notifications and system")
        n = self._grid()
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
        lay.addLayout(n)

    # ------------------------------------------------------------ reset
    def _reset(self):
        if self.reset_btn.text() != "Click again to reset":
            self.reset_btn.setText("Click again to reset")
            QTimer.singleShot(3000, lambda: self.reset_btn.setText("Reset all settings"))
            return
        self.reset_btn.setText("Reset all settings")
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
            ("⇄", "Ctrl for tools · Alt for file actions", f"or tap {trigger_label} again to go round the wheels"),
            ("✦", "Works with almost anything", "photos, PDFs, video, audio, Office files, folders"),
        ]
        for n, head, sub in steps:
            row = QHBoxLayout()
            badge = QLabel(n)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(34, 34)
            from . import glass
            badge.setStyleSheet(f"background: {glass.accent().name()}; color: #ffffff; "
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
