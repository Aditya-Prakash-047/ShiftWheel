"""Every control in Settings, in every theme: nothing breaks, every stored value stays valid,
and open windows take the new theme's colours at once (inputs and dropdowns included)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QSlider, QSpinBox

from shiftwheel import glass, radial, themes
from shiftwheel import settings as S

app = QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, monkeypatch):
    # never touch the real start-up entry or Explorer menu from a test
    monkeypatch.setattr(S, "set_autostart", lambda on: None)
    monkeypatch.setattr(S, "set_context_menu", lambda on: None)
    monkeypatch.setattr(S, "autostart_enabled", lambda: False)
    monkeypatch.setattr(S, "context_menu_enabled", lambda: False)
    store = S.Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    w = S.SettingsWindow(store)
    w.changed.connect(lambda: _follow(w, store))
    yield w, store
    w.close()
    glass.set_ui(None, True)
    glass.set_mode(True)


def _follow(w, store):
    """What the app does after every change (ShiftWheel.apply_look): new look, open windows restyled."""
    look = store.look()
    accent = look.accent if store.custom(store.get("theme")).get("accent") else None
    glass.set_mode(look.dark, accent)
    glass.set_ui(look.ui, look.dark)
    w.restyle()


def _all_valid(store):
    for key in S.DEFAULTS:
        store.get(key)                   # validated read: raises if a stored value is broken
    store.look()


def _exercise(w, store, widgets):
    for combo in [x for x in widgets if isinstance(x, QComboBox)]:
        if not combo.isEnabled():
            continue
        for i in range(combo.count()):
            if combo.itemData(i) == "custom":          # opens a colour or folder picker
                continue
            combo.setCurrentIndex(i)
            _all_valid(store)
    for box in [x for x in widgets if isinstance(x, QCheckBox) and x.isEnabled()]:
        box.toggle()
        box.toggle()
        _all_valid(store)
    for sl in [x for x in widgets if isinstance(x, (QSlider, QSpinBox)) and x.isEnabled()]:
        for v in (sl.minimum(), sl.maximum(), (sl.minimum() + sl.maximum()) // 2):
            sl.setValue(v)
        _all_valid(store)
    for edit in [x for x in widgets if isinstance(x, QLineEdit) and x.isEnabled() and not x.isReadOnly()]:
        if isinstance(edit.parent(), (QComboBox, QSpinBox)):
            continue
        edit.setText("Photoshop.exe, figma.exe")
        edit.editingFinished.emit()
        _all_valid(store)


def test_every_control_on_every_page(window):
    w, store = window
    for i in range(w.stack.count()):
        w.show_page(i)
        page = w.stack.widget(i)
        _exercise(w, store, page.findChildren(QComboBox) + page.findChildren(QCheckBox)
                  + page.findChildren(QSlider) + page.findChildren(QSpinBox) + page.findChildren(QLineEdit))
    w.close()                                                       # no Save: everything goes back
    assert store.get("theme") == themes.DEFAULT_THEME


@pytest.mark.parametrize("key", [t.key for t in themes.BUILTIN])
def test_customise_panel_in_each_theme(window, key):
    w, store = window
    w._pick_theme(key)
    _exercise(w, store, [w.mode, w.accent, w.outline, w.lift, w.opacity] + [s for s, _, _ in w.sliders.values()])
    assert w.outline.isEnabled()                    # every theme, Liquid glass included, has shapes


def test_switching_themes_restyles_open_controls(window):
    w, store = window
    for t in themes.BUILTIN:
        w._pick_theme(t.key)
        assert w.styleSheet() == glass.qss(), t.key        # inputs and dropdowns use this theme's colours
        ui = glass.tokens()
        for card in w.cards:
            accent = ui.accent.name() if ui is not None else themes.THEMES[card.key].accent.name()
            assert accent in card.styleSheet(), (t.key, card.key)


def _alpha_at(look, x, y):
    items = [radial.Item(s) for s in ("PNG", "JPG", "WEBP")]
    img = radial.render_preview(look, items, size=radial.SIZE).toImage()
    dpr = img.devicePixelRatio()
    return img.pixelColor(int(x * dpr), int(y * dpr)).alpha()


def test_liquid_glass_follows_the_chosen_shape():
    c = radial.SIZE / 2
    corner = QPointF(c + radial.R_OUT * 0.8, c - radial.R_OUT * 0.8)   # inside a square, outside a circle
    round_ = themes.resolve("glass", {"shape": {"outline": "circle"}})
    square = themes.resolve("glass", {"shape": {"outline": "square"}})
    assert _alpha_at(round_, corner.x(), corner.y()) == 0
    assert _alpha_at(square, corner.x(), corner.y()) > 0
    m = radial.RadialMenu(lambda ps: {}, lambda ps: "")
    m.set_look(square)
    m.rings = {"Convert": [radial.Item(s) for s in ("PNG", "JPG", "WEBP")]}
    m.ring_names, m.ring_idx = ["Convert"], 0
    assert m.hit(corner) == 0                                       # the corner is part of a slice
    m.deleteLater()


def test_opacity_is_a_customisation_of_every_theme():
    assert themes.resolve("glass").opacity == 0.65                 # frosted by default, like macOS
    assert themes.resolve("ember").opacity == 1.0
    assert themes.resolve("glass", {"opacity": 30}).opacity == 0.3
    assert themes.resolve("santra", {"opacity": 5}).opacity == 0.2      # never invisible
    assert themes.resolve("glass", {"opacity": "lots"}).opacity == 0.65
    data = themes.theme_to_dict(themes.THEMES["glass"], {"opacity": 40})
    assert data["opacity"] == 0.4 and themes.theme_from_dict(data).opacity == 0.4


def test_default_liquid_glass_hides_text_behind_it():
    """macOS-style frost: fine detail behind the glass (text) is blurred away, colour stays."""
    import numpy as np
    from PIL import Image

    from shiftwheel import liquid
    w = h = 160
    stripes = np.zeros((h, w, 3), np.uint8)
    for x in range(0, w, 8):
        stripes[:, x:x + 2] = 255                                   # 2-px strokes, like small text
    stripes[..., 0] = np.maximum(stripes[..., 0], 180)              # and a colour that should survive
    sdf = liquid.sdf_circle(w, h, w / 2, h / 2, 70)

    def detail(opacity):
        blur, tint = themes.frost(opacity)
        img, _ = liquid.render(Image.fromarray(stripes), sdf, liquid.GlassStyle(blur=blur, tint=tint))
        core = np.asarray(img, np.float32)[60:100, 60:100, 1]       # the middle, away from the rim
        return core.std(), np.asarray(img, np.float32)[60:100, 60:100, 0].mean()

    sharp, _ = detail(0.2)
    frosted, red = detail(0.65)
    assert frosted < 4 < sharp                                      # strokes gone at the default
    assert red > 100                                                # the colour behind still shows
