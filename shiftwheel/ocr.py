"""Offline text recognition (RapidOCR / PP-OCR models bundled, nothing uploaded).

* image → text (in reading order)
* PDF or images → searchable PDF (invisible text layer over the page, so you can select,
  copy and search the scanned text)"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .util import UserError, sibling

_ENGINE = None
_LOCK = threading.RLock()   # re-entrant: recognize() holds it while engine() loads


def available() -> bool:
    try:
        import rapidocr  # noqa: F401  (availability check)
        return True
    except Exception:
        return False


def engine():
    global _ENGINE
    with _LOCK:
        if _ENGINE is None:
            try:
                from rapidocr import RapidOCR
            except Exception as e:
                raise UserError("Text recognition isn't included in this build.") from e
            for name in ("RapidOCR", "rapidocr"):
                logging.getLogger(name).setLevel(logging.ERROR)
            _ENGINE = RapidOCR(params={"Global.log_level": "warning"}) if _accepts_params() else RapidOCR()
        return _ENGINE


def _accepts_params() -> bool:
    import inspect
    from rapidocr import RapidOCR
    try:
        return "params" in inspect.signature(RapidOCR.__init__).parameters
    except (TypeError, ValueError):
        return False


def recognize(im: Image.Image) -> list[tuple[np.ndarray, str, float]]:
    """[(box 4×2 in pixels, text, score)] for one image."""
    im = im.convert("RGB")
    scale = 1.0
    if max(im.size) > 3000:              # keep it fast on big scans
        scale = 3000 / max(im.size)
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    with _LOCK:
        r = engine()(np.asarray(im)[:, :, ::-1])   # BGR, like cv2
    if r is None or getattr(r, "boxes", None) is None or r.txts is None:
        return []
    return [(np.asarray(b, dtype="float32") / scale, t, float(s))
            for b, t, s in zip(r.boxes, r.txts, r.scores) if t and s >= 0.5]


def to_lines(items) -> str:
    """Group boxes into lines (similar baseline) and lines into text."""
    if not items:
        return ""
    rows = sorted(items, key=lambda it: (it[0][:, 1].mean(), it[0][:, 0].min()))
    lines, cur, cur_y, cur_h = [], [], None, 0.0
    for box, text, _ in rows:
        y = box[:, 1].mean()
        h = box[:, 1].max() - box[:, 1].min()
        if cur and abs(y - cur_y) > max(cur_h, h) * 0.6:
            lines.append(cur)
            cur = []
        if not cur:
            cur_y, cur_h = y, h
        cur.append((float(box[:, 0].min()), float(box[:, 0].max()), text))
    if cur:
        lines.append(cur)
    return "\n".join(_join_line(sorted(line)) for line in lines)


def _join_line(items) -> str:
    """Join word boxes left→right. The detector sometimes lets a box run into the next one
    ('Selftest 2' + '2026'); drop characters that sit inside the following box *and* repeat
    its start. Boxes are padded, so neighbours nearly always overlap a little: an overlap
    alone is no reason to cut letters."""
    out = []
    for k, (x0, x1, text) in enumerate(items):
        if k + 1 < len(items):
            nx0, nxt = items[k + 1][0], items[k + 1][2].strip()
            overlap = x1 - nx0
            if overlap > 0 and len(text) > 1:
                char_w = (x1 - x0) / len(text)
                drop = int(round(overlap / max(char_w, 1.0)))
                for d in range(min(drop + 1, len(text) - 1), 0, -1):
                    tail = text[-d:].strip()
                    if tail and nxt.startswith(tail):
                        text = text[:-d]
                        break
        text = text.strip()
        if text:
            out.append(text)
    return " ".join(out)


def image_text(path) -> str:
    from .convert import open_image
    return to_lines(recognize(open_image(path)))


def image_to_txt(path) -> list[Path]:
    text = image_text(path)
    if not text.strip():
        raise UserError("No text found in this image.")
    out = sibling(path, "Text", ".txt")
    out.write_text(text, encoding="utf-8")
    return [out]


def make_searchable(pdf_in, out=None, dpi: int = 200, progress=None) -> Path:
    """Add an invisible OCR text layer to every page that doesn't already have text."""
    from .convert import fitz, open_pdf
    pdf_in = Path(pdf_in)
    out = Path(out) if out else sibling(pdf_in, "Searchable", ".pdf")
    with open_pdf(pdf_in) as doc:
        n = doc.page_count
        for i, page in enumerate(doc):
            if page.get_text("text").strip():
                continue    # already has real text
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            k = 72.0 / dpi
            for box, text, _ in recognize(im):
                x0, y0 = float(box[:, 0].min()) * k, float(box[:, 1].min()) * k
                x1, y1 = float(box[:, 0].max()) * k, float(box[:, 1].max()) * k
                h = max(1.0, y1 - y0)
                size = h * 0.82
                width = fitz.get_text_length(text, fontname="helv", fontsize=size) or 1.0
                # stretch the invisible text horizontally to cover the word box
                m = fitz.Matrix((x1 - x0) / width, 1)
                page.insert_text(fitz.Point(x0, y1 - h * 0.2), text, fontsize=size, fontname="helv",
                                 render_mode=3, morph=(fitz.Point(x0, y1 - h * 0.2), m))
            if progress:
                progress((i + 1) / n)
        tmp = out.with_name(f".~{out.name}.part")
        doc.save(tmp, garbage=3, deflate=True)
    tmp.replace(out)
    return out


def images_to_searchable_pdf(paths, progress=None) -> Path:
    from .convert import images_to_single_pdf
    pdf = images_to_single_pdf(paths)[0]
    try:
        out = make_searchable(pdf, sibling(paths[0], "Searchable", ".pdf"), progress=progress)
    finally:
        pdf.unlink(missing_ok=True)
    return out
