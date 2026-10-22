"""Wheel themes: a small library of looks, each with a light and a dark palette.

A palette is plain data; radial.py paints any palette with one renderer (plus the original
liquid-glass refraction for the "glass" theme). Light/dark can follow Windows, and the
highlight colour can follow the Windows accent colour."""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace

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


@dataclass(frozen=True)
class Palette:
    dark: bool = True
    glass: bool = False               # refract what's behind the menu (the original look)
    gap: float = 3.2                  # degrees between slices; 0 = one solid disc
    frost: bool = False               # blurred desktop shows through the disc
    base: QColor | None = None        # disc under and around the slices (rim, gaps, hub ring)
    rim: float = 7.0                  # how far the disc reaches past the slices
    base_edge: QColor | None = None
    slice_in: QColor = _c(40, 40, 48)     # slice gradient: centre side →
    slice_out: QColor = _c(34, 34, 40)    # → outer edge
    slice_edge: QColor | None = None
    divider: QColor | None = None     # lines between slices (solid-disc themes)
    divider_w: float = 1.0
    inner_ring: bool = False          # a divider-coloured ring between hub and slices
    hub: QColor | None = None
    hub_edge: QColor | None = None
    pill: tuple[QColor, QColor] | None = None   # rounded label plate in the hub
    hub_text: QColor | None = None    # text on the pill/hub when it differs from `text`
    text: QColor = _c(255, 255, 255)
    text_dim: QColor = _c(255, 255, 255, 180)
    text_shadow: QColor | None = None
    hover_in: QColor = _c("#ff9142")
    hover_out: QColor = _c("#e9401f")
    hover_text: QColor = _c(255, 255, 255)
    hover_alpha: float = 0.96
    pop: bool = True                  # the hovered slice lifts towards the cursor
    arc: QColor | None = None         # accent arc on the rim beside the hovered slice
    glow: QColor | None = None        # coloured halo around the disc
    shadow: QColor | None = _c(0, 0, 0, 90)
    neon: bool = False                # glowing outlines


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    blurb: str
    credit: str
    light: Palette
    dark: Palette
    accent: QColor                    # the theme's own highlight colour


# ---------------------------------------------------------------- the library
CORAL = hexa("#F4774F")

EMBER = Theme(
    "ember", "Ember", "Matte, calm and readable. One coral slice says exactly where the file lands.",
    "ShiftWheel's own design",
    light=Palette(
        dark=False, gap=0, base=hexa("#FFFFFF", 250), rim=6, base_edge=rgba(15, 20, 30, 22),
        slice_in=hexa("#FFFFFF"), slice_out=hexa("#F2F0ED"), divider=rgba(20, 24, 33, 20), divider_w=1.2,
        hub=hexa("#FFFFFF"), hub_edge=hexa("#F4774F", 170), text=hexa("#1B2130"), text_dim=hexa("#6B7385"),
        hover_in=hexa("#FF9A6B"), hover_out=hexa("#F4574F"), pop=False, arc=CORAL,
        glow=rgba(244, 119, 79, 30), shadow=rgba(30, 20, 10, 60)),
    dark=Palette(
        dark=True, gap=0, base=hexa("#0F1218", 246), rim=6, base_edge=rgba(255, 255, 255, 24),
        slice_in=hexa("#1A1E27"), slice_out=hexa("#232834"), divider=rgba(255, 255, 255, 18), divider_w=1.2,
        hub=hexa("#0C0F14"), hub_edge=hexa("#F4774F", 160), text=hexa("#E8EDF5"), text_dim=hexa("#8D9AAF"),
        hover_in=hexa("#FF9A6B"), hover_out=hexa("#F4574F"), pop=False, arc=CORAL,
        glow=rgba(244, 119, 79, 42), shadow=rgba(0, 0, 0, 120)),
    accent=CORAL)

SANTRA = Theme(
    "santra", "Santra", "Warm peach slices with an orange highlight, like Santra.",
    "Santra (from the reels)",
    light=Palette(
        dark=False, gap=3.2, frost=True, base=rgba(255, 240, 228, 200), rim=7, base_edge=rgba(255, 255, 255, 200),
        slice_in=rgba(255, 232, 212, 214), slice_out=rgba(251, 208, 176, 214), slice_edge=rgba(255, 255, 255, 150),
        pill=(hexa("#ffd3a4"), hexa("#ffad6b")), text=hexa("#341E12"), text_dim=rgba(52, 30, 18, 165),
        text_shadow=rgba(255, 255, 255, 90), shadow=rgba(60, 20, 10, 70)),
    dark=Palette(
        dark=True, gap=3.2, frost=True, base=rgba(46, 28, 20, 215), rim=7, base_edge=rgba(255, 190, 140, 70),
        slice_in=rgba(78, 50, 35, 232), slice_out=rgba(60, 38, 27, 232), slice_edge=rgba(255, 200, 160, 45),
        pill=(hexa("#ffc58a"), hexa("#ff9a4d")), hub_text=hexa("#3A1E0E"), text=hexa("#FFE8D6"),
        text_dim=rgba(255, 232, 214, 170), text_shadow=rgba(0, 0, 0, 90), shadow=rgba(0, 0, 0, 110)),
    accent=hexa("#ff7a2f"))

_GLASS = Palette(dark=True, glass=True, hover_alpha=0.78, shadow=None)
GLASS = Theme(
    "glass", "Liquid glass", "Clear glass that refracts whatever is behind it. Adapts to any wallpaper.",
    "The original DragShift look", light=_GLASS, dark=_GLASS, accent=hexa("#ff7a2f"))

FROST = Theme(
    "frost", "Frost", "Milky frosted glass, big quiet hub. Feels at home next to macOS-style apps.",
    "Apple's 'Release to Select' menu",
    light=Palette(
        dark=False, gap=0, frost=True, base=rgba(246, 240, 255, 150), rim=0, base_edge=rgba(255, 255, 255, 190),
        slice_in=rgba(255, 255, 255, 0), slice_out=rgba(255, 255, 255, 40), hub=rgba(255, 255, 255, 190),
        hub_edge=rgba(255, 255, 255, 230), text=hexa("#2A2340"), text_dim=rgba(42, 35, 64, 150),
        hover_in=rgba(255, 255, 255, 190), hover_out=rgba(255, 255, 255, 130), hover_text=hexa("#2A2340"),
        pop=False, arc=hexa("#8B5CF6"), shadow=rgba(40, 20, 80, 60)),
    dark=Palette(
        dark=True, gap=0, frost=True, base=rgba(38, 34, 52, 170), rim=0, base_edge=rgba(255, 255, 255, 70),
        slice_in=rgba(255, 255, 255, 0), slice_out=rgba(255, 255, 255, 16), hub=rgba(70, 64, 92, 200),
        hub_edge=rgba(255, 255, 255, 70), text=hexa("#F2EEFF"), text_dim=rgba(242, 238, 255, 160),
        hover_in=rgba(255, 255, 255, 70), hover_out=rgba(255, 255, 255, 40), hover_text=hexa("#FFFFFF"),
        pop=False, arc=hexa("#A78BFA"), shadow=rgba(0, 0, 0, 100)),
    accent=hexa("#8B5CF6"))

GRAPHITE = Theme(
    "graphite", "Graphite", "Near-black disc with hairline dividers and a faint blue halo. Minimal.",
    "Radial for macOS",
    light=Palette(
        dark=False, gap=0, base=hexa("#F5F5F7"), rim=5, base_edge=rgba(0, 0, 0, 26), slice_in=hexa("#FFFFFF"),
        slice_out=hexa("#FAFAFB"), divider=rgba(0, 0, 0, 22), hub=hexa("#F5F5F7"), hub_edge=rgba(0, 0, 0, 26),
        text=hexa("#1D1D1F"), text_dim=hexa("#6E6E73"), hover_in=hexa("#E8E8ED"), hover_out=hexa("#DEDEE4"),
        hover_text=hexa("#1D1D1F"), pop=False, glow=rgba(90, 100, 255, 36), shadow=rgba(0, 0, 0, 50)),
    dark=Palette(
        dark=True, gap=0, base=hexa("#0E0E10"), rim=5, base_edge=rgba(120, 130, 255, 80), slice_in=hexa("#141416"),
        slice_out=hexa("#19191C"), divider=rgba(255, 255, 255, 20), hub=hexa("#09090A"), hub_edge=rgba(255, 255, 255, 32),
        text=hexa("#D9D9DE"), text_dim=hexa("#86868D"), hover_in=hexa("#26262B"), hover_out=hexa("#303037"),
        hover_text=hexa("#FFFFFF"), pop=False, glow=rgba(90, 100, 255, 60), shadow=rgba(0, 0, 0, 120)),
    accent=hexa("#6E7BFF"))

BLOSSOM = Theme(
    "blossom", "Blossom", "Soft tiles split by bold dividers, with a pink highlight. Playful and very clear.",
    "FileFlow concept",
    light=Palette(
        dark=False, gap=0, base=hexa("#23262F"), rim=6, slice_in=hexa("#F7F0F4"), slice_out=hexa("#EEE5EB"),
        divider=hexa("#23262F"), divider_w=7, inner_ring=True, hub=hexa("#FFFFFF"), text=hexa("#23262F"),
        text_dim=hexa("#7C7F8A"), hover_in=hexa("#F87299"), hover_out=hexa("#F25C86"), pop=False,
        shadow=rgba(0, 0, 0, 70)),
    dark=Palette(
        dark=True, gap=0, base=hexa("#15171D"), rim=6, slice_in=hexa("#2E323D"), slice_out=hexa("#272B35"),
        divider=hexa("#15171D"), divider_w=7, inner_ring=True, hub=hexa("#1F222B"), text=hexa("#F1E9EE"),
        text_dim=hexa("#A39AA2"), hover_in=hexa("#F87299"), hover_out=hexa("#F25C86"), pop=False,
        shadow=rgba(0, 0, 0, 110)),
    accent=hexa("#F25C86"))

_NEON = Palette(
    dark=True, gap=0, base=rgba(10, 6, 22, 238), rim=6, base_edge=rgba(255, 62, 165, 170),
    slice_in=rgba(18, 10, 36, 0), slice_out=rgba(42, 16, 72, 95), divider=rgba(51, 225, 255, 120), divider_w=1.2,
    neon=True, hub=rgba(8, 4, 18, 240), hub_edge=rgba(51, 225, 255, 210), text=hexa("#E9F7FF"),
    text_dim=hexa("#8FB7D9"), hover_in=hexa("#FF3EA5"), hover_out=hexa("#7B5CFF"), hover_alpha=0.88, pop=False,
    arc=hexa("#33E1FF"), glow=rgba(255, 62, 165, 60), shadow=rgba(0, 0, 0, 120))
NEON = Theme("neon", "Neon Night", "Synthwave HUD: glowing cyan lines, magenta highlight. Dark only.",
             "OG Converter's Neon Night", light=_NEON, dark=_NEON, accent=hexa("#FF3EA5"))

THEMES: dict[str, Theme] = {t.key: t for t in (EMBER, SANTRA, GLASS, FROST, GRAPHITE, BLOSSOM, NEON)}
DEFAULT_THEME = "ember"

MODES = [("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")]
ACCENTS = [("theme", "Theme colour", None), ("windows", "Windows accent", None),
           ("coral", "Coral", "#F4774F"), ("orange", "Orange", "#FF7A2F"), ("pink", "Pink", "#EC4899"),
           ("violet", "Violet", "#8B5CF6"), ("blue", "Blue", "#3B82F6"), ("teal", "Teal", "#14B8A6"),
           ("green", "Green", "#22C55E")]


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
        return windows_accent() or t.accent
    hexes = {k: h for k, _, h in ACCENTS if h}
    return QColor(hexes[accent]) if accent in hexes else QColor(t.accent)


def palette(theme_key: str, mode: str = "system", accent: str = "theme") -> Palette:
    """The palette to paint now. Unknown keys fall back to the defaults, never raise."""
    t = THEMES.get(theme_key, THEMES[DEFAULT_THEME])
    pal = t.dark if is_dark(mode) else t.light
    if accent in ("theme", "") or accent not in {k for k, _, _ in ACCENTS}:
        return pal
    a = accent_color(theme_key, accent)
    hi = QColor(a).lighter(122)
    return replace(pal, hover_in=hi, hover_out=QColor(a), hover_text=_on(a),
                   arc=QColor(a) if pal.arc is not None else None,
                   hub_edge=hexa(a.name(), 170) if pal.hub_edge is not None and not pal.glass and t.key == "ember"
                   else pal.hub_edge,
                   glow=hexa(a.name(), pal.glow.alpha()) if pal.glow is not None else None)


def _on(c: QColor) -> QColor:
    """Readable text colour on top of `c`."""
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return QColor("#1A1A1A") if lum > 170 else QColor("#FFFFFF")
