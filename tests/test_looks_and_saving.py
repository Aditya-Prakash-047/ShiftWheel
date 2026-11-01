"""Themes, light/dark, validated settings, where results are saved and how they are named."""
from __future__ import annotations


import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from shiftwheel import glass, radial, saveas, settings as S, themes
from shiftwheel.util import CONFIG, sibling


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    return S.Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))


@pytest.fixture(autouse=True)
def restore_config():
    saved = dict(CONFIG)
    yield
    CONFIG.clear()
    CONFIG.update(saved)


def test_every_theme_paints_in_both_modes_with_every_accent():
    items = [radial.Item(t) for t in ("PNG", "WEBP", "HEIC", "PDF")]
    for key in themes.THEMES:
        for mode in ("light", "dark"):
            for accent, _, _ in themes.ACCENTS:
                pal = themes.palette(key, mode, accent)
                assert pal.text.isValid() and pal.hover_out.isValid()
            img = radial.render_preview(themes.palette(key, mode), items, hover=1, size=120).toImage()
            painted = sum(img.pixelColor(x, y).alpha() > 0 for x in range(0, img.width(), 6)
                          for y in range(0, img.height(), 6))
            assert painted > 100, f"{key}/{mode} drew nothing"


def test_palette_choice_and_fallbacks(monkeypatch):
    assert themes.palette("ember", "dark").dark and not themes.palette("ember", "light").dark
    assert themes.palette("no-such-theme", "dark") == themes.THEMES[themes.DEFAULT_THEME].dark
    monkeypatch.setattr(themes, "system_is_dark", lambda: False)
    assert not themes.palette("ember", "system").dark
    pink = themes.palette("ember", "dark", "pink")
    assert pink.hover_out.name() == "#ec4899" and pink.arc.name() == "#ec4899"
    monkeypatch.setattr(themes, "windows_accent", lambda: None)            # no accent stored: theme colour
    assert themes.accent_color("santra", "windows") == themes.SANTRA.accent


def test_settings_validate_migrate_and_reset(tmp_path):
    q = QSettings(str(tmp_path / "old.ini"), QSettings.IniFormat)
    q.setValue("wheel_style", "santra")                                  # what 1.0 stored
    q.setValue("trigger", "ctrl")
    q.setValue("appearance", "dark")                                        # what 1.1 stored globally
    q.setValue("accent", "pink")
    q.setValue("output", "nonsense")
    q.setValue("wheel_size", "huge")
    q.setValue("pdf_dpi", 999)
    s = S.Settings(q)
    assert s.get("theme") == "santra" and s.get("key_convert") == "ctrl"
    assert s.custom("santra") == {"mode": "dark", "accent": "pink"} and not q.contains("appearance")
    assert s.get("output") == "next" and s.get("wheel_size") == 100 and s.get("pdf_dpi") == 200
    s.set("ask_name", True)
    s.set("welcomed", True)
    s.set("excluded_apps", "Photoshop.exe; figma.EXE , ")
    assert s.excluded_apps() == {"photoshop.exe", "figma.exe"}
    s.reset()
    assert s.get("ask_name") is False and s.get("theme") == themes.DEFAULT_THEME
    assert s.get("welcomed") is True                                        # no welcome window again


def test_output_folder_and_conflicts(tmp_path, store):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    (tmp_path / "a.png").write_bytes(b"old")
    store.apply()
    assert sibling(src, ext=".png").name == "a (1).png"                     # keep both
    store.set("on_conflict", "replace")
    assert sibling(src, ext=".png") == tmp_path / "a.png"                   # replace the older result…
    assert sibling(src).name == "a (1).jpg"                                 # …but never the original
    out = tmp_path / "Results"
    store.set("output_folder", str(out))
    store.set("output", "custom")
    assert sibling(src, ext=".png") == out / "a.png" and out.is_dir()
    store.set("output", "folder")
    assert sibling(src, ext=".png").parent == tmp_path / "ShiftWheel"


def test_clean_names_and_moving_results(tmp_path):
    assert saveas.clean_name('Invoice: "May"/2026. ') == "Invoice_ _May__2026"
    assert saveas.clean_name("con") == "con_"
    f = tmp_path / "Photo.png"
    f.write_bytes(b"png")
    new = saveas.move_result(f, tmp_path / "sub", "Holiday")
    assert new == tmp_path / "sub" / "Holiday.png" and new.read_bytes() == b"png" and not f.exists()


def test_save_as_window_renames_or_keeps(tmp_path):
    got = []
    f = tmp_path / "Scan.pdf"
    f.write_bytes(b"%PDF")
    w = saveas.SaveAsWindow(f, got.append)
    w.name.setText("Aadhaar copy")
    w.save()
    assert got == [tmp_path / "Aadhaar copy.pdf"] and (tmp_path / "Aadhaar copy.pdf").exists()
    g = tmp_path / "Other.pdf"
    g.write_bytes(b"%PDF")
    (tmp_path / "Taken.pdf").write_bytes(b"keep?")
    w = saveas.SaveAsWindow(g, got.append)
    w.name.setText("Taken")
    w.save()                                                                 # asks first…
    assert len(got) == 1 and "already exists" in w.warning.text()
    w.save()                                                                 # …replaces on a second Save
    assert got[-1] == tmp_path / "Taken.pdf" and (tmp_path / "Taken.pdf").read_bytes() == b"%PDF"
    h = tmp_path / "Keep.pdf"
    h.write_bytes(b"%PDF")
    w = saveas.SaveAsWindow(h, got.append)
    w.close()                                                                # Esc / Keep: unchanged
    assert got[-1] == h and h.exists()


def test_glass_light_mode_stylesheet():
    try:
        glass.set_mode(False, themes.hexa("#22C55E"))
        css = glass.qss()
        assert "color: #1d1a26;" in css and "#22c55e" in css.lower()
        assert glass.ink().red() < 60 and glass.surface_tint("solid").red() > 200
    finally:
        glass.set_mode(True)
    assert "color: #ffffff;" in glass.qss()


def test_settings_window_builds_and_saves(store):
    w = S.SettingsWindow(store)
    keys = list(themes.THEMES)
    card = w.cards[keys.index("ember")]
    card.click()
    assert store.get("theme") == "ember" and card.isChecked()
    w.mode.setCurrentIndex([k for k, _ in themes.MODES].index("light"))
    assert store.custom("ember") == {"mode": "light"}                       # per theme
    w._shape("outline", "square")
    assert store.look().shape.outline == "square"
    w._color("slices", themes.hexa("#123456"))
    assert store.custom("ember")["colors"] == {"slices": "#123456"}
    w.key_boxes["key_tools"].setCurrentIndex(w.key_boxes["key_tools"].findData("shift"))
    assert store.get("key_tools") == "shift" and store.get("key_convert") == "none"   # no duplicates
    w.ask.setChecked(True)
    assert store.get("ask_name") is True
    w.reset_btn.click()
    w.reset_btn.click()
    assert store.get("theme") == themes.DEFAULT_THEME and store.get("ask_name") is False
    assert store.custom("ember") == {} and store.get("key_convert") == "shift"
    w.close()


def test_foreground_exe_is_a_name():
    from shiftwheel.trigger import foreground_exe
    name = foreground_exe()
    assert isinstance(name, str) and "\\" not in name
