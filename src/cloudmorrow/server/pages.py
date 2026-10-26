"""Pages: text files the editor kit draws, and the pictures kept beside them.

A page is a text file in a folder of somebody's drive: a note in `Notes`, a
journal entry, a wiki page. Nothing here is special to notes. It is what the
`file` datamodel does for any text file — its words as a field, a line of
it for a list, a search through names and lines — and for the pictures a
page's Markdown points at, which are kept in an `img` folder at the top of
the folder the pages are in, named by when they arrived.

A document (docs/DOCS.md) and a sheet (docs/CELLS.md) are text files too,
and so are Word's and Excel's own: a `.docx` is read and written as the
document's text, an `.xlsx` as the sheet's, so every surface edits them as
the same field. `export` hands either over in another shape — Word, Excel,
PDF — for the record API's `/export`.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import secrets
from pathlib import Path

from cloudmorrow.quill import cells, convert, docs, docx, xlsx

__all__ = [
    "IMAGE_DIR",
    "IMAGE_TYPES",
    "MAX_IMAGE_BYTES",
    "MAX_TEXT_BYTES",
    "ExportError",
    "export",
    "image_name",
    "is_document",
    "is_image_name",
    "is_sheet",
    "is_text",
    "preview",
    "preview_of",
    "read_text",
    "search",
    "sniff_image",
    "too_big",
    "words_of",
    "write_text",
]

# A text file bigger than this is not read whole: not as a field, not for
# a preview, not for a search. Two megabytes of Markdown is a book.
MAX_TEXT_BYTES = 2_000_000
# A Word or Excel file carries its pictures and fonts along; what the kit keeps of it is small.
MAX_OFFICE_BYTES = 25_000_000
# Names Python may not know as text yet; `.cell` is a sheet (docs/CELLS.md),
# `.docs` a document (docs/DOCS.md).
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".text", ".rst", ".org", ".cell", ".docs"})
# A document's file: its own, or Word's, read and written as the same text
# (quill/docx.py turns a .docx into a document's blocks and back); a sheet's:
# its own, or Excel's (quill/xlsx.py).
DOCUMENT_SUFFIXES = frozenset({".docs", ".docx"})
SHEET_SUFFIXES = frozenset({".cell", ".xlsx"})
WORD_SUFFIX = docx.WORD_SUFFIX
EXCEL_SUFFIX = xlsx.EXCEL_SUFFIX
# Office's packages: zips read and written as text through a converter.
OFFICE_SUFFIXES = frozenset({WORD_SUFFIX, EXCEL_SUFFIX})

PREVIEW_CHARS = 120
PREVIEW_BYTES = 4096
MAX_SEARCH_RESULTS = 200

# Where a folder's pictures go, and what one may be.
IMAGE_DIR = "img"
MAX_IMAGE_BYTES = 25_000_000
IMAGE_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,160}$")
_IMAGE_STEM_RE = re.compile(r"[^a-z0-9]+")


# -- text --------------------------------------------------------------------------
def is_text(path: Path | str, mime: str = "") -> bool:
    """Is this a file whose bytes are words: by its type, or by a name Python
    does not know as text yet?"""
    if mime.startswith("text/"):
        return True
    suffix = Path(path).suffix.lower()
    return suffix in TEXT_SUFFIXES or suffix in OFFICE_SUFFIXES


def is_document(path: Path | str) -> bool:
    """A document of the document kit: its own `.docs`, or a Word file."""
    return Path(path).suffix.lower() in DOCUMENT_SUFFIXES


def is_sheet(path: Path | str) -> bool:
    """A sheet of the sheet kit: its own `.cell`, or an Excel file."""
    return Path(path).suffix.lower() in SHEET_SUFFIXES


def too_big(path: Path) -> bool:
    """Too big to read whole as a field, a preview or a search."""
    limit = MAX_OFFICE_BYTES if Path(path).suffix.lower() in OFFICE_SUFFIXES else MAX_TEXT_BYTES
    return path.stat().st_size > limit


def read_text(path: Path) -> str:
    """The file's words. Bytes that are not UTF-8 become the replacement
    character rather than an error: a page is read to be shown. A Word
    file's text is the document in it, as a `.docs` file would hold it;
    an Excel file's the sheet in it, as a `.cell` file would."""
    suffix = path.suffix.lower()
    if suffix == WORD_SUFFIX:
        try:
            return docx.read_docx(path.read_bytes()).to_text()
        except docx.DocxError:
            return ""
    if suffix == EXCEL_SUFFIX:
        try:
            return xlsx.read_xlsx(path.read_bytes()).to_text()
        except xlsx.XlsxError:
            return ""
    return path.read_bytes().decode("utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    """Write the whole of *text* so the file is whole or untouched. A Word
    file is written as Word's own package, from the document in *text*;
    an Excel file as Excel's, from the sheet."""
    tmp = path.with_name(f".{path.name}.tmp")
    suffix = path.suffix.lower()
    if suffix == WORD_SUFFIX:
        tmp.write_bytes(docx.write_docx(docs.Doc.from_text(text)))
    elif suffix == EXCEL_SUFFIX:
        tmp.write_bytes(xlsx.write_xlsx(cells.Sheet.from_text(text)))
    else:
        tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def words_of(path: Path) -> str:
    """What a search reads and a preview shows: a page's text, a
    document's words alone, a block a line, or a sheet's cells as typed,
    a cell a line."""
    text = read_text(path)
    if is_document(path):
        return docs.Doc.from_text(text).text
    if is_sheet(path):
        return "\n".join(cells.Sheet.from_text(text).cells.values())
    return text


def preview_of(path: Path) -> str:
    """The line or two a list shows under a file's name."""
    if is_document(path):
        return docs.preview(docs.Doc.from_text(read_text(path)))
    if is_sheet(path):
        sheet = cells.Sheet.from_text(read_text(path))
        shown = [sheet.shown(name) for name in list(sheet.cells)[:8]]
        return " · ".join(s for s in shown if s)[:PREVIEW_CHARS]
    return preview(read_text(path), path.stem)


# -- in another shape -----------------------------------------------------------------
class ExportError(ValueError):
    """A file nothing here exports, or a shape it has not got."""


def export(path: Path, fmt: str) -> tuple[bytes, str, str]:
    """The file as *fmt* says — a document as Word, PDF, Markdown or
    `.docs`; a sheet as Excel, PDF, CSV or `.cell` — with its media type
    and the name to save it by. A file asked for as itself is its own bytes."""
    suffix = convert.suffix_of(fmt)
    name = path.stem + suffix
    if is_document(path):
        formats = convert.DOCUMENT_FORMATS
    elif is_sheet(path):
        formats = convert.SHEET_FORMATS
    else:
        raise ExportError(f"{path.name} is not a document or a sheet")
    if suffix not in formats:
        raise ExportError(f"{path.name} goes out as {', '.join(formats)}, not {fmt or 'nothing'}")
    media_type = formats[suffix][1]
    if path.suffix.lower() == suffix:
        return path.read_bytes(), media_type, name
    if too_big(path):
        raise ExportError(f"{path.name} is too big to export")
    try:
        if is_document(path):
            return convert.document_bytes(docs.Doc.from_text(read_text(path)), suffix, path.stem), media_type, name
        return convert.sheet_bytes(cells.Sheet.from_text(read_text(path)), suffix, path.stem), media_type, name
    except convert.ConvertError as exc:
        raise ExportError(str(exc)) from None


def preview(text: str, stem: str, *, chars: int = PREVIEW_CHARS) -> str:
    """The first line or two of a page, as a list would show them.

    A heading that repeats the page's name is skipped — the terminal starts
    every new page with one — and so are blank lines, a picture on a line
    of its own, and the Markdown markers a phone does not need to see. Only
    the head of the text is looked at, since a list does this for every
    page it shows.
    """
    head = text[:PREVIEW_BYTES]
    lines: list[str] = []
    for raw in head.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") and line.lstrip("#").strip() == stem:
            continue
        if line.startswith("![") and line.endswith(")"):
            continue
        line = line.lstrip("#").strip()
        for marker in ("- [ ] ", "- [x] ", "- ", "* "):
            line = line.removeprefix(marker)
        lines.append(line)
        if len(" ".join(lines)) >= chars or len(lines) >= 2:
            break
    joined = " ".join(lines)
    return joined[: chars - 1] + "…" if len(joined) > chars else joined


def search(files: list[tuple[str, Path, str]], query: str, *, limit: int = MAX_SEARCH_RESULTS) -> dict[str, str]:
    """Which of *files* — `(key, path, mime)` — hold *query* in their name or,
    for a text file, in a line; by key, with the first line that matched
    (its name when only the name did). Case does not matter."""
    needle = query.strip().casefold()
    found: dict[str, str] = {}
    if not needle:
        return found
    for key, path, mime in files:
        hit = needle in path.name.casefold()
        line = path.name if hit else ""
        if is_text(path, mime):
            try:
                if not too_big(path):
                    for candidate in words_of(path).splitlines():
                        if needle in candidate.casefold():
                            hit, line = True, candidate.strip()[:200]
                            break
            except OSError:
                pass
        if hit:
            found[key] = line
            if len(found) >= limit:
                break
    return found


# -- pictures ----------------------------------------------------------------------
def sniff_image(data: bytes) -> str | None:
    """The media type the bytes say they are — never what the upload claimed."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_name(filename: str, content_type: str) -> str:
    """A name that says when a picture arrived: `20260917-134501-ab12cd-holiday.jpg`.

    The moment, six random hex so two pastes in one second cannot collide,
    and what the file was called if it was called anything, so `ls img/`
    still means something. The suffix is the type the bytes said.
    """
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = _IMAGE_STEM_RE.sub("-", Path(filename).stem.lower()).strip("-")[:40]
    name = "-".join(part for part in (stamp, secrets.token_hex(3), stem) if part)
    return f"{name}.{IMAGE_TYPES[content_type]}"


def is_image_name(name: str) -> bool:
    return bool(_IMAGE_NAME_RE.match(name or ""))
