"""Print ring windows: ID Card, Passport, Scan, Print.

Each shows a live preview of the exact sheet that will be saved or printed, and ends with
Save PDF / Print. Printing goes through Qt with scaling off, so sizes stay true."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)

from . import printing as P
from .convert import fitz, open_image, open_pdf
from .glass import qimage_from_pil
from .tools import CropView, ToolWindow, section, toggle_row
from .util import category, sibling
from .window import ImageView

PREVIEW_MAX = 1400   # px: working copies of photos for the on-screen editors


# ---------------------------------------------------------------- sources
def load_sources(paths, max_pages: int = 20) -> list[tuple[str, Image.Image]]:
    """Images as-is; PDFs become one image per page (300 dpi). -> [(label, image)]"""
    out = []
    for p in paths:
        p = Path(p)
        if category(p) == "pdf":
            with open_pdf(p) as doc:
                for i, page in enumerate(doc):
                    if i >= max_pages:
                        break
                    pix = page.get_pixmap(dpi=300, alpha=False)
                    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    out.append((f"{p.stem} p{i + 1}" if doc.page_count > 1 else p.stem, im))
        elif category(p) == "image":
            out.append((p.stem, P.rgb(open_image(p))))
    return out


def small(im: Image.Image) -> tuple[Image.Image, float]:
    """Reduced working copy and the factor back to full resolution."""
    if max(im.size) <= PREVIEW_MAX:
        return im, 1.0
    s = im.copy()
    s.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
    return s, im.width / s.width


# ---------------------------------------------------------------- widgets
class QuadView(ImageView):
    """Image with four draggable corners (like a phone scanner app)."""
    R = 9

    def __init__(self, image: QImage, quad):
        super().__init__(image)
        self.quad = [QPointF(float(x), float(y)) for x, y in quad]
        self.drag = -1
        self.setCursor(Qt.CrossCursor)

    def set_quad(self, quad):
        self.quad = [QPointF(float(x), float(y)) for x, y in quad]
        self.update()
        self.changed.emit()

    def quad_array(self) -> np.ndarray:
        return np.array([[p.x(), p.y()] for p in self.quad], dtype="float32")

    def mousePressEvent(self, e):
        pos = e.position()
        best, bd = -1, 1e9
        for i, q in enumerate(self.quad):
            d = (self.to_widget(q) - pos).manhattanLength()
            if d < bd:
                best, bd = i, d
        self.drag = best if bd < 40 else -1

    def mouseMoveEvent(self, e):
        if self.drag < 0:
            return
        p = self.to_image(e.position())
        p.setX(min(max(0.0, p.x()), self.image.width() - 1))
        p.setY(min(max(0.0, p.y()), self.image.height() - 1))
        self.quad[self.drag] = p
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag >= 0:
            self.drag = -1
            self.changed.emit()

    def paint_overlay(self, p: QPainter, t: QRectF):
        pts = [self.to_widget(q) for q in self.quad]
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        poly = QPainterPath()
        poly.moveTo(pts[0])
        for q in pts[1:]:
            poly.lineTo(q)
        poly.closeSubpath()
        p.fillPath(shade.subtracted(poly), QColor(0, 0, 0, 110))
        p.setPen(QPen(QColor(255, 120, 60), 2))
        p.drawPath(poly)
        p.setBrush(QColor(255, 255, 255))
        for q in pts:
            p.drawEllipse(q, self.R, self.R)


class SheetPreview(QWidget):
    """Shows rendered pages with ‹ › navigation."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(300, 380)
        self.label.setStyleSheet("background: rgba(0,0,0,0.18); border-radius: 10px;")
        lay.addWidget(self.label, 1)
        nav = QHBoxLayout()
        self.prev, self.next = QPushButton("‹"), QPushButton("›")
        self.info = QLabel("")
        self.info.setObjectName("dim")
        self.info.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.prev)
        nav.addWidget(self.info, 1)
        nav.addWidget(self.next)
        lay.addLayout(nav)
        self.prev.clicked.connect(lambda: self.go(-1))
        self.next.clicked.connect(lambda: self.go(1))
        self.pages: list[Image.Image] = []
        self.i = 0

    def set_pages(self, pages: list[Image.Image], caption: str = ""):
        self.pages = pages
        self.caption = caption
        self.i = min(self.i, len(pages) - 1) if pages else 0
        self._show()

    def go(self, d):
        if self.pages:
            self.i = max(0, min(len(self.pages) - 1, self.i + d))
            self._show()

    def _show(self):
        if not self.pages:
            self.label.clear()
            return
        pg = self.pages[self.i]
        box = self.label.size()
        th = pg.copy()
        th.thumbnail((max(80, box.width() - 16), max(80, box.height() - 16)), Image.LANCZOS)
        pm = QPixmap.fromImage(qimage_from_pil(th))
        # paper drop shadow
        canvas = QPixmap(pm.width() + 8, pm.height() + 8)
        canvas.fill(Qt.transparent)
        pa = QPainter(canvas)
        pa.fillRect(6, 6, pm.width(), pm.height(), QColor(0, 0, 0, 70))
        pa.drawPixmap(0, 0, pm)
        pa.end()
        self.label.setPixmap(canvas)
        n = len(self.pages)
        w, h = P.page_size_mm(pg)
        self.info.setText(f"Page {self.i + 1} of {n}  ·  {w:.0f} × {h:.0f} mm" +
                          (f"  ·  {self.caption}" if self.caption else ""))
        self.prev.setEnabled(self.i > 0)
        self.next.setEnabled(self.i < n - 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._show()


def combo(items, current=None) -> QComboBox:
    c = QComboBox()
    c.addItems(list(items))
    if current is not None:
        c.setCurrentText(current)
    return c


class PrintableWindow(ToolWindow):
    """Base: options on the left, live sheet preview on the right, Save PDF / Print footer."""
    suffix = "Print"
    working_text = "Saving PDF…"

    def __init__(self, title, paths, notify, size=(1080, 760)):
        super().__init__(title, paths, notify, size=size)
        self.cols = QHBoxLayout()
        self.cols.setSpacing(16)
        self.left = QVBoxLayout()
        self.cols.addLayout(self.left, 5)
        self.preview = SheetPreview()
        self.cols.addWidget(self.preview, 4)
        self.body.addLayout(self.cols, 1)
        self.pages: list[Image.Image] = []
        self.timer = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)

    def build_footer(self):
        printers, default = P.printer_names()
        self.printer = combo(printers or ["(no printer found)"], default or None)
        self.printer.setMinimumWidth(200)
        self.copies = QSpinBox()
        self.copies.setRange(1, 99)
        self.copies.setPrefix("× ")
        self.save_btn = QPushButton("Save PDF")
        self.save_btn.clicked.connect(self.save_pdf)
        lab = QLabel("Printer")
        lab.setObjectName("dim")
        row = self.footer("Print", self.print_now, None, extra_buttons=[lab, self.printer, self.copies])
        row.insertWidget(row.count() - 2, self.save_btn)
        if not printers:
            self.primary_btn.setEnabled(False)
            self.primary_btn.setToolTip("No printer is installed")
        self.body.addLayout(row)
        self.schedule()

    # subclasses implement
    def render_pages(self, full: bool = False) -> list[Image.Image]:
        """full=False: quick preview; full=True: full resolution for saving/printing."""
        raise NotImplementedError

    def save_extra(self) -> str:
        return self.caption()

    def color_mode(self) -> str:
        return "Color"

    def caption(self) -> str:
        return ""

    def schedule(self, *_):
        self.timer.start()

    def refresh(self):
        try:
            self.pages = self.render_pages()
            self.preview.set_pages(self.pages, self.caption())
        except Exception as e:  # noqa: BLE001
            self.preview.info.setText(f"⚠ {e}")

    def out_path(self) -> Path:
        return sibling(self.path, self.suffix, ".pdf")

    def save_pdf(self):
        pages = self.render_pages(full=True)
        color, out = self.color_mode(), self.out_path()
        self.run(lambda: [P.save_pdf(pages, out, color)], self.working_text, self.save_extra())

    def print_now(self):
        pages = self.render_pages(full=True)
        name = self.printer.currentText()
        try:
            P.print_pages(pages, name, self.copies.value(), title=self.path.name)
        except Exception as e:  # noqa: BLE001
            self.preview.info.setText(f"⚠ {e}")
            return
        self.notify(f"tool:{self.tool_name}", [str(p) for p in self.paths], [],
                    f"Sent {len(pages)} page{'s' if len(pages) != 1 else ''} to {name} at 100% scale")
        self.close()


# ================================================================ ID CARD
class IDCardWindow(PrintableWindow):
    tool_name = "ID Card"
    suffix = "ID Card"
    working_text = "Making ID card sheet…"

    def __init__(self, paths, notify):
        super().__init__("ID Card Photocopy", paths, notify)
        srcs = load_sources(self.paths, max_pages=4)
        if not srcs:
            raise ValueError("Drop a photo or scan of the card.")
        self.full = [im for _, im in srcs]
        self.names = [n for n, _ in srcs]
        self.work = [small(im) for im in self.full]
        self.quads = []
        self.detected = []
        for im, k in self.work:
            q = P.find_card(im)
            self.detected.append(q is not None)
            self.quads.append(q if q is not None else P.default_quad(im, 0.0))
        self.order = list(range(len(self.full)))
        self.cur = 0

        self.left.addWidget(section("Card edges — drag the corners if needed"))
        sel = QHBoxLayout()
        labels = ["Front", "Back"] + [f"Card {i + 1}" for i in range(2, len(self.full))]
        row, self.side = toggle_row(labels[:len(self.full)])
        self.side.idClicked.connect(self.pick)
        sel.addLayout(row)
        swap = QPushButton("⇅ Swap front/back")
        swap.clicked.connect(self.swap)
        swap.setVisible(len(self.full) >= 2)
        sel.addWidget(swap)
        redetect = QPushButton("Auto-detect")
        redetect.clicked.connect(self.redetect)
        sel.addWidget(redetect)
        self.left.addLayout(sel)
        im0, _ = self.work[0]
        self.view = QuadView(qimage_from_pil(im0), self.quads[0])
        self.view.changed.connect(self._quad_changed)
        self.left.addWidget(self.view, 1)
        self.note = QLabel("")
        self.note.setObjectName("dim")
        self.note.setWordWrap(True)
        self.left.addWidget(self.note)

        g = QGridLayout()
        self.card = combo(P.CARD_SIZES)
        self.paper = combo(P.PAPERS, "A4")
        self.color = combo(P.COLOR_MODES)
        self.sets = QSpinBox()
        self.sets.setRange(1, 5)
        self.sets.setSuffix(" per sheet")
        self.guides = QCheckBox("Cut lines")
        self.guides.setChecked(True)
        self.pairs = QCheckBox("Front + back of one card")
        self.pairs.setChecked(len(self.full) >= 2)
        for r, (lab, w) in enumerate((("Card size", self.card), ("Paper", self.paper), ("Colour", self.color),
                                      ("Copies", self.sets))):
            g.addWidget(QLabel(lab), r // 2, (r % 2) * 2)
            g.addWidget(w, r // 2, (r % 2) * 2 + 1)
        g.addWidget(self.pairs, 2, 0, 1, 2)
        g.addWidget(self.guides, 2, 2, 1, 2)
        self.left.addLayout(g)
        for w in (self.card, self.paper, self.color):
            w.currentIndexChanged.connect(self.schedule)
        self.sets.valueChanged.connect(self.schedule)
        self.guides.toggled.connect(self.schedule)
        self.pairs.toggled.connect(self.schedule)
        self._update_note()
        self.build_footer()

    def pick(self, i):
        self.cur = self.order[i]
        im, _ = self.work[self.cur]
        self.view.set_image(qimage_from_pil(im))
        self.view.set_quad(self.quads[self.cur])
        self._update_note()

    def swap(self):
        if len(self.order) >= 2:
            self.order[0], self.order[1] = self.order[1], self.order[0]
            self.pick(self.side.checkedId())
            self.schedule()

    def redetect(self):
        im, _ = self.work[self.cur]
        q = P.find_card(im)
        self.detected[self.cur] = q is not None
        self.quads[self.cur] = q if q is not None else P.default_quad(im, 0.0)
        self.view.set_quad(self.quads[self.cur])
        self._update_note()

    def _quad_changed(self):
        self.quads[self.cur] = self.view.quad_array()
        self.schedule()

    def _update_note(self):
        name = self.names[self.cur]
        if self.detected[self.cur]:
            self.note.setText(f"✓ Card found in {name}. It's straightened and printed at real size.")
        else:
            self.note.setText(f"Card edges not found in {name} — drag the four corners onto the card's corners. "
                              "(Tip: shoot the card on a dark, plain surface.)")

    def cards(self, full: bool) -> list[Image.Image]:
        out = []
        for i in self.order:
            im, k = self.work[i]
            q = self.quads[i]
            if full:
                out.append(P.warp_quad(self.full[i], np.asarray(q) * k))
            else:
                out.append(P.warp_quad(im, q))
        return out

    def render_pages(self, full: bool = False):
        return P.id_sheet(self.cards(full), self.paper.currentText(), self.color.currentText(),
                          self.sets.value(), self.pairs.isChecked(), P.CARD_SIZES[self.card.currentText()],
                          self.guides.isChecked())

    def color_mode(self):
        return self.color.currentText()

    def caption(self):
        w, h = P.CARD_SIZES[self.card.currentText()]
        return f"card {w:g} × {h:g} mm"




# ================================================================ PASSPORT
class PassportWindow(PrintableWindow):
    tool_name = "Passport"
    suffix = "Passport Photos"
    working_text = "Making passport photo sheet…"

    def __init__(self, paths, notify):
        super().__init__("Passport Photo Sheet", paths, notify)
        self.full = P.rgb(open_image(self.path))
        self.work, self.k = small(self.full)
        self.left.addWidget(section("Frame the face — head about 70% of the height"))
        self.view = CropView(qimage_from_pil(self.work), self.k)
        self.left.addWidget(self.view, 1)
        g = QGridLayout()
        self.psize = combo(P.PHOTO_SIZES)
        self.paper = combo(P.PAPERS, "A4")
        self.color = combo(P.COLOR_MODES[:2])
        self.n = QSpinBox()
        self.n.setRange(1, 60)
        self.n.setValue(8)
        self.n.setSuffix(" photos")
        self.border = QCheckBox("White border")
        self.guides = QCheckBox("Cut lines")
        self.guides.setChecked(True)
        for r, (lab, w) in enumerate((("Size", self.psize), ("Paper", self.paper), ("Copies", self.n),
                                      ("Colour", self.color))):
            g.addWidget(QLabel(lab), r // 2, (r % 2) * 2)
            g.addWidget(w, r // 2, (r % 2) * 2 + 1)
        g.addWidget(self.border, 2, 0, 1, 2)
        g.addWidget(self.guides, 2, 2, 1, 2)
        self.left.addLayout(g)
        self.jpg_btn = QPushButton("Save JPG (photo lab)")
        self.jpg_btn.clicked.connect(self.save_jpg)
        self.left.addWidget(self.jpg_btn, 0, Qt.AlignLeft)
        for w in (self.psize, self.paper, self.color):
            w.currentIndexChanged.connect(self.schedule)
        self.psize.currentIndexChanged.connect(self._ratio)
        self.n.valueChanged.connect(self.schedule)
        self.border.toggled.connect(self.schedule)
        self.guides.toggled.connect(self.schedule)
        self.view.changed.connect(self.schedule)
        self._ratio()
        self.build_footer()

    def _ratio(self):
        w, h = P.PHOTO_SIZES[self.psize.currentText()]
        self.view.set_ratio(w / h)
        self.schedule()

    def photo(self, full: bool) -> Image.Image:
        s = self.view.sel
        if full:
            k = self.k
            return self.full.crop((round(s.left() * k), round(s.top() * k), round(s.right() * k), round(s.bottom() * k)))
        return self.work.crop((round(s.left()), round(s.top()), round(s.right()), round(s.bottom())))

    def render_pages(self, full: bool = False):
        return P.passport_sheet(self.photo(full), P.PHOTO_SIZES[self.psize.currentText()], self.n.value(),
                                self.paper.currentText(), self.color.currentText(), self.guides.isChecked(),
                                1.0 if self.border.isChecked() else 0.0)

    def caption(self):
        w, h = P.PHOTO_SIZES[self.psize.currentText()]
        return f"{self.n.value()} × {w:g}×{h:g} mm"

    def color_mode(self):
        return self.color.currentText()


    def save_jpg(self):
        pages = self.render_pages(full=True)
        base = sibling(self.path, self.suffix, ".jpg")

        def work():
            outs = []
            for i, pg in enumerate(pages):
                o = base if i == 0 else sibling(self.path, f"{self.suffix} {i + 1}", ".jpg")
                pg.save(o, "JPEG", quality=95, dpi=(P.DPI, P.DPI))
                outs.append(o)
            return outs
        self.run(work, self.working_text, self.caption())



# ================================================================ SCAN (document)
class ScanWindow(PrintableWindow):
    tool_name = "Scan"
    suffix = "Scan"
    working_text = "Scanning to PDF…"

    def __init__(self, paths, notify):
        super().__init__("Scan to PDF", paths, notify)
        srcs = load_sources(self.paths, max_pages=50)
        if not srcs:
            raise ValueError("Drop photos of the pages.")
        self.full = [im for _, im in srcs]
        self.work = [small(im) for im in self.full]
        self.quads, self.found = [], []
        for im, _ in self.work:
            q = P.find_document(im)
            self.found.append(q is not None)
            self.quads.append(q if q is not None else P.default_quad(im, 0.0))
        self.cur = 0
        self.left.addWidget(section("Page edges — drag the corners if needed"))
        nav = QHBoxLayout()
        self.prev, self.next = QPushButton("‹ Page"), QPushButton("Page ›")
        self.which = QLabel("")
        self.which.setObjectName("dim")
        nav.addWidget(self.prev)
        nav.addWidget(self.which, 1, Qt.AlignCenter)
        nav.addWidget(self.next)
        self.prev.clicked.connect(lambda: self.pick(self.cur - 1))
        self.next.clicked.connect(lambda: self.pick(self.cur + 1))
        self.left.addLayout(nav)
        self.view = QuadView(qimage_from_pil(self.work[0][0]), self.quads[0])
        self.view.changed.connect(self._changed)
        self.left.addWidget(self.view, 1)
        g = QGridLayout()
        self.mode = combo(P.SCAN_MODES)
        self.paper = combo(P.PAPERS, "A4")
        g.addWidget(QLabel("Look"), 0, 0)
        g.addWidget(self.mode, 0, 1)
        g.addWidget(QLabel("Paper"), 0, 2)
        g.addWidget(self.paper, 0, 3)
        from . import ocr
        self.searchable = QCheckBox("Searchable text (OCR, offline)")
        self.searchable.setChecked(ocr.available())
        self.searchable.setEnabled(ocr.available())
        g.addWidget(self.searchable, 1, 0, 1, 4)
        self.left.addLayout(g)
        self.mode.currentIndexChanged.connect(self.schedule)
        self.paper.currentIndexChanged.connect(self.schedule)
        self.pick(0)
        self.build_footer()

    def pick(self, i):
        self.cur = max(0, min(len(self.work) - 1, i))
        self.view.set_image(qimage_from_pil(self.work[self.cur][0]))
        self.view.set_quad(self.quads[self.cur])
        found = "page found" if self.found[self.cur] else "drag the corners onto the page"
        self.which.setText(f"{self.cur + 1} / {len(self.work)} · {found}")
        self.prev.setEnabled(self.cur > 0)
        self.next.setEnabled(self.cur < len(self.work) - 1)

    def _changed(self):
        self.quads[self.cur] = self.view.quad_array()
        self.schedule()

    def render_pages(self, full: bool = False):
        mode, paper = self.mode.currentText(), self.paper.currentText()
        pages = []
        for i, (im, k) in enumerate(self.work):
            if full:
                pages.append(P.scan_page(self.full[i], np.asarray(self.quads[i]) * k, paper, mode))
            else:
                pages.append(P.scan_page(im, self.quads[i], paper, mode))
        return pages

    def color_mode(self):
        m = self.mode.currentText()
        return "Grayscale" if m.startswith(("Black", "Gray")) else "Color"

    def caption(self):
        return self.mode.currentText()

    def save_pdf(self):
        pages = self.render_pages(full=True)
        color, out, ocr_on = self.color_mode(), self.out_path(), self.searchable.isChecked()

        def work(progress=None):
            from . import ocr
            if not ocr_on:
                return [P.save_pdf(pages, out, color)]
            # the PDF only appears once it has its text layer: never a half-done file
            tmp = out.with_name(f".~{out.stem} scan.pdf")
            try:
                P.save_pdf(pages, tmp, color)
                ocr.make_searchable(tmp, out, progress=progress)
            finally:
                tmp.unlink(missing_ok=True)
            return [out]
        self.run(work, self.working_text, self.save_extra())

    def save_extra(self):
        n = len(self.work)
        return f"{n} page{'s' if n != 1 else ''} · {self.mode.currentText()}"



# ================================================================ PRINT
class PrintWindow(PrintableWindow):
    tool_name = "Print"
    suffix = "Print"
    working_text = "Saving print layout…"
    MODES = [("Fit to page", "fit"), ("Fill page (crop)", "fill"), ("Actual size", "actual")]

    def __init__(self, paths, notify):
        super().__init__("Print", paths, notify)
        self.is_pdf = category(self.path) == "pdf"
        self.srcs = load_sources(self.paths, max_pages=200)
        if not self.srcs:
            raise ValueError("Nothing printable here.")
        self.dpis = []
        for p in self.paths:
            if category(p) == "pdf":
                with fitz.open(p) as d:
                    self.dpis += [300.0] * min(d.page_count, 200)
            else:
                self.dpis.append(P.image_dpi(p))
        self.thumbs = [small(im)[0] for _, im in self.srcs]
        self.left.addWidget(section("Layout"))
        row, self.mode = toggle_row([m for m, _ in self.MODES], 2 if self.is_pdf else 0)
        self.mode.idClicked.connect(self.schedule)
        self.left.addLayout(row)
        g = QGridLayout()
        self.paper = combo(P.PAPERS, "A4")
        self.orient = combo(["Auto", "Portrait", "Landscape"])
        self.per = combo(["1", "2", "4", "6", "9"])
        self.color = combo(P.COLOR_MODES)
        self.margin = QSpinBox()
        self.margin.setRange(0, 40)
        self.margin.setValue(0 if self.is_pdf else 6)
        self.margin.setSuffix(" mm margin")
        for r, (lab, w) in enumerate((("Paper", self.paper), ("Orientation", self.orient),
                                      ("Per sheet", self.per), ("Colour", self.color), ("Margin", self.margin))):
            g.addWidget(QLabel(lab), r // 2, (r % 2) * 2)
            g.addWidget(w, r // 2, (r % 2) * 2 + 1)
        self.left.addLayout(g)
        tip = QLabel("Actual size keeps the file's real dimensions (PDF pages, or the image's DPI). "
                     "ShiftWheel prints at 100% scale — the printer never shrinks it.")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        self.left.addWidget(tip)
        self.left.addStretch(1)
        for w in (self.paper, self.orient, self.per, self.color):
            w.currentIndexChanged.connect(self.schedule)
        self.margin.valueChanged.connect(self.schedule)
        self.build_footer()

    def print_layout(self) -> P.PrintLayout:
        return P.PrintLayout(self.paper.currentText(), self.MODES[self.mode.checkedId()][1],
                             self.orient.currentText().lower(), float(self.margin.value()),
                             int(self.per.currentText()), self.color.currentText())

    def render_pages(self, full: bool = False):
        L = self.print_layout()
        if full:
            ims = [im for _, im in self.srcs]
            dpis = self.dpis
        else:
            ims = self.thumbs
            dpis = [(d or 300.0) * t.width / im.width for d, t, (_, im) in zip(self.dpis, self.thumbs, self.srcs)]
        return P.layout_pages(ims, L, dpis)

    def color_mode(self):
        return self.color.currentText()

    def caption(self):
        return self.MODES[self.mode.checkedId()][0]


