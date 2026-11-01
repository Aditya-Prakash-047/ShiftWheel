"""The tools added to match Santra: video crop / split / redact, audio channels / bleep /
visualizer / silence trim, collage, QR codes, PDF organising, metadata editing, % compression."""
from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from shiftwheel import extras as X
from shiftwheel import media as M
from shiftwheel.convert import fitz
from shiftwheel.util import UserError


@pytest.fixture
def clip(tmp_path, media_dir):
    p = tmp_path / "clip.mp4"
    shutil.copy(media_dir / "clip.mp4", p)
    return p


@pytest.fixture
def stereo(tmp_path):
    p = tmp_path / "talk.wav"
    subprocess.run([M.ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-filter_complex",
                    "[0][1]join=inputs=2:channel_layout=stereo", str(p)], check=True)
    return p


def _level(path, start, end, channel=None) -> float:
    """Mean absolute level of an audio file between two times (via ffmpeg → raw floats)."""
    r = subprocess.run([M.ffmpeg_exe(), "-loglevel", "error", "-i", str(path), "-ss", str(start), "-t", str(end - start),
                        "-f", "f32le", "-acodec", "pcm_f32le", "-"], capture_output=True, check=True)
    info = M.probe(path)
    a = np.frombuffer(r.stdout, np.float32)
    2 if "stereo" in str(info.__dict__) or len(a) % 2 == 0 and channel is not None else 1
    if channel is not None:
        a = a.reshape(-1, 2)[:, channel]
    return float(np.abs(a).mean())


def test_crop_video(clip):
    out = X.crop_video(clip, 10, 20, 201, 151)
    info = M.probe(out)
    assert (info.width, info.height) == (200, 150) and info.has_audio            # even sizes, audio kept


def test_split_points_and_video(clip):
    assert X.split_points(10, parts=4) == [(0, 2.5), (2.5, 5), (5, 7.5), (7.5, 10)]
    assert X.split_points(10, every=4) == [(0, 4), (4, 8), (8, 10)]
    assert X.split_points(10, points=[7, 3, 3, 20]) == [(0, 3), (3, 7), (7, 10)]
    outs = X.split_video(clip, X.split_points(M.probe(clip).duration, parts=2))
    assert len(outs) == 2 and outs[0].parent.name == "clip parts"
    assert all(abs(M.probe(o).duration - M.probe(clip).duration / 2) < 0.3 for o in outs)


def test_redact_video_blur_and_box(clip):
    out = X.redact_video(clip, [X.Box(0, 0, 80, 60, 0, 1.5, blur=False), X.Box(100, 100, 60, 60, blur=True)])
    f0, _src0 = M.frame_image(out, 0.5, 240), M.frame_image(clip, 0.5, 240)
    k = 240 / M.probe(clip).height
    corner = f0.crop((2, 2, int(70 * k), int(50 * k)))
    assert max(corner.convert("L").getextrema()) < 30                            # solid black there
    late = M.frame_image(out, 3.0, 240).crop((2, 2, int(70 * k), int(50 * k)))
    assert max(late.convert("L").getextrema()) > 60                              # …only in its time range
    with pytest.raises(UserError):
        X.redact_video(clip, [])


def test_channels(stereo):
    left = X.channels(stereo, "left")
    assert _level(left, 0.5, 1.0, 0) == pytest.approx(_level(left, 0.5, 1.0, 1), rel=0.05)
    mono = X.channels(stereo, "mono")
    assert M.probe(mono).streams and "mono" in subprocess.run(
        [M.ffmpeg_exe(), "-hide_banner", "-i", str(mono)], capture_output=True, text=True).stderr


def test_bleep(stereo):
    out = X.bleep(stereo, [(1.0, 2.0)], freq=1000)
    spec_in = np.abs(np.fft.rfft(_raw(out, 1.2, 1.8)))
    spec_out = np.abs(np.fft.rfft(_raw(out, 0.2, 0.8)))
    f = np.fft.rfftfreq(len(_raw(out, 1.2, 1.8)), 1 / 48000)
    assert abs(f[spec_in.argmax()] - 1000) < 20                                  # the bleep replaced it
    assert abs(f[spec_out.argmax()] - 1000) > 50                                 # outside: untouched
    with pytest.raises(UserError):
        X.bleep(stereo, [])


def _raw(path, a, b):
    r = subprocess.run([M.ffmpeg_exe(), "-loglevel", "error", "-i", str(path), "-ss", str(a), "-t", str(b - a),
                        "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32)


def test_trim_silence(tmp_path):
    p = tmp_path / "padded.wav"
    subprocess.run([M.ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=mono:d=1", "-f", "lavfi", "-i", "sine=frequency=500:duration=1",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1", "-filter_complex",
                    "[0][1][2]concat=n=3:v=0:a=1", str(p)], check=True)
    out = X.trim_silence(p)
    assert abs(M.probe(out).duration - 1.0) < 0.25 and abs(M.probe(p).duration - 3.0) < 0.1


def test_visualizer(media_dir, tmp_path):
    tone = tmp_path / "tone.wav"
    shutil.copy(media_dir / "tone.wav", tone)
    out = X.visualizer(tone, "square", "wave", "#ff5200")
    info = M.probe(out)
    assert (info.width, info.height) == (1080, 1080) and info.has_audio and abs(info.duration - M.probe(tone).duration) < 0.5


def test_collage(tmp_path):
    paths = []
    for k, c in enumerate(("red", "green", "blue")):
        p = tmp_path / f"{k}.png"
        Image.new("RGB", (400 + k * 100, 300), c).save(p)
        paths.append(p)
    for layout, _ in X.COLLAGE_LAYOUTS:
        cells = X.collage_cells(3, layout, 1000, 800, 20)
        assert len(cells) == 3 and all(w > 0 and h > 0 and x + w <= 1000 and y + h <= 800 for x, y, w, h in cells)
    out = X.save_collage(paths, layout="row", size=(1200, 400), spacing=20, corners=0, background="#000000")
    with Image.open(out) as im:
        r, g, b = im.getpixel((200, 200))[:3]
        assert im.size == (1200, 400) and r > 250 and g < 5 and b < 5
        assert im.getpixel((5, 5))[:3] == (0, 0, 0)                               # spacing shows the background


def test_qr(tmp_path):
    import cv2
    enc = cv2.QRCodeEncoder.create()
    qr = enc.encode("https://example.com/ticket/42")
    big = cv2.resize(qr, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    canvas = Image.new("RGB", (big.shape[1] + 200, big.shape[0] + 200), "white")
    canvas.paste(Image.fromarray(big).convert("RGB"), (100, 100))
    p = tmp_path / "ticket.png"
    canvas.save(p)
    assert X.read_qr(p) == ["https://example.com/ticket/42"]
    assert X.qr_to_txt(p).read_text(encoding="utf-8").strip() == "https://example.com/ticket/42"
    blank = tmp_path / "blank.png"
    Image.new("RGB", (300, 300), "white").save(blank)
    with pytest.raises(UserError):
        X.qr_to_txt(blank)


def test_organize_pdf(tmp_path):
    doc = fitz.open()
    for k in range(3):
        doc.new_page().insert_text((72, 72), f"Page {k + 1}")
    p = tmp_path / "doc.pdf"
    doc.save(p)
    out = X.organize_pdf(p, [(2, 0), (0, 90), (0, 0)])                         # reorder, rotate, duplicate, drop 2
    with fitz.open(out) as d:
        assert [pg.get_text().strip() for pg in d] == ["Page 3", "Page 1", "Page 1"]
        assert [pg.rotation for pg in d] == [0, 90, 0]


def test_metadata_editing(tmp_path, clip):
    img = tmp_path / "photo.jpg"
    ex = Image.Exif()
    ex[0x013B] = "Old Author"
    Image.new("RGB", (64, 48), "orange").save(img, exif=ex)
    assert X.read_fields(img)["author"] == "Old Author"
    out = X.write_fields(img, {"author": "", "title": "Holiday", "copyright": "(c) Me"})
    f = X.read_fields(out)
    assert f["author"] == "" and f["title"] == "Holiday" and f["copyright"] == "(c) Me"
    pdf = tmp_path / "d.pdf"
    d = fitz.open()
    d.new_page()
    d.save(pdf)
    assert X.read_fields(X.write_fields(pdf, {"title": "Report", "author": "Aditya"}))["author"] == "Aditya"
    v = X.write_fields(clip, {"title": "Trip", "artist": "Me"})
    assert X.read_fields(v)["title"] == "Trip"


def test_compress_percent(tmp_path):
    rng = np.random.default_rng(1)
    p = tmp_path / "noisy.jpg"
    Image.fromarray(rng.integers(0, 255, (900, 1200, 3), dtype=np.uint8)).save(p, quality=95)
    out = X.compress_percent(p, 50)
    assert out.stat().st_size <= p.stat().st_size * 0.5 * 1.05
