"""Compression levels: each level really is smaller than the one before, and the size shown
before compressing is close to the size you get."""
from __future__ import annotations

import os
import subprocess

import pytest
from PIL import Image

from shiftwheel import archive, imaging, media
from shiftwheel.util import file_size


@pytest.fixture
def photo_pdf(tmp_path):
    """Three pages, each a large noisy photo (what makes real PDFs big)."""
    import fitz
    doc = fitz.open()
    for i in range(3):
        im = Image.effect_noise((2400, 1800), 40 + i * 10).convert("RGB")
        p = tmp_path / f"p{i}.png"
        im.save(p)
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, filename=str(p))
        page.insert_text((40, 40), f"Page {i + 1}", fontsize=18)
    out = tmp_path / "Photos.pdf"
    doc.save(out)
    return out


def test_pdf_levels_shrink_in_order_and_estimates_match(photo_pdf, tmp_path):
    sizes = {}
    for key, *_ in imaging.PDF_LEVELS:
        est, exact = imaging.estimate_pdf(photo_pdf, key)
        out = imaging.compress_pdf(photo_pdf, level=key, out=tmp_path / f"{key}.pdf")
        real = file_size(out)
        sizes[key] = real
        assert exact and abs(est - real) <= max(2048, real * 0.02), (key, est, real)
    assert sizes["light"] > sizes["balanced"] > sizes["strong"] > sizes["smallest"]
    with imaging.open_pdf(tmp_path / "smallest.pdf") as d:
        assert d.page_count == 3 and "Page 1" in d[0].get_text()      # text survives


def test_pdf_estimate_from_sample_pages_is_close(photo_pdf, tmp_path):
    est, exact = imaging.estimate_pdf(photo_pdf, "strong", max_pages=1)    # forces sampling
    real = file_size(imaging.compress_pdf(photo_pdf, level="strong", out=tmp_path / "s.pdf"))
    assert not exact and 0.6 * real <= est <= 1.6 * real


def test_archive_levels_and_estimates(tmp_path):
    folder = tmp_path / "Project"
    folder.mkdir()
    (folder / "notes.txt").write_text("ShiftWheel compresses text very well. " * 4000, encoding="utf-8")
    (folder / "data.csv").write_text("\n".join(f"{i},{i * i},{i % 7}" for i in range(40000)), encoding="utf-8")
    (folder / "noise.bin").write_bytes(os.urandom(300_000))           # incompressible
    for fmt in ("ZIP", "7Z"):
        real = {}
        for key, *_ in archive.ARCHIVE_LEVELS:
            est = archive.estimate_archive([folder], fmt, key)
            out = archive.zip_paths([folder], fmt, key)
            real[key] = file_size(out)
            out.unlink()
            assert 0.8 * real[key] <= est <= 1.25 * real[key], (fmt, key, est, real[key])
        assert real["store"] > real["fast"] >= real["maximum"]
    assert archive.packed_share([folder]) == 0.0


def test_audio_levels(media_dir, tmp_path):
    wav = media_dir / "tone.wav"
    sizes = []
    for key, *_ in media.AUDIO_LEVELS:
        est = media.estimate_audio(wav, key)
        out = media.compress_audio(wav, level=key)
        real = file_size(out)
        out.rename(tmp_path / f"{key}.mp3")
        sizes.append(real)
        assert 0.85 * real <= est <= 1.2 * real, (key, est, real)
    assert sizes == sorted(sizes, reverse=True)
    probe = subprocess.run([media.ffmpeg_exe(), "-hide_banner", "-i", str(tmp_path / "voice.mp3")],
                           capture_output=True, text=True).stderr
    assert "mono" in probe


def test_video_estimate_is_close(media_dir, tmp_path):
    clip = media_dir / "clip.mp4"
    for q in ("small", "high"):
        est = media.estimate_video(clip, q)
        out = media.compress_video(clip, q)
        real = file_size(out)
        out.rename(tmp_path / f"{q}.mp4")
        assert 0.6 * real <= est <= 1.5 * real, (q, est, real)
