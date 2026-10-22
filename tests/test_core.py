"""Run with: python -m pytest -q"""
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from shiftwheel import convert, imaging
from shiftwheel.util import category, sibling


@pytest.fixture
def img(tmp_path) -> Path:
    im = Image.new("RGBA", (640, 420), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((40, 40, 600, 380), fill=(255, 120, 80, 255))
    d.text((60, 60), "ShiftWheel test", fill=(0, 0, 0, 255))
    p = tmp_path / "Page 001.png"
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    im.save(p, exif=exif)
    return p


@pytest.fixture
def pdf(tmp_path, img) -> Path:
    doc = convert.fitz.open()
    for i in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), f"Hello page {i + 1}", fontsize=24)
        page.insert_text((72, 120), "Body text line for extraction.", fontsize=11)
        page.insert_image(convert.fitz.Rect(72, 150, 300, 300), filename=str(img))
    doc.set_metadata({"author": "Jimmy", "title": "Demo"})
    p = tmp_path / "Doc.pdf"
    doc.save(p)
    return p


@pytest.mark.parametrize("target", convert.targets_for("image", ".png"))
def test_image_targets(img, target):
    out = convert.convert(img, "image", target)[0]
    assert out.exists() and out.stat().st_size > 0
    if target != "PDF":
        Image.open(out).load()


def test_pdf_conversions(pdf):
    imgs = convert.convert(pdf, "pdf", "JPG")
    assert len(imgs) == 2 and all(p.exists() for p in imgs)
    txt = convert.convert(pdf, "pdf", "TXT")[0]
    assert "Hello page 2" in txt.read_text()
    docx = convert.convert(pdf, "pdf", "DOCX")[0]
    from docx import Document
    d = Document(docx)
    assert any("Hello page 1" in p.text for p in d.paragraphs)
    assert d.inline_shapes, "images should be carried over"


def test_docx_and_text(tmp_path, pdf):
    docx = convert.convert(pdf, "pdf", "DOCX")[0]
    out_pdf = convert.convert(docx, "docx", "PDF")[0]
    with convert.fitz.open(out_pdf) as d:
        assert "Hello page 1" in d[0].get_text()
    assert "Hello" in convert.convert(docx, "docx", "TXT")[0].read_text()
    t = tmp_path / "notes.txt"
    t.write_text("line one\nline two <b>not bold</b>\n" * 80)
    tp = convert.convert(t, "text", "PDF")[0]
    with convert.fitz.open(tp) as d:
        assert d.page_count >= 2 and "<b>not bold</b>" in d[0].get_text()
    assert convert.convert(t, "text", "DOCX")[0].exists()


def test_tools(img, pdf):
    im = convert.open_image(img)
    assert imaging.save_like(im.crop((0, 0, 100, 100)), img, "Cropped").name == "Page 001 Cropped.png"
    bg = imaging.add_background(im, imaging.Background(aspect="16:9"))
    assert abs(bg.width / bg.height - 16 / 9) < 0.01
    red = imaging.redact(im, [(40, 40, 200, 200)], "black")
    assert red.getpixel((100, 100))[:3] == (0, 0, 0)
    for m in ("pixelate", "blur"):
        imaging.redact(im, [(40, 40, 200, 200)], m)
    ed = imaging.apply_adjust(im, imaging.Adjust(brightness=1.2, rotate=90, flip_h=True, warmth=0.5, resize_pct=50))
    assert ed.size == (210, 320)
    assert "Make" in imaging.read_image_metadata(img)
    clean = imaging.strip_image_metadata(img)
    assert "Make" not in imaging.read_image_metadata(clean)
    c = imaging.compress_image(img, 60)
    assert c.exists()
    assert imaging.compress_image(img, 60, 300, to_webp=True).suffix == ".webp"
    assert imaging.read_pdf_metadata(pdf)["author"] == "Jimmy"
    assert "author" not in imaging.read_pdf_metadata(imaging.strip_pdf_metadata(pdf))
    assert len(imaging.split_pdf(pdf)) == 2
    assert imaging.compress_pdf(pdf).exists()
    assert imaging.rotate_pdf(pdf).exists()
    assert imaging.merge_pdfs([pdf, pdf]).exists()
    assert convert.images_to_single_pdf([img, img])[0].exists()


def test_paths(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"x")
    assert sibling(f, ext=".jpg").name == "a (1).jpg"
    assert category("x.HEIC") == "image" and category("x.pdf") == "pdf" and category("x.zip") == "archive" \
        and category("x.unknownext") is None and category("x.csv") == "sheet" and category("x.mkv") == "video"


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows shortcuts")
def test_shortcut_resolves_to_target(img, tmp_path):
    import win32com.client
    from shiftwheel.util import resolve_shortcuts
    lnk = tmp_path / "pic.lnk"
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(lnk))
    sc.TargetPath = str(img)
    sc.Save()
    out = resolve_shortcuts([str(lnk)])
    assert Path(out[0]) == img and category(out[0]) == "image"
    assert resolve_shortcuts([str(img)]) == [str(img)]


def test_shift_tap_switches_ring_even_when_missed_or_early():
    from PySide6.QtWidgets import QApplication
    from shiftwheel.trigger import TAP_GRACE, ShiftWheelWatcher
    QApplication.instance() or QApplication([])
    state = {"visible": True, "got_drag": False}
    w = ShiftWheelWatcher(lambda: state["visible"], lambda: state["got_drag"])
    flips = []
    w.toggle_ring.connect(lambda: flips.append(1))
    feed = iter([])
    w._state = lambda: next(feed)
    w._shift_was = True                                  # Shift still held from opening the menu

    def run(*states):
        nonlocal feed
        feed = iter(states)
        for _ in states:
            w._tick()

    held, up = (True, True, False, False), (True, False, False, False)
    run(held, held, up)                                  # releasing Shift is not a tap
    assert flips == []
    run(up, (True, False, False, True))                  # a whole tap between two polls
    assert flips == []                                   # drag not on the menu yet: kept…
    state["got_drag"] = True
    run(up)
    assert flips == [1]                                  # …and applied once it arrives
    run((True, True, False, True), held, held, up)       # an ordinary press; auto-repeat ignored
    assert flips == [1, 1]
    state["got_drag"] = False
    run((True, True, False, False), *[up] * (TAP_GRACE + 2))
    state["got_drag"] = True
    run(up)
    assert flips == [1, 1]                               # a stale tap expires


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows registry")
def test_right_click_menu_toggle(monkeypatch):
    import winreg
    from shiftwheel import settings as S
    base = r"Software\ShiftWheelTest"
    monkeypatch.setattr(S, "MENU_KEYS", (base + r"\file\ShiftWheel", base + r"\dir\ShiftWheel"))
    try:
        S.set_context_menu(True)
        assert S.context_menu_enabled()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base + r"\dir\ShiftWheel\command") as k:
            assert winreg.QueryValueEx(k, "")[0].endswith('"%1"')
        S.set_context_menu(False)
        assert not S.context_menu_enabled()
    finally:
        for sub in (r"\file\ShiftWheel\command", r"\file\ShiftWheel", r"\file", r"\dir\ShiftWheel\command",
                    r"\dir\ShiftWheel", r"\dir", ""):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + sub)
            except OSError:
                pass


def test_markdown_and_html_render_instead_of_printing_source(tmp_path):
    md = tmp_path / "README.md"
    md.write_text("# Title\n\nSome **bold** text.\n\n- one\n- two\n", encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<html><head><title>T</title><style>p{color:red}</style></head>"
                    "<body><h1>Hello</h1><p>World <b>wide</b></p><script>x=1</script></body></html>",
                    encoding="utf-8")
    assert convert.targets_for("text", ".md") == ["PDF", "DOCX", "HTML"]
    assert convert.targets_for("text", ".html") == ["PDF", "DOCX", "TXT"]
    with convert.fitz.open(convert.convert(md, "text", "PDF")[0]) as d:
        text = d[0].get_text()
    assert "Title" in text and "bold" in text and "#" not in text and "**" not in text
    with convert.fitz.open(convert.convert(page, "text", "PDF")[0]) as d:
        text = d[0].get_text()
    assert "Hello" in text and "<h1>" not in text and "color:red" not in text
    assert "<h1>Title</h1>" in convert.convert(md, "text", "HTML")[0].read_text(encoding="utf-8")
    txt = convert.convert(page, "text", "TXT")[0].read_text(encoding="utf-8")
    assert "Hello" in txt and "World wide" in txt and "x=1" not in txt and "<" not in txt
    from docx import Document
    doc = Document(convert.convert(md, "text", "DOCX")[0])
    paras = [(p.style.name, p.text) for p in doc.paragraphs]
    assert ("Heading 1", "Title") in paras and ("List Bullet", "two") in paras
    assert any(r.bold and r.text.strip() == "bold" for p in doc.paragraphs for r in p.runs)


def test_file_ring_actions(tmp_path):
    import hashlib
    from shiftwheel import fileops
    from shiftwheel.app import ShiftWheelApp
    f = tmp_path / "Report.pdf"
    f.write_bytes(b"%PDF-1.4 hello")
    folder = tmp_path / "Project"
    (folder / "sub").mkdir(parents=True)
    (folder / "sub" / "a.txt").write_text("a")
    assert fileops.duplicate(f).name == "Report Copy.pdf"
    assert fileops.duplicate(f).name == "Report Copy (1).pdf" or fileops.duplicate(f).exists()
    d = fileops.duplicate(folder)
    assert d.name == "Project Copy" and (d / "sub" / "a.txt").read_text() == "a"
    [(p, digest)] = fileops.sha256([f, folder])
    assert p == f and digest == hashlib.sha256(b"%PDF-1.4 hello").hexdigest()
    for paths in ([str(f)], [str(folder)], [str(f), str(folder)]):
        rings = ShiftWheelApp.build_rings(None, paths)
        assert list(rings)[-1] == "File"
        assert [i.label for i in rings["File"]] == ["Copy path", "Show", "SHA-256", "Duplicate"]
