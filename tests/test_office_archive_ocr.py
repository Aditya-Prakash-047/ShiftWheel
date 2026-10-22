"""Spreadsheets/CSV, archives and OCR."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from shiftwheel import archive as A
from shiftwheel import office as O
from shiftwheel.convert import fitz
from shiftwheel.util import UserError


@pytest.fixture
def csv_file(tmp_path):
    p = tmp_path / "sales.csv"
    p.write_text("Region;Units;Price\nNorth;12;3.5\nSouth;7;4.25\nWest;0042;10\n", encoding="utf-8")
    return p


def test_csv_to_xlsx_types_and_back(csv_file):
    from openpyxl import load_workbook
    x = O.convert_sheet(csv_file, "XLSX")[0]
    ws = load_workbook(x).active
    assert ws["A1"].value == "Region" and ws["A1"].font.bold
    assert ws["B2"].value == 12 and ws["C3"].value == 4.25
    assert ws["B4"].value == "0042"                 # leading zeros kept as text (PIN codes, IDs)
    back = O.convert_sheet(x, "CSV")[0]
    assert back.read_text(encoding="utf-8-sig").splitlines()[1] == "North,12,3.5"


def test_sheet_to_json_html_pdf(csv_file):
    j = json.loads(O.convert_sheet(csv_file, "JSON")[0].read_text(encoding="utf-8"))
    assert j[0] == {"Region": "North", "Units": 12, "Price": 3.5}
    assert "<th>Region</th>" in O.convert_sheet(csv_file, "HTML")[0].read_text(encoding="utf-8")
    pdf = O.convert_sheet(csv_file, "PDF")[0]
    with fitz.open(pdf) as d:
        assert "South" in d[0].get_text()


def test_multi_sheet_xlsx_to_csv_and_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "find_soffice", lambda: None)      # the built-in renderer
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Jan"
    wb.active.append(["a", "b"])
    wb.active.append([1, 2])
    ws = wb.create_sheet("Feb")
    ws.append(["x"] * 10)                    # wide → landscape PDF
    ws.append(list(range(10)))
    p = tmp_path / "book.xlsx"
    wb.save(p)
    outs = O.convert_sheet(p, "CSV")
    assert sorted(o.name for o in outs) == ["book Feb.csv", "book Jan.csv"]
    pdf = O.convert_sheet(p, "PDF")[0]
    with fitz.open(pdf) as d:
        assert d[0].rect.width > d[0].rect.height


@pytest.mark.skipif(O.find_soffice() is None, reason="LibreOffice not installed")
def test_libreoffice_engine_xlsx_and_pptx(tmp_path):
    from openpyxl import Workbook
    from pptx import Presentation
    wb = Workbook()
    wb.active.append(["Budget", 2026])
    x = tmp_path / "budget.xlsx"
    wb.save(x)
    with fitz.open(O.convert_sheet(x, "PDF")[0]) as d:
        assert "Budget" in d[0].get_text()
    prs = Presentation()
    for title in ("First slide", "Second slide"):
        s = prs.slides.add_slide(prs.slide_layouts[0])
        s.shapes.title.text = title
    deck = tmp_path / "deck.pptx"
    prs.save(deck)
    pdf = O.convert_slides(deck, "PDF")[0]
    with fitz.open(pdf) as d:
        assert d.page_count == 2 and "Second slide" in d[1].get_text()
    pngs = O.convert_slides(deck, "PNG")
    assert len(pngs) == 2 and all(p.suffix == ".png" for p in pngs)
    assert not (tmp_path / "deck (1).pdf").exists()            # the temporary PDF was cleaned up


def test_slides_without_office_gives_clear_message(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "find_soffice", lambda: None)
    from pptx import Presentation
    p = tmp_path / "deck.pptx"
    Presentation().save(p)
    with pytest.raises(UserError, match="LibreOffice"):
        O.convert_slides(p, "PDF")


def test_rtf_to_txt_without_office(tmp_path, monkeypatch):
    monkeypatch.setattr(O, "find_soffice", lambda: None)
    p = tmp_path / "note.rtf"
    p.write_text(r"{\rtf1\ansi{\fonttbl\f0 Arial;}\f0 Hello \b world\b0\par Caf\'e9 time}", encoding="latin-1")
    out = O.convert_worddoc(p, "TXT")[0]
    assert out.read_text(encoding="utf-8") == "Hello world\nCafé time"
    assert O.rtf_to_text(r"{\rtf1{\*\generator Word;}{\colortbl;\red0;}A\tab B\uc1\u8364?5\line C}") == "A\tB€5\nC"


# ---------------------------------------------------------------- archives
def test_zip_and_extract_roundtrip(tmp_path):
    d = tmp_path / "proj"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("A")
    (d / "sub" / "b.txt").write_text("B")
    z = A.zip_paths([d])
    assert z.name == "proj.zip"
    with zipfile.ZipFile(z) as f:
        assert sorted(f.namelist()) == ["proj/a.txt", "proj/sub/b.txt"]
    out = A.extract(z)
    assert (out / "a.txt").read_text() == "A" and (out / "sub" / "b.txt").read_text() == "B"  # lifted, no proj/proj


def test_7z_tar_and_convert(tmp_path):
    f1 = tmp_path / "one.txt"
    f1.write_text("1")
    f2 = tmp_path / "two.txt"
    f2.write_text("2")
    s = A.zip_paths([f1, f2], "7Z")
    assert s.suffix == ".7z"
    ex = A.extract(s)
    assert (ex / "two.txt").read_text() == "2"
    import tarfile
    t = tmp_path / "pack.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        tf.add(f1, "one.txt")
    assert (A.extract(t) / "one.txt").read_text() == "1"
    z = A.convert_archive(t, "ZIP")
    assert z.name == "pack.zip" and zipfile.ZipFile(z).namelist() == ["one.txt"]


def test_zip_slip_is_blocked(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../outside.txt", "x")
    with pytest.raises(UserError, match="outside"):
        A.extract(evil)
    assert not (tmp_path.parent / "outside.txt").exists()
    assert not (tmp_path / "evil").exists()


def test_damaged_archive(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(b"PK\x03\x04 nope")
    with pytest.raises(UserError, match="damaged"):
        A.extract(p)


# ---------------------------------------------------------------- OCR
def _text_image(path: Path, lines):
    import glob
    fonts = glob.glob("/usr/share/fonts/**/DejaVuSans.ttf", recursive=True) + \
        glob.glob("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(fonts[0], 40) if fonts else ImageFont.load_default(size=40)
    im = Image.new("RGB", (1200, 80 + 90 * len(lines)), "white")
    d = ImageDraw.Draw(im)
    for i, t in enumerate(lines):
        d.text((40, 40 + i * 90), t, fill="black", font=font)
    im.save(path)
    return path


ocr = pytest.importorskip("shiftwheel.ocr")


@pytest.mark.skipif(not ocr.available(), reason="OCR not installed")
def test_ocr_image_to_text(tmp_path):
    p = _text_image(tmp_path / "invoice.png", ["Invoice No. 4471", "Total payable Rs 12,450.00"])
    out = ocr.image_to_txt(p)[0]
    text = out.read_text(encoding="utf-8")
    assert "Invoice No. 4471" in text and "12,450.00" in text
    assert text.index("Invoice") < text.index("Total")


@pytest.mark.skipif(not ocr.available(), reason="OCR not installed")
def test_searchable_pdf(tmp_path):
    p = _text_image(tmp_path / "scan.png", ["Quarterly report for ShiftWheel"])
    out = ocr.images_to_searchable_pdf([p])
    with fitz.open(out) as d:
        assert "Quarterly report" in d[0].get_text()
        assert d[0].search_for("ShiftWheel")              # searchable, and positioned on the word


def test_ocr_no_text(tmp_path):
    if not ocr.available():
        pytest.skip("OCR not installed")
    p = tmp_path / "blank.png"
    Image.new("RGB", (400, 300), "white").save(p)
    with pytest.raises(UserError):
        ocr.image_to_txt(p)
