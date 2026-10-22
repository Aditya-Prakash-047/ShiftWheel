"""Excel, PowerPoint, legacy Word and CSV.

Fidelity first: Microsoft Office (if installed) does the export, then LibreOffice (if
installed), then a built-in renderer where one is good enough (spreadsheets, CSV)."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .util import UserError, sibling

IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

SHEET_TARGETS = ["PDF", "XLSX", "CSV", "JSON", "HTML"]
SLIDE_TARGETS = ["PDF", "PNG", "JPG"]
WORDDOC_TARGETS = ["PDF", "DOCX", "TXT"]
HINTS = {"XLSX": "Excel workbook", "CSV": "Plain table", "JSON": "For developers", "HTML": "Web table",
         "PDF": "Print-ready", "PNG": "One image per slide", "JPG": "One image per slide",
         "DOCX": "Modern Word", "TXT": "Plain text"}
LIBREOFFICE_HINT = ("Install Microsoft Office or the free LibreOffice "
                    "(winget install TheDocumentFoundation.LibreOffice), then try again.")


# ---------------------------------------------------------------- engines
def find_soffice() -> str | None:
    env = os.environ.get("SHIFTWHEEL_SOFFICE")
    if env and os.path.isfile(env):
        return env
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base:
                p = Path(base) / "LibreOffice" / "program" / "soffice.exe"
                if p.exists():
                    return str(p)
    elif sys.platform == "darwin":
        p = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if p.exists():
            return str(p)
    return None


def libreoffice_convert(src: Path, fmt: str, out: Path) -> bool:
    soffice = find_soffice()
    if not soffice:
        return False
    with tempfile.TemporaryDirectory() as td:
        profile = Path(td) / "profile"
        cmd = [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore",
               "--convert-to", fmt, "--outdir", td, str(src)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=240, creationflags=CREATE_NO_WINDOW)
        except (subprocess.TimeoutExpired, OSError):
            return False
        ext = fmt.split(":")[0]
        produced = Path(td) / f"{src.stem}.{ext}"
        if not produced.exists():
            return False
        shutil.move(str(produced), out)
    return out.exists()


def _com(app_name: str):
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore
    pythoncom.CoInitialize()
    return win32com.client.DispatchEx(app_name)


def office_export(src: Path, kind: str, target: str, out: Path) -> bool:
    """kind: 'sheet' | 'slides' | 'worddoc'. Uses Microsoft Office via COM (Windows)."""
    if not IS_WIN:
        return False
    src_s, out_s = str(src.resolve()), str(out.resolve())
    try:
        if kind == "sheet":
            xl = _com("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            try:
                wb = xl.Workbooks.Open(src_s, ReadOnly=True)
                if target == "PDF":
                    wb.ExportAsFixedFormat(0, out_s)               # xlTypePDF
                elif target == "XLSX":
                    wb.SaveAs(out_s, FileFormat=51)                # xlOpenXMLWorkbook
                else:
                    return False
                wb.Close(False)
            finally:
                xl.Quit()
        elif kind == "slides":
            pp = _com("PowerPoint.Application")
            try:
                pres = pp.Presentations.Open(src_s, ReadOnly=True, WithWindow=False)
                if target != "PDF":
                    return False
                pres.SaveAs(out_s, 32)                             # ppSaveAsPDF
                pres.Close()
            finally:
                pp.Quit()
        elif kind == "worddoc":
            word = _com("Word.Application")
            word.Visible = False
            try:
                doc = word.Documents.Open(src_s, ReadOnly=True)
                fmt = {"PDF": 17, "DOCX": 16, "TXT": 7}[target]   # wdFormatPDF / DocumentDefault / UnicodeText
                doc.SaveAs(out_s, FileFormat=fmt)
                doc.Close(False)
            finally:
                word.Quit()
        else:
            return False
        return out.exists()
    except Exception:
        return False


# ---------------------------------------------------------------- reading tables
def read_table(src: Path) -> dict[str, list[list]]:
    """{sheet name: rows}. CSV/TSV, XLSX/XLSM, ODS via LibreOffice, XLS via xlrd or Office."""
    ext = src.suffix.lower()
    if ext in (".csv", ".tsv"):
        text = _read_text(src)
        try:
            dialect = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if ext == ".tsv" else csv.excel
        rows = [[_typed(c) for c in r] for r in csv.reader(io.StringIO(text), dialect)]
        return {src.stem[:31] or "Sheet1": rows}
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(src, data_only=True, read_only=True)
        out = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
        wb.close()
        return out
    if ext == ".xls":
        try:
            import xlrd  # type: ignore
            book = xlrd.open_workbook(str(src))
            return {s.name: [s.row_values(i) for i in range(s.nrows)] for s in book.sheets()}
        except ImportError:
            pass
    # anything else: let Office / LibreOffice turn it into xlsx first
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / (src.stem + ".xlsx")
        if office_export(src, "sheet", "XLSX", tmp) or libreoffice_convert(src, "xlsx", tmp):
            return read_table(tmp)
    raise UserError(f"Can't read {ext} spreadsheets without Excel or LibreOffice. {LIBREOFFICE_HINT}")


def _read_text(src: Path) -> str:
    raw = src.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _typed(v: str):
    """'12' → 12, '3.5' → 3.5; keeps IDs like '0042', '+91…', '1e5' and '1,234' as text."""
    s = v.strip()
    if not s:
        return None
    body = s[1:] if s.startswith("-") else s
    if len(body) > 1 and body.startswith("0") and not body.startswith("0."):
        return v                      # leading zero: PIN codes, phone numbers, IDs
    if body.isdigit():
        return int(s) if len(body) <= 15 else v   # long digit strings (Aadhaar, card nos.) stay text
    head, dot, tail = body.partition(".")
    if dot and head.isdigit() and tail.isdigit():
        return float(s)
    return v


def _trim(rows: list[list]) -> list[list]:
    """Drop fully empty trailing rows/columns (Excel's 'used range' is often padded)."""
    rows = [list(r) for r in rows]
    while rows and all(c in (None, "") for c in rows[-1]):
        rows.pop()
    width = max((max((i + 1 for i, c in enumerate(r) if c not in (None, "")), default=0) for r in rows), default=0)
    return [r[:width] + [None] * (width - len(r[:width])) for r in rows]


# ---------------------------------------------------------------- writers
def write_xlsx(tables: dict[str, list[list]], out: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in tables.items():
        ws = wb.create_sheet(title=(name or "Sheet")[:31])
        rows = _trim(rows)
        for r in rows:
            ws.append(r)
        if rows:
            for c in ws[1]:
                c.font = Font(bold=True)
                c.fill = PatternFill("solid", fgColor="FFE9D5")
            ws.freeze_panes = "A2"
            for i in range(1, len(rows[0]) + 1):
                width = max((len(str(r[i - 1])) for r in rows[:500] if i - 1 < len(r) and r[i - 1] is not None),
                            default=6)
                ws.column_dimensions[get_column_letter(i)].width = min(60, max(8, width + 2))
    wb.save(out)
    return out


def table_html(tables: dict[str, list[list]]) -> str:
    parts = []
    for name, rows in tables.items():
        rows = _trim(rows)
        if len(tables) > 1:
            parts.append(f"<h2>{html.escape(str(name))}</h2>")
        parts.append("<table>")
        for i, r in enumerate(rows):
            tag = "th" if i == 0 else "td"
            cells = "".join(f"<{tag}>{html.escape(_fmt(c))}</{tag}>" for c in r)
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    return "\n".join(parts)


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) >= 1000 else f"{v:g}"
    return str(v)


SHEET_CSS = """
* { font-family: sans-serif; }
h2 { font-size: 12pt; margin: 10pt 0 4pt 0; }
table { border-collapse: collapse; }
th { background: #ffe9d5; font-weight: bold; }
th, td { border: 0.5pt solid #999; padding: 2pt 4pt; font-size: 8pt; }
"""


def tables_to_pdf(tables: dict[str, list[list]], out: Path) -> Path:
    from .convert import fitz
    wide = max((len(_trim(r)[0]) if _trim(r) else 0) for r in tables.values()) > 7
    story = fitz.Story(html=table_html(tables), user_css=SHEET_CSS)
    writer = fitz.DocumentWriter(str(out))
    box = fitz.paper_rect("a4-l" if wide else "a4")
    where = box + (28, 28, -28, -28)
    more = True
    while more:
        dev = writer.begin_page(box)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return out


# ---------------------------------------------------------------- public
def convert_sheet(src, target: str) -> list[Path]:
    src, t = Path(src), target.upper()
    out = sibling(src, ext="." + t.lower())
    if t == "PDF":
        if src.suffix.lower() not in (".csv", ".tsv") and (office_export(src, "sheet", "PDF", out)
                                                            or libreoffice_convert(src, "pdf", out)):
            return [out]
        return [tables_to_pdf(read_table(src), out)]
    tables = read_table(src)
    if t == "XLSX":
        return [write_xlsx(tables, out)]
    if t == "CSV":
        outs = []
        for i, (name, rows) in enumerate(tables.items()):
            o = out if len(tables) == 1 else sibling(src, name, ".csv")
            with open(o, "w", newline="", encoding="utf-8-sig") as f:   # BOM: Excel opens UTF-8 correctly
                csv.writer(f).writerows([["" if c is None else c for c in r] for r in _trim(rows)])
            outs.append(o)
        return outs
    if t == "JSON":
        data = {}
        for name, rows in tables.items():
            rows = _trim(rows)
            if not rows:
                data[name] = []
                continue
            head = [str(h) if h is not None else f"col{i + 1}" for i, h in enumerate(rows[0])]
            data[name] = [dict(zip(head, [_json_safe(c) for c in r])) for r in rows[1:]]
        out.write_text(json.dumps(data if len(data) > 1 else next(iter(data.values())), indent=2,
                                  ensure_ascii=False), encoding="utf-8")
        return [out]
    if t == "HTML":
        out.write_text(f"<!doctype html><meta charset='utf-8'><style>{SHEET_CSS}</style>{table_html(tables)}",
                       encoding="utf-8")
        return [out]
    raise ValueError(t)


def _json_safe(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def convert_slides(src, target: str) -> list[Path]:
    src, t = Path(src), target.upper()
    pdf = sibling(src, ext=".pdf")
    ok = office_export(src, "slides", "PDF", pdf) or libreoffice_convert(src, "pdf", pdf)
    if not ok:
        raise UserError(f"Converting slides needs PowerPoint or LibreOffice. {LIBREOFFICE_HINT}")
    if t == "PDF":
        return [pdf]
    from .convert import pdf_to_images
    try:
        return pdf_to_images(pdf, t)
    finally:
        pdf.unlink(missing_ok=True)


def convert_worddoc(src, target: str) -> list[Path]:
    """.doc / .rtf / .odt"""
    src, t = Path(src), target.upper()
    out = sibling(src, ext="." + t.lower())
    if office_export(src, "worddoc", t, out):
        return [out]
    fmt = {"PDF": "pdf", "DOCX": "docx:MS Word 2007 XML", "TXT": "txt:Text (encoded):UTF8"}[t]
    if libreoffice_convert(src, fmt, out):
        return [out]
    if t == "TXT" and src.suffix.lower() == ".rtf":
        out.write_text(rtf_to_text(_read_text(src)), encoding="utf-8")
        return [out]
    raise UserError(f"Converting {src.suffix} files needs Word or LibreOffice. {LIBREOFFICE_HINT}")


RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "headerl", "headerr",
            "footerl", "footerr", "listtable", "listoverridetable", "rsidtbl", "generator", "themedata",
            "colorschememapping", "latentstyles", "datastore", "xmlnstbl", "object", "fldinst"}


def rtf_to_text(rtf: str) -> str:
    """Small RTF → text parser: honours groups, skips destinations (font tables, pictures…),
    decodes \\'hh and \\uN escapes, turns \\par/\\line into newlines and \\tab into tabs."""
    import re
    token = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])|([{}])|([^\\{}\r\n]+)|[\r\n]+")
    out, stack, skip, uc, pending_skip = [], [], False, 1, 0
    for m in token.finditer(rtf):
        word, arg, hexch, sym, brace, text = m.groups()
        if brace == "{":
            stack.append((skip, uc))
        elif brace == "}":
            skip, uc = stack.pop() if stack else (False, 1)
        elif pending_skip and (text or hexch):
            n = min(pending_skip, len(text)) if text else 1
            pending_skip -= n
            if text and not skip:
                out.append(text[n:])
        elif word:
            if word in RTF_SKIP:
                skip = True
            elif word in ("par", "line", "sect", "row"):
                if not skip:
                    out.append("\n")
            elif word == "tab" or word == "cell":
                if not skip:
                    out.append("\t")
            elif word == "uc":
                uc = int(arg or 1)
            elif word == "u" and not skip:
                out.append(chr(int(arg) % 65536))
                pending_skip = uc
        elif sym == "*":
            skip = True
        elif sym and not skip:
            out.append({"~": "\u00a0", "-": "", "_": "-"}.get(sym, sym))
        elif hexch and not skip:
            out.append(bytes.fromhex(hexch).decode("cp1252", "replace"))
        elif text and not skip:
            out.append(text)
    txt = "".join(out)
    txt = "\n".join(line.strip() for line in txt.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", txt).strip()
