"""Santra's extra formats: EPUB, Markdown export, PDF → Excel / PowerPoint / Markdown / EPUB,
subtitles, SVG input, TAR / GZIP / RAR archives."""
from __future__ import annotations

import shutil
import subprocess
import tarfile
import zipfile

import pytest
from PIL import Image

from shiftwheel import archive, convert, docs
from shiftwheel.util import UserError, category


@pytest.fixture
def report_pdf(tmp_path):
    doc = convert.fitz.open()
    page = doc.new_page()
    page.insert_text((72, 80), "Quarterly Report", fontsize=26)
    page.insert_text((72, 130), "Sales grew in every region this quarter.", fontsize=11)
    y = 170
    for row in (("Region", "Units", "Price"), ("North", "12", "3.50"), ("South", "7", "4.25")):
        for k, cell in enumerate(row):
            page.insert_text((72 + k * 120, y), cell, fontsize=11)
        y += 22
    for k in range(4):
        page.draw_line((66, 156 + k * 22), (426, 156 + k * 22))
    for x in (66, 186, 306, 426):
        page.draw_line((x, 156), (x, 222))
    p = tmp_path / "report.pdf"
    doc.save(p)
    return p


def test_pdf_targets_follow_santra():
    assert convert.targets_for("pdf", ".pdf") == ["DOCX", "PPTX", "XLSX", "JPG", "PNG", "EPUB", "TXT", "MD"]


def test_pdf_to_markdown_xlsx_pptx_epub(report_pdf):
    md = convert.convert(report_pdf, "pdf", "MD")[0].read_text(encoding="utf-8")
    assert md.startswith("# Quarterly Report") and "Sales grew" in md
    from openpyxl import load_workbook
    ws = load_workbook(convert.convert(report_pdf, "pdf", "XLSX")[0]).active
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert ["North", 12, 3.5] in rows                                   # a real table, typed cells
    from pptx import Presentation
    prs = Presentation(convert.convert(report_pdf, "pdf", "PPTX")[0])
    assert len(prs.slides) == 1 and prs.slide_width / prs.slide_height == pytest.approx(595 / 842, rel=0.01)   # same shape as the page
    epub = convert.convert(report_pdf, "pdf", "EPUB")[0]
    with convert.fitz.open(epub) as d:
        assert "Sales grew" in d[0].get_text()


def test_pdf_to_pptx_tiny_and_huge_pages(tmp_path):
    from pptx import Presentation
    for name, size in (("tiny", (40, 30)), ("huge", (5000, 3000))):
        doc = convert.fitz.open()
        doc.new_page(width=size[0], height=size[1])
        p = tmp_path / f"{name}.pdf"
        doc.save(p)
        prs = Presentation(convert.convert(p, "pdf", "PPTX")[0])
        assert 914400 <= prs.slide_width <= 51206400 and 914400 <= prs.slide_height <= 51206400
        assert prs.slide_width / prs.slide_height == pytest.approx(size[0] / size[1], rel=0.02)


def test_epub_round_trip(tmp_path):
    md = tmp_path / "Book.md"
    md.write_text("# Chapter One\n\nIt was a **bright** day & cold.\n\n# Chapter Two\n\n- a\n- b\n", encoding="utf-8")
    assert "EPUB" in convert.targets_for("text", ".md")
    epub = convert.convert(md, "text", "EPUB")[0]
    with zipfile.ZipFile(epub) as z:
        assert z.namelist()[0] == "mimetype" and z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert {"OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml", "OEBPS/nav.xhtml"} <= set(z.namelist())
    assert category(epub) == "ebook"
    title, body = docs.epub_html(epub)
    assert title == "Chapter One" and "Chapter Two" in body
    back = convert.convert(epub, "ebook", "MD")[0].read_text(encoding="utf-8")
    assert "# Chapter One" in back and "**bright**" in back and "- b" in back
    with convert.fitz.open(convert.convert(epub, "ebook", "PDF")[0]) as d:
        assert "bright" in "".join(p.get_text() for p in d)
    from docx import Document
    doc = Document(convert.convert(epub, "ebook", "DOCX")[0])
    assert ("Heading 1", "Chapter Two") in [(p.style.name, p.text) for p in doc.paragraphs]


def test_word_to_markdown_and_html(tmp_path):
    from docx import Document
    d = Document()
    d.add_heading("Letter", 1)
    d.add_paragraph("Dear reader,")
    p = tmp_path / "letter.docx"
    d.save(p)
    md = convert.convert(p, "docx", "MD")[0].read_text(encoding="utf-8")
    assert md.startswith("# Letter") and "Dear reader," in md
    assert "<h1>Letter</h1>" in convert.convert(p, "docx", "HTML")[0].read_text(encoding="utf-8")


def test_subtitles(tmp_path):
    srt = tmp_path / "talk.srt"
    srt.write_text("1\n00:00:01,500 --> 00:00:03,000\nHello <i>there</i>\n\n2\n00:00:04,000 --> 00:00:06,250\n"
                   "Second line\nwraps\n", encoding="utf-8")
    assert category(srt) == "subtitle" and convert.targets_for("subtitle", ".srt") == ["VTT", "TXT"]
    vtt = convert.convert(srt, "subtitle", "VTT")[0]
    text = vtt.read_text(encoding="utf-8")
    assert text.startswith("WEBVTT") and "00:00:01.500 --> 00:00:03.000" in text
    back = convert.convert(vtt, "subtitle", "SRT")[0].read_text(encoding="utf-8")
    assert "2\n00:00:04,000 --> 00:00:06,250\nSecond line\nwraps" in back
    assert convert.convert(srt, "subtitle", "TXT")[0].read_text(encoding="utf-8") == "Hello <i>there</i>\nSecond line\nwraps\n"
    bad = tmp_path / "empty.srt"
    bad.write_text("nothing here", encoding="utf-8")
    with pytest.raises(UserError):
        convert.convert(bad, "subtitle", "VTT")


def test_svg_input(tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
                   '<rect x="10" y="10" width="80" height="80" fill="#ff5200"/></svg>', encoding="utf-8")
    assert category(svg) == "image" and "SVG" not in convert.targets_for("image", ".svg")
    png = convert.convert(svg, "image", "PNG")[0]
    with Image.open(png) as im:
        assert im.size[0] >= 2000 and im.mode == "RGBA"
        assert im.getpixel((im.width // 4, im.height // 2))[:3] == (255, 82, 0)
        assert im.getpixel((im.width - 5, 5))[3] == 0                  # transparent background


def test_tar_gzip_and_rar(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "a.txt").write_text("A")
    t = archive.zip_paths([d], "TAR")
    g = archive.zip_paths([d], "GZIP")
    assert t.name == "proj.tar" and g.name == "proj.tar.gz"
    with tarfile.open(g) as tf:
        assert tf.getnames() == ["proj/a.txt"]
    assert archive.kind(g) == "tgz" and archive.kind(t) == "tar"
    assert (archive.extract(g) / "a.txt").read_text() == "A"
    z = archive.convert_archive(t, "ZIP")
    assert z.suffix == ".zip" and zipfile.ZipFile(z).namelist() == ["a.txt"]
    winrar = shutil.which("rar")
    if winrar is None:
        pytest.skip("no RAR creator here to make a test file (extraction uses Windows' tar.exe)")
    subprocess.run([winrar, "a", str(tmp_path / "p.rar"), str(d / "a.txt")], check=True, capture_output=True)
    assert (archive.extract(tmp_path / "p.rar") / "a.txt").read_text() == "A"
