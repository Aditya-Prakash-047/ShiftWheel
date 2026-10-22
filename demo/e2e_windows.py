"""End-to-end test on a real Windows desktop.

Every scenario: real mouse drag of a file (from File Explorer or the Desktop) → press Shift →
drop on a slice → (drive the tool window) → verify the output file on disk.
Writes e2e_out/results.json, results.md, log.txt, screenshots and a screen recording."""
from __future__ import annotations

import json
import shutil
import time
import traceback
from pathlib import Path

import pyautogui
from PIL import Image, ImageDraw

import winkit as wk
import shiftwheel.convert  # noqa: F401  (registers HEIC/AVIF support for the verifiers)

OUT = wk.ROOT / "e2e_out"
OUT.mkdir(exist_ok=True)
(OUT / "shots").mkdir(exist_ok=True)
EXP = Path(r"C:\ShiftWheelTest")
DESK = wk.desktop_dir()
STASH = Path(r"C:\ShiftWheelTest_outputs")
RESULTS: list[dict] = []


# ------------------------------------------------------------------ sample files
def make_photo(path: Path, size=(2400, 1600), gps=True):
    import random
    random.seed(3)
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    for y in range(size[1]):
        t = y / size[1]
        d.line([(0, y), (size[0], y)], fill=(int(255 - 120 * t), int(170 - 90 * t), int(90 + 110 * t)))
    for _ in range(250):
        x, y = random.randrange(size[0]), random.randrange(size[1])
        r = random.randrange(10, 90)
        d.ellipse((x, y, x + r, y + r), fill=tuple(random.randrange(256) for _ in range(3)))
    ex = Image.Exif()
    ex[0x010F] = "Apple"
    ex[0x0110] = "iPhone 15 Pro"
    if gps:
        ex[0x8825] = {1: "N", 2: (24.0, 33.0, 18.0), 3: "W", 4: (81.0, 47.0, 0.0)}
    im.save(path, quality=95, exif=ex)


def make_pdf(path: Path, img: Path, pages=3, title="Report"):
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        pg = doc.new_page()
        pg.insert_text((72, 80), f"{title} — page {i + 1}", fontsize=22)
        for j in range(12):
            pg.insert_text((72, 120 + j * 18), "Lorem ipsum dolor sit amet, consectetur adipiscing.", fontsize=11)
        pg.insert_image(pymupdf.Rect(72, 360, 420, 600), filename=str(img))
    doc.set_metadata({"author": "Jimmy", "title": title})
    doc.save(path)


def make_files(folder: Path, prefix=""):
    folder.mkdir(exist_ok=True)
    make_photo(folder / f"{prefix}Photo.jpg")
    make_photo(folder / f"{prefix}Second.jpg", size=(1200, 900), gps=False)
    Image.open(folder / f"{prefix}Photo.jpg").resize((800, 533)).save(folder / f"{prefix}Graphic.png")
    make_pdf(folder / f"{prefix}Report.pdf", folder / f"{prefix}Second.jpg")
    make_pdf(folder / f"{prefix}Appendix.pdf", folder / f"{prefix}Second.jpg", pages=2, title="Appendix")
    from docx import Document
    d = Document()
    d.add_heading("Letter", 1)
    d.add_paragraph("Hello from the ShiftWheel end-to-end test.")
    d.save(folder / f"{prefix}Letter.docx")
    (folder / f"{prefix}Notes.txt").write_text("Shopping list\n- coffee\n- limes\n", encoding="utf-8")
    make_extras(folder, prefix)


def _card_photo(path: Path, label: str, color, angle: float):
    """An ID card photographed at an angle, with perspective, on a wooden table."""
    import numpy as np
    import cv2
    card = Image.new("RGB", (1712, 1080), color)
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([0, 0, 1711, 1079], radius=60, outline=(40, 40, 40), width=6)
    d.rectangle([60, 60, 1652, 200], fill=(200, 80, 30))
    d.rectangle([80, 280, 480, 780], fill=(120, 120, 160))
    for i in range(6):
        d.rectangle([560, 300 + i * 90, 1500, 340 + i * 90], fill=(60, 60, 60))
    src = np.array(card)
    bg = np.full((1500, 2000, 3), (92, 70, 55), np.uint8)
    cx, cy, rad = 1000, 750, np.deg2rad(angle)
    pts = [[cx + (x * np.cos(rad) - y * np.sin(rad)) * k, cy + (x * np.sin(rad) + y * np.cos(rad)) * k]
           for (x, y), k in zip([(-650, -410), (650, -410), (650, 410), (-650, 410)], [1, 0.92, 0.95, 1.04])]
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [1712, 0], [1712, 1080], [0, 1080]]), np.float32(pts))
    warped = cv2.warpPerspective(src, M, (2000, 1500))
    mask = cv2.warpPerspective(np.full((1080, 1712), 255, np.uint8), M, (2000, 1500))
    bg[mask > 0] = warped[mask > 0]
    Image.fromarray(bg).save(path, quality=92)


def make_extras(folder: Path, prefix=""):
    import subprocess
    import imageio_ffmpeg
    _card_photo(folder / f"{prefix}IDFront.jpg", "FRONT", (235, 240, 250), 12)
    _card_photo(folder / f"{prefix}IDBack.jpg", "BACK", (250, 245, 230), -8)
    im = Image.new("RGB", (1400, 520), "white")
    d = ImageDraw.Draw(im)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 54)
    except Exception:
        font = None
    for i, line in enumerate(["CITY SUPERMARKET", "Basmati rice 5kg   612.00", "TOTAL   1,284.50"]):
        d.text((60, 60 + i * 150), line, fill="black", font=font)
    im.save(folder / f"{prefix}Receipt.png")
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=25:duration=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(folder / f"{prefix}Clip.mp4")], check=True)
    subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=330:duration=5", str(folder / f"{prefix}Tone.wav")], check=True)
    (folder / f"{prefix}Sales.csv").write_text("Region,Units\nNorth,12\nSouth,7\n", encoding="utf-8")
    proj = folder / f"{prefix}Project"
    proj.mkdir(exist_ok=True)
    (proj / "readme.txt").write_text("project files", encoding="utf-8")


def snapshot(folder: Path) -> set[str]:
    return {str(p.relative_to(folder)) for p in folder.rglob("*")}


def new_files(folder: Path, before: set[str], timeout=15) -> list[Path]:
    """New files (ignoring in-progress '.~*.part'), once their sizes stop changing."""
    end = time.time() + timeout

    def current():
        now = snapshot(folder) - before
        return {n: (folder / n).stat().st_size for n in now
                if (folder / n).is_file() and not Path(n).name.startswith(".~")}
    while time.time() < end:
        a = current()
        if a:
            time.sleep(0.8)
            b = current()
            if a == b:
                return sorted(folder / n for n in b)
        time.sleep(0.25)
    return []


def stash(folder: Path, before: set[str]):
    """Move outputs out of the way so the folder only holds the sources again."""
    STASH.mkdir(exist_ok=True)
    for n in sorted(snapshot(folder) - before, key=len, reverse=True):
        p = folder / n
        try:
            if p.is_file():
                dest = STASH / f"{int(time.time() * 1000)}_{p.name}"
                shutil.move(str(p), dest)
            elif p.is_dir():
                p.rmdir()
        except Exception:
            pass


SOURCES = ["Photo.jpg", "Second.jpg", "Graphic.png", "Report.pdf", "Appendix.pdf", "Letter.docx", "Notes.txt",
           "IDFront.jpg", "IDBack.jpg", "Receipt.png", "Clip.mp4", "Tone.wav", "Sales.csv", "Project"]


def restore_sources(folder: Path):
    """If an earlier failure let Windows move a file away (Shift-drop without the menu = move),
    put it back so one failure can't cascade into the rest of the run."""
    prefix = "" if folder == EXP else "D-"
    missing = [n for n in SOURCES if not (folder / (prefix + n)).exists()]
    if missing:
        wk.log("restoring sources:", missing)
        for n in missing:
            stray = DESK / (prefix + n) if folder == EXP else None
            if stray is not None and stray.exists():
                stray.unlink()
        make_files(folder, prefix)
        time.sleep(1.0)
    # stray copies of Explorer files dropped on the desktop
    for n in SOURCES:
        if (DESK / n).exists():
            (DESK / n).unlink()


# ------------------------------------------------------------------ verification helpers
def img_ok(p: Path, fmt=None):
    with Image.open(p) as im:
        im.load()
        if fmt:
            assert im.format == fmt, f"{p.name}: format {im.format} != {fmt}"
        return im.size


def pdf_pages(p: Path) -> int:
    import pymupdf
    with pymupdf.open(p) as d:
        return d.page_count


# ------------------------------------------------------------------ menu layout (from the app itself)
def ring_index(paths: list[str], ring: str, label: str) -> tuple[int, int, int]:
    from shiftwheel.app import ShiftWheelApp
    rings = ShiftWheelApp.build_rings(None, paths)
    names = list(rings)
    items = rings[ring]
    labels = [i.label for i in items]
    return names.index(ring), labels.index(label), len(items)


# ------------------------------------------------------------------ scenario runner
def safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_ ." else "_" for c in name).replace(" ", "_")


def run(name: str, where: str, files: list[str], ring: str, label: str, verify, tool=None, select_extra=None):
    folder = EXP if where == "explorer" else DESK
    srcs = [str(folder / f) for f in files]
    restore_sources(folder)
    before = snapshot(folder)
    t0 = time.time()
    status, msg = "PASS", ""
    try:
        ring_i, idx, n = ring_index(srcs, ring, label)
        container = EX if where == "explorer" else wk.desktop_view()
        if where == "desktop":
            pyautogui.hotkey("win", "d") if not DESKTOP_SHOWN[0] else None
            DESKTOP_SHOWN[0] = True
        else:
            if DESKTOP_SHOWN[0]:
                EX.set_focus()
                DESKTOP_SHOWN[0] = False
                time.sleep(0.6)
        # select extra files first (multi-select), then drag the last one
        if select_extra:
            first = wk.item_center(container, files[0])
            wk.glide(*first, 0.4)
            pyautogui.click()
            for f in files[1:]:
                c = wk.item_center(container, f)
                wk.glide(*c, 0.35)
                pyautogui.keyDown("ctrl")
                pyautogui.click()
                pyautogui.keyUp("ctrl")
            src_xy = wk.item_center(container, files[-1])
        else:
            src_xy = wk.item_center(container, files[0])
        sw, sh = pyautogui.size()
        dy = 260 if src_xy[1] < 300 else (60 if src_xy[1] < sh - 400 else -260)
        nudge = (min(640, sw - src_xy[0] - 260), dy)
        c = wk.drag_open_menu(src_xy, nudge)
        for _ in range(ring_i):            # tap Shift once per ring: Convert → Tools → Print
            wk.switch_ring()
        target = wk.petal_xy(c, n, idx)
        wk.glide(*target, 0.4)
        time.sleep(0.35)
        wk.shot(OUT / "shots" / f"{len(RESULTS) + 1:02d}_{safe(name)}_menu.png")
        wk.drop()
        if tool:
            tool()
        outs = new_files(folder, before)
        if not outs:
            raise AssertionError("no output file appeared")
        note = verify(outs, srcs)
        msg = note or ", ".join(o.name for o in outs[:3])
    except Exception as e:
        status = "FAIL"
        msg = f"{type(e).__name__}: {e}"
        wk.log(traceback.format_exc())
        wk.shot(OUT / "shots" / f"{len(RESULTS) + 1:02d}_FAIL_{safe(name)}.png")
        pyautogui.mouseUp()
        pyautogui.keyUp("shift")
        pyautogui.press("esc")
        time.sleep(0.5)
        # close any stray ShiftWheel window
        try:
            for w in wk.uia().windows(title_re=".*— ShiftWheel"):
                w.close()
        except Exception:
            pass
    dt = time.time() - t0
    RESULTS.append({"name": name, "where": where, "status": status, "detail": msg, "seconds": round(dt, 1),
                    "t": round(time.time() - wk.T0, 1)})
    wk.log(f"{status:4} {where:8} {name:34} {dt:5.1f}s  {msg}")
    stash(folder, before)
    time.sleep(0.6)


# ------------------------------------------------------------------ tool drivers
def tool_win(title_re):
    return wk.find_window(title_re, 12)


def drive_compress():
    w = tool_win("Compress.*")
    time.sleep(0.5)
    wk.click_title(w, "Target size")
    wk.click_title(w, "200 KB", 0.8)
    btns = [b for b in w.descendants(control_type="Button") if b.window_text().startswith("Compress")]
    r = btns[-1].rectangle()
    wk.glide((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    pyautogui.click()


def drive_resize():
    w = tool_win("Resize.*")
    wk.click_title(w, "50%", 0.5)
    btns = [b for b in w.descendants(control_type="Button") if b.window_text().startswith("Resize")]
    r = btns[-1].rectangle()
    wk.glide((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    pyautogui.click()


def drive_crop():
    w = tool_win("Crop Image.*")
    time.sleep(0.4)
    wk.click_title(w, "1:1", 0.6)
    wk.click_title(w, "Apply")


def drive_edit():
    w = tool_win("Edit.*")
    time.sleep(0.4)
    wk.click_title(w, "✦ Auto", 0.6)
    wk.click_title(w, "⟳", 0.6)
    wk.click_title(w, "Save")


def _canvas(w):
    r = wk.image_area(w)
    if r is None:
        wr = w.rectangle()
        return (wr.left + 60, wr.top + 80, wr.right - 60, wr.top + int(wr.height() * 0.6))
    return (r.left, r.top, r.right, r.bottom)


def drive_annotate():
    w = tool_win("Annotate.*")
    time.sleep(0.6)
    x0, y0, x1, y1 = _canvas(w)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    wk.glide(cx - 150, cy + 80)
    pyautogui.mouseDown()
    wk.glide(cx + 120, cy - 60, 0.5)
    pyautogui.mouseUp()
    wk.click_title(w, "① Step", 0.3)
    wk.glide(cx + 160, cy - 80)
    pyautogui.click()
    time.sleep(0.4)
    wk.click_title(w, "Save")


def drive_redact():
    w = tool_win("Redact.*")
    time.sleep(0.6)
    x0, y0, x1, y1 = _canvas(w)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    wk.glide(cx - 120, cy - 60)
    pyautogui.mouseDown()
    wk.glide(cx + 120, cy + 60, 0.5)
    pyautogui.mouseUp()
    time.sleep(0.5)
    wk.click_title(w, "Save")


def drive_addbg():
    w = tool_win("Add BG.*")
    time.sleep(0.7)
    wk.click_title(w, "1:1", 0.6)
    wk.click_title(w, "Save with Background")


def drive_meta_location():
    w = tool_win("Metadata.*")
    time.sleep(0.5)
    wk.click_title(w, "Remove location only")


def drive_meta_all():
    w = tool_win("Metadata.*")
    time.sleep(0.5)
    wk.click_title(w, "Remove all metadata")


def drive_protect():
    w = tool_win("Password-protect.*")
    time.sleep(0.4)
    edits = w.descendants(control_type="Edit")
    for e in edits[:2]:
        r = e.rectangle()
        wk.glide((r.left + r.right) // 2, (r.top + r.bottom) // 2, 0.3)
        pyautogui.click()
        pyautogui.typewrite("keywest2026", interval=0.02)
    time.sleep(0.3)
    wk.click_title(w, "Protect")


def drive_button(title_re, button, wait_enabled=0.0):
    def drive():
        w = tool_win(title_re)
        time.sleep(1.2 + wait_enabled)   # first preview render / background work
        wk.click_title(w, button)
    return drive


def drive_video_target():
    w = tool_win("Compress Video.*")
    time.sleep(0.6)
    wk.click_title(w, "Target size")
    wk.click_title(w, "Compress")


# ------------------------------------------------------------------ verifiers
def v_format(fmt, ext):
    def v(outs, srcs):
        o = outs[0]
        assert o.suffix.lower() == ext, f"extension {o.suffix}"
        if fmt == "PDF":
            assert pdf_pages(o) >= 1
            return f"{o.name} · {pdf_pages(o)} page(s)"
        if fmt in ("DOCX",):
            from docx import Document
            assert Document(o).paragraphs
            return o.name
        if fmt == "TXT":
            assert o.read_text(encoding="utf-8").strip()
            return o.name
        size = img_ok(o, None if fmt in ("HEIC", "AVIF") else fmt)
        return f"{o.name} · {size[0]}×{size[1]}"
    return v


def v_pages_to_images(n, ext):
    def v(outs, srcs):
        imgs = [o for o in outs if o.suffix.lower() == ext]
        assert len(imgs) == n, f"{len(imgs)} images, expected {n}"
        for o in imgs:
            img_ok(o)
        return f"{n} × {ext}"
    return v


def v_compress(limit):
    def v(outs, srcs):
        o = outs[0]
        s0, s1 = Path(srcs[0]).stat().st_size, o.stat().st_size
        assert s1 <= limit, f"{s1} bytes > {limit}"
        img_ok(o)
        return f"{s0 // 1024} KB → {s1 // 1024} KB ({(1 - s1 / s0) * 100:.0f}% smaller)"
    return v


def v_dims(fn):
    def v(outs, srcs):
        with Image.open(srcs[0]) as a:
            sa = a.size
        sb = img_ok(outs[0])
        assert fn(sa, sb), f"{sa} → {sb}"
        return f"{sa[0]}×{sa[1]} → {sb[0]}×{sb[1]}"
    return v


def v_exists(outs, srcs):
    img_ok(outs[0])
    return outs[0].name


def v_redact(outs, srcs):
    with Image.open(outs[0]) as im:
        im = im.convert("RGB")
        w, h = im.size
        px = im.getpixel((w // 2, h // 2))
    assert sum(px) < 40, f"centre pixel {px} not blacked out"
    return f"{outs[0].name} · centre blacked out"


def v_no_gps_keep_camera(outs, srcs):
    from shiftwheel import imaging
    s = imaging.metadata_summary(outs[0])
    assert "Location" not in s, "GPS still present"
    assert "Camera" in s, "camera info was removed"
    return f"GPS removed, kept {s['Camera']}"


def v_no_meta(outs, srcs):
    from shiftwheel import imaging
    n, gps = imaging.count_metadata(outs[0])
    assert n == 0 and not gps, f"{n} fields remain"
    return "0 metadata fields left"


def v_pdf_n(n):
    def v(outs, srcs):
        pdfs = [o for o in outs if o.suffix.lower() == ".pdf"]
        assert len(pdfs) == n, f"{len(pdfs)} PDFs"
        return f"{n} PDFs"
    return v


def v_merged(outs, srcs):
    total = sum(pdf_pages(Path(s)) for s in srcs)
    got = pdf_pages(outs[0])
    assert got == total, f"{got} pages, expected {total}"
    return f"{got} pages"


def v_rotated(outs, srcs):
    import pymupdf
    with pymupdf.open(outs[0]) as d:
        assert all(p.rotation == 90 for p in d)
    return "all pages at 90°"


def v_protected(outs, srcs):
    import pymupdf
    d = pymupdf.open(outs[0])
    assert d.needs_pass and d.authenticate("keywest2026")
    return "AES-256, password works"


def v_pdf_meta(outs, srcs):
    import pymupdf
    with pymupdf.open(outs[0]) as d:
        assert not (d.metadata or {}).get("author")
    return "author/title removed"


def v_pdf_compress(outs, srcs):
    s0, s1 = Path(srcs[0]).stat().st_size, outs[0].stat().st_size
    assert pdf_pages(outs[0]) == pdf_pages(Path(srcs[0]))
    return f"{s0 // 1024} KB → {s1 // 1024} KB"


def v_extract(outs, srcs):
    assert outs and all(o.parent.name.endswith("images") for o in outs)
    for o in outs:
        img_ok(o)
    return f"{len(outs)} image(s) in {outs[0].parent.name}/"


def v_combined(outs, srcs):
    assert pdf_pages(outs[0]) == len(srcs)
    return f"{len(srcs)} images → {pdf_pages(outs[0])}-page PDF"


# ------------------------------------------------------------------ IPC / Send To path
def _ink_runs(img, thresh=245):
    import numpy as np
    rows = (np.asarray(img.convert("L")) < thresh).any(axis=1)
    runs, start = [], None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        if not v and start is not None:
            runs.append((start, y - 1))
            start = None
    return runs


def v_idcard(outs, srcs):
    import pymupdf
    pdf = [o for o in outs if o.suffix == ".pdf"][0]
    with pymupdf.open(pdf) as d:
        page = d[0]
        wmm, hmm = page.rect.width / 72 * 25.4, page.rect.height / 72 * 25.4
        assert abs(wmm - 210) < 1 and abs(hmm - 297) < 1, f"page {wmm:.0f}×{hmm:.0f} mm"
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    runs = _ink_runs(img)
    assert len(runs) == 2, f"{len(runs)} cards found on the sheet"
    sizes = [round((b - a + 1) / 300 * 25.4, 1) for a, b in runs]
    assert all(abs(s - 54) < 1.0 for s in sizes), f"card heights {sizes} mm"
    return f"A4, front + back at {sizes[0]} mm tall (real card: 54 mm)"


def v_pdf_text(word):
    def v(outs, srcs):
        import pymupdf
        pdf = [o for o in outs if o.suffix == ".pdf"][0]
        with pymupdf.open(pdf) as d:
            text = " ".join(p.get_text() for p in d)
        assert word in text, f"{word!r} not searchable; text layer: {text[:80]!r}"
        return f"searchable: '{word}' found"
    return v


def v_txt_has(word):
    def v(outs, srcs):
        t = [o for o in outs if o.suffix == ".txt"][0].read_text(encoding="utf-8")
        assert word in t, f"OCR text: {t[:120]!r}"
        return t.replace("\n", " / ")[:60]
    return v


def v_media(ext, vcodec=None, acodec=None, dur=None):
    def v(outs, srcs):
        from shiftwheel import media
        o = [x for x in outs if x.suffix.lower() == ext][0]
        i = media.probe(o)
        if vcodec:
            assert i.vcodec == vcodec, f"video codec {i.vcodec}"
        if acodec:
            assert i.acodec == acodec, f"audio codec {i.acodec}"
        if dur:
            assert abs(i.duration - dur) < 0.4, f"duration {i.duration:.2f}s"
        return f"{o.name} · {i.vcodec or i.acodec} · {i.duration:.1f}s"
    return v


def v_size_under(limit):
    def v(outs, srcs):
        o = [x for x in outs if x.is_file()][0]
        assert o.stat().st_size <= limit, f"{o.stat().st_size} bytes"
        return f"{o.stat().st_size // 1024} KB"
    return v


def v_xlsx(outs, srcs):
    from openpyxl import load_workbook
    ws = load_workbook([o for o in outs if o.suffix == ".xlsx"][0]).active
    assert ws["A2"].value == "North" and ws["B2"].value == 12
    return "typed cells, bold header"


def v_zip_has(name):
    def v(outs, srcs):
        import zipfile
        z = [o for o in outs if o.suffix == ".zip"][0]
        names = zipfile.ZipFile(z).namelist()
        assert any(n.endswith(name) for n in names), names
        return f"{z.name}: {', '.join(names)}"
    return v


def run_ipc(name: str, file: str, label: str, verify):
    """Launch a second copy with a file (what 'Send to' / right-click does) → menu → click."""
    import subprocess
    import sys
    folder = EXP
    before = snapshot(folder)
    t0 = time.time()
    status, msg = "PASS", ""
    try:
        sw, sh = pyautogui.size()
        wk.glide(int(sw * 0.62), int(sh * 0.45), 0.4)
        c = wk.menu_center(pyautogui.position())
        pyw = Path(sys.executable).with_name("pythonw.exe")
        env = dict(__import__("os").environ, SHIFTWHEEL_RECORDING="1")
        subprocess.Popen([str(pyw), "-m", "shiftwheel", str(folder / file)], cwd=str(wk.ROOT), env=env)
        time.sleep(2.5)  # instant hand-off to the running copy, menu opens
        _, idx, n = ring_index([str(folder / file)], "Convert", label)
        wk.glide(*wk.petal_xy(c, n, idx), 0.4)
        time.sleep(0.3)
        wk.shot(OUT / "shots" / f"{len(RESULTS) + 1:02d}_{safe(name)}_menu.png")
        pyautogui.click()
        outs = new_files(folder, before)
        if not outs:
            raise AssertionError("no output file appeared")
        msg = verify(outs, [str(folder / file)])
    except Exception as e:
        status, msg = "FAIL", f"{type(e).__name__}: {e}"
        wk.log(traceback.format_exc())
        pyautogui.press("esc")
    dt = time.time() - t0
    RESULTS.append({"name": name, "where": "send-to", "status": status, "detail": msg, "seconds": round(dt, 1),
                    "t": round(time.time() - wk.T0, 1)})
    wk.log(f"{status:4} send-to  {name:34} {dt:5.1f}s  {msg}")
    stash(folder, before)


# ------------------------------------------------------------------ main
EX = None
DESKTOP_SHOWN = [False]


def main():
    global EX
    wk.set_log(OUT / "log.txt")
    wk.prepare_desktop()
    for f in DESK.glob("*"):
        if f.is_file() and f.suffix.lower() in (".jpg", ".png", ".pdf", ".docx", ".txt", ".mp4", ".wav", ".csv"):
            f.unlink()
    shutil.rmtree(EXP, ignore_errors=True)
    shutil.rmtree(STASH, ignore_errors=True)
    make_files(EXP)
    make_files(DESK, "D-")
    app = wk.start_app()
    time.sleep(5)
    EX = wk.open_explorer(EXP)
    rec = wk.start_recording(OUT / "e2e.mp4")
    time.sleep(1.5)
    wk.T0 = time.time()
    try:
        # ---- conversions from Explorer
        for fmt in ["PNG", "WEBP", "HEIC", "TIFF", "AVIF", "BMP", "PDF", "ICO", "GIF"]:
            ext = {"TIFF": ".tiff", "HEIC": ".heic"}.get(fmt, "." + fmt.lower())
            run(f"JPG → {fmt}", "explorer", ["Photo.jpg"], "Convert", fmt, v_format(fmt, ext))
        run("PNG → JPG", "explorer", ["Graphic.png"], "Convert", "JPG", v_format("JPEG", ".jpg"))
        run("PDF → JPG (3 pages)", "explorer", ["Report.pdf"], "Convert", "JPG", v_pages_to_images(3, ".jpg"))
        run("PDF → PNG (3 pages)", "explorer", ["Report.pdf"], "Convert", "PNG", v_pages_to_images(3, ".png"))
        run("PDF → DOCX", "explorer", ["Report.pdf"], "Convert", "DOCX", v_format("DOCX", ".docx"))
        run("PDF → TXT", "explorer", ["Report.pdf"], "Convert", "TXT", v_format("TXT", ".txt"))
        run("DOCX → PDF", "explorer", ["Letter.docx"], "Convert", "PDF", v_format("PDF", ".pdf"))
        run("DOCX → TXT", "explorer", ["Letter.docx"], "Convert", "TXT", v_format("TXT", ".txt"))
        run("TXT → PDF", "explorer", ["Notes.txt"], "Convert", "PDF", v_format("PDF", ".pdf"))
        run("TXT → DOCX", "explorer", ["Notes.txt"], "Convert", "DOCX", v_format("DOCX", ".docx"))
        run("2 images → 1 PDF", "explorer", ["Photo.jpg", "Second.jpg"], "Convert", "PDF", v_combined,
            select_extra=True)
        # ---- image tools
        run("Compress to 200 KB", "explorer", ["Photo.jpg"], "Tools", "Compress", v_compress(200_000), drive_compress)
        run("Resize 50%", "explorer", ["Photo.jpg"], "Tools", "Resize",
            v_dims(lambda a, b: b == (a[0] // 2, a[1] // 2)), drive_resize)
        run("Crop 1:1", "explorer", ["Photo.jpg"], "Tools", "Crop", v_dims(lambda a, b: b[0] == b[1] == min(a)), drive_crop)
        run("Edit: auto + rotate", "explorer", ["Photo.jpg"], "Tools", "Edit",
            v_dims(lambda a, b: b == (a[1], a[0])), drive_edit)
        run("Annotate", "explorer", ["Photo.jpg"], "Tools", "Annotate", v_exists, drive_annotate)
        run("Redact", "explorer", ["Photo.jpg"], "Tools", "Redact", v_redact, drive_redact)
        run("Add BG 1:1", "explorer", ["Photo.jpg"], "Tools", "Add BG", v_dims(lambda a, b: b[0] == b[1]), drive_addbg)
        run("Metadata: remove location", "explorer", ["Photo.jpg"], "Tools", "Metadata", v_no_gps_keep_camera,
            drive_meta_location)
        run("Metadata: remove all", "explorer", ["Photo.jpg"], "Tools", "Metadata", v_no_meta, drive_meta_all)
        # ---- PDF tools
        run("PDF Compress", "explorer", ["Report.pdf"], "Tools", "Compress", v_pdf_compress)
        run("PDF Split", "explorer", ["Report.pdf"], "Tools", "Split", v_pdf_n(3))
        run("PDF Rotate", "explorer", ["Report.pdf"], "Tools", "Rotate", v_rotated)
        run("PDF Protect", "explorer", ["Report.pdf"], "Tools", "Protect", v_protected, drive_protect)
        run("PDF Extract images", "explorer", ["Report.pdf"], "Tools", "Extract", v_extract)
        run("PDF Metadata", "explorer", ["Report.pdf"], "Tools", "Metadata", v_pdf_meta, drive_meta_all)
        run("Merge 2 PDFs", "explorer", ["Appendix.pdf", "Report.pdf"], "Tools", "Merge", v_merged,
            select_extra=True)
        # ---- ShiftWheel additions: Print ring
        run("ID card front+back → A4 PDF", "explorer", ["IDFront.jpg", "IDBack.jpg"], "Print", "ID Card", v_idcard,
            drive_button("ID Card Photocopy.*", "Save PDF"), select_extra=True)
        run("Passport photo sheet", "explorer", ["Photo.jpg"], "Print", "Passport", v_pdf_n(1),
            drive_button("Passport Photo Sheet.*", "Save PDF"))
        run("Scan → searchable PDF", "explorer", ["Receipt.png"], "Print", "Scan", v_pdf_text("TOTAL"),
            drive_button("Scan to PDF.*", "Save PDF"))
        run("Image → text (OCR)", "explorer", ["Receipt.png"], "Tools", "Text", v_txt_has("TOTAL"),
            drive_button("Extract Text.*", "Save .txt", wait_enabled=6))
        # ---- video & audio
        run("MP4 → MOV", "explorer", ["Clip.mp4"], "Convert", "MOV", v_media(".mov", "h264", dur=4))
        run("MP4 → WEBM", "explorer", ["Clip.mp4"], "Convert", "WEBM", v_media(".webm", "vp9", "opus", dur=4))
        run("MP4 → GIF", "explorer", ["Clip.mp4"], "Convert", "GIF", v_format("GIF", ".gif"))
        run("MP4 → MP3", "explorer", ["Clip.mp4"], "Convert", "MP3", v_media(".mp3", acodec="mp3", dur=4))
        run("Video trim", "explorer", ["Clip.mp4"], "Tools", "Trim", v_media(".mp4", "h264", dur=4),
            drive_button("Trim.*", "Save Trimmed"))
        run("Video compress (target size)", "explorer", ["Clip.mp4"], "Tools", "Compress", v_media(".mp4", "h264"),
            drive_video_target)
        run("WAV → MP3", "explorer", ["Tone.wav"], "Convert", "MP3", v_media(".mp3", acodec="mp3", dur=5))
        # ---- office & files
        run("CSV → XLSX", "explorer", ["Sales.csv"], "Convert", "XLSX", v_xlsx)
        run("Folder → ZIP", "explorer", ["Project"], "Tools", "Zip", v_zip_has("readme.txt"))
        # ---- second launch with a file (Send To / right-click path)
        run_ipc("Send To → PNG", "Photo.jpg", "PNG", v_format("PNG", ".png"))
        # ---- from the Desktop
        run("Desktop: JPG → PNG", "desktop", ["D-Photo.jpg"], "Convert", "PNG", v_format("PNG", ".png"))
        run("Desktop: PDF → TXT", "desktop", ["D-Report.pdf"], "Convert", "TXT", v_format("TXT", ".txt"))
        run("Desktop: DOCX → PDF", "desktop", ["D-Letter.docx"], "Convert", "PDF", v_format("PDF", ".pdf"))
        run("Desktop: Compress", "desktop", ["D-Photo.jpg"], "Tools", "Compress", v_compress(200_000), drive_compress)
        run("Desktop: Crop", "desktop", ["D-Photo.jpg"], "Tools", "Crop", v_dims(lambda a, b: b[0] == b[1]), drive_crop)
        run("Desktop: Add BG", "desktop", ["D-Graphic.png"], "Tools", "Add BG", v_dims(lambda a, b: b[0] == b[1]),
            drive_addbg)
        run("Desktop: 2 PDFs merge", "desktop", ["D-Appendix.pdf", "D-Report.pdf"], "Tools", "Merge", v_merged,
            select_extra=True)
    except Exception:
        wk.log("E2E ABORTED\n" + traceback.format_exc())
    finally:
        pyautogui.mouseUp()
        pyautogui.keyUp("shift")
        time.sleep(1)
        wk.stop_recording(rec)
        app.kill()
        wk.copy_app_log(OUT / "app_log.txt")
        try:  # the drag picture must never be baked into the glass
            log_text = (OUT / "app_log.txt").read_text(encoding="utf-8", errors="replace")
            n = log_text.count("drag image(s) during capture")
            RESULTS.append({"name": "Drag picture kept out of the glass", "where": "all",
                            "status": "PASS" if n > 0 else "FAIL",
                            "detail": f"hidden during {n} menu captures", "seconds": 0, "t": 0})
        except Exception as e:
            wk.log("drag image check failed", e)
        passed = sum(r["status"] == "PASS" for r in RESULTS)
        (OUT / "results.json").write_text(json.dumps(RESULTS, indent=1))
        lines = [f"# ShiftWheel end-to-end test — {passed}/{len(RESULTS)} passed", "",
                 "| # | Where | Scenario | Result | Detail | Time |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(RESULTS, 1):
            mark = "✅" if r["status"] == "PASS" else "❌"
            lines.append(f"| {i} | {r['where']} | {r['name']} | {mark} | {r['detail']} | {r['seconds']}s |")
        (OUT / "results.md").write_text("\n".join(lines), encoding="utf-8")
        wk.log(f"DONE {passed}/{len(RESULTS)} passed")


if __name__ == "__main__":
    main()
