"""Every new tool window opens on a real file and saves through its own Save button."""
from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from shiftwheel import app as A
from shiftwheel import media as M
from shiftwheel import tools, tools2
from shiftwheel.convert import fitz


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def saved(win, click=None):
    got = []
    win.notify = lambda action, srcs, outs, extra="": got.extend(outs)
    (click or win.primary_btn.click)()
    return [p for p in got]


@pytest.fixture
def clip(tmp_path, media_dir):
    p = tmp_path / "clip.mp4"
    shutil.copy(media_dir / "clip.mp4", p)
    return p


@pytest.fixture
def tone(tmp_path, media_dir):
    p = tmp_path / "tone.wav"
    shutil.copy(media_dir / "tone.wav", p)
    return p


def test_collage_window(tmp_path):
    paths = []
    for k, c in enumerate(("red", "green", "blue", "yellow")):
        p = tmp_path / f"{k}.jpg"
        Image.new("RGB", (300, 200), c).save(p)
        paths.append(str(p))
    w = tools2.CollageWindow(paths, lambda *a: None)
    w.layout_grp.button(3).click()                       # featured
    w.render()
    outs = saved(w)
    with Image.open(outs[0]) as im:
        assert im.size == (2400, 2400)


def test_organize_window(tmp_path):
    doc = fitz.open()
    for k in range(3):
        doc.new_page().insert_text((72, 72), f"Page {k + 1}")
    p = tmp_path / "doc.pdf"
    doc.save(p)
    w = tools2.OrganizePdfWindow(str(p), lambda *a: None)
    w.list.item(0).setSelected(True)
    w._rotate(90)
    w.list.clearSelection()
    w.list.item(2).setSelected(True)
    w._remove()
    outs = saved(w)
    with fitz.open(outs[0]) as d:
        assert d.page_count == 2 and d[0].rotation == 90


def test_video_crop_split_redact_windows(clip):
    w = tools2.VideoCropWindow(str(clip), lambda *a: None)
    w.grp.button(1).click()                              # 1:1
    out = saved(w)[0]
    i = M.probe(out)
    assert i.width == i.height
    w = tools2.SplitWindow(str(clip), lambda *a: None)
    w.parts.setValue(3)
    outs = saved(w)
    assert len(outs) == 3
    w = tools2.RedactVideoWindow(str(clip), lambda *a: None)
    from PySide6.QtCore import QRectF
    w.add_box(QRectF(10, 10, 60, 40))
    assert M.probe(saved(w)[0]).has_video


def test_audio_windows(tone):
    w = tools2.ChannelsWindow(str(tone), lambda *a: None)
    assert saved(w)[0].exists()
    w = tools2.BleepWindow(str(tone), lambda *a: None)
    w.bar.set_range(1.0, 2.0)
    w._add()
    assert saved(w)[0].exists()
    w = tools2.VisualizerWindow(str(tone), lambda *a: None)
    w.layout_grp.button(2).click()
    out = saved(w)[0]
    assert (M.probe(out).width, M.probe(out).height) == (1080, 1080)


def test_metadata_edit_window(tmp_path, clip):
    w = tools2.MetadataEditWindow(str(clip), lambda *a: None)
    w.edits["title"].setText("Holiday")
    from shiftwheel import extras
    assert extras.read_fields(saved(w)[0])["title"] == "Holiday"


def test_compress_percent_mode(tmp_path):
    import numpy as np
    p = tmp_path / "noise.jpg"
    Image.fromarray(np.random.default_rng(2).integers(0, 255, (600, 800, 3), dtype=np.uint8)).save(p, quality=95)
    w = tools.CompressWindow([str(p)], lambda *a: None)
    w.mode.button(2).click()
    w.pct.setValue(60)
    w.estimate()
    out = saved(w)[0]
    assert out.stat().st_size <= p.stat().st_size * 0.4 * 1.05


def test_new_slices_are_on_the_wheels(tmp_path):
    rings = A.ShiftWheelApp.build_rings(None, [str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")])
    assert {"QR code", "Collage"} <= {i.label for i in rings["Tools"]}
    rings = A.ShiftWheelApp.build_rings(None, [str(tmp_path / "a.mp4")])
    assert {"Crop", "Split", "Redact", "Metadata"} <= {i.label for i in rings["Tools"]}
    rings = A.ShiftWheelApp.build_rings(None, [str(tmp_path / "a.mp3")])
    assert {"Channels", "Bleep", "Visualize", "Silence"} <= {i.label for i in rings["Tools"]}
    rings = A.ShiftWheelApp.build_rings(None, [str(tmp_path / "a.pdf")])
    assert "Organize" in {i.label for i in rings["Tools"]}
    assert [i.label for i in rings["Convert"]] == ["DOCX", "PPTX", "XLSX", "JPG", "PNG", "EPUB", "TXT", "MD"]
    for name in ("a.srt", "a.epub", "a.svg", "a.rar"):
        assert A.ShiftWheelApp.build_rings(None, [str(tmp_path / name)])
