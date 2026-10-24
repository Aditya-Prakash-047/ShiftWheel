"""About window: creator, links, what's new and credits."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from shiftwheel import __version__, aboutwin


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_about_window_has_every_page():
    w = aboutwin.AboutWindow(None, page=1)
    assert [b.text() for b in w.tab_buttons] == ["About", "What's new", "Credits"]
    assert w.stack.currentIndex() == 1 and w.tab_buttons[1].isChecked()
    assert __version__ in w.upd_status.text() and not w.upd_check.isEnabled()      # no controller here
    w.show_page(2)
    assert w.tab_buttons[2].isChecked()
    w.close()


def test_release_notes_are_bundled_and_read():
    notes = aboutwin.release_notes()
    assert notes.lstrip().startswith("-") and "Share" in notes


def test_links_are_https():
    for _, url in aboutwin.LINKS + aboutwin.APP_LINKS:
        assert url.startswith("https://")
    for name, what, lic, url in aboutwin.CREDITS:
        assert name and what and lic and url.startswith("https://")
