"""Themes: how the wheel, the windows and the notifications look (and which sounds play).

A theme has
* a **shape** (outline, ring proportions, gaps, rounded tile corners, label sizes, icon set),
* a light and a dark **palette** for the wheel,
* light and dark **UI tokens** for windows, notifications and menus (design tokens, turned
  into one stylesheet by glass.qss()),
* a **sound pack**.

Built-in themes live here; more can be imported from theme files (see `load_theme_file`).
Every theme can be customised in Settings (light/dark, Windows accent, colours, shape), and
the result saved as a new theme or exported to share."""
from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtGui import QColor


def rgba(r: int, g: int, b: int, a: int = 255) -> QColor:
    return QColor(r, g, b, a)


def hexa(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


def _c(*v):
    """A colour default for a dataclass field (QColor is mutable, so it needs a factory)."""
    return field(default_factory=lambda: QColor(v[0]) if isinstance(v[0], str) else rgba(*v))


# ---------------------------------------------------------------- data
@dataclass(frozen=True)
class Shape:
    outline: str = "circle"          # circle | squircle | square | hexagon | octagon
    inner: float = 0.38              # inner radius of the slices ÷ outer radius
    gap: float = 0.0                 # px between slices (constant width)
    corner: float = 0.0              # px rounding of each slice's corners
    rim: float = 7.0                 # px the wheel's backing reaches past the slices
    lift: bool = False               # the hovered slice lifts towards the cursor
    label_r: float = 0.5             # label radius between inner (0) and outer (1) edge
    label_px: int = 14               # format labels (PNG, PDF…)
    tool_px: int = 10                # tool labels (COMPRESS…)
    icon_px: int = 20
    icons: str = "fluent"            # fluent (Windows icon font) | glyph (plain symbols)
    hub_label: str = "plain"         # plain | pill (a frosted capsule)
    font: str = ""                   # "" = the UI font


OUTLINES = ["circle", "squircle", "square", "hexagon", "octagon"]


@dataclass(frozen=True)
class Palette:
    dark: bool = True
    glass: bool = False               # refract what's behind the menu (the original look)
    frost: bool = False               # blurred desktop shows through the backing
    base: QColor | None = None        # backing under and around the slices (rim, gaps, hub)
    base_edge: QColor | None = None
    slice_in: QColor = _c(40, 40, 48)     # slice gradient: centre side →
    slice_out: QColor = _c(34, 34, 40)    # → outer edge
    slice_mid: QColor | None = None   # optional middle stop (at 68 %)
    tile_gradient: bool = False       # gradient per slice (glossy tiles) instead of across the wheel
    slice_edge: QColor | None = None
    slice_edge_w: float = 1.0
    divider: QColor | None = None     # lines between slices (solid-disc themes)
    divider_w: float = 1.0
    inner_ring: bool = False          # a divider-coloured ring between hub and slices
    hub: QColor | None = None
    hub_edge: QColor | None = None
    pill: QColor | None = None        # hub label capsule fill
    pill_edge: QColor | None = None
    hub_text: QColor | None = None    # text on the pill/hub when it differs from `text`
    text: QColor = _c(255, 255, 255)
    text_dim: QColor = _c(255, 255, 255, 180)
    text_shadow: QColor | None = None
    hover_in: QColor = _c("#ff9142")
    hover_out: QColor = _c("#e9401f")
    hover_edge: QColor | None = None
    hover_text: QColor = _c(255, 255, 255)
    hover_alpha: float = 0.96
    arc: QColor | None = None         # accent arc on the rim beside the hovered slice
    glow: QColor | None = None        # coloured halo around the wheel
    shadow: QColor | None = _c(0, 0, 0, 90)
    neon: bool = False                # glowing outlines


@dataclass(frozen=True)
class Ui:
    """Design tokens for windows, notifications and menus."""
    glass: bool = False               # paint liquid glass instead of solid surfaces
    window: QColor = _c("#15171C")
    surface: QColor = _c("#1F2229")   # buttons, cards, popups
    hover: QColor = _c("#2A2E37")
    border: QColor = _c("#323743")
    input: QColor = _c("#111318")
    text: QColor = _c("#E8EDF5")
    text_dim: QColor = _c("#8D9AAF")
    accent: QColor = _c("#F4774F")
    on_accent: QColor = _c("#FFFFFF")
    good: QColor = _c("#3DD68C")
    warn: QColor = _c("#F5B83D")
    bad: QColor = _c("#F2555A")
    radius: int = 14                  # window corners
    control_radius: int = 9           # buttons and inputs


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    blurb: str
    credit: str
    light: Palette
    dark: Palette
    accent: QColor                    # the theme's own highlight colour
    shape: Shape = field(default_factory=Shape)
    ui_light: Ui | None = None        # None: derived from the wheel palette
    ui_dark: Ui | None = None
    sounds: str = "santra"            # sound pack key (see sounds.py)
    sound_files: dict = field(default_factory=dict)   # event → wav (themes from files)
    dark_only: bool = False
    builtin: bool = True
    source: str = ""                  # folder of an imported theme


@dataclass(frozen=True)
class Look:
    """Everything resolved for painting right now."""
    theme: Theme
    pal: Palette
    shape: Shape
    ui: Ui
    dark: bool
    accent: QColor


# ---------------------------------------------------------------- built-in library
CORAL = hexa("#F4774F")
ORANGE = hexa("#FF5200")

EMBER = Theme(
    "ember", "Ember", "Matte, calm and readable. One coral slice says exactly where the file lands.",
    "ShiftWheel's own design",
    light=Palette(
        dark=False, base=hexa("#FFFFFF", 250), base_edge=rgba(15, 20, 30, 22),
        slice_in=hexa("#FFFFFF"), slice_out=hexa("#F2F0ED"), divider=rgba(20, 24, 33, 20), divider_w=1.2,
        hub=hexa("#FFFFFF"), hub_edge=hexa("#F4774F", 170), text=hexa("#1B2130"), text_dim=hexa("#6B7385"),
        hover_in=hexa("#FF9A6B"), hover_out=hexa("#F4574F"), arc=CORAL,
        glow=rgba(244, 119, 79, 30), shadow=rgba(30, 20, 10, 60)),
    dark=Palette(
        dark=True, base=hexa("#0F1218", 246), base_edge=rgba(255, 255, 255, 24),
        slice_in=hexa("#1A1E27"), slice_out=hexa("#232834"), divider=rgba(255, 255, 255, 18), divider_w=1.2,
        hub=hexa("#0C0F14"), hub_edge=hexa("#F4774F", 160), text=hexa("#E8EDF5"), text_dim=hexa("#8D9AAF"),
        hover_in=hexa("#FF9A6B"), hover_out=hexa("#F4574F"), arc=CORAL,
        glow=rgba(244, 119, 79, 42), shadow=rgba(0, 0, 0, 120)),
    accent=CORAL, shape=Shape(rim=6),
    ui_light=Ui(window=hexa("#FAFAF9"), surface=hexa("#FFFFFF"), hover=hexa("#F1EFEC"), border=hexa("#E4E1DC"),
                input=hexa("#FFFFFF"), text=hexa("#1B2130"), text_dim=hexa("#6B7385"), accent=CORAL,
                good=hexa("#13834F"), warn=hexa("#A35F00"), bad=hexa("#D93036")),
    ui_dark=Ui(window=hexa("#12151B"), surface=hexa("#1C2029"), hover=hexa("#252A35"), border=hexa("#2A303C"),
               input=hexa("#0E1116"), text=hexa("#E8EDF5"), text_dim=hexa("#8D9AAF"), accent=CORAL),
    sounds="soft")

SANTRA = Theme(
    "santra", "Santra", "Frosted glass tiles, black labels, a bright orange slice.",
    "",
    light=Palette(
        dark=False, frost=True, base=rgba(192, 201, 205, 64), base_edge=rgba(255, 255, 255, 85),
        tile_gradient=True, slice_in=rgba(255, 255, 255, 204), slice_mid=rgba(243, 246, 247, 148),
        slice_out=rgba(244, 246, 246, 191), slice_edge=rgba(93, 102, 102, 56), slice_edge_w=0.9,
        hub=rgba(255, 255, 255, 60), pill=rgba(255, 255, 255, 184), pill_edge=rgba(255, 255, 255, 179),
        hub_text=hexa("#000000"), text=hexa("#000000"), text_dim=rgba(0, 0, 0, 150),
        hover_in=ORANGE, hover_out=ORANGE, hover_edge=rgba(194, 101, 52, 112), hover_alpha=1.0,
        shadow=rgba(38, 52, 56, 40)),
    dark=Palette(
        dark=True, frost=True, base=rgba(40, 40, 44, 150), base_edge=rgba(255, 255, 255, 40),
        tile_gradient=True, slice_in=rgba(78, 78, 84, 215), slice_mid=rgba(58, 58, 63, 190),
        slice_out=rgba(64, 64, 70, 205), slice_edge=rgba(255, 255, 255, 30), slice_edge_w=0.9,
        hub=rgba(30, 30, 32, 90), pill=rgba(28, 28, 30, 190), pill_edge=rgba(255, 255, 255, 46),
        hub_text=hexa("#F5F5F7"), text=hexa("#F5F5F7"), text_dim=rgba(245, 245, 247, 150),
        hover_in=hexa("#FF5F1A"), hover_out=hexa("#FF5F1A"), hover_edge=rgba(255, 160, 110, 110), hover_alpha=1.0,
        shadow=rgba(0, 0, 0, 110)),
    accent=ORANGE,
    shape=Shape(inner=0.407, gap=5.3, corner=26.6, rim=8.5, label_r=0.56, label_px=18, tool_px=11, icon_px=23,
                hub_label="pill"),
    ui_light=Ui(window=hexa("#F4F4F4"), surface=hexa("#FFFFFF"), hover=hexa("#EDEDED"), border=hexa("#E6E6E6"),
                input=hexa("#FFFFFF"), text=hexa("#1A1A1A"), text_dim=hexa("#757575"), accent=ORANGE,
                good=hexa("#13834F"), warn=hexa("#A35F00"), bad=hexa("#D93036"), radius=18, control_radius=10),
    ui_dark=Ui(window=hexa("#1C1C1E"), surface=hexa("#2C2C2E"), hover=hexa("#3A3A3C"), border=hexa("#38383A"),
               input=hexa("#1C1C1E"), text=hexa("#F2F2F7"), text_dim=hexa("#98989F"), accent=hexa("#FF6A1A"),
               radius=18, control_radius=10),
    sounds="santra")

_GLASS = Palette(dark=True, glass=True, hover_alpha=0.78, shadow=None)
GLASS = Theme(
    "glass", "Liquid glass", "Clear glass that refracts whatever is behind it. Adapts to any wallpaper.",
    "The original DragShift look", light=_GLASS, dark=_GLASS, accent=hexa("#ff7a2f"),
    shape=Shape(icons="glyph"), ui_light=Ui(glass=True), ui_dark=Ui(glass=True), sounds="glass")

FROST = Theme(
    "frost", "Frost", "Milky frosted glass, big quiet hub. Feels at home next to macOS-style apps.",
    "Apple's 'Release to Select' menu",
    light=Palette(
        dark=False, frost=True, base=rgba(246, 240, 255, 150), base_edge=rgba(255, 255, 255, 190),
        slice_in=rgba(255, 255, 255, 0), slice_out=rgba(255, 255, 255, 40), hub=rgba(255, 255, 255, 190),
        hub_edge=rgba(255, 255, 255, 230), text=hexa("#2A2340"), text_dim=rgba(42, 35, 64, 150),
        hover_in=rgba(255, 255, 255, 190), hover_out=rgba(255, 255, 255, 130), hover_text=hexa("#2A2340"),
        arc=hexa("#8B5CF6"), shadow=rgba(40, 20, 80, 60)),
    dark=Palette(
        dark=True, frost=True, base=rgba(38, 34, 52, 170), base_edge=rgba(255, 255, 255, 70),
        slice_in=rgba(255, 255, 255, 0), slice_out=rgba(255, 255, 255, 16), hub=rgba(70, 64, 92, 200),
        hub_edge=rgba(255, 255, 255, 70), text=hexa("#F2EEFF"), text_dim=rgba(242, 238, 255, 160),
        hover_in=rgba(255, 255, 255, 70), hover_out=rgba(255, 255, 255, 40), hover_text=hexa("#FFFFFF"),
        arc=hexa("#A78BFA"), shadow=rgba(0, 0, 0, 100)),
    accent=hexa("#8B5CF6"), shape=Shape(rim=0),
    ui_light=Ui(window=hexa("#F6F3FB"), surface=hexa("#FFFFFF"), hover=hexa("#EEE9F7"), border=hexa("#E2DCEF"),
                input=hexa("#FFFFFF"), text=hexa("#2A2340"), text_dim=hexa("#6E6788"), accent=hexa("#8B5CF6"),
                good=hexa("#13834F"), warn=hexa("#A35F00"), bad=hexa("#D93036"), radius=18),
    ui_dark=Ui(window=hexa("#1D1A26"), surface=hexa("#282435"), hover=hexa("#332E44"), border=hexa("#3A3550"),
               input=hexa("#17151F"), text=hexa("#F2EEFF"), text_dim=hexa("#A39DBA"), accent=hexa("#A78BFA"),
               radius=18),
    sounds="glass")

GRAPHITE = Theme(
    "graphite", "Graphite", "Near-black disc with hairline dividers and a faint blue halo. Minimal.",
    "Radial for macOS",
    light=Palette(
        dark=False, base=hexa("#F5F5F7"), base_edge=rgba(0, 0, 0, 26), slice_in=hexa("#FFFFFF"),
        slice_out=hexa("#FAFAFB"), divider=rgba(0, 0, 0, 22), hub=hexa("#F5F5F7"), hub_edge=rgba(0, 0, 0, 26),
        text=hexa("#1D1D1F"), text_dim=hexa("#6E6E73"), hover_in=hexa("#E8E8ED"), hover_out=hexa("#DEDEE4"),
        hover_text=hexa("#1D1D1F"), glow=rgba(90, 100, 255, 36), shadow=rgba(0, 0, 0, 50)),
    dark=Palette(
        dark=True, base=hexa("#0E0E10"), base_edge=rgba(120, 130, 255, 80), slice_in=hexa("#141416"),
        slice_out=hexa("#19191C"), divider=rgba(255, 255, 255, 20), hub=hexa("#09090A"), hub_edge=rgba(255, 255, 255, 32),
        text=hexa("#D9D9DE"), text_dim=hexa("#86868D"), hover_in=hexa("#26262B"), hover_out=hexa("#303037"),
        hover_text=hexa("#FFFFFF"), glow=rgba(90, 100, 255, 60), shadow=rgba(0, 0, 0, 120)),
    accent=hexa("#6E7BFF"), shape=Shape(rim=5),
    ui_light=Ui(window=hexa("#F5F5F7"), surface=hexa("#FFFFFF"), hover=hexa("#ECECEF"), border=hexa("#E3E3E6"),
                input=hexa("#FFFFFF"), text=hexa("#1D1D1F"), text_dim=hexa("#6E6E73"), accent=hexa("#4F5BD5"),
                good=hexa("#13834F"), warn=hexa("#A35F00"), bad=hexa("#D93036"), radius=12, control_radius=7),
    ui_dark=Ui(window=hexa("#0E0E10"), surface=hexa("#18181B"), hover=hexa("#232327"), border=hexa("#2A2A2E"),
               input=hexa("#0B0B0D"), text=hexa("#E4E4E7"), text_dim=hexa("#8A8A90"), accent=hexa("#6E7BFF"),
               radius=12, control_radius=7),
    sounds="soft")

BLOSSOM = Theme(
    "blossom", "Blossom", "Soft tiles split by bold dividers, with a pink highlight. Playful and very clear.",
    "FileFlow concept",
    light=Palette(
        dark=False, base=hexa("#23262F"), slice_in=hexa("#F7F0F4"), slice_out=hexa("#EEE5EB"),
        divider=hexa("#23262F"), divider_w=7, inner_ring=True, hub=hexa("#FFFFFF"), text=hexa("#23262F"),
        text_dim=hexa("#7C7F8A"), hover_in=hexa("#F87299"), hover_out=hexa("#F25C86"), shadow=rgba(0, 0, 0, 70)),
    dark=Palette(
        dark=True, base=hexa("#15171D"), slice_in=hexa("#2E323D"), slice_out=hexa("#272B35"),
        divider=hexa("#15171D"), divider_w=7, inner_ring=True, hub=hexa("#1F222B"), text=hexa("#F1E9EE"),
        text_dim=hexa("#A39AA2"), hover_in=hexa("#F87299"), hover_out=hexa("#F25C86"), shadow=rgba(0, 0, 0, 110)),
    accent=hexa("#F25C86"), shape=Shape(rim=6),
    ui_light=Ui(window=hexa("#F7F0F4"), surface=hexa("#FFFFFF"), hover=hexa("#F1E5EC"), border=hexa("#E9DDE4"),
                input=hexa("#FFFFFF"), text=hexa("#23262F"), text_dim=hexa("#7C7F8A"), accent=hexa("#F25C86"),
                good=hexa("#13834F"), warn=hexa("#A35F00"), bad=hexa("#D93036"), radius=16, control_radius=12),
    ui_dark=Ui(window=hexa("#15171D"), surface=hexa("#23262F"), hover=hexa("#2E323D"), border=hexa("#343846"),
               input=hexa("#111318"), text=hexa("#F1E9EE"), text_dim=hexa("#A39AA2"), accent=hexa("#F25C86"),
               radius=16, control_radius=12),
    sounds="pop")

_NEON = Palette(
    dark=True, base=rgba(10, 6, 22, 238), base_edge=rgba(255, 62, 165, 170),
    slice_in=rgba(18, 10, 36, 0), slice_out=rgba(42, 16, 72, 95), divider=rgba(51, 225, 255, 120), divider_w=1.2,
    neon=True, hub=rgba(8, 4, 18, 240), hub_edge=rgba(51, 225, 255, 210), text=hexa("#E9F7FF"),
    text_dim=hexa("#8FB7D9"), hover_in=hexa("#FF3EA5"), hover_out=hexa("#7B5CFF"), hover_alpha=0.88,
    arc=hexa("#33E1FF"), glow=rgba(255, 62, 165, 60), shadow=rgba(0, 0, 0, 120))
_NEON_UI = Ui(window=hexa("#0B0614"), surface=hexa("#140C24"), hover=hexa("#1E1236"), border=hexa("#3A1F5C"),
              input=hexa("#08040F"), text=hexa("#E9F7FF"), text_dim=hexa("#8FB7D9"), accent=hexa("#FF3EA5"),
              good=hexa("#33E1FF"), radius=10, control_radius=6)
NEON = Theme("neon", "Neon Night", "Synthwave HUD: glowing cyan lines, magenta highlight. Dark only.",
             "OG Converter's Neon Night", light=_NEON, dark=_NEON, accent=hexa("#FF3EA5"),
             shape=Shape(rim=6), ui_light=_NEON_UI, ui_dark=_NEON_UI, sounds="arcade", dark_only=True)

BUILTIN = (SANTRA, EMBER, GLASS, FROST, GRAPHITE, BLOSSOM, NEON)
THEMES: dict[str, Theme] = {t.key: t for t in BUILTIN}
DEFAULT_THEME = "santra"

MODES = [("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")]
ACCENTS = [("theme", "Theme colour", None), ("windows", "Windows accent", None),
           ("coral", "Coral", "#F4774F"), ("orange", "Orange", "#FF5200"), ("pink", "Pink", "#EC4899"),
           ("violet", "Violet", "#8B5CF6"), ("blue", "Blue", "#3B82F6"), ("teal", "Teal", "#14B8A6"),
           ("green", "Green", "#22C55E")]
COLOR_ROLES = [("highlight", "Highlight"), ("slices", "Slices"), ("ring", "Wheel backing"), ("text", "Labels")]


# ---------------------------------------------------------------- the system's preferences
def system_is_dark() -> bool:
    """Windows 'app mode' (Settings → Personalisation → Colours), via Qt when it's running."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.instance() is not None:
            scheme = QGuiApplication.styleHints().colorScheme()
            if scheme != Qt.ColorScheme.Unknown:
                return scheme == Qt.ColorScheme.Dark
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except OSError:
            pass
    return True


def windows_accent() -> QColor | None:
    """The accent colour picked in Windows settings (stored as ABGR)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as k:
            v = winreg.QueryValueEx(k, "AccentColor")[0]
        return QColor(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
    except OSError:
        return None


# ---------------------------------------------------------------- resolving a choice
def is_dark(mode: str) -> bool:
    return system_is_dark() if mode not in ("light", "dark") else mode == "dark"


def accent_color(theme_key: str, accent: str) -> QColor:
    t = THEMES.get(theme_key, THEMES[DEFAULT_THEME])
    if accent == "windows":
        return windows_accent() or QColor(t.accent)
    hexes = {k: h for k, _, h in ACCENTS if h}
    if accent in hexes:
        return QColor(hexes[accent])
    if isinstance(accent, str) and accent.startswith("#") and QColor(accent).isValid():
        return QColor(accent)
    return QColor(t.accent)


def _on(c: QColor) -> QColor:
    """Readable text colour on top of `c`."""
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor("#1A1A1A") if lum > 170 else QColor("#FFFFFF")


def _with_alpha(c: QColor, a: int) -> QColor:
    c = QColor(c)
    c.setAlpha(a)
    return c


def ui_from(pal: Palette) -> Ui:
    """UI tokens for a theme that only describes its wheel (e.g. an imported file)."""
    acc = QColor(pal.hover_out)
    if pal.dark:
        return Ui(text=QColor(pal.text), text_dim=QColor(pal.text_dim), accent=acc, on_accent=_on(acc))
    return Ui(window=hexa("#F6F6F7"), surface=hexa("#FFFFFF"), hover=hexa("#EEEFF1"), border=hexa("#E2E3E6"),
              input=hexa("#FFFFFF"), text=QColor(pal.text), text_dim=QColor(pal.text_dim), accent=acc,
              on_accent=_on(acc), good=hexa("#13834F"), warn=hexa("#A35F00"), bad=hexa("#D93036"))


def resolve(theme_key: str, custom: dict | None = None) -> Look:
    """The look to paint now: a theme plus its customisations (mode, accent, colours, shape).
    Unknown keys and bad values fall back to the theme's own, never raise."""
    t = THEMES.get(theme_key) or THEMES[DEFAULT_THEME]
    custom = custom or {}
    dark = True if t.dark_only else is_dark(custom.get("mode", "system"))
    pal = t.dark if dark else t.light
    ui = (t.ui_dark if dark else t.ui_light) or ui_from(pal)
    shape = t.shape

    accent_key = custom.get("accent", "theme")
    colors = custom.get("colors") or {}
    acc = accent_color(t.key, accent_key)
    hl = _color(colors.get("highlight"))
    if hl is not None:
        acc = hl
    if accent_key not in ("theme", "", None) or hl is not None:
        pal = replace(pal, hover_in=QColor(acc).lighter(112) if pal.hover_in != pal.hover_out else QColor(acc),
                      hover_out=QColor(acc), hover_text=_on(acc),
                      arc=QColor(acc) if pal.arc is not None else None,
                      hub_edge=_with_alpha(acc, 170) if pal.hub_edge is not None and t.key == "ember" else pal.hub_edge,
                      glow=_with_alpha(acc, pal.glow.alpha()) if pal.glow is not None else None,
                      hover_edge=QColor(acc).darker(130) if pal.hover_edge is not None else None)
        if not ui.glass:
            ui = replace(ui, accent=QColor(acc), on_accent=_on(acc))
    sl = _color(colors.get("slices"))
    if sl is not None:
        a_in, a_out = pal.slice_in.alpha(), pal.slice_out.alpha()
        pal = replace(pal, slice_in=_with_alpha(QColor(sl).lighter(108), max(a_in, 200)),
                      slice_out=_with_alpha(sl, max(a_out, 200)),
                      slice_mid=_with_alpha(sl, max(a_out, 190)) if pal.slice_mid is not None else None)
    rg = _color(colors.get("ring"))
    if rg is not None:
        pal = replace(pal, base=rg, divider=QColor(rg) if pal.inner_ring else pal.divider)
    tx = _color(colors.get("text"))
    if tx is not None:
        pal = replace(pal, text=tx, text_dim=_with_alpha(tx, 165),
                      hub_text=tx if pal.hub_text is not None else None)

    sh = custom.get("shape") or {}
    if sh:
        shape = _shape_from(sh, shape, [])
    return Look(t, pal, shape, ui, dark, QColor(acc))


def palette(theme_key: str, mode: str = "system", accent: str = "theme") -> Palette:
    """Shorthand for the wheel palette of a theme in a mode."""
    return resolve(theme_key, {"mode": mode, "accent": accent}).pal


# ---------------------------------------------------------------- theme files
FORMAT = "shiftwheel-theme"
PAL_KEYS = {   # file key → Palette field (colours unless listed in PAL_BOOL / PAL_NUM)
    "disc": "base", "discEdge": "base_edge", "sliceInner": "slice_in", "sliceMiddle": "slice_mid",
    "sliceOuter": "slice_out", "sliceEdge": "slice_edge", "divider": "divider", "hub": "hub", "hubEdge": "hub_edge",
    "pill": "pill", "pillEdge": "pill_edge", "hubText": "hub_text", "text": "text", "textDim": "text_dim",
    "textShadow": "text_shadow", "hoverInner": "hover_in", "hoverOuter": "hover_out", "hoverEdge": "hover_edge",
    "hoverText": "hover_text", "arc": "arc", "glow": "glow", "shadow": "shadow",
    "glass": "glass", "frost": "frost", "tileGradient": "tile_gradient", "innerRing": "inner_ring", "neon": "neon",
    "dividerWidth": "divider_w", "sliceEdgeWidth": "slice_edge_w", "hoverAlpha": "hover_alpha"}
PAL_BOOL = {"glass", "frost", "tile_gradient", "inner_ring", "neon"}
PAL_NUM = {"divider_w": (0, 20), "slice_edge_w": (0, 6), "hover_alpha": (0, 1)}
UI_KEYS = {"glass": "glass", "window": "window", "surface": "surface", "hover": "hover", "border": "border",
           "input": "input", "text": "text", "textDim": "text_dim", "accent": "accent", "onAccent": "on_accent",
           "good": "good", "warn": "warn", "bad": "bad", "radius": "radius", "controlRadius": "control_radius"}
UI_NUM = {"radius": (0, 32), "control_radius": (0, 24)}
SHAPE_KEYS = {"outline": "outline", "innerRatio": "inner", "gap": "gap", "corner": "corner", "rim": "rim",
              "lift": "lift", "labelRadius": "label_r", "labelSize": "label_px", "toolLabelSize": "tool_px",
              "iconSize": "icon_px", "iconSet": "icons", "hubLabel": "hub_label", "font": "font"}
SHAPE_NUM = {"inner": (0.2, 0.7), "gap": (0, 24), "corner": (0, 60), "rim": (0, 30), "label_r": (0.1, 0.9),
             "label_px": (8, 32), "tool_px": (7, 24), "icon_px": (10, 40)}
SHAPE_CHOICE = {"outline": OUTLINES, "icons": ["fluent", "glyph"], "hub_label": ["plain", "pill"]}
SOUND_EVENTS = ["open", "highlight", "switch", "select", "done", "error"]


class ThemeError(ValueError):
    """A theme file that can't be used at all (the message is shown to the user)."""


def _color(v) -> QColor | None:
    """'#RGB', '#RRGGBB', '#RRGGBBAA' (CSS order), 'rgba(r,g,b,a)', a colour name, or null."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, QColor):
        return QColor(v)
    s = str(v).strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{8})", s)
    if m:
        h = m.group(1)
        return QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", s)
    if m:
        a = m.group(4)
        alpha = 255 if a is None else int(round(float(a) * 255)) if float(a) <= 1 else int(float(a))
        return QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)), max(0, min(255, alpha)))
    c = QColor(s)
    return c if c.isValid() else None


def color_text(c: QColor | None) -> str | None:
    if c is None:
        return None
    return c.name() if c.alpha() == 255 else f"{c.name()}{c.alpha():02x}"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _apply(obj, data: dict, keys: dict, bools: set, nums: dict, where: str, warn: list, choices=None):
    changes = {}
    for k, v in (data or {}).items():
        attr = keys.get(k)
        if attr is None:
            warn.append(f"{where}: unknown key “{k}” ignored")
            continue
        if attr in bools or attr in ("glass", "lift"):
            if isinstance(v, bool):
                changes[attr] = v
            else:
                warn.append(f"{where}.{k}: expected true/false")
        elif attr in nums:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                lo, hi = nums[attr]
                val = _clamp(float(v), lo, hi)
                changes[attr] = int(round(val)) if isinstance(getattr(obj, attr), int) and not isinstance(
                    getattr(obj, attr), bool) else val
            else:
                warn.append(f"{where}.{k}: expected a number")
        elif choices and attr in choices:
            if v in choices[attr]:
                changes[attr] = v
            else:
                warn.append(f"{where}.{k}: must be one of {', '.join(choices[attr])}")
        elif attr == "font":
            changes[attr] = str(v)[:60]
        else:
            if v is None:
                changes[attr] = None
                continue
            c = _color(v)
            if c is None:
                warn.append(f"{where}.{k}: “{v}” is not a colour")
            else:
                changes[attr] = c
    return replace(obj, **changes) if changes else obj


def _shape_from(data: dict, base: Shape, warn: list) -> Shape:
    return _apply(base, data, SHAPE_KEYS, set(), SHAPE_NUM, "shape", warn, SHAPE_CHOICE)


def theme_from_dict(d: dict, source: str = "", warn: list | None = None, check_files: bool = True) -> Theme:
    warn = [] if warn is None else warn
    if not isinstance(d, dict):
        raise ThemeError("This isn't a ShiftWheel theme (expected a JSON object).")
    if d.get("format") not in (None, FORMAT):
        raise ThemeError(f"Unknown format “{d.get('format')}”: expected “{FORMAT}”.")
    if int(d.get("version", 1) or 1) > 1:
        warn.append("made for a newer ShiftWheel: some parts may be ignored")
    name = str(d.get("name") or "").strip()
    if not name:
        raise ThemeError("The theme has no name.")
    key = slug(str(d.get("id") or name))
    base = THEMES.get(str(d.get("base") or "ember")) or EMBER
    if d.get("base") and d.get("base") not in THEMES:
        warn.append(f"base theme “{d.get('base')}” not found: using Ember")
    shape = _shape_from(d.get("shape") or {}, base.shape, warn)
    modes = {}
    for mode in ("light", "dark"):
        part = d.get(mode) or {}
        pal = _apply(getattr(base, mode), part.get("wheel") or {}, PAL_KEYS, PAL_BOOL, PAL_NUM, f"{mode}.wheel", warn)
        pal = replace(pal, dark=(mode == "dark"))
        base_ui = getattr(base, f"ui_{mode}") or ui_from(pal)
        ui = _apply(base_ui, part.get("ui") or {}, UI_KEYS, {"glass"}, UI_NUM, f"{mode}.ui", warn)
        modes[mode] = (pal, ui)
    if not d.get("light") and d.get("dark"):          # one mode given: use it for both
        modes["light"] = modes["dark"]
    accent = _color(d.get("accent")) or QColor(modes["light"][0].hover_out)
    sounds = d.get("sounds") or {}
    pack = str(sounds.get("pack") or base.sounds)
    files = {}
    for ev, rel in (sounds.get("files") or {}).items():
        if ev not in SOUND_EVENTS:
            warn.append(f"sounds.files: unknown event “{ev}”")
            continue
        if not check_files:           # validating a package before its files are unpacked
            continue
        p = (Path(source) / str(rel)) if source else Path(str(rel))
        if p.suffix.lower() == ".wav" and p.is_file():
            files[ev] = str(p)
        else:
            warn.append(f"sounds.files.{ev}: “{rel}” is not a .wav file in the theme")
    return Theme(key, name[:40], str(d.get("description") or "")[:240],
                 str(d.get("author") or "Imported theme")[:80],
                 light=modes["light"][0], dark=modes["dark"][0], accent=accent, shape=shape,
                 ui_light=modes["light"][1], ui_dark=modes["dark"][1], sounds=pack, sound_files=files,
                 dark_only=bool(d.get("darkOnly", False)), builtin=False, source=source)


def theme_to_dict(t: Theme, look_custom: dict | None = None) -> dict:
    """A complete, self-contained description (every value written out)."""
    if look_custom:
        t = bake(t, look_custom)

    def pal_dict(p: Palette):
        out = {}
        for fk, attr in PAL_KEYS.items():
            v = getattr(p, attr)
            out[fk] = v if isinstance(v, (bool, int, float)) and not isinstance(v, QColor) else color_text(v)
        return out

    def ui_dict(u: Ui):
        out = {}
        for fk, attr in UI_KEYS.items():
            v = getattr(u, attr)
            out[fk] = v if isinstance(v, (bool, int, float)) and not isinstance(v, QColor) else color_text(v)
        return out

    shape = {fk: getattr(t.shape, attr) for fk, attr in SHAPE_KEYS.items()}
    return {"format": FORMAT, "version": 1, "id": t.key, "name": t.name, "author": t.credit,
            "description": t.blurb, "accent": color_text(t.accent), "darkOnly": t.dark_only, "shape": shape,
            "light": {"wheel": pal_dict(t.light), "ui": ui_dict(t.ui_light or ui_from(t.light))},
            "dark": {"wheel": pal_dict(t.dark), "ui": ui_dict(t.ui_dark or ui_from(t.dark))},
            "sounds": {"pack": t.sounds, "files": {ev: f"sounds/{ev}.wav" for ev in t.sound_files}}}


def bake(t: Theme, custom: dict) -> Theme:
    """A theme with its customisations applied to both modes (for "Save as new theme")."""
    light = resolve_with(t, dict(custom, mode="light"))
    dark = resolve_with(t, dict(custom, mode="dark"))
    return replace(t, light=light.pal, dark=dark.pal, ui_light=light.ui, ui_dark=dark.ui, shape=light.shape,
                   accent=light.accent)


def resolve_with(t: Theme, custom: dict) -> Look:
    """resolve() for a theme that may not be registered."""
    saved = THEMES.get(t.key)
    THEMES[t.key] = t
    try:
        return resolve(t.key, custom)
    finally:
        if saved is None:
            THEMES.pop(t.key, None)
        else:
            THEMES[t.key] = saved


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40] or "theme"


# ---------------------------------------------------------------- user theme folder
def themes_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "ShiftWheel" / "themes"
    return base


def load_theme_file(path: str | Path) -> tuple[dict, Path | None, list[str]]:
    """Read a .swtheme (zip: theme.json + sounds/) or a .json theme.
    Returns (data, folder with its files or None, warnings)."""
    p = Path(path)
    warn: list[str] = []
    try:
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
                main = next((n for n in names if n.rsplit("/", 1)[-1] == "theme.json"), None)
                if main is None:
                    raise ThemeError("The theme package has no theme.json inside.")
                data = json.loads(z.read(main).decode("utf-8-sig"))
            return data, p, warn
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data, None, warn
    except ThemeError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ThemeError(f"Couldn't read the theme: {e}") from e


def install_theme(path: str | Path) -> tuple[Theme, list[str]]:
    """Import a theme file into the user theme folder and register it."""
    data, package, warn = load_theme_file(path)
    theme = theme_from_dict(data, warn=warn, check_files=package is None)   # validate before touching the disk
    key = theme.key
    if key in {b.key for b in BUILTIN}:
        key = f"{key}-custom"
    dest = themes_dir() / key
    dest.mkdir(parents=True, exist_ok=True)
    if package is not None:
        with zipfile.ZipFile(package) as z:
            for n in z.namelist():
                if n.startswith("sounds/") and n.lower().endswith(".wav") and ".." not in n:
                    (dest / "sounds").mkdir(exist_ok=True)
                    (dest / "sounds" / Path(n).name).write_bytes(z.read(n))
    data = dict(data, id=key)
    (dest / "theme.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    theme = theme_from_dict(data, str(dest), warn=warn if package is not None else [])
    THEMES[theme.key] = theme
    return theme, warn


def save_user_theme(t: Theme, sound_files: dict | None = None) -> Theme:
    """Write a (baked) theme to the user folder, copying its sound files, and register it."""
    import shutil
    key = t.key if t.key not in {b.key for b in BUILTIN} else f"{t.key}-custom"
    dest = themes_dir() / key
    dest.mkdir(parents=True, exist_ok=True)
    files = dict(t.sound_files, **(sound_files or {}))
    t = replace(t, key=key, builtin=False, sound_files=files)
    data = theme_to_dict(t)
    if files:
        (dest / "sounds").mkdir(exist_ok=True)
        for ev, src in files.items():
            if Path(src).is_file() and Path(src).resolve() != (dest / "sounds" / f"{ev}.wav").resolve():
                shutil.copyfile(src, dest / "sounds" / f"{ev}.wav")
    (dest / "theme.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    theme = theme_from_dict(data, str(dest), warn=[])
    THEMES[theme.key] = theme
    return theme


def export_theme(t: Theme, out: str | Path, custom: dict | None = None, sound_files: dict | None = None) -> Path:
    """A shareable .swtheme package: theme.json plus any sound files it uses."""
    out = Path(out)
    t = bake(t, custom) if custom else t
    files = dict(t.sound_files, **(sound_files or {}))
    t = replace(t, sound_files=files)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("theme.json", json.dumps(theme_to_dict(t), indent=2))
        for ev, src in files.items():
            if Path(src).is_file():
                z.write(src, f"sounds/{ev}.wav")
    return out


def delete_user_theme(key: str) -> None:
    import shutil
    t = THEMES.get(key)
    if t is None or t.builtin:
        return
    shutil.rmtree(themes_dir() / key, ignore_errors=True)
    THEMES.pop(key, None)


def load_user_themes() -> list[str]:
    """Register every theme in the user folder. Returns problems to log (bad files are skipped)."""
    problems = []
    d = themes_dir()
    if not d.is_dir():
        return problems
    for sub in sorted(d.iterdir()):
        f = sub / "theme.json"
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))
            t = theme_from_dict(dict(data, id=sub.name), str(sub), warn=[])
            THEMES[t.key] = t
        except (ThemeError, OSError, ValueError) as e:
            problems.append(f"{sub.name}: {e}")
    return problems


def schema_example() -> dict:
    """What a theme file looks like (written next to exported themes, and in the README)."""
    return {
        "format": FORMAT, "version": 1, "name": "Square Mint", "author": "you",
        "description": "A rounded-square wheel in mint green.", "base": "ember",
        "shape": {"outline": "square", "corner": 14, "gap": 4, "innerRatio": 0.42},
        "light": {"wheel": {"hoverOuter": "#10B981", "hoverInner": "#34D399", "sliceInner": "#FFFFFF",
                            "sliceOuter": "#ECFDF5", "arc": "#10B981"},
                  "ui": {"accent": "#10B981"}},
        "dark": {"wheel": {"hoverOuter": "#10B981", "hoverInner": "#34D399", "arc": "#34D399"},
                 "ui": {"accent": "#34D399"}},
        "sounds": {"pack": "pop"}}
