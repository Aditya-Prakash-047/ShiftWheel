"""Print layouts that come out at the right physical size.

* ID card photocopy: find the card in a phone photo, straighten it, and lay front + back at
  real card size (85.6 × 54 mm) on one sheet, like a photocopy shop does.
* Passport photo sheet: N copies of a 35 × 45 mm (or other) photo with cut lines.
* Document scan: straighten a photographed page and clean it up like a scanner.
* Print: fit / actual size / fill, N-up, on any paper.

Every page is rendered at 300 DPI onto a canvas the exact size of the paper, so a PDF
saved here, or printed through `print_pages` (Qt, scaling off), keeps true dimensions."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

try:
    import cv2  # type: ignore
    import numpy as np
    CV_OK = True
except Exception:  # pragma: no cover
    CV_OK = False
    import numpy as np  # numpy is a hard dependency anyway

DPI = 300
PAPERS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "A5": (148.0, 210.0),
    "4×6 photo": (101.6, 152.4),
}
CARD_SIZES: dict[str, tuple[float, float]] = {
    "ID card (85.6 × 54)": (85.6, 54.0),     # ISO 7810 ID-1: Aadhaar PVC, PAN, DL, voter, bank cards
    "Old Aadhaar cut-out (87 × 55)": (87.0, 55.0),
    "Visiting card (90 × 55)": (90.0, 55.0),
    "Large ID (105 × 74)": (105.0, 74.0),      # ID-2 / A7
}
PHOTO_SIZES: dict[str, tuple[float, float]] = {
    "India / UK / EU passport (35 × 45)": (35.0, 45.0),
    "US passport / visa (51 × 51)": (51.0, 51.0),
    "Stamp size (20 × 25)": (20.0, 25.0),
    "Canada passport (50 × 70)": (50.0, 70.0),
    "China visa (33 × 48)": (33.0, 48.0),
}
COLOR_MODES = ["Color", "Grayscale", "Photocopy (B&W)"]


def mm(v: float) -> int:
    """millimetres → pixels at DPI"""
    return int(round(v / 25.4 * DPI))


def paper_px(paper: str, landscape: bool = False) -> tuple[int, int]:
    w, h = PAPERS[paper]
    if landscape:
        w, h = h, w
    return mm(w), mm(h)


def new_page(paper: str, landscape: bool = False) -> Image.Image:
    return Image.new("RGB", paper_px(paper, landscape), "white")


def rgb(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA", "P", "PA"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, "white")
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB") if im.mode != "RGB" else im


# ---------------------------------------------------------------- colour
def apply_color(im: Image.Image, mode: str) -> Image.Image:
    if mode == "Grayscale":
        return ImageOps.grayscale(im).convert("RGB")
    if mode.startswith("Photocopy"):
        g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=2)
        g = ImageEnhance.Contrast(g).enhance(1.5)
        g = g.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
        return g.convert("RGB")
    return rgb(im)


# ---------------------------------------------------------------- quad detection / warp
def order_corners(pts) -> "np.ndarray":
    pts = np.asarray(pts, dtype="float32").reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()  # y - x
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
                    dtype="float32")


def find_quad(img: Image.Image, min_ratio: float = 1.2, max_ratio: float = 2.2,
              min_area: float = 0.10):
    """Corners (tl, tr, br, bl) of the biggest convex 4-sided shape whose side ratio is within
    [min_ratio, max_ratio], in image pixels. None if nothing card/page-like is found."""
    if not CV_OK:
        return None
    arr = np.asarray(rgb(img))
    h, w = arr.shape[:2]
    scale = min(1.0, 1000.0 / max(h, w))
    small = cv2.resize(arr, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    frame = float(sh * sw)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 50, 50)
    kernel = np.ones((5, 5), np.uint8)
    found = []
    for lo, hi in ((20, 60), (40, 120), (75, 200)):
        edges = cv2.Canny(gray, lo, hi)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:6]:
            hull = cv2.convexHull(c)
            area = cv2.contourArea(hull)
            if area < min_area * frame or area > 0.985 * frame:
                continue
            peri = cv2.arcLength(hull, True)
            quad = None
            for eps in (0.02, 0.03, 0.04, 0.06):  # rounded corners need a looser fit
                approx = cv2.approxPolyDP(hull, eps * peri, True)
                if len(approx) == 4:
                    quad = approx.reshape(4, 2).astype("float32")
                    break
            if quad is None:
                box = cv2.boxPoints(cv2.minAreaRect(hull)).astype("float32")
                if area / max(1.0, cv2.contourArea(box)) < 0.88:
                    continue
                quad = box
            q = order_corners(quad)
            W, H = quad_size(q)
            if min(W, H) < 20:
                continue
            ratio = max(W, H) / min(W, H)
            if min_ratio <= ratio <= max_ratio:
                found.append((cv2.contourArea(q), q))
        if found:
            break
    if not found:
        return None
    return max(found, key=lambda t: t[0])[1] / scale


def quad_size(q) -> tuple[float, float]:
    tl, tr, br, bl = [np.asarray(p, dtype="float32") for p in q]
    W = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    H = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    return float(W), float(H)


def default_quad(img: Image.Image, inset: float = 0.08):
    w, h = img.size
    dx, dy = w * inset, h * inset
    return np.array([[dx, dy], [w - dx, dy], [w - dx, h - dy], [dx, h - dy]], dtype="float32")


def warp_quad(img: Image.Image, quad, out_size: tuple[int, int] | None = None) -> Image.Image:
    """Perspective-correct the region inside `quad` (tl, tr, br, bl)."""
    q = np.asarray(quad, dtype="float32").reshape(4, 2)
    W, H = out_size or tuple(int(round(v)) for v in quad_size(q))
    W, H = max(2, W), max(2, H)
    if not CV_OK:  # pragma: no cover - axis-aligned fallback
        xs, ys = q[:, 0], q[:, 1]
        return rgb(img).crop((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))).resize((W, H))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(q, dst)
    out = cv2.warpPerspective(np.asarray(rgb(img)), M, (W, H), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(out)


def find_card(img: Image.Image):
    return find_quad(img, 1.2, 2.2, 0.08)


def find_document(img: Image.Image):
    return find_quad(img, 1.0, 1.9, 0.20)


# ---------------------------------------------------------------- document scan
SCAN_MODES = ["Auto (clean colour)", "Black & white", "Grayscale", "Original"]


def enhance_document(im: Image.Image, mode: str) -> Image.Image:
    im = rgb(im)
    if mode == "Original":
        return im
    if mode == "Grayscale":
        return ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=1).convert("RGB")
    if not CV_OK:  # pragma: no cover
        return ImageOps.autocontrast(im, cutoff=1)
    arr = np.asarray(im).astype(np.float32)
    # flatten lighting: divide by a heavily blurred copy (removes shadows / yellow cast)
    k = max(31, (min(im.size) // 12) | 1)
    bg = cv2.GaussianBlur(arr, (k, k), 0)
    bg = cv2.dilate(bg, np.ones((7, 7), np.uint8))
    flat = np.clip(arr / np.maximum(bg, 1) * 255.0, 0, 255).astype(np.uint8)
    if mode.startswith("Black"):
        g = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY)
        bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 12)
        return Image.fromarray(bw).convert("RGB")
    out = Image.fromarray(flat)
    out = ImageEnhance.Contrast(out).enhance(1.15)
    return ImageEnhance.Color(out).enhance(1.1)


def scan_page(img: Image.Image, quad, paper: str, mode: str, margin_mm: float = 0.0) -> Image.Image:
    """Straightened page scaled to fill `paper` (keeping the page's own aspect)."""
    W, H = quad_size(quad)
    landscape = W > H * 1.05
    pw, ph = paper_px(paper, landscape)
    mpx = mm(margin_mm)
    aw, ah = pw - 2 * mpx, ph - 2 * mpx
    s = min(aw / W, ah / H)
    flat = warp_quad(img, quad, (max(2, int(W * s)), max(2, int(H * s))))
    flat = enhance_document(flat, mode)
    page = Image.new("RGB", (pw, ph), "white")
    page.paste(flat, ((pw - flat.width) // 2, (ph - flat.height) // 2))
    return page


# ---------------------------------------------------------------- layout primitives
def draw_cut_guide(page: Image.Image, x: int, y: int, w: int, h: int) -> None:
    d = ImageDraw.Draw(page)
    d.rectangle([x - 2, y - 2, x + w + 1, y + h + 1], outline=(150, 150, 150), width=2)


def flow_rows(rows, paper, top_mm=12.0, gap_mm=6.0, bottom_mm=10.0, guides=True,
              block_width=None, landscape=False):
    """rows: list of (gap_before_mm, [images]). Rows go top-down, centred; new page when full."""
    pages = []
    page = new_page(paper, landscape)
    pw, ph = page.size
    y = mm(top_mm)
    bottom = ph - mm(bottom_mm)
    empty = True
    for gap_before, cells in rows:
        rw = sum(c.width for c in cells) + mm(gap_mm) * (len(cells) - 1)
        rh = max(c.height for c in cells)
        ny = y if empty else y + mm(gap_before)
        if ny + rh > bottom and not empty:
            pages.append(page)
            page = new_page(paper, landscape)
            ny = mm(top_mm)
        y = ny
        x = (pw - (block_width or rw)) // 2
        for c in cells:
            cy = y + (rh - c.height) // 2
            page.paste(c, (x, cy))
            if guides:
                draw_cut_guide(page, x, cy, c.width, c.height)
            x += c.width + mm(gap_mm)
        y += rh
        empty = False
    pages.append(page)
    return pages


# ---------------------------------------------------------------- ID card sheet
def card_to_box(card: Image.Image, card_mm=(85.6, 54.0)) -> Image.Image:
    """Scale a card image to its exact physical size (portrait cards stay portrait)."""
    cw, ch = max(card_mm), min(card_mm)
    if card.height > card.width:  # vertical college / company ID cards
        cw, ch = ch, cw
    W, H = mm(cw), mm(ch)
    card = rgb(card)
    if abs((card.width / card.height) / (W / H) - 1) <= 0.15:
        return card.resize((W, H), Image.LANCZOS)  # it is the card: exact size
    c = ImageOps.contain(card, (W, H), Image.LANCZOS)  # not card-shaped: fit, don't distort
    box = Image.new("RGB", (W, H), "white")
    box.paste(c, ((W - c.width) // 2, (H - c.height) // 2))
    return box


def id_sheet(cards: list[Image.Image], paper: str = "A4", color: str = "Color", copies: int = 1,
             pairs: bool = True, card_mm=(85.6, 54.0), guides: bool = True) -> list[Image.Image]:
    """cards: already straightened card images, in order front, back, front, back…

    copies == 1 → the classic photocopy: front above back, top of the page.
    copies > 1  → rows of [front | back], repeated."""
    boxes = [card_to_box(apply_color(c, color), card_mm) for c in cards]
    if not boxes:
        return [new_page(paper)]
    copies = max(1, int(copies))
    rows = []
    if pairs:
        for i in range(0, len(boxes), 2):
            g = boxes[i:i + 2]
            if copies == 1:
                rows.append((14, [g[0]]))
                rows += [(8, [c]) for c in g[1:]]
            else:
                rows += [(14 if k == 0 else 6, list(g)) for k in range(copies)]
    else:
        for c in boxes:
            cs = [c] * copies
            rows += [(8, cs[i:i + 2]) for i in range(0, len(cs), 2)]
    return flow_rows(rows, paper, top_mm=15, gap_mm=8, guides=guides)


# ---------------------------------------------------------------- passport sheet
def passport_sheet(photo: Image.Image, size_mm=(35.0, 45.0), copies: int = 8, paper: str = "A4",
                   color: str = "Color", guides: bool = True, border_mm: float = 0.0) -> list[Image.Image]:
    """`photo` should already be cropped to the right aspect; it's centre-fitted anyway."""
    W, H = mm(size_mm[0]), mm(size_mm[1])
    cell = ImageOps.fit(apply_color(photo, color), (W, H), Image.LANCZOS, centering=(0.5, 0.4))
    if border_mm > 0:
        b = mm(border_mm)
        framed = Image.new("RGB", (W + 2 * b, H + 2 * b), "white")
        framed.paste(cell, (b, b))
        cell = framed
    pw, _ = paper_px(paper)
    gap = mm(2.5)
    margin = mm(5 if paper == "4×6 photo" else 8)
    cols = max(1, (pw - 2 * margin + gap) // (cell.width + gap))
    cells = [cell] * max(1, int(copies))
    rows = [(2.5, cells[i:i + cols]) for i in range(0, len(cells), cols)]
    block = cols * cell.width + (cols - 1) * gap
    top = 6 if paper == "4×6 photo" else 10
    return flow_rows(rows, paper, top_mm=top, gap_mm=2.5, bottom_mm=5, guides=guides, block_width=block)


# ---------------------------------------------------------------- general print layout
@dataclass
class PrintLayout:
    paper: str = "A4"
    mode: str = "fit"          # fit | fill | actual
    orientation: str = "auto"  # auto | portrait | landscape
    margin_mm: float = 6.0
    per_page: int = 1          # 1, 2, 4, 6, 9 (N-up)
    color: str = "Color"


def _grid(n: int, landscape: bool) -> tuple[int, int]:
    """columns, rows for n-up."""
    table = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 9: (3, 3), 12: (3, 4)}
    c, r = table.get(n, (math.ceil(math.sqrt(n)), math.ceil(n / math.ceil(math.sqrt(n)))))
    return (r, c) if landscape else (c, r)


def layout_pages(images: list[Image.Image], L: PrintLayout, dpis: list[float] | None = None) -> list[Image.Image]:
    """Place images on pages. `dpis` (one per image) is used by mode 'actual'."""
    pages = []
    n = max(1, int(L.per_page))
    for start in range(0, len(images), n):
        chunk = images[start:start + n]
        if L.orientation == "auto":
            # one per page: follow the image; N-up: portrait sheet, cells rotate to fit
            landscape = n == 1 and chunk[0].width > chunk[0].height * 1.05
        else:
            landscape = L.orientation == "landscape"
        page = new_page(L.paper, landscape)
        pw, ph = page.size
        m = mm(L.margin_mm)
        cols, rows = _grid(n, landscape)
        gap = mm(4) if n > 1 else 0
        cw = (pw - 2 * m - gap * (cols - 1)) // cols
        chh = (ph - 2 * m - gap * (rows - 1)) // rows
        for k, im in enumerate(chunk):
            im = apply_color(im, L.color)
            cx = m + (k % cols) * (cw + gap)
            cy = m + (k // cols) * (chh + gap)
            if n > 1 and (im.width > im.height) != (cw > chh):
                im = im.rotate(90, expand=True)   # use the cell better
            if L.mode == "fill":
                placed = ImageOps.fit(im, (cw, chh), Image.LANCZOS)
            elif L.mode == "actual" and dpis:
                dpi = dpis[start + k] or 300.0
                tw, th = int(im.width / dpi * DPI), int(im.height / dpi * DPI)
                if tw > cw or th > chh:  # bigger than the paper: shrink to fit
                    placed = ImageOps.contain(im, (cw, chh), Image.LANCZOS)
                else:
                    placed = im.resize((max(1, tw), max(1, th)), Image.LANCZOS)
            else:
                placed = ImageOps.contain(im, (cw, chh), Image.LANCZOS)
            page.paste(placed, (cx + (cw - placed.width) // 2, cy + (chh - placed.height) // 2))
        pages.append(page)
    return pages or [new_page(L.paper)]


def image_dpi(path: str | Path) -> float:
    try:
        with Image.open(path) as im:
            d = im.info.get("dpi")
            if d and d[0] and d[0] > 30:
                return float(d[0])
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------- output
def save_pdf(pages: list[Image.Image], out: str | Path, color: str = "Color") -> Path:
    from .convert import atomic_save
    if color != "Color":
        pages = [p.convert("L") for p in pages]
    out = Path(out)

    def write(dst):
        pages[0].save(dst, "PDF", resolution=float(DPI), save_all=True, append_images=pages[1:], quality=92)
    atomic_save(write, out)
    return out


def page_size_mm(page: Image.Image) -> tuple[float, float]:
    return page.width / DPI * 25.4, page.height / DPI * 25.4


def printer_names() -> tuple[list[str], str]:
    try:
        from PySide6.QtPrintSupport import QPrinterInfo
        return list(QPrinterInfo.availablePrinterNames()), QPrinterInfo.defaultPrinterName()
    except Exception:
        return [], ""


def print_pages(pages: list[Image.Image], printer_name: str = "", copies: int = 1,
                pdf_file: str | None = None, title: str = "ShiftWheel") -> None:
    """Print at 100 %: each page image is drawn over the whole sheet, so 1 mm stays 1 mm.
    `pdf_file` prints to a PDF through Qt instead (used by the tests)."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPainter
    from PySide6.QtPrintSupport import QPrinter

    from .glass import qimage_from_pil

    printer = QPrinter(QPrinter.HighResolution)
    if pdf_file:
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(str(pdf_file))
    elif printer_name:
        printer.setPrinterName(printer_name)
    printer.setDocName(title)
    printer.setCopyCount(max(1, int(copies)))
    printer.setFullPage(True)

    def setup(pg):
        w, h = page_size_mm(pg)
        landscape = w > h
        size = QPageSize(QSizeF(min(w, h), max(w, h)), QPageSize.Millimeter, "", QPageSize.ExactMatch)
        printer.setPageLayout(QPageLayout(size, QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                          QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter))

    setup(pages[0])
    painter = QPainter()
    if not painter.begin(printer):
        raise RuntimeError("Couldn't start the printer. Is it connected and switched on?")
    try:
        for i, pg in enumerate(pages):
            if i:
                setup(pg)
                printer.newPage()
            target = printer.paperRect(QPrinter.DevicePixel)
            painter.drawImage(target, qimage_from_pil(rgb(pg)))
    finally:
        painter.end()
