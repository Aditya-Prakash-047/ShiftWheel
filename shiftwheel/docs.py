"""Documents beyond the basics (Santra's list): EPUB in and out, Markdown export, PDF to
Excel / PowerPoint / Markdown / EPUB, and subtitles (SRT ⇄ VTT, text)."""
from __future__ import annotations

import html
import re
import uuid
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from .util import UserError, sibling


# ---------------------------------------------------------------- HTML → Markdown
class _MD(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "blockquote", "tr", "table", "ul", "ol", "br", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.lists: list[list] = []        # [kind, counter]
        self.href: list[str] = []
        self.pre = False

    def _nl(self, n=2):
        text = "".join(self.out)
        have = len(text) - len(text.rstrip("\n"))
        if text.strip():
            self.out.append("\n" * max(0, n - have))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._nl()
            self.out.append("#" * int(tag[1]) + " ")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self._nl()
            self.out.append("```\n")
            self.pre = True
        elif tag in ("ul", "ol"):
            self._nl(1 if self.lists else 2)
            self.lists.append([tag, 0])
        elif tag == "li":
            self._nl(1)
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            self.out.append("  " * (len(self.lists) - 1) + (f"{kind[1]}. " if kind[0] == "ol" else "- "))
        elif tag == "a":
            self.href.append(a.get("href") or "")
            self.out.append("[")
        elif tag == "img":
            self.out.append(f"![{a.get('alt') or ''}]({a.get('src') or ''})")
        elif tag == "br":
            self.out.append("  \n")
        elif tag == "hr":
            self._nl()
            self.out.append("---")
            self._nl()
        elif tag in self.BLOCK:
            self._nl()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "blockquote", "table"):
            self._nl()
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code" and not self.pre:
            self.out.append("`")
        elif tag == "pre":
            self.out.append("\n```")
            self.pre = False
            self._nl()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self._nl()
        elif tag == "a":
            self.out.append(f"]({self.href.pop() if self.href else ''})")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        if self.skip:
            return
        self.out.append(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_markdown(markup: str) -> str:
    p = _MD()
    p.feed(markup)
    text = "".join(p.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# ---------------------------------------------------------------- EPUB
def epub_html(src: str | Path) -> tuple[str, str]:
    """(title, the book's chapters as one HTML body) in reading order."""
    try:
        z = zipfile.ZipFile(src)
    except zipfile.BadZipFile as e:
        raise UserError("This EPUB is damaged.") from e
    with z:
        container = z.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
        opf = z.read(opf_path).decode("utf-8", "replace")
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        title = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.S)
        manifest = {m.group(1): m.group(2) for m in re.finditer(r'<item\b[^>]*\bid="([^"]+)"[^>]*\bhref="([^"]+)"', opf)}
        manifest.update({m.group(2): m.group(1) for m in
                         re.finditer(r'<item\b[^>]*\bhref="([^"]+)"[^>]*\bid="([^"]+)"', opf)})
        parts = []
        for idref in re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf):
            href = manifest.get(idref)
            if not href:
                continue
            try:
                doc = z.read(base + href).decode("utf-8", "replace")
            except KeyError:
                continue
            body = re.search(r"<body[^>]*>(.*)</body>", doc, re.S | re.I)
            parts.append(body.group(1) if body else doc)
    return (html.unescape(title.group(1).strip()) if title else Path(src).stem), "\n".join(parts)


def epub_to(src: str | Path, target: str) -> list[Path]:
    from .convert import CSS, _html_into_docx, fitz
    t = target.upper()
    if t == "PDF":
        out = sibling(src, ext=".pdf")
        with fitz.open(src) as doc:
            pdf = fitz.open("pdf", doc.convert_to_pdf())
            pdf.save(out, garbage=3, deflate=True)
        return [out]
    title, body = epub_html(src)
    if t == "HTML":
        out = sibling(src, ext=".html")
        out.write_text(f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style>"
                       f"{body}", encoding="utf-8")
    elif t == "MD":
        out = sibling(src, ext=".md")
        out.write_text(html_to_markdown(body), encoding="utf-8")
    elif t == "TXT":
        out = sibling(src, ext=".txt")
        with fitz.open(src) as doc:
            out.write_text("\n".join(p.get_text() for p in doc).strip() + "\n", encoding="utf-8")
    elif t == "DOCX":
        from docx import Document
        d = Document()
        _html_into_docx(body, d)
        out = sibling(src, ext=".docx")
        d.save(out)
    else:
        raise ValueError(t)
    return [out]


def write_epub(title: str, body_html: str, out: Path, author: str = "") -> Path:
    """A valid EPUB 3 (one chapter per <h1>, with a table of contents)."""
    chapters = [c for c in re.split(r"(?=<h1[\s>])", body_html, flags=re.I) if c.strip()] or [body_html]
    book_id = f"urn:uuid:{uuid.uuid4()}"

    def xhtml(t, b):
        return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n<html xmlns="http://www.w3.org/1999/xhtml" '
                f'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>{html.escape(t)}</title>'
                f'<link rel="stylesheet" href="style.css"/></head><body>{_xhtml_safe(b)}</body></html>')
    names = []
    for i, ch in enumerate(chapters, 1):
        h = re.search(r"<h1[^>]*>(.*?)</h1>", ch, re.S | re.I)
        names.append((f"ch{i}.xhtml", re.sub(r"<[^>]+>", "", h.group(1)).strip() if h else f"Part {i}"))
    nav = "".join(f'<li><a href="{f}">{html.escape(n)}</a></li>' for f, n in names)
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
           'unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="bookid">{book_id}</dc:identifier><dc:title>{html.escape(title)}</dc:title>'
           f'<dc:language>en</dc:language>{f"<dc:creator>{html.escape(author)}</dc:creator>" if author else ""}'
           '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata><manifest>'
           '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="css" href="style.css" media-type="text/css"/>'
           + "".join(f'<item id="c{i}" href="{f}" media-type="application/xhtml+xml"/>' for i, (f, _) in enumerate(names))
           + '</manifest><spine>' + "".join(f'<itemref idref="c{i}"/>' for i in range(len(names)))
           + '</spine></package>')
    out = Path(out)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)   # must be first, stored
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                   'full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
                   compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", "body{font-family:serif;line-height:1.5} h1,h2,h3{font-family:sans-serif}",
                   compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/nav.xhtml", xhtml("Contents", f'<nav epub:type="toc"><h1>Contents</h1><ol>{nav}</ol></nav>'),
                   compress_type=zipfile.ZIP_DEFLATED)
        for (f, n), ch in zip(names, chapters):
            z.writestr(f"OEBPS/{f}", xhtml(n, ch), compress_type=zipfile.ZIP_DEFLATED)
    return out


def _xhtml_safe(fragment: str) -> str:
    """EPUB chapters are XML: close void tags and escape stray ampersands."""
    fragment = re.sub(r"<(br|hr|img|meta|link|input)([^>]*?)(?<!/)>", r"<\1\2/>", fragment, flags=re.I)
    return re.sub(r"&(?!#?\w+;)", "&amp;", fragment)


# ---------------------------------------------------------------- PDF → more
def pdf_to_markdown(src: str | Path) -> list[Path]:
    """Headings from font size, paragraphs from blocks, bold from font flags."""
    from .convert import open_pdf
    lines_out = []
    with open_pdf(src) as doc:
        sizes = []
        for page in doc:
            for b in page.get_text("dict")["blocks"]:
                for line in b.get("lines", []):
                    for sp in line["spans"]:
                        if sp["text"].strip():
                            sizes.append(round(sp["size"]))
        body = max(set(sizes), key=sizes.count) if sizes else 11
        for page in doc:
            for b in page.get_text("dict")["blocks"]:
                if "lines" not in b:
                    continue
                text, size, bold = [], 0, True
                for line in b["lines"]:
                    for sp in line["spans"]:
                        if sp["text"].strip():
                            size = max(size, sp["size"])
                            bold = bold and bool(sp["flags"] & 16)
                    text.append("".join(sp["text"] for sp in line["spans"]))
                t = " ".join(x.strip() for x in text if x.strip())
                if not t:
                    continue
                if size >= body * 1.6:
                    lines_out.append(f"# {t}")
                elif size >= body * 1.25 or (bold and len(t) < 90):
                    lines_out.append(f"## {t}")
                else:
                    lines_out.append(t)
    out = sibling(src, ext=".md")
    out.write_text("\n\n".join(lines_out).strip() + "\n", encoding="utf-8")
    return [out]


def pdf_to_xlsx(src: str | Path) -> list[Path]:
    """Every table found on every page becomes a sheet; pages without tables keep their lines."""
    from openpyxl import Workbook
    from .convert import open_pdf
    wb = Workbook()
    wb.remove(wb.active)
    with open_pdf(src) as doc:
        for pno, page in enumerate(doc, 1):
            try:
                tables = page.find_tables().tables
            except Exception:
                tables = []
            words = page.get_text("words")
            for k, tb in enumerate(tables, 1):
                ws = wb.create_sheet(f"Page {pno}" + (f" ({k})" if len(tables) > 1 else ""))
                for row in _table_rows(tb, words):
                    ws.append([_cell(c) for c in row])
            if not tables:
                text = page.get_text().strip()
                if text:
                    ws = wb.create_sheet(f"Page {pno}")
                    for line in text.splitlines():
                        ws.append([_cell(c) for c in re.split(r"\s{2,}|\t", line.strip())])
    if not wb.sheetnames:
        raise UserError("No text or tables found (is it a scan? Run OCR first).")
    out = sibling(src, ext=".xlsx")
    wb.save(out)
    return [out]


def _table_rows(tb, words) -> list[list[str]]:
    """Cell text rebuilt from the page's words inside each cell (in reading order); columns
    that are empty in every row (ruling artefacts) are dropped."""
    rows = []
    for row in tb.rows:
        out = []
        for cell in row.cells:
            if cell is None:
                out.append("")
                continue
            x0, y0, x1, y1 = cell
            inside = [w for w in words if x0 - 1 <= (w[0] + w[2]) / 2 <= x1 + 1 and y0 - 1 <= (w[1] + w[3]) / 2 <= y1 + 1]
            inside.sort(key=lambda w: (round(w[3]), w[0]))
            out.append(" ".join(w[4] for w in inside))
        rows.append(out)
    keep = [i for i in range(max((len(r) for r in rows), default=0)) if any(i < len(r) and r[i] for r in rows)]
    return [[r[i] if i < len(r) else "" for i in keep] for r in rows]


def _cell(v):
    if v is None:
        return None
    s = str(v).strip()
    try:
        return int(s) if re.fullmatch(r"-?\d{1,15}", s) else float(s) if re.fullmatch(r"-?\d+\.\d+", s) else s
    except ValueError:
        return s


def pdf_to_pptx(src: str | Path) -> list[Path]:
    """One slide per page, the page as a sharp full-slide picture (keeps the exact look)."""
    import io
    from pptx import Presentation
    from pptx.util import Emu
    from .convert import open_pdf
    prs = Presentation()
    with open_pdf(src) as doc:
        first = doc[0].rect
        w, h = first.width * 12700, first.height * 12700           # points → EMU
        # PowerPoint only allows slides 1–56 inches a side: scale into range, same shape
        lo, hi = 914400, 51206400
        k = max(1.0, lo / max(1.0, min(w, h)))
        k = min(k, hi / max(w, h)) if max(w, h) * k > hi else k
        prs.slide_width = Emu(int(min(hi, max(lo, w * k))))
        prs.slide_height = Emu(int(min(hi, max(lo, h * k))))
        blank = prs.slide_layouts[6]
        for page in doc:
            pix = page.get_pixmap(dpi=200, alpha=False)
            slide = prs.slides.add_slide(blank)
            slide.shapes.add_picture(io.BytesIO(pix.tobytes("png")), 0, 0, prs.slide_width, prs.slide_height)
    out = sibling(src, ext=".pptx")
    prs.save(out)
    return [out]


def pdf_to_epub(src: str | Path) -> list[Path]:
    from .convert import open_pdf
    parts = []
    with open_pdf(src) as doc:
        title = (doc.metadata or {}).get("title") or Path(src).stem
        for page in doc:
            for b in page.get_text("blocks"):
                t = b[4].strip()
                if t:
                    parts.append(f"<p>{html.escape(' '.join(t.split()))}</p>")
    if not parts:
        raise UserError("No text found (is it a scan? Run OCR first).")
    out = sibling(src, ext=".epub")
    return [write_epub(title, f"<h1>{html.escape(title)}</h1>" + "\n".join(parts), out)]


# ---------------------------------------------------------------- documents → MD / HTML / EPUB
def document_html(src: str | Path) -> tuple[str, str]:
    """(title, HTML) for DOCX, Markdown, HTML and plain text."""
    from .convert import as_html, docx_to_html
    p = Path(src)
    body = docx_to_html(p) if p.suffix.lower() == ".docx" else as_html(p)
    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S | re.I)
    return (re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else p.stem), body


def document_to(src: str | Path, target: str) -> list[Path]:
    from .convert import CSS
    title, body = document_html(src)
    t = target.upper()
    if t == "MD":
        out = sibling(src, ext=".md")
        out.write_text(html_to_markdown(body), encoding="utf-8")
    elif t == "HTML":
        out = sibling(src, ext=".html")
        out.write_text(f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style>"
                       f"{body}", encoding="utf-8")
    elif t == "EPUB":
        out = write_epub(title, body, sibling(src, ext=".epub"))
    else:
        raise ValueError(t)
    return [out]


# ---------------------------------------------------------------- subtitles
_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _ms(m: re.Match) -> int:
    h, mi, s, f = m.group(1), m.group(2), m.group(3), m.group(4)
    return ((int(h or 0) * 60 + int(mi)) * 60 + int(s)) * 1000 + int(f.ljust(3, "0"))


def parse_subtitles(text: str) -> list[tuple[int, int, str]]:
    """[(start ms, end ms, text)] from SRT or WebVTT."""
    cues = []
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                ma, mb = _TIME.search(a), _TIME.search(b)
                if ma and mb:
                    body = "\n".join(lines[i + 1:]).strip()
                    if body:
                        cues.append((_ms(ma), _ms(mb), body))
                break
    if not cues:
        raise UserError("No subtitles found in this file.")
    return cues


def _stamp(ms: int, sep: str) -> str:
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def subtitles_to(src: str | Path, target: str) -> list[Path]:
    from .convert import read_text
    cues = parse_subtitles(read_text(src))
    t = target.upper()
    out = sibling(src, ext="." + t.lower())
    if t == "SRT":
        body = "\n".join(f"{i}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n{_strip_vtt(x)}\n" for i, (a, b, x) in enumerate(cues, 1))
    elif t == "VTT":
        body = "WEBVTT\n\n" + "\n".join(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n{x}\n" for a, b, x in cues)
    elif t == "TXT":
        body = "\n".join(_strip_vtt(x) for _, _, x in cues) + "\n"
    else:
        raise ValueError(t)
    out.write_text(body, encoding="utf-8")
    return [out]


def _strip_vtt(text: str) -> str:
    """SRT has no WebVTT voice/class tags (<v Name>, <c.red>); keep <b>/<i>/<u> which both know."""
    return re.sub(r"</?(?:v|c|lang|ruby|rt)(?:[.\s][^>]*)?>", "", text)
