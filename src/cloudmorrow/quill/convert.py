"""A document or a sheet in another shape: what Export hands over, on every surface.

A document (quill/docs.py) goes out as Word (`.docx`), PDF, Markdown or
its own `.docs`; a sheet (quill/cells.py) as Excel (`.xlsx`), PDF, CSV or
its own `.cell`. The same table serves the web app's Export button, the
terminal's and the command line's `export`, so the file a phone saves and
the one `cm docs export` writes are the same bytes.
"""

from __future__ import annotations

import csv
import io

from cloudmorrow.quill import cells, docs, docx, pdf, xlsx

# By suffix: what it is called, and the media type it is served as.
DOCUMENT_FORMATS: dict[str, tuple[str, str]] = {
    ".docx": ("Word", docx.MEDIA_TYPE),
    ".pdf": ("PDF", pdf.MEDIA_TYPE),
    ".md": ("Markdown", "text/markdown; charset=utf-8"),
    ".docs": ("Document", "application/json; charset=utf-8"),
}
SHEET_FORMATS: dict[str, tuple[str, str]] = {
    ".xlsx": ("Excel", xlsx.MEDIA_TYPE),
    ".pdf": ("PDF", pdf.MEDIA_TYPE),
    ".csv": ("CSV", "text/csv; charset=utf-8"),
    ".cell": ("Sheet", "application/json; charset=utf-8"),
}


class ConvertError(ValueError):
    """A shape nothing here can make."""


def suffix_of(fmt: str) -> str:
    """`pdf`, `.PDF` or `PDF` → `.pdf`."""
    fmt = str(fmt or "").strip().lower()
    return fmt if fmt.startswith(".") else "." + fmt


def document_bytes(doc: docs.Doc, fmt: str, title: str = "") -> bytes:
    """The document as a file of the kind *fmt* names (a suffix)."""
    suffix = suffix_of(fmt)
    if suffix == ".docx":
        return docx.write_docx(doc)
    if suffix == ".pdf":
        return pdf.document_pdf(doc, title)
    if suffix == ".md":
        return docs.to_markdown(doc).encode("utf-8")
    if suffix == ".docs":
        return doc.to_text().encode("utf-8")
    raise ConvertError(f"a document goes out as {', '.join(DOCUMENT_FORMATS)}, not {fmt}")


def sheet_csv(sheet: cells.Sheet) -> str:
    """The sheet's values as CSV, a row a line, as far as its cells go."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for row in cells.table(sheet)[1:]:
        writer.writerow(row[1:])
    return out.getvalue()


def sheet_bytes(sheet: cells.Sheet, fmt: str, title: str = "") -> bytes:
    """The sheet as a file of the kind *fmt* names (a suffix)."""
    suffix = suffix_of(fmt)
    if suffix == ".xlsx":
        return xlsx.write_xlsx(sheet)
    if suffix == ".pdf":
        return pdf.sheet_pdf(sheet, title)
    if suffix == ".csv":
        return sheet_csv(sheet).encode("utf-8")
    if suffix == ".cell":
        return sheet.to_text().encode("utf-8")
    raise ConvertError(f"a sheet goes out as {', '.join(SHEET_FORMATS)}, not {fmt}")
