"""Settings Save / Cancel, any-key bindings, batch 'apply to all', and the share plumbing."""
from __future__ import annotations

import sys
import time

import pytest
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from shiftwheel import compresswin, imaging, keys, settings as S, tools


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path):
    return S.Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))


# ---------------------------------------------------------------- settings: save / cancel
def test_closing_without_save_puts_everything_back(store):
    store.set("ask_name", False)
    before_theme = store.get("theme")
    w = S.SettingsWindow(store)
    w.cards[list(S.themes.THEMES).index("ember")].click()
    w.ask.setChecked(True)
    w.key_boxes["key_tools"].setCurrentIndex(w.key_boxes["key_tools"].findData("f8"))
    assert store.get("theme") == "ember" and store.get("key_tools") == "f8"     # live preview
    assert w.dirty_label.isVisibleTo(w)
    w.close()                                                                  # no Save
    assert store.get("theme") == before_theme and store.get("ask_name") is False
    assert store.get("key_tools") == keys.defaults()["key_tools"]


def test_save_keeps_changes(store):
    w = S.SettingsWindow(store)
    w.ask.setChecked(True)
    w.save_btn.click()
    assert store.get("ask_name") is True
    w2 = S.SettingsWindow(store)
    w2.ask.setChecked(False)
    w2.cancel_btn.click()
    assert store.get("ask_name") is True


# ---------------------------------------------------------------- keys
def test_key_catalog():
    ids = [k for k, _ in keys.choices()]
    assert ids[0] == "none" and "shift" in ids and len(ids) == len(set(ids))
    if sys.platform == "win32":
        assert {"f1", "f24", "rctrl", "win", "xbutton1", "xbutton2", "mbutton"} <= set(ids)
        assert "fn" not in ids                                 # never reaches Windows
        assert keys.vk("f1") == 0x70 and keys.vk("f24") == 0x87 and keys.vk("vk:96") == 96
        assert keys.valid("vk:96") and not keys.valid("vk:1") and not keys.valid("vk:27") and not keys.valid("bogus")
        assert keys.label("f11") == "F11" and keys.label("vk:96")             # Num 0, by the layout
    assert keys.mac_down("fn", 1 << 23, lambda c: False, 0)
    assert keys.mac_down("cmd", 1 << 20, lambda c: False, 0) and not keys.mac_down("cmd", 1 << 18, lambda c: False, 0)
    assert keys.mac_down("f5", 0, lambda c: c == 96, 0) and keys.mac_down("xbutton1", 0, lambda c: False, 1 << 3)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows virtual keys")
def test_recorder_picks_the_key():
    pick = S.KeyRecorder._pick
    assert pick({0x10, 0xA0}) == "shift"                       # Shift also reports Left Shift
    assert pick({0x7A}) == "f11" and pick({0x05}) == "xbutton1" and pick({0x60}) == "vk:96"


def test_settings_reject_unknown_keys(store):
    store.q.setValue("key_print", "bogus")
    assert store.get("key_print") == "none"
    if sys.platform == "win32":
        store.q.setValue("key_print", "vk:96")
        assert store.get("key_print") == "vk:96"


def test_watcher_binds_recorded_and_f_keys():
    from shiftwheel.trigger import ShiftWheelWatcher
    w = ShiftWheelWatcher(lambda: False, lambda: False)
    w.set_bindings({"Convert": "shift", "Print": "vk:96", "Tools": "f8", "Actions": "none"})
    if sys.platform == "win32":
        assert w.bindings == {"Convert": ("shift", 0x10), "Print": ("vk:96", 96), "Tools": ("f8", 0x77)}


# ---------------------------------------------------------------- batch: apply to all
def _img(path, size, color):
    Image.new("RGB", size, color).save(path, quality=92)
    return path


def test_edit_applies_to_every_file(tmp_path):
    a = _img(tmp_path / "a.jpg", (800, 600), (200, 80, 40))
    b = _img(tmp_path / "b.jpg", (640, 900), (40, 80, 200))
    got = []
    w = tools.EditWindow([str(a), str(b)], lambda action, srcs, outs, extra="": got.append((srcs, outs)))
    assert w.all_files.isChecked() and "2 files" in w.subtitle.text()
    w.save()
    srcs, outs = got[0]
    assert len(srcs) == 2 and len(outs) == 2 and all(o.exists() for o in outs)


def test_edit_only_the_shown_file_when_unticked(tmp_path):
    a = _img(tmp_path / "a.jpg", (800, 600), (200, 80, 40))
    b = _img(tmp_path / "b.jpg", (640, 900), (40, 80, 200))
    got = []
    w = tools.EditWindow([str(a), str(b)], lambda action, srcs, outs, extra="": got.append(outs))
    w.all_files.setChecked(False)
    w.save()
    assert len(got[0]) == 1


def test_square_crop_on_images_of_different_sizes(tmp_path):
    a = _img(tmp_path / "a.jpg", (1200, 800), (200, 80, 40))
    b = _img(tmp_path / "b.jpg", (600, 1000), (40, 80, 200))
    got = []
    w = tools.CropWindow([str(a), str(b)], lambda action, srcs, outs, extra="": got.append(outs))
    w.view.set_ratio(1.0)
    w.apply()
    sizes = [Image.open(o).size for o in got[0]]
    assert sizes[0] == (800, 800) and sizes[1][0] == sizes[1][1] == 600


def test_metadata_cleans_every_file(tmp_path):
    a = _img(tmp_path / "a.jpg", (300, 200), (1, 2, 3))
    b = _img(tmp_path / "b.jpg", (300, 200), (4, 5, 6))
    got = []
    w = tools.MetadataWindow([str(a), str(b)], lambda action, srcs, outs, extra="": got.append(outs))
    w.strip()
    assert len(got[0]) == 2


def test_relative_box_keeps_ratio_inside_the_image():
    assert imaging.relative_box((1000, 500), (0.25, 0.0, 0.5, 1.0)) == (250, 0, 750, 500)
    x0, y0, x1, y1 = imaging.relative_box((400, 1000), (0.1, 0.1, 0.8, 0.5), ratio=16 / 9)
    assert 0 <= x0 < x1 <= 400 and 0 <= y0 < y1 <= 1000
    assert abs((x1 - x0) / (y1 - y0) - 16 / 9) < 0.02


# ---------------------------------------------------------------- compress levels window
def test_level_window_shows_estimates(tmp_path):
    folder = tmp_path / "Docs"
    folder.mkdir()
    (folder / "a.txt").write_text("hello world " * 20000, encoding="utf-8")
    got = []
    w = compresswin.archive_window([str(folder)], lambda action, srcs, outs, extra="": got.append(outs), "ZIP")
    end = time.time() + 20
    while time.time() < end and any(lab.text() == "calculating…" for lab in w.est_labels.values()):
        QApplication.processEvents()
        time.sleep(0.02)
    assert "smaller" in w.est_labels["normal"].text()
    assert w.est_labels["store"].text().endswith("no smaller")
    w.group.button(w.keys.index("maximum")).setChecked(True)
    w.save()
    assert got[0][0].suffix == ".zip" and got[0][0].stat().st_size < 5000


# ---------------------------------------------------------------- share
def test_share_interface_ids():
    from shiftwheel import winshare
    # known IIDs: IIterable<String>, IIterable<IStorageItem>
    assert str(winshare.pinterface("pinterface({faa585ea-6214-4217-afda-7f46de5869b3};string)")) == \
        "e2fcc7c1-3bfc-5a0b-b2b0-72e769d1cb7e"
    assert str(winshare.IID_IIterable_IStorageItem) == "bb8b8418-65d1-544b-b083-6d172f568c73"
