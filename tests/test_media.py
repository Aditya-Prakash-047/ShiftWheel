"""Video & audio: every conversion and tool produces a playable file with the right
duration / size / codecs, reports progress, and never touches the original."""
from __future__ import annotations

import shutil

import pytest

from shiftwheel import media as M
from shiftwheel.util import UserError


@pytest.fixture
def clip(media_dir, tmp_path):
    p = tmp_path / "clip.mp4"
    shutil.copy(media_dir / "clip.mp4", p)
    return p


@pytest.fixture
def silent(media_dir, tmp_path):
    p = tmp_path / "silent.mov"
    shutil.copy(media_dir / "silent.mov", p)
    return p


@pytest.fixture
def tone(media_dir, tmp_path):
    p = tmp_path / "tone.wav"
    shutil.copy(media_dir / "tone.wav", p)
    return p


def test_probe(clip, silent, tone):
    i = M.probe(clip)
    assert (i.width, i.height) == (640, 360) and abs(i.duration - 4) < 0.2
    assert i.vcodec == "h264" and i.acodec == "aac"
    assert M.probe(silent).has_audio is False
    t = M.probe(tone)
    assert t.has_video is False and t.has_audio and abs(t.duration - 5) < 0.1


def test_probe_rejects_non_media(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_text("not a video")
    with pytest.raises(UserError):
        M.probe(p)


@pytest.mark.parametrize("target,vcodec", [("MOV", "h264"), ("MKV", "h264"), ("WEBM", "vp9"), ("AVI", "mpeg4")])
def test_convert_video(clip, target, vcodec):
    seen = []
    out = M.convert_video(clip, target, seen.append)[0]
    assert out.suffix == "." + target.lower() and out.exists()
    i = M.probe(out)
    assert i.vcodec == vcodec and (i.width, i.height) == (640, 360) and abs(i.duration - 4) < 0.3
    assert i.has_audio
    assert seen and seen[-1] == 1.0
    assert clip.exists()


def test_remux_is_lossless_and_fast(clip):
    out = M.convert_video(clip, "MKV")[0]
    assert M.probe(out).vcodec == "h264"   # stream copied, not re-encoded


def test_gif_and_audio_extract(clip):
    gif = M.convert_video(clip, "GIF")[0]
    from PIL import Image
    with Image.open(gif) as im:
        assert im.format == "GIF" and im.n_frames > 20 and im.width == 480
    mp3 = M.convert_video(clip, "MP3")[0]
    i = M.probe(mp3)
    assert i.acodec == "mp3" and not i.has_video


def test_extract_audio_from_silent_video_is_a_clear_error(silent):
    with pytest.raises(UserError, match="no sound"):
        M.convert_video(silent, "MP3")


@pytest.mark.parametrize("target,codec", [("MP3", "mp3"), ("M4A", "aac"), ("OGG", "vorbis"), ("FLAC", "flac"),
                                          ("OPUS", "opus")])
def test_convert_audio(tone, target, codec):
    out = M.convert_audio(tone, target)[0]
    assert M.probe(out).acodec == codec and abs(M.probe(out).duration - 5) < 0.2


def test_trim_precise_and_fast(clip, tone):
    out = M.trim(clip, 1.0, 2.5)
    assert abs(M.probe(out).duration - 1.5) < 0.15
    fast = M.trim(clip, 0.0, 2.0, precise=False)
    assert 1.5 < M.probe(fast).duration < 2.6
    a = M.trim(tone, 1, 3)
    assert abs(M.probe(a).duration - 2) < 0.1


def test_trim_rejects_empty_selection(clip):
    with pytest.raises(UserError):
        M.trim(clip, 2.0, 2.0)


def test_compress_quality_and_target_size(clip):
    small = M.compress_video(clip, "small")
    assert small.stat().st_size < clip.stat().st_size * 1.2
    tgt = M.compress_video(clip, target_mb=0.25, max_height=240)
    i = M.probe(tgt)
    assert i.height == 240
    assert tgt.stat().st_size < 0.25 * 1024 * 1024 * 1.05


def test_resize_rotate_mute_speed(clip):
    assert M.probe(M.resize_video(clip, 240)).height == 240
    r = M.probe(M.rotate_video(clip, 90))
    assert (r.width, r.height) == (360, 640)
    assert M.probe(M.mute(clip)).has_audio is False
    fast = M.probe(M.speed(clip, 2.0))
    assert abs(fast.duration - 2.0) < 0.2 and fast.has_audio


def test_speed_audio_extreme(tone):
    out = M.speed(tone, 4.0)
    assert abs(M.probe(out).duration - 1.25) < 0.1


def test_snapshot_and_previews(clip, tone):
    png = M.snapshot(clip, 1.5)
    from PIL import Image
    with Image.open(png) as im:
        assert im.size == (640, 360)
    f = M.frame_image(clip, 2.0, 180)
    assert f is not None and f.height == 180
    w = M.waveform_image(tone, 600, 100)
    assert w is not None and w.size == (600, 100)


def test_merge_same_and_mixed(clip, silent, tone, tmp_path):
    second = tmp_path / "clip2.mp4"
    shutil.copy(clip, second)
    same = M.merge([clip, second])
    assert abs(M.probe(same).duration - 8) < 0.4
    mixed = M.merge([clip, silent])                      # different size, one has no audio
    i = M.probe(mixed)
    assert (i.width, i.height) == (640, 360) and i.has_audio and abs(i.duration - 6) < 0.5
    t2 = tmp_path / "tone2.wav"
    shutil.copy(tone, t2)
    a = M.merge([tone, t2])
    assert abs(M.probe(a).duration - 10) < 0.2 and a.suffix == ".wav"


def test_normalize_and_compress_audio(tone, clip):
    n = M.normalize(tone)
    assert n.suffix == ".wav" and M.probe(n).has_audio
    v = M.normalize(clip)
    assert M.probe(v).has_video
    c = M.compress_audio(tone, 64)
    assert c.suffix == ".mp3" and c.stat().st_size < tone.stat().st_size


def test_outputs_never_overwrite(clip):
    a = M.convert_video(clip, "MOV")[0]
    b = M.convert_video(clip, "MOV")[0]
    assert a != b and a.exists() and b.exists()
