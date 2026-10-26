"""Pages: text files the editor kit draws, and the pictures kept beside them.

A page is a text file in a folder of somebody's drive: a note in `Notes`, a
journal entry, a wiki page. Nothing here is special to notes. It is what the
`file` datamodel does for any text file — its words as a field, a line of
it for a list, a search through names and lines — and for the pictures a
page's Markdown points at, which are kept in an `img` folder at the top of
the folder the pages are in, named by when they arrived.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import secrets
from pathlib import Path

from cloudmorrow.quill import docs, docx

__all__ = [
    "IMAGE_DIR",
    "IMAGE_TYPES",
    "MAX_IMAGE_BYTES",
    "MAX_TEXT_BYTES",
    "image_name",
    "is_document",
    "is_image_name",
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
# A Word file carries its pictures and fonts along; what the kit keeps of it is small.
MAX_WORD_BYTES = 25_000_000
# Names Python may not know as text yet; `.cell` is a sheet (docs/CELLS.md),
# `.docs` a document (docs/DOCS.md).
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".text", ".rst", ".org", ".cell", ".docs"})
# A document's file: its own, or Word's, read and written as the same text
# (quill/docx.py turns a .docx into a document's blocks and back).
DOCUMENT_SUFFIXES = frozenset({".docs", ".docx"})
WORD_SUFFIX = ".docx"

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
    return suffix in TEXT_SUFFIXES or suffix == WORD_SUFFIX


def is_document(path: Path | str) -> bool:
    """A document of the document kit: its own `.docs`, or a Word file."""
    return Path(path).suffix.lower() in DOCUMENT_SUFFIXES


def too_big(path: Path) -> bool:
    """Too big to read whole as a field, a preview or a search."""
    limit = MAX_WORD_BYTES if Path(path).suffix.lower() == WORD_SUFFIX else MAX_TEXT_BYTES
    return path.stat().st_size > limit


def read_text(path: Path) -> str:
    """The file's words. Bytes that are not UTF-8 become the replacement
    character rather than an error: a page is read to be shown. A Word
    file's text is the document in it, as a `.docs` file would hold it."""
    if path.suffix.lower() == WORD_SUFFIX:
        try:
            return docx.read_docx(path.read_bytes()).to_text()
        except docx.DocxError:
            return ""
    return path.read_bytes().decode("utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    """Write the whole of *text* so the file is whole or untouched. A Word
    file is written as Word's own package, from the document in *text*."""
    tmp = path.with_name(f".{path.name}.tmp")
    if path.suffix.lower() == WORD_SUFFIX:
        tmp.write_bytes(docx.write_docx(docs.Doc.from_text(text)))
    else:
        tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def words_of(path: Path) -> str:
    """What a search reads and a preview shows: a page's text, or a
    document's words alone, a block a line."""
    text = read_text(path)
    return docs.Doc.from_text(text).text if is_document(path) else text


def preview_of(path: Path) -> str:
    """The line or two a list shows under a file's name."""
    if is_document(path):
        return docs.preview(docs.Doc.from_text(read_text(path)))
    return preview(read_text(path), path.stem)


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
