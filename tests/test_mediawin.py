"""Media windows: open on real clips, handles move, saving produces the right files."""
from __future__ import annotations

import shutil

import pytest
from PySide6.QtWidgets import QApplication

from shiftwheel import media as M
from shiftwheel import mediawin as W


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class Sink:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a)


@pytest.fixture
def clip(media_dir, tmp_path):
    p = tmp_path / "clip.mp4"
    shutil.copy(media_dir / "clip.mp4", p)
    return p


@pytest.fixture
def tone(media_dir, tmp_path):
    p = tmp_path / "tone.wav"
    shutil.copy(media_dir / "tone.wav", p)
    return p


def test_trim_window_video(clip):
    s = Sink()
    w = W.TrimWindow(str(clip), s, "trim")
    w._load_visuals()
    assert w.bar.strip is not None and w.frame.pixmap() is not None
    w.bar.set_range(0.5, 2.0)
    assert abs(w.s_spin.value() - 0.5) < 1e-6 and abs(w.e_spin.value() - 2.0) < 1e-6
    w.save()
    out = s.calls[-1][2][0]
    assert abs(M.probe(out).duration - 1.5) < 0.15


def test_trim_window_audio_waveform(tone):
    s = Sink()
    w = W.TrimWindow(str(tone), s, "trim")
    w._load_visuals()
    assert w.bar.strip is not None
    w.bar.set_range(1.0, 4.0)
    w.precise.button(0).click()
    w.save()
    assert abs(M.probe(s.calls[-1][2][0]).duration - 3.0) < 0.1


def test_gif_and_snapshot_windows(clip):
    s = Sink()
    g = W.TrimWindow(str(clip), s, "gif")
    g.bar.set_range(1.0, 3.0)
    g.save()
    from PIL import Image
    with Image.open(s.calls[-1][2][0]) as im:
        assert im.format == "GIF" and im.width == 480
    sn = W.TrimWindow(str(clip), s, "snapshot")
    sn.bar.set_range(2.0, 2.0)
    sn.save()
    assert s.calls[-1][2][0].suffix == ".png"


def test_gif_window_refuses_audio(tone):
    with pytest.raises(ValueError):
        W.TrimWindow(str(tone), Sink(), "gif")


def test_compress_window_target_size(clip):
    s = Sink()
    w = W.VideoCompressWindow([str(clip)], s)
    w.q.button(3).click()
    w.mb.setValue(0.3)
    w.save()
    out = s.calls[-1][2][0]
    assert out.suffix == ".mp4" and out.stat().st_size < 0.3 * 1048576 * 1.05


def test_speed_window(clip):
    s = Sink()
    w = W.SpeedWindow(str(clip), s)
    w.grp.button(5).click()   # 2×
    w.save()
    assert abs(M.probe(s.calls[-1][2][0]).duration - 2.0) < 0.2


def test_rings_for_media(clip, tone):
    from shiftwheel.app import ShiftWheelApp
    rings = ShiftWheelApp.build_rings(None, [str(clip)])
    assert [i.label for i in rings["Convert"]][:3] == ["MOV", "MKV", "WEBM"]   # MP4 itself is skipped
    assert "Trim" in [i.label for i in rings["Tools"]]
    rings = ShiftWheelApp.build_rings(None, [str(tone), str(tone)])
    assert "WAV" not in [i.label for i in rings["Convert"]]
    assert [i.label for i in rings["Tools"]][-1] == "Merge"
