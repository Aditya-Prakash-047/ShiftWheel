"""When the wheel may open, staying out of the way, asking before many files, and the update
hand-over really starting."""
from __future__ import annotations

import subprocess
import sys

import pytest
from PySide6.QtCore import QObject, QPoint, QSettings
from PySide6.QtWidgets import QApplication

import shiftwheel.trigger as T
from shiftwheel import aboutwin, imaging, settings as S, updater
from shiftwheel.confirmwin import ConfirmManyWindow


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def watcher(monkeypatch):
    monkeypatch.setattr(T, "foreground_exe", lambda: "explorer.exe")
    monkeypatch.setattr(T, "drag_image_visible", lambda: True)
    w = T.ShiftWheelWatcher(lambda: False, lambda: False)
    w.set_bindings({"Convert": "shift"}, {"shift": 0x10})
    w.shown = []
    w.show_menu.connect(lambda pos, ring: w.shown.append(ring))
    return w


def play(w, monkeypatch, *steps):
    """steps: (button down, Shift down, x). Runs them through the real decision code."""
    for down, key, x in steps:
        w._state = lambda down=down, key=key: (down, False, {"Convert": (key, False)})
        monkeypatch.setattr(T, "QCursor", type("C", (), {"pos": staticmethod(lambda x=x: QPoint(x, 0))}))
        w._tick()


def test_drag_then_shift_opens(watcher, monkeypatch):
    play(watcher, monkeypatch, (True, False, 0), (True, False, 50), (True, True, 50))
    assert watcher.shown == ["Convert"]


def test_shift_then_drag_does_not_open(watcher, monkeypatch):
    play(watcher, monkeypatch, (False, True, 0), (True, True, 0), (True, True, 50), (True, True, 90))
    assert watcher.shown == []


def test_shift_released_and_pressed_again_during_the_drag_opens(watcher, monkeypatch):
    play(watcher, monkeypatch, (True, True, 0), (True, True, 50), (True, False, 60), (True, True, 70))
    assert watcher.shown == ["Convert"]


def test_stale_tap_from_before_the_press_is_ignored(watcher, monkeypatch):
    watcher._state = lambda: (True, False, {"Convert": (False, True)})     # key-state bit from earlier
    monkeypatch.setattr(T, "QCursor", type("C", (), {"pos": staticmethod(lambda: QPoint(0, 0))}))
    watcher._tick()
    play(watcher, monkeypatch, (True, False, 50))
    assert watcher.shown == []


def test_selecting_with_a_rubber_band_is_not_a_file_drag(watcher, monkeypatch):
    monkeypatch.setattr(T, "drag_image_visible", lambda: False)
    play(watcher, monkeypatch, (True, False, 0), (True, False, 50), (True, True, 50), (True, True, 80))
    assert watcher.shown == []


def test_other_apps_are_left_alone(watcher, monkeypatch):
    monkeypatch.setattr(T, "foreground_exe", lambda: "chrome.exe")
    play(watcher, monkeypatch, (True, False, 0), (True, False, 50), (True, True, 50))
    assert watcher.shown == []
    watcher.only_in = None                        # "In every app, except…"
    watcher._reset()
    play(watcher, monkeypatch, (True, False, 0), (True, False, 50), (True, True, 50))
    assert watcher.shown == ["Convert"]
    watcher.shown.clear()
    watcher.excluded = {"chrome.exe"}
    watcher._reset()
    play(watcher, monkeypatch, (True, False, 0), (True, False, 50), (True, True, 50))
    assert watcher.shown == []


def test_idle_polling_reads_no_keys_and_slows_down_for_games(watcher, monkeypatch):
    watcher._left_down = lambda: False
    watcher._state = lambda: pytest.fail("keys read with the button up")
    monkeypatch.setattr(T, "game_or_fullscreen", lambda: True)
    monkeypatch.setattr(T, "foreground_exe", lambda: "game.exe")
    for _ in range(T.BUSY_EVERY + 1):
        watcher._poll()
    assert watcher._busy and watcher.timer.interval() == T.BUSY_MS
    watcher._left_down = lambda: True             # firing in a game: still no key reads
    watcher._poll()
    assert watcher.timer.interval() == T.BUSY_MS


# ---------------------------------------------------------------- updates
@pytest.mark.skipif(sys.platform != "win32", reason="Windows hand-over")
def test_finish_script_really_runs_with_the_apps_launch_flags(tmp_path):
    """Regression: DETACHED_PROCESS made cmd.exe exit at once, so no update ever installed."""
    marker = tmp_path / "installed.txt"
    setup = tmp_path / "fake-setup.cmd"
    setup.write_text(f'@echo ran>"{marker}"\r\n', encoding="ascii", newline="")
    dl = tmp_path / "ShiftWheel-Setup.exe"
    dl.write_bytes(b"")
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    script, cmd = updater.install_script("installed", dl, app.pid, tmp_path / "missing.exe")
    text = script.read_text(encoding="utf-8").replace(f'"{dl}"', f'call "{setup}"')
    script.write_text(text, encoding="utf-8", newline="")
    p = subprocess.Popen(cmd, creationflags=updater.LAUNCH_FLAGS, close_fds=True, cwd=str(tmp_path))
    p.wait(timeout=30)
    app.wait()
    assert marker.exists()


def test_a_verified_download_is_reused(tmp_path):
    import hashlib
    data = b"installer"
    f = tmp_path / "ShiftWheel-Setup.exe"
    f.write_bytes(data)
    good = updater.Asset(f.name, "http://127.0.0.1:9/never", len(data), hashlib.sha256(data).hexdigest())
    assert updater.download(good, tmp_path) == f              # no network touched
    with pytest.raises(updater.UserError):
        updater.download(updater.Asset(f.name, "http://127.0.0.1:9/never", len(data), "0" * 64), tmp_path)


class _App(QObject):
    def __init__(self, tmp_path):
        super().__init__()
        self.settings = S.Settings(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
        self.cards = []
        self.toasts = type("T", (), {"prompt": lambda _s, title, *a, **k: self.cards.append(title),
                                     "info": lambda *a, **k: None, "error": lambda *a, **k: None})()
        self.watcher = type("W", (), {"busy": False, "is_busy": lambda s: s.busy})()


def test_an_update_is_offered_once_and_never_over_a_game(tmp_path):
    from shiftwheel.updatectl import UpdateController
    app = _App(tmp_path)
    c = UpdateController(app)
    rel = updater.Release("9.0.0")
    app.watcher.busy = True
    c._maybe_offer(rel)
    assert app.cards == []                                    # held back
    app.watcher.busy = False
    c._maybe_offer(rel)
    c._maybe_offer(rel)
    assert len(app.cards) == 1                                # once per version
    c._maybe_offer(updater.Release("9.1.0"))
    assert len(app.cards) == 2


def test_a_failed_update_is_reported_after_the_restart(tmp_path, monkeypatch):
    from shiftwheel import updatectl
    app = _App(tmp_path)
    app.settings.set("update_attempt", "9.0.0")
    monkeypatch.setattr(updatectl.QTimer, "singleShot", lambda _ms, fn: fn())
    updatectl.UpdateController(app)._after_update()
    assert "didn't install" in app.cards[0] and app.settings.get("update_attempt") == ""


# ---------------------------------------------------------------- many files
def test_confirm_says_how_many_and_lets_you_make_fewer():
    got = []
    w = ConfirmManyWindow("Split", 1111, "Split makes one PDF per page.", "Saved in C:\\x.", got.append, pages=1111)
    assert "1,111 files" in w.head.text() and "1,111" in w.yes.text()
    w.every.setValue(100)
    assert w.files() == 12 and "12 files" in w.head.text()
    w.yes.click()
    assert got == [100]


def test_split_every_n_pages_goes_in_a_folder_when_many(tmp_path):
    doc = imaging.fitz.open()
    for _ in range(25):
        doc.new_page()
    src = tmp_path / "Big.pdf"
    doc.save(src)
    doc.close()
    assert len(imaging.split_pdf(src, every=10)) == 3
    outs = imaging.split_pdf(src)
    assert len(outs) == 25 and {o.parent.name for o in outs} == {"Big pages"}


def test_app_counts_files_before_a_split(tmp_path):
    from shiftwheel.app import ShiftWheelApp
    doc = imaging.fitz.open()
    for _ in range(12):
        doc.new_page()
    src = tmp_path / "Big.pdf"
    doc.save(src)
    doc.close()
    n, why, pages = ShiftWheelApp._expected_files(None, "tool", "Split", "pdf", [str(src)])
    assert n == 12 and pages == 12 and "12 pages" in why
    n, *_ = ShiftWheelApp._expected_files(None, "convert", "JPG", "pdf", [str(src)])
    assert n == 12
    assert S.DEFAULTS["confirm_files"] == 10


# ---------------------------------------------------------------- about
def test_about_has_licence_privacy_and_a_useful_report_link():
    w = aboutwin.AboutWindow(None, 3)
    assert w.tab_buttons[3].text() == "Licence" and "MIT" in aboutwin.licence_text()
    assert "Aditya Prakash" in aboutwin.licence_text()
    url = aboutwin.report_url()
    assert url.startswith("https://") and "ShiftWheel" in url and "/issues/new?" in url
    w.close()
