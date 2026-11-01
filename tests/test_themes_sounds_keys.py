"""Wheel shapes, theme files (import / export / customise / save), sounds, and shortcuts."""
from __future__ import annotations

import json
import math
import subprocess
import wave
import zipfile

import numpy as np
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from shiftwheel import hotkey, radial, sounds, themes, wheelshape


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def theme_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "themes_dir", lambda: tmp_path / "themes")
    before = dict(themes.THEMES)
    yield tmp_path / "themes"
    themes.THEMES.clear()
    themes.THEMES.update(before)


# ---------------------------------------------------------------- shapes
@pytest.mark.parametrize("outline", themes.OUTLINES)
def test_every_outline_slices_cleanly(outline):
    c = QPointF(200, 200)
    for n in (2, 4, 7, 9):
        paths = wheelshape.slices(outline, n, c, 64, 158, gap=5, corner=12)
        assert len(paths) == n
        for i, p in enumerate(paths):
            a = wheelshape.center_angle(n, i)
            mid = QPointF(c.x() + 110 * math.cos(a), c.y() - 110 * math.sin(a))
            assert p.contains(mid), f"{outline}/{n}: slice {i} misses its label point"
            assert not p.contains(c)                                   # the hub stays clear
        assert not paths[0].intersects(paths[1]) or paths[0].intersected(paths[1]).isEmpty()


def test_round_slice_geometry():
    # reference size: inner 48.64, outer 119.52, gap 4, corner 20.16 (their units)
    p = wheelshape.round_slice(QPointF(0, 0), math.pi / 2, 2 * math.pi / 7, 48.64, 119.52, 4.0, 20.16)
    r = p.boundingRect()
    assert -119.6 < r.top() < -115 and r.bottom() < -40                # reaches the outer edge, not the hub
    assert abs(r.center().x()) < 0.5                                   # centred at 12 o'clock
    gap_left = wheelshape.round_slice(QPointF(0, 0), math.pi / 2 - 2 * math.pi / 7, 2 * math.pi / 7,
                                          48.64, 119.52, 4.0, 20.16)
    assert p.intersected(gap_left).isEmpty()                           # the 4-unit gap is real


def test_menu_hit_test_follows_the_shape():
    m = radial.RadialMenu(lambda ps: {}, lambda ps: "")
    m.set_look(themes.resolve("ember", {"shape": {"outline": "square"}}))
    m.rings = {"Convert": [radial.Item(t) for t in ("A", "B", "C", "D")]}
    m.ring_names = ["Convert"]
    corner = QPointF(200 + 150, 200 - 150)          # inside the rounded square, outside a circle
    assert m.hit(corner) == 1
    m.set_look(themes.resolve("ember"))
    assert m.hit(corner) == -1


def test_keyboard_in_the_wheel():
    m = radial.RadialMenu(lambda ps: {}, lambda ps: "")
    m.rings = {"Convert": [radial.Item(t) for t in ("A", "B", "C")], "Tools": [radial.Item("Z", "z")]}
    m.ring_names = ["Convert", "Tools"]
    m.spring = [0.0] * 3
    got = []
    m.activated.connect(lambda item, paths: got.append(item.label))
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    def key(k):
        m.keyPressEvent(QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
    key(Qt.Key_Right)
    key(Qt.Key_Right)
    assert m.hover == 1
    key(Qt.Key_Return)
    QApplication.processEvents()
    assert got == ["B"]
    key(Qt.Key_3)
    QApplication.processEvents()
    assert got == ["B", "C"]
    key(Qt.Key_Tab)
    assert m.ring_names[m.ring_idx] == "Tools"


# ---------------------------------------------------------------- themes
def test_santra_is_the_default_design():
    t = themes.SANTRA
    assert t.light.hover_out.name() == "#ff5200" and t.light.text.name() == "#000000"
    assert t.shape.hub_label == "pill" and t.shape.gap > 0 and t.shape.corner > 20
    assert themes.DEFAULT_THEME == "santra"


def test_customise_mode_accent_colours_and_shape(monkeypatch):
    monkeypatch.setattr(themes, "windows_accent", lambda: themes.hexa("#0078D4"))
    look = themes.resolve("santra", {"mode": "dark", "accent": "windows",
                                        "colors": {"slices": "#203040", "text": "#ffeeaa"},
                                        "shape": {"outline": "hexagon", "corner": 10}})
    assert look.dark and look.pal.hover_out.name() == "#0078d4" and look.ui.accent.name() == "#0078d4"
    assert look.pal.text.name() == "#ffeeaa" and look.shape.outline == "hexagon"
    bad = themes.resolve("santra", {"mode": "sideways", "colors": {"slices": "not a colour"},
                                       "shape": {"outline": "star"}})
    assert bad.shape.outline == "circle" and bad.pal.slice_out == themes.resolve("santra").pal.slice_out


def test_theme_file_round_trip_with_sound(theme_dir, tmp_path):
    wav = sounds.write_wav(tmp_path / "beep.wav", sounds.synth("arcade", "select"))
    out = themes.export_theme(themes.EMBER, tmp_path / "mine.swtheme",
                              {"colors": {"highlight": "#10b981"}, "shape": {"outline": "squircle"}},
                              {"select": str(wav)})
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == {"theme.json", "sounds/select.wav"}
        data = json.loads(z.read("theme.json"))
    assert data["format"] == "shiftwheel-theme" and data["shape"]["outline"] == "squircle"
    t, warn = themes.install_theme(out)
    assert warn == [] and t.key in themes.THEMES and not t.builtin
    assert t.light.hover_out.name() == "#10b981" and t.shape.outline == "squircle"
    assert (theme_dir / t.key / "sounds" / "select.wav").exists() and "select" in t.sound_files
    themes.delete_user_theme(t.key)
    assert t.key not in themes.THEMES and not (theme_dir / t.key).exists()


def test_theme_file_validation(theme_dir, tmp_path):
    f = tmp_path / "square.json"
    f.write_text(json.dumps(themes.schema_example()), encoding="utf-8")
    t, warn = themes.install_theme(f)
    assert t.shape.outline == "square" and warn == []
    messy = dict(themes.schema_example(), name="Messy", shape={"outline": "star", "corner": 999, "wobble": 1},
                 light={"wheel": {"hoverOuter": "nope", "glass": "yes"}})
    f.write_text(json.dumps(messy), encoding="utf-8")
    t, warn = themes.install_theme(f)
    assert t.shape.corner == 60 and t.shape.outline == "circle"               # clamped / ignored
    assert len(warn) == 4 and any("wobble" in w for w in warn)
    for bad, msg in (({"name": ""}, "no name"), ({"format": "other", "name": "x"}, "Unknown format"), ([], "JSON object")):
        f.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(themes.ThemeError, match=msg):
            themes.install_theme(f)
    f.write_text("{ not json", encoding="utf-8")
    with pytest.raises(themes.ThemeError, match="Couldn't read"):
        themes.install_theme(f)


def test_save_customised_theme_and_reload(theme_dir):
    from dataclasses import replace
    baked = themes.bake(themes.SANTRA, {"colors": {"highlight": "#2563eb"}})
    t = themes.save_user_theme(replace(baked, key="blue-santra", name="Blue Santra"))
    themes.THEMES.pop(t.key)
    assert themes.load_user_themes() == []
    assert themes.THEMES["blue-santra"].dark.hover_out.name() == "#2563eb"


# ---------------------------------------------------------------- sounds
def test_every_pack_has_every_sound():
    for pack in sounds.PACK_KEYS[:-1]:
        for ev in sounds.EVENT_KEYS:
            x = sounds.synth(pack, ev)
            assert 0.02 < float(np.abs(x).max()) <= 0.2, (pack, ev)          # audible, never loud
            assert len(x) < sounds.RATE                                       # short


def test_santra_tick_shape():
    x = sounds.synth("santra", "highlight")
    assert abs(len(x) / sounds.RATE - 0.060) < 0.001
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / sounds.RATE)
    assert 7000 < (sp * f).sum() / sp.sum() < 10000                         # the original: ~8 kHz


def test_player_uses_custom_and_theme_sounds(tmp_path, monkeypatch):
    monkeypatch.setattr(sounds, "cache_dir", lambda: tmp_path / "cache")
    mine = sounds.write_wav(tmp_path / "mine.wav", sounds.synth("pop", "done"))
    themed = sounds.write_wav(tmp_path / "themed.wav", sounds.synth("glass", "open"))
    p = sounds.Player()
    p.configure(True, 50, "theme", {"error": False}, {"done": str(mine)}, {"open": str(themed)}, "arcade")
    assert p.files["done"] == str(mine) and p.files["open"] == str(themed)
    assert p.files["select"].endswith("arcade\\select.wav") or p.files["select"].endswith("arcade/select.wav")
    assert p.on["error"] is False and p.volume == 0.5
    p.play("highlight")
    p.play("error")                                                         # switched off: silent, no error


def test_import_any_audio_as_wav(tmp_path, monkeypatch):
    monkeypatch.setattr(sounds, "custom_dir", lambda: tmp_path / "custom")
    from shiftwheel.media import ffmpeg_exe
    mp3 = tmp_path / "ding.mp3"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=800:duration=5",
                    str(mp3)], check=True)
    out = sounds.import_sound(mp3, "done")
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == sounds.RATE
        assert w.getnframes() <= sounds.RATE * 3                            # trimmed to 3 s
    bad = tmp_path / "x.mp3"
    bad.write_text("not audio")
    from shiftwheel.util import UserError
    with pytest.raises(UserError):
        sounds.import_sound(bad, "error")


# ---------------------------------------------------------------- shortcuts
def test_hotkey_parsing():
    m, vk = hotkey.parse("Ctrl+Alt+Space")
    assert vk == 0x20 and m & hotkey.MOD_CONTROL and m & hotkey.MOD_ALT and m & hotkey.MOD_NOREPEAT
    assert hotkey.parse("Ctrl+Shift+K")[1] == ord("K")
    assert hotkey.parse("F8")[1] == 0x77                                   # F-keys alone are fine
    assert hotkey.parse("K") is None and hotkey.parse("") is None          # a bare letter would steal typing


def test_ui_tokens_stylesheet():
    from shiftwheel import glass
    look = themes.resolve("santra", {"mode": "light"})
    try:
        glass.set_ui(look.ui, look.dark)
        css = glass.qss()
        assert "#ff5200" in css and "rgba(255,255,255,0.13)" not in css      # tokens, not the glass look
        assert glass.ink().name() == look.ui.text.name() and glass.window_radius() == 18
    finally:
        glass.set_ui(None, True)


def test_same_key_goes_round_every_wheel():
    """Shift, Shift, Shift: Convert → Tools → Print (the key pressed last keeps cycling);
    a different key jumps to its own wheel."""
    from types import SimpleNamespace

    from shiftwheel.app import ShiftWheelApp
    m = radial.RadialMenu(lambda ps: {}, lambda ps: "")
    m.rings = {r: [radial.Item("A")] for r in ("Convert", "Tools", "Print", "Actions")}
    m.ring_names = list(m.rings)
    app = SimpleNamespace(menu=m, settings=SimpleNamespace(get=lambda k: True), _last_key_ring="Convert")
    seen = []
    for key_ring in ("Convert", "Convert", "Convert", "Tools", "Tools", "Convert"):
        ShiftWheelApp._switch_ring(app, key_ring)
        seen.append(m.ring_names[m.ring_idx])
    assert seen == ["Tools", "Print", "Actions", "Tools", "Print", "Convert"]
