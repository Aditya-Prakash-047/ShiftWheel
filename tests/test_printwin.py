"""Print-ring windows open on real inputs, preview the right sheet, and save true-size PDFs."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from shiftwheel import printing as P
from shiftwheel import printwin as W
from shiftwheel.convert import convert, fitz


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class Sink:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a)


def saved(sink):
    assert sink.calls, "nothing was saved"
    return [p for p in sink.calls[-1][2]]


def test_id_card_window_front_back(card_photos):
    sink = Sink()
    w = W.IDCardWindow([str(p) for p in card_photos], sink)
    assert all(w.detected)
    w.refresh()
    assert len(w.pages) == 1 and w.pages[0].size == (2480, 3508)
    w.swap()
    assert w.order == [1, 0]
    w.save_pdf()
    out = saved(sink)[0]
    with fitz.open(out) as d:
        assert d.page_count == 1 and abs(d[0].rect.width / 72 * 25.4 - 210) < 0.5


def test_id_card_from_pdf_and_manual_corners(tmp_path, card_photos):
    pdf = convert(card_photos[0], "image", "PDF")[0]
    sink = Sink()
    w = W.IDCardWindow([str(pdf)], sink)
    im, _ = w.work[0]
    w.view.set_quad([[10, 10], [im.width - 10, 10], [im.width - 10, im.height - 10], [10, im.height - 10]])
    w.refresh()
    assert len(w.pages) == 1
    w.close()


def test_passport_window(portrait):
    sink = Sink()
    w = W.PassportWindow([str(portrait)], sink)
    s = w.view.sel
    assert abs(s.width() / s.height() - 35 / 45) < 0.02
    w.n.setValue(12)
    w.refresh()
    assert len(w.pages) == 1
    w.save_jpg()
    out = saved(sink)[0]
    assert out.suffix == ".jpg"


def test_scan_window_multi_page(doc_photo, tmp_path):
    import shutil
    second = tmp_path / "page2.jpg"
    shutil.copy(doc_photo, second)
    sink = Sink()
    w = W.ScanWindow([str(doc_photo), str(second)], sink)
    assert all(w.found)
    w.save_pdf()
    with fitz.open(saved(sink)[0]) as d:
        assert d.page_count == 2


def test_print_window_modes(portrait, card_photos):
    sink = Sink()
    w = W.PrintWindow([str(portrait), str(card_photos[0]), str(card_photos[1])], sink)
    w.per.setCurrentText("4")
    w.refresh()
    assert len(w.pages) == 1
    w.mode.button(1).click()
    w.refresh()
    w.save_pdf()
    assert saved(sink)[0].exists()


def test_print_window_pdf_actual_size(tmp_path, card_photos):
    pdf = P.save_pdf(P.id_sheet([P.rgb(P.Image.open(card_photos[0]))], "A4"), tmp_path / "s.pdf")
    w = W.PrintWindow([str(pdf)], Sink())
    w.refresh()
    assert w.mode.checkedId() == 2                   # PDFs default to Actual size
    assert w.pages[0].size == (2480, 3508)
