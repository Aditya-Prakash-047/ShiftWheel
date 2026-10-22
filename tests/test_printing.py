"""Print ring: physical sizes must be exact, card/document detection must work on real-looking
photos, and the Qt print path must not rescale anything."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from shiftwheel import printing as P
from shiftwheel.convert import open_image, fitz


def ink_bbox(page: Image.Image, thresh=245):
    a = np.asarray(page.convert("L")) < thresh
    ys, xs = np.where(a)
    return xs.min(), ys.min(), xs.max(), ys.max()


def blocks_y(page: Image.Image, thresh=245):
    """Vertical runs of rows containing ink (each card is one run)."""
    rows = (np.asarray(page.convert("L")) < thresh).any(axis=1)
    runs, start = [], None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        if not v and start is not None:
            runs.append((start, y - 1))
            start = None
    if start is not None:
        runs.append((start, len(rows) - 1))
    return runs


def px2mm(px):
    return px / P.DPI * 25.4


def test_card_detected_and_straightened(card_photos):
    for p in card_photos:
        img = open_image(p)
        q = P.find_card(img)
        assert q is not None, f"card not found in {p.name}"
        W, H = P.quad_size(q)
        assert 1.45 < W / H < 1.75   # ID-1 is 1.586
        flat = P.warp_quad(img, q)
        # straightened card: top band (orange header) must be horizontal → same row at both ends
        a = np.asarray(flat.resize((400, 252)))
        orange = (a[..., 0] > 160) & (a[..., 1] < 120) & (a[..., 2] < 80)
        cols_left, cols_right = orange[:, 40:60].any(axis=1), orange[:, 340:360].any(axis=1)
        yl, yr = np.where(cols_left)[0], np.where(cols_right)[0]
        assert len(yl) and len(yr)
        assert abs(int(yl.mean()) - int(yr.mean())) <= 6


def test_id_sheet_classic_layout_is_real_size(card_photos):
    cards = [P.warp_quad(open_image(p), P.find_card(open_image(p))) for p in card_photos]
    pages = P.id_sheet(cards, "A4")
    assert len(pages) == 1
    pg = pages[0]
    assert pg.size == (2480, 3508)                                # A4 @ 300 dpi
    runs = blocks_y(pg)
    assert len(runs) == 2                                         # front above back
    for y0, y1 in runs:
        assert abs(px2mm(y1 - y0 + 1) - 54.0) < 0.8               # card height incl. 2 px cut line
    x0, _, x1, _ = ink_bbox(pg)
    assert abs(px2mm(x1 - x0 + 1) - 85.6) < 0.8
    assert abs((x0 + x1) / 2 - pg.width / 2) < 3                  # centred
    assert runs[0][0] < P.mm(20)                                  # at the top of the page
    assert runs[1][1] < pg.height / 2                             # whole thing in the top half


def test_id_sheet_copies_and_bw(card_photos):
    cards = [open_image(p).resize((856, 540)) for p in card_photos]
    pages = P.id_sheet(cards, "A4", color="Photocopy (B&W)", copies=3)
    pg = pages[0]
    runs = blocks_y(pg)
    assert len(runs) == 3                                          # 3 rows of [front | back]
    a = np.asarray(pg)
    assert np.abs(a[..., 0].astype(int) - a[..., 2].astype(int)).max() <= 2   # no colour left


def test_portrait_card_stays_portrait():
    box = P.card_to_box(Image.new("RGB", (540, 856), "red"))
    assert box.size == (P.mm(54), P.mm(85.6))


def test_passport_sheet(portrait):
    pages = P.passport_sheet(open_image(portrait), (35, 45), copies=8)
    assert len(pages) == 1
    pg = pages[0]
    a = np.asarray(pg)
    blue = (a[..., 2] > 100) & (a[..., 0] < 80)          # the shirt in every copy
    rows = blue.any(axis=1)
    # count photo rows: 8 photos at 35 mm on A4 (5 per row) → 2 rows
    starts = np.flatnonzero(rows[1:] & ~rows[:-1])
    assert len(starts) == 2
    x0, y0, x1, y1 = ink_bbox(pg)
    assert abs(px2mm(y1 - y0 + 1) - (45 * 2 + 2.5)) < 1.2


def test_passport_on_4x6_paper(portrait):
    pages = P.passport_sheet(open_image(portrait), (35, 45), copies=6, paper="4×6 photo")
    assert pages[0].size == (P.mm(101.6), P.mm(152.4))
    assert len(pages) == 1


def test_document_scan(doc_photo):
    img = open_image(doc_photo)
    q = P.find_document(img)
    assert q is not None
    expected = np.float32([[260, 180], [1380, 240], [1450, 1860], [180, 1800]])  # from the fixture
    assert np.abs(q - expected).max() < 25
    page = P.scan_page(img, q, "A4", "Black & white")
    assert page.size == (2480, 3508)
    a = np.asarray(page.convert("L"))
    assert (a < 60).mean() > 0.05 and (a > 200).mean() > 0.6   # crisp text on white


def test_layout_fit_fill_actual_nup():
    land = Image.new("RGB", (3000, 2000), "blue")
    pages = P.layout_pages([land], P.PrintLayout(mode="fit"))
    assert pages[0].width > pages[0].height                     # auto landscape
    small = Image.new("RGB", (300, 300), "red")                 # 1 inch at 300 dpi
    pg = P.layout_pages([small], P.PrintLayout(mode="actual"), dpis=[300.0])[0]
    x0, y0, x1, y1 = ink_bbox(pg)
    assert abs(px2mm(x1 - x0 + 1) - 25.4) < 0.3
    pages = P.layout_pages([small] * 5, P.PrintLayout(per_page=4))
    assert len(pages) == 2


def test_save_pdf_keeps_paper_size(tmp_path, card_photos):
    pages = P.id_sheet([open_image(card_photos[0])], "Letter")
    out = P.save_pdf(pages, tmp_path / "x.pdf", "Grayscale")
    with fitz.open(out) as d:
        r = d[0].rect
        assert abs(r.width / 72 * 25.4 - 215.9) < 0.5 and abs(r.height / 72 * 25.4 - 279.4) < 0.5


def test_qt_print_path_is_unscaled(tmp_path, card_photos):
    """Printing goes through QPrinter; print to PDF and measure the card on the result."""
    pytest.importorskip("PySide6.QtPrintSupport")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    cards = [P.warp_quad(open_image(p), P.find_card(open_image(p))) for p in card_photos]
    pages = P.id_sheet(cards, "A4")
    out = tmp_path / "printed.pdf"
    P.print_pages(pages, pdf_file=str(out))
    with fitz.open(out) as d:
        page = d[0]
        assert abs(page.rect.width / 72 * 25.4 - 210) < 0.6 and abs(page.rect.height / 72 * 25.4 - 297) < 0.6
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    runs = blocks_y(img)
    assert len(runs) == 2
    for y0, y1 in runs:
        assert abs(px2mm(y1 - y0 + 1) - 54.0) < 1.0
