"""Format conversions. Every function takes a source path and returns a list of
output paths written next to the source."""
from __future__ import annotations

import html
import io
import sys
from pathlib import Path

from PIL import Image, ImageOps

from .util import LazyModule, UserError, sibling

try:  # HEIC / HEIF support
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

# loaded on the first PDF job, not at start-up; its optional layout add-on is left out on purpose
fitz = LazyModule("pymupdf", "fitz", on_load=lambda m: getattr(m, "no_recommend_layout", lambda: None)())

IMAGE_TARGETS = ["PNG", "JPG", "WEBP", "HEIC", "TIFF", "AVIF", "BMP", "PDF", "ICO", "GIF"]
PDF_TARGETS = ["DOCX", "PPTX", "XLSX", "JPG", "PNG", "EPUB", "TXT", "MD"]     # Santra's order
DOCX_TARGETS = ["PDF", "TXT", "MD", "HTML", "EPUB"]
TEXT_TARGETS = ["PDF", "DOCX", "EPUB"]
MARKDOWN_TARGETS = ["PDF", "DOCX", "HTML", "EPUB", "TXT"]
HTML_TARGETS = ["PDF", "DOCX", "TXT", "MD", "EPUB"]
EBOOK_TARGETS = ["PDF", "DOCX", "TXT", "MD", "HTML"]
SUBTITLE_TARGETS = ["SRT", "VTT", "TXT"]

PIL_FORMAT = {"PNG": "PNG", "JPG": "JPEG", "WEBP": "WEBP", "HEIC": "HEIF", "TIFF": "TIFF",
              "AVIF": "AVIF", "BMP": "BMP", "PDF": "PDF", "ICO": "ICO", "GIF": "GIF"}
NO_ALPHA = {"JPG", "PDF", "BMP"}


# ---------------------------------------------------------------- images
def _svg(path: str | Path, max_side: int = 2400) -> Image.Image:
    """SVG (input only): rendered by MuPDF, transparent background, about max_side across."""
    with fitz.open(path) as doc:
        page = doc[0]
        k = max(1.0, max_side / max(page.rect.width, page.rect.height, 1))
        pix = page.get_pixmap(matrix=fitz.Matrix(k, k), alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)


def open_image(path: str | Path) -> Image.Image:
    if str(path).lower().endswith(".svg"):
        return _svg(path)
    im = Image.open(path)
    im.seek(0)
    im = ImageOps.exif_transpose(im)  # honour camera rotation
    if im.mode in ("P", "LA", "PA"):
        im = im.convert("RGBA")
    elif im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGB")
    return im


def open_preview(path: str | Path, max_side: int = 1400) -> Image.Image:
    """Fast, reduced-size decode for on-screen previews (JPEG decodes at 1/2, 1/4, 1/8 scale)."""
    if str(path).lower().endswith(".svg"):
        return _svg(path, max_side)
    im = Image.open(path)
    im.seek(0)
    if im.format == "JPEG":
        im.draft("RGB", (max_side, max_side))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("P", "LA", "PA"):
        im = im.convert("RGBA")
    elif im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
    return im


def open_pdf(path: str | Path):
    doc = fitz.open(path)
    if doc.needs_pass:
        doc.close()
        raise UserError("This PDF is password-protected. Remove the password first.")
    return doc


def flatten(im: Image.Image, bg=(255, 255, 255)) -> Image.Image:
    if im.mode == "RGBA":
        base = Image.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[3])
        return base
    return im.convert("RGB") if im.mode != "RGB" else im


def save_image(im: Image.Image, out: Path, target: str, quality: int | None = None, exif=None) -> None:
    from .util import CONFIG
    quality = quality or int(CONFIG.get("jpg_quality", 90))
    target = target.upper()
    fmt = PIL_FORMAT[target]
    if target in NO_ALPHA:
        im = flatten(im)
    kw: dict = {}
    if target in ("JPG", "WEBP", "AVIF", "HEIC"):
        kw["quality"] = quality
    if target == "JPG":
        kw.update(optimize=True, progressive=True)
    if target == "PNG":
        kw["optimize"] = True
    if target == "ICO":
        side = min(256, max(im.size))
        im = ImageOps.contain(im.convert("RGBA"), (side, side))
        kw["sizes"] = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256) if s <= side]
    if target == "PDF":
        kw["resolution"] = 150.0
    if exif and target in ("JPG", "WEBP", "PNG", "TIFF"):
        kw["exif"] = exif
    atomic_save(lambda dst: im.save(dst, fmt, **kw), out)


def atomic_save(write, out):
    """Write to a hidden temp file, then rename: Explorer never shows a half-written file."""
    import os
    if not isinstance(out, (str, Path)):
        write(out)  # in-memory buffer
        return
    out = Path(out)
    tmp = out.with_name(f".~{out.name}.part")
    try:
        write(tmp)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def image_to(src: str | Path, target: str) -> list[Path]:
    target = target.upper()
    im = open_image(src)
    out = sibling(src, ext="." + target.lower())
    save_image(im, out, target)
    return [out]


def images_to_single_pdf(srcs: list[str | Path]) -> list[Path]:
    pages = [flatten(open_image(s)) for s in srcs]
    out = sibling(srcs[0], "Combined", ".pdf")
    pages[0].save(out, "PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return [out]


# ---------------------------------------------------------------- PDF
def pdf_to_images(src: str | Path, target: str, dpi: int | None = None) -> list[Path]:
    from .util import CONFIG
    dpi = dpi or int(CONFIG.get("pdf_dpi", 200))
    target = target.upper()
    outs = []
    with open_pdf(src) as doc:
        n = doc.page_count
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            label = f"page {i + 1}" if n > 1 else ""
            out = sibling(src, label, "." + target.lower())
            save_image(im, out, target)
            outs.append(out)
    return outs


def pdf_to_txt(src: str | Path) -> list[Path]:
    with open_pdf(src) as doc:
        text = "\n\f\n".join(page.get_text("text") for page in doc)
    out = sibling(src, ext=".txt")
    out.write_text(text, encoding="utf-8")
    return [out]


def pdf_to_docx(src: str | Path) -> list[Path]:
    """Text blocks become paragraphs, embedded images are kept, one Word page per PDF page."""
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Inches

    d = Document()
    with open_pdf(src) as doc:
        for pno, page in enumerate(doc):
            if pno:
                d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            items = []
            for b in page.get_text("dict")["blocks"]:
                y = b["bbox"][1]
                if b.get("type") == 0:
                    lines = []
                    size = 11.0
                    bold = False
                    for ln in b["lines"]:
                        spans = ln["spans"]
                        if spans:
                            size = max(size, max(s["size"] for s in spans)) if not lines else size
                            bold = bold or any("Bold" in s["font"] for s in spans)
                        lines.append("".join(s["text"] for s in spans))
                    txt = " ".join(l.strip() for l in lines).strip()
                    if txt:
                        items.append((y, "text", (txt, size, bold)))
                elif b.get("type") == 1 and b.get("image"):
                    items.append((y, "img", (b["image"], b["bbox"])))
            items.sort(key=lambda t: t[0])
            for _, kind, data in items:
                if kind == "text":
                    txt, size, bold = data
                    if size >= 16:
                        d.add_heading(txt, level=1 if size >= 20 else 2)
                    else:
                        p = d.add_paragraph()
                        r = p.add_run(txt)
                        r.bold = bold and len(txt) < 120
                else:
                    raw, bbox = data
                    width_in = min(6.5, max(0.5, (bbox[2] - bbox[0]) / 72))
                    try:
                        d.add_picture(io.BytesIO(raw), width=Inches(width_in))
                    except Exception:
                        pass
    out = sibling(src, ext=".docx")
    d.save(out)
    return [out]


# ---------------------------------------------------------------- DOCX
def _docx_paragraph_html(p) -> str:
    parts = []
    for r in p.runs:
        t = html.escape(r.text)
        if not t:
            continue
        if r.bold:
            t = f"<b>{t}</b>"
        if r.italic:
            t = f"<i>{t}</i>"
        if r.underline:
            t = f"<u>{t}</u>"
        parts.append(t)
    body = "".join(parts) or "&nbsp;"
    style = (p.style.name or "").lower() if p.style is not None else ""
    if style.startswith("heading"):
        lvl = "".join(c for c in style if c.isdigit()) or "1"
        lvl = str(min(int(lvl), 6))
        return f"<h{lvl}>{body}</h{lvl}>"
    if style == "title":
        return f"<h1>{body}</h1>"
    if "list" in style:
        return f"<p>&bull; {body}</p>"
    return f"<p>{body}</p>"


def docx_to_html(src: str | Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(src)
    out = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(_docx_paragraph_html(Paragraph(child, d)))
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for row in t.rows:
                cells = "".join(f"<td>{html.escape(c.text)}</td>" for c in row.cells)
                rows.append(f"<tr>{cells}</tr>")
            out.append("<table>" + "".join(rows) + "</table>")
    return "\n".join(out)


def docx_to_txt(src: str | Path) -> list[Path]:
    from docx import Document
    d = Document(src)
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            lines.append("\t".join(c.text for c in row.cells))
    out = sibling(src, ext=".txt")
    out.write_text("\n".join(lines), encoding="utf-8")
    return [out]


def _word_to_pdf(src: Path, out: Path) -> bool:
    """Use Microsoft Word (if installed) for a perfect-fidelity export."""
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # type: ignore
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        try:
            # positional: late-bound COM can silently drop keyword arguments, and without
            # ReadOnly Word leaves a '~$name.docx' lock file next to the user's document
            doc = word.Documents.Open(str(src.resolve()), False, True)   # ConfirmConversions, ReadOnly
            doc.SaveAs(str(out.resolve()), 17)                           # wdFormatPDF
            doc.Close(False)
        finally:
            word.Quit()
        return out.exists()
    except Exception:
        return False


CSS = """
* { font-family: sans-serif; }
body { font-size: 11pt; line-height: 1.35; }
h1 { font-size: 20pt; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
p { margin: 0 0 6pt 0; }
pre { font-family: monospace; font-size: 9.5pt; white-space: pre-wrap; }
table { border-collapse: collapse; margin: 6pt 0; }
td { border: 1px solid #888; padding: 3pt 5pt; font-size: 10pt; }
"""


def html_to_pdf(body_html: str, out: Path, base_dir: Path | None = None) -> None:
    """base_dir: where relative <img src> paths are looked up (an HTML or Markdown file's folder)."""
    from .util import default_paper
    archive = fitz.Archive(str(base_dir)) if base_dir else None
    story = fitz.Story(html=body_html, user_css=CSS, archive=archive)
    writer = fitz.DocumentWriter(str(out))
    mediabox = fitz.paper_rect(default_paper())
    where = mediabox + (54, 54, -54, -54)
    more = True
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()


def docx_to_pdf(src: str | Path) -> list[Path]:
    src = Path(src)
    out = sibling(src, ext=".pdf")
    if not _word_to_pdf(src, out):
        html_to_pdf(docx_to_html(src), out)
    return [out]


# ---------------------------------------------------------------- text
def read_text(src: str | Path) -> str:
    raw = Path(src).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


MARKUP_EXTS = {".md", ".markdown", ".html", ".htm"}


def markdown_to_html(text: str) -> str:
    import markdown
    return markdown.markdown(text, extensions=["extra", "sane_lists"])


def as_html(src: str | Path) -> str:
    """The document a text file stands for: HTML as itself, Markdown rendered, anything else as-is."""
    ext, text = Path(src).suffix.lower(), read_text(src)
    if ext in (".html", ".htm"):
        return text
    if ext in (".md", ".markdown"):
        return markdown_to_html(text)
    return f"<pre>{html.escape(text)}</pre>"


def text_to_pdf(src: str | Path) -> list[Path]:
    out = sibling(src, ext=".pdf")
    html_to_pdf(as_html(src), out, Path(src).parent)
    return [out]


def text_to_html(src: str | Path) -> list[Path]:
    out = sibling(src, ext=".html")
    title = html.escape(Path(src).stem)
    out.write_text(f"<!doctype html><meta charset='utf-8'><title>{title}</title><style>{CSS}</style>"
                   f"{as_html(src)}", encoding="utf-8")
    return [out]


def html_to_text(src: str | Path) -> list[Path]:
    """Readable text of a web page (no tags, scripts or styles)."""
    with fitz.open(stream=as_html(src).encode("utf-8"), filetype="html") as doc:
        text = "\n".join(page.get_text("text") for page in doc)
    out = sibling(src, ext=".txt")
    out.write_text(text.strip() + "\n", encoding="utf-8")
    return [out]


def text_to_docx(src: str | Path) -> list[Path]:
    from docx import Document
    d = Document()
    if Path(src).suffix.lower() in MARKUP_EXTS:
        _html_into_docx(as_html(src), d)
    else:
        for line in read_text(src).splitlines():
            d.add_paragraph(line)
    out = sibling(src, ext=".docx")
    d.save(out)
    return [out]


def _html_into_docx(markup: str, d) -> None:
    """Headings, paragraphs, list items and preformatted blocks, with bold/italic runs."""
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.par, self.bold, self.ital, self.skip, self.pre = None, 0, 0, 0, False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "head", "title"):
                self.skip += 1
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.par = d.add_heading(level=min(int(tag[1]), 4))
            elif tag == "li":
                self.par = d.add_paragraph(style="List Bullet")
            elif tag in ("p", "div", "blockquote", "tr", "pre"):
                self.par = d.add_paragraph()
                self.pre = self.pre or tag == "pre"
            elif tag == "br" and self.par is not None:
                self.par.add_run().add_break()
            elif tag in ("b", "strong"):
                self.bold += 1
            elif tag in ("i", "em"):
                self.ital += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style", "head", "title"):
                self.skip = max(0, self.skip - 1)
            elif tag in ("b", "strong"):
                self.bold = max(0, self.bold - 1)
            elif tag in ("i", "em"):
                self.ital = max(0, self.ital - 1)
            elif tag == "pre":
                self.pre = False
                self.par = None
            elif tag in ("p", "li", "div", "blockquote", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
                self.par = None

        def handle_data(self, data):
            if self.skip or (not self.pre and not data.strip()):
                return
            if self.par is None:
                self.par = d.add_paragraph()
            if self.pre:
                text = data.strip("\n")
            else:
                text = " ".join(data.split())
                if data[:1].isspace() and self.par.text:
                    text = " " + text
                if data[-1:].isspace():
                    text += " "
            run = self.par.add_run(text)
            run.bold, run.italic = bool(self.bold) or None, bool(self.ital) or None
            if self.pre:
                run.font.name = "Consolas"

    Parser().feed(markup)


# ---------------------------------------------------------------- dispatch
def targets_for(cat: str, src_ext: str) -> list[str]:
    src_ext = src_ext.lower().lstrip(".")
    same = {"jpeg": "JPG", "jpg": "JPG", "tif": "TIFF", "tiff": "TIFF", "heif": "HEIC"}
    cur = same.get(src_ext, src_ext.upper())
    if cat == "image":
        t = [x for x in IMAGE_TARGETS if x != cur]
        if not HEIF_OK:
            t = [x for x in t if x != "HEIC"]
        return t
    if cat == "text" and src_ext in ("md", "markdown"):
        return MARKDOWN_TARGETS
    if cat == "text" and src_ext in ("html", "htm"):
        return HTML_TARGETS
    if cat == "subtitle":
        return [t for t in SUBTITLE_TARGETS if t != cur]
    return {"pdf": PDF_TARGETS, "docx": DOCX_TARGETS, "text": TEXT_TARGETS, "ebook": EBOOK_TARGETS}.get(cat, [])


def convert(src: str | Path, cat: str, target: str) -> list[Path]:
    target = target.upper()
    if cat == "image":
        return image_to(src, target)
    if cat == "pdf":
        if target in ("JPG", "PNG"):
            return pdf_to_images(src, target)
        if target == "TXT":
            return pdf_to_txt(src)
        if target == "DOCX":
            return pdf_to_docx(src)
        from . import docs
        return {"MD": docs.pdf_to_markdown, "XLSX": docs.pdf_to_xlsx, "PPTX": docs.pdf_to_pptx,
                "EPUB": docs.pdf_to_epub}[target](src)
    if cat == "docx":
        if target in ("MD", "HTML", "EPUB"):
            from . import docs
            return docs.document_to(src, target)
        return docx_to_pdf(src) if target == "PDF" else docx_to_txt(src)
    if cat == "text":
        if target in ("MD", "EPUB") or (target == "HTML" and Path(src).suffix.lower() not in MARKUP_EXTS):
            from . import docs
            return docs.document_to(src, target)
        return {"PDF": text_to_pdf, "DOCX": text_to_docx, "HTML": text_to_html, "TXT": html_to_text}[target](src)
    if cat == "ebook":
        from . import docs
        return docs.epub_to(src, target)
    if cat == "subtitle":
        from . import docs
        return docs.subtitles_to(src, target)
    raise ValueError(f"Can't convert {cat} to {target}")
