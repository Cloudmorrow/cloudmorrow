"""A document, or a sheet, as a PDF: pages anyone opens, prints and sends.

A PDF here is made by hand from the standard library alone: pages of
Helvetica — the font every reader has, so nothing is embedded — with the
words wrapped to the page, headings larger and bold, lists with their
markers, quotes set in, tables and grids ruled, and links that open. It
is a printout, not an editor: what the document kit keeps (quill/docs.py)
and what a sheet comes to (quill/cells.py) are drawn, and nothing is read
back. Letters outside Latin-1 become `?`, which is what Helvetica has.
"""

from __future__ import annotations

import unicodedata

from cloudmorrow.quill import cells
from cloudmorrow.quill.cells import Sheet
from cloudmorrow.quill.docs import Doc

MEDIA_TYPE = "application/pdf"
PDF_SUFFIX = ".pdf"

A4 = (595.0, 842.0)
MARGIN = 56.0

# -- Helvetica's widths, per thousandth of the size ------------------------------------
_REGULAR_ASCII = (
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 "
    "278 278 584 584 584 556 1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778 722 667 "
    "611 722 667 944 667 667 611 278 278 278 469 556 333 556 556 500 556 556 278 556 556 222 222 500 222 833 "
    "556 556 556 556 333 500 278 556 500 722 500 500 500 334 260 334 584"
)
_BOLD_ASCII = (
    "278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 "
    "333 333 584 584 584 611 975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 667 778 722 667 "
    "611 722 667 944 667 667 611 333 278 333 584 556 333 556 611 556 611 556 333 611 611 278 278 556 278 889 "
    "611 611 611 611 389 556 333 611 556 778 556 556 500 389 280 389 584"
)
# The letters above 127 that are not an accented one of the first 128.
_REGULAR_MORE = {
    "Æ": 1000,
    "æ": 889,
    "Ø": 778,
    "ø": 611,
    "Œ": 1000,
    "œ": 944,
    "ß": 611,
    "Ð": 722,
    "ð": 556,
    "Þ": 667,
    "þ": 556,
    "ƒ": 556,
    "€": 556,
    "–": 556,
    "—": 1000,
    "‘": 222,
    "’": 222,
    "‚": 222,
    "“": 333,
    "”": 333,
    "„": 333,
    "†": 556,
    "‡": 556,
    "•": 350,
    "…": 1000,
    "‰": 1000,
    "‹": 333,
    "›": 333,
    "™": 1000,
    "ˆ": 333,
    "˜": 333,
    "\xa0": 278,
    "¡": 333,
    "¢": 556,
    "£": 556,
    "¤": 556,
    "¥": 556,
    "¦": 260,
    "§": 556,
    "¨": 333,
    "©": 737,
    "ª": 370,
    "«": 556,
    "¬": 584,
    "\xad": 333,
    "®": 737,
    "¯": 333,
    "°": 400,
    "±": 584,
    "²": 333,
    "³": 333,
    "´": 333,
    "µ": 556,
    "¶": 537,
    "·": 278,
    "¸": 333,
    "¹": 333,
    "º": 365,
    "»": 556,
    "¼": 834,
    "½": 834,
    "¾": 834,
    "¿": 611,
    "×": 584,
    "÷": 584,
}
_BOLD_MORE = {
    **_REGULAR_MORE,
    "ð": 611,
    "þ": 611,
    "‘": 278,
    "’": 278,
    "‚": 278,
    "“": 500,
    "”": 500,
    "„": 500,
    "¦": 280,
    "µ": 611,
    "¶": 556,
}


def _widths(ascii_widths: str, more: dict[str, int]) -> dict[int, int]:
    """Per byte of WinAnsi, the glyph's width."""
    table = {32 + i: int(w) for i, w in enumerate(ascii_widths.split())}
    for code in range(128, 256):
        char = bytes([code]).decode("cp1252", errors="ignore")
        if not char:
            continue
        if char in more:
            table[code] = more[char]
            continue
        base = unicodedata.normalize("NFD", char)[0]
        table[code] = table.get(ord(base), 556)
    return table


FONTS = {
    "F1": ("Helvetica", _widths(_REGULAR_ASCII, _REGULAR_MORE)),
    "F2": ("Helvetica-Bold", _widths(_BOLD_ASCII, _BOLD_MORE)),
    "F3": ("Helvetica-Oblique", _widths(_REGULAR_ASCII, _REGULAR_MORE)),
    "F4": ("Helvetica-BoldOblique", _widths(_BOLD_ASCII, _BOLD_MORE)),
}


def font_for(bold: bool = False, italic: bool = False) -> str:
    return "F" + str(1 + (1 if bold else 0) + (2 if italic else 0))


def encode(text: str) -> bytes:
    """The text as WinAnsi bytes; what Helvetica has not got is a `?`."""
    return str(text).encode("cp1252", errors="replace")


def width_of(text: str, font: str, size: float) -> float:
    table = FONTS[font][1]
    return sum(table.get(b, 556) for b in encode(text)) * size / 1000


# -- the file ---------------------------------------------------------------------------
def _literal(data: bytes) -> str:
    out = []
    for b in data:
        if b in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(b))
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def _number(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


class Pdf:
    """Pages drawn with a few operators, and written out as one file."""

    def __init__(self, *, landscape: bool = False, title: str = "") -> None:
        self.width, self.height = (A4[1], A4[0]) if landscape else A4
        self.title = title
        self.pages: list[list[str]] = []
        self.links: list[list[tuple[float, float, float, float, str]]] = []

    def new_page(self) -> None:
        self.pages.append([])
        self.links.append([])

    def text(self, x: float, y: float, text: str, font: str, size: float, color: str = "0 g") -> None:
        """*text* with its baseline at *y* from the bottom of the page."""
        if not text:
            return
        self.pages[-1].append(
            f"BT {color} /{font} {_number(size)} Tf 1 0 0 1 {_number(x)} {_number(y)} Tm {_literal(encode(text))} Tj ET"
        )

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5, gray: float = 0.0) -> None:
        self.pages[-1].append(
            f"{_number(gray)} G {_number(width)} w {_number(x1)} {_number(y1)} m {_number(x2)} {_number(y2)} l S"
        )

    def link(self, x1: float, y1: float, x2: float, y2: float, url: str) -> None:
        self.links[-1].append((x1, y1, x2, y2, url))

    def render(self) -> bytes:
        if not self.pages:
            self.new_page()
        objects: list[bytes] = []

        def add(body: str | bytes) -> int:
            objects.append(body.encode("latin-1") if isinstance(body, str) else body)
            return len(objects)

        # 1 is the catalog, 2 the pages: filled in once the pages are numbered.
        add("")
        add("")
        fonts = {
            name: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>")
            for name, (base, _widths) in FONTS.items()
        }
        resources = "<< /Font << " + " ".join(f"/{n} {num} 0 R" for n, num in fonts.items()) + " >> >>"
        page_numbers = []
        for ops, links in zip(self.pages, self.links, strict=True):
            stream = "\n".join(ops).encode("latin-1")
            content = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
            annots = ""
            if links:
                numbers = []
                for x1, y1, x2, y2, url in links:
                    uri = _literal(url.encode("utf-8"))
                    numbers.append(
                        add(
                            f"<< /Type /Annot /Subtype /Link /Rect [{_number(x1)} {_number(y1)} {_number(x2)} "
                            f"{_number(y2)}] /Border [0 0 0] /A << /S /URI /URI {uri} >> >>"
                        )
                    )
                annots = " /Annots [" + " ".join(f"{n} 0 R" for n in numbers) + "]"
            page_numbers.append(
                add(
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_number(self.width)} {_number(self.height)}] "
                    f"/Resources {resources} /Contents {content} 0 R{annots} >>"
                )
            )
        objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
        kids = " ".join(f"{n} 0 R" for n in page_numbers)
        objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_numbers)} >>".encode("latin-1")
        title = "<FEFF" + self.title.encode("utf-16-be").hex().upper() + ">"
        info = add(f"<< /Title {title} /Producer (Cloudmorrow) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for index, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode()
        trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R /Info {info} 0 R >>"
        out += f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


# -- flowing words ----------------------------------------------------------------------
# A piece is a word, or the space after one, in a run's style; a line is
# the pieces that fit across, measured in the font each is set in.
LINK_COLOR = "0.05 0.35 0.75 rg"


def _pieces(runs: list[dict], size: float) -> list[dict]:
    pieces = []
    for r in runs:
        font = font_for(bool(r.get("bold")), bool(r.get("italic")))
        for line_no, line in enumerate(r["text"].split("\n")):
            if line_no:
                pieces.append({"break": True})
            for word in line.replace("\t", "    ").split(" "):
                pieces.append({"text": word, "font": font, "size": size, "width": width_of(word, font, size), "run": r})
                pieces.append({"space": True, "font": font, "size": size, "width": width_of(" ", font, size), "run": r})
            if pieces and pieces[-1].get("space"):
                pieces.pop()
    return pieces


def flow(runs: list[dict], width: float, size: float) -> list[list[dict]]:
    """The runs as lines that fit in *width*: each a list of pieces."""
    lines: list[list[dict]] = [[]]
    used = 0.0
    for piece in _pieces(runs, size):
        if piece.get("break"):
            lines.append([])
            used = 0.0
            continue
        if piece.get("space"):
            if lines[-1]:
                lines[-1].append(piece)
                used += piece["width"]
            continue
        if lines[-1] and used + piece["width"] > width:
            # Trailing spaces do not count against the line.
            while lines[-1] and lines[-1][-1].get("space"):
                lines[-1].pop()
            lines.append([])
            used = 0.0
        lines[-1].append(piece)
        used += piece["width"]
    for line in lines:
        while line and line[-1].get("space"):
            line.pop()
    return lines


def _line_width(line: list[dict]) -> float:
    return sum(p["width"] for p in line)


def _draw_line(pdf: Pdf, line: list[dict], x: float, y: float, size: float) -> None:
    """One flowed line at baseline *y*, with its underlines, strikes and links."""
    at = x
    for piece in line:
        r = piece["run"]
        text = " " if piece.get("space") else piece["text"]
        color = LINK_COLOR if r.get("link") else "0 g"
        if not piece.get("space"):
            pdf.text(at, y, text, piece["font"], size, color)
        end = at + piece["width"]
        if r.get("underline") or r.get("link"):
            gray = 0.0 if r.get("underline") else 0.3
            pdf.line(at, y - size * 0.12, end, y - size * 0.12, width=size * 0.05, gray=gray)
        if r.get("strike"):
            pdf.line(at, y + size * 0.28, end, y + size * 0.28, width=size * 0.06)
        if r.get("link"):
            pdf.link(at, y - size * 0.25, end, y + size * 0.9, str(r["link"]))
        at = end


# -- a document --------------------------------------------------------------------------
HEADING_SIZES = {1: 20.0, 2: 15.0, 3: 12.5}
BODY_SIZE = 11.0
LEADING = 1.35
LIST_INDENT = 18.0
QUOTE_INDENT = 22.0
CELL_PAD = 4.0


class _Page:
    """Where the next line goes on the page, and a new page when it is full."""

    def __init__(self, pdf: Pdf) -> None:
        self.pdf = pdf
        self.y = 0.0
        self.left = MARGIN
        self.right = pdf.width - MARGIN
        self.bottom = MARGIN
        self.fresh()

    def fresh(self) -> None:
        self.pdf.new_page()
        self.y = self.pdf.height - MARGIN

    def need(self, height: float) -> None:
        if self.y - height < self.bottom and self.y < self.pdf.height - MARGIN:
            self.fresh()

    @property
    def width(self) -> float:
        return self.right - self.left


def _paragraph(
    page: _Page,
    b: dict,
    *,
    size: float,
    indent: float = 0.0,
    before: float = 0.0,
    after: float = 0.0,
    marker: str = "",
    bar: bool = False,
) -> None:
    runs = b.get("runs") or []
    if bar:
        runs = [{**r, "italic": True} for r in runs]
    lead = size * LEADING
    lines = flow(runs, page.width - indent, size) or [[]]
    if page.y < page.pdf.height - MARGIN:
        page.y -= before
    page.need(lead * min(2, len(lines)))
    top = page.y
    marker_font = font_for(bool(runs and runs[0].get("bold")))
    for index, line in enumerate(lines):
        page.need(lead)
        baseline = page.y - size
        x = page.left + indent
        align = b.get("align", "")
        if align in ("center", "right"):
            slack = page.width - indent - _line_width(line)
            x += slack / 2 if align == "center" else slack
        if index == 0 and marker:
            gutter = page.left + indent - width_of(marker, marker_font, size) - 5
            page.pdf.text(gutter, baseline, marker, marker_font, size)
        _draw_line(page.pdf, line, x, baseline, size)
        page.y -= lead
    if bar:
        bar_x = page.left + indent - 10
        page.pdf.line(bar_x, top - 2, bar_x, page.y + lead - size + 1, width=1.5, gray=0.6)
    page.y -= after


def _table(page: _Page, b: dict) -> None:
    rows = b.get("rows") or []
    if not rows:
        return
    columns = max(len(row) for row in rows)
    col_width = page.width / columns
    inner = col_width - 2 * CELL_PAD
    lead = BODY_SIZE * LEADING
    page.y -= 2
    for row in rows:
        flowed = [flow(cell.get("runs") or [], inner, BODY_SIZE) or [[]] for cell in row]
        height = max(len(lines) for lines in flowed) * lead + 2 * CELL_PAD
        page.need(height)
        top = page.y
        for index, lines in enumerate(flowed):
            x = page.left + index * col_width
            y = top - CELL_PAD
            for line in lines:
                _draw_line(page.pdf, line, x + CELL_PAD, y - BODY_SIZE, BODY_SIZE)
                y -= lead
        bottom = top - height
        page.pdf.line(page.left, top, page.right, top, gray=0.5)
        page.pdf.line(page.left, bottom, page.right, bottom, gray=0.5)
        for index in range(columns + 1):
            x = page.left + index * col_width
            page.pdf.line(x, top, x, bottom, gray=0.5)
        page.y = bottom
    page.y -= 10


def document_pdf(doc: Doc, title: str = "") -> bytes:
    """The document as pages: headings, paragraphs, lists, quotes, tables."""
    pdf = Pdf(title=title)
    page = _Page(pdf)
    counters: dict[int, int] = {}
    previous = ""
    for b in doc.blocks:
        kind = b["kind"]
        if kind not in ("bullet", "numbered"):
            counters.clear()
        if kind == "heading":
            level = int(b.get("level") or 1)
            size = HEADING_SIZES.get(level, BODY_SIZE)
            _paragraph(
                page,
                {**b, "runs": [{**r, "bold": True} for r in b["runs"]]},
                size=size,
                before=(14.0, 10.0, 8.0)[min(level, 3) - 1] if previous else 0.0,
                after=5.0,
            )
        elif kind in ("bullet", "numbered"):
            level = int(b.get("level") or 0)
            for deeper in [k for k in counters if k > level]:
                del counters[deeper]
            if kind == "numbered":
                counters[level] = counters.get(level, 0) + 1
                marker = f"{counters[level]}."
            else:
                marker = ("•", "–", "·")[min(level, 2)]
            _paragraph(page, b, size=BODY_SIZE, indent=LIST_INDENT * (level + 1), marker=marker, after=2.0)
        elif kind == "quote":
            _paragraph(page, b, size=BODY_SIZE, indent=QUOTE_INDENT, before=4.0, after=8.0, bar=True)
        elif kind == "table":
            _table(page, b)
        else:
            _paragraph(page, b, size=BODY_SIZE, after=7.0)
        previous = kind
    return pdf.render()


# -- a sheet -----------------------------------------------------------------------------
GRID_SIZE = 9.0
GRID_LEAD = 15.0
GRID_PAD = 4.0
MIN_COL = 36.0
MAX_COL = 200.0


def _shown(sheet: Sheet, name: str) -> tuple[str, bool]:
    """A cell's text, and whether it sits to the right (a number does)."""
    value = sheet.value(name)
    return cells.display(value), isinstance(value, (int, float)) and not isinstance(value, bool)


def _fit(text: str, font: str, size: float, width: float) -> str:
    """The text that fits in *width*, cut with an ellipsis when it does not."""
    if width_of(text, font, size) <= width:
        return text
    while text and width_of(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _chunks(sizes: list[float], room: float) -> list[tuple[int, int]]:
    """Runs of (start, end) indexes whose sizes fit in *room* together."""
    out: list[tuple[int, int]] = []
    start = 0
    used = 0.0
    for index, size in enumerate(sizes):
        if index > start and used + size > room:
            out.append((start, index))
            start, used = index, 0.0
        used += size
    out.append((start, len(sizes)))
    return out


def sheet_pdf(sheet: Sheet, title: str = "") -> bytes:
    """The sheet as a ruled grid of what its cells come to, column and row
    headings in grey, the borders it has in black; wide sheets go
    landscape, and what does not fit a page goes on the next ones."""
    places = [cells.parse_ref(n) for n in list(sheet.cells) + list(sheet.format)]
    rows = max((at[0] + 1 for at in places if at), default=1)
    cols = max((at[1] + 1 for at in places if at), default=1)
    shown: dict[str, tuple[str, bool]] = {}
    widths = []
    for c in range(cols):
        widest = MIN_COL
        for r in range(rows):
            name = cells.ref_name(r, c)
            if name not in sheet.cells:
                continue
            shown[name] = _shown(sheet, name)
            widest = max(widest, width_of(shown[name][0], "F1", GRID_SIZE) + 2 * GRID_PAD)
        widths.append(min(MAX_COL, widest))
    head_width = width_of(str(rows), "F1", GRID_SIZE) + 2 * GRID_PAD
    total = head_width + sum(widths)
    landscape = total > A4[0] - 2 * MARGIN
    pdf = Pdf(landscape=landscape, title=title)
    room_across = pdf.width - 2 * MARGIN - head_width
    room_down = pdf.height - 2 * MARGIN - (GRID_LEAD + 10 if title else 0) - GRID_LEAD
    col_chunks = _chunks(widths, room_across)
    row_chunks = _chunks([GRID_LEAD] * rows, room_down)
    for r0, r1 in row_chunks:
        for c0, c1 in col_chunks:
            pdf.new_page()
            top = pdf.height - MARGIN
            if title:
                pdf.text(MARGIN, top - 11, title, "F2", 11)
                top -= GRID_LEAD + 10
            xs = [MARGIN + head_width]
            for c in range(c0, c1):
                xs.append(xs[-1] + widths[c])
            ys = [top - GRID_LEAD * (i + 1) for i in range(-1, r1 - r0 + 1)]
            # Headings: the column names across, the row numbers down.
            for i, c in enumerate(range(c0, c1)):
                name = cells.col_name(c)
                pdf.text(
                    xs[i] + (widths[c] - width_of(name, "F1", GRID_SIZE)) / 2,
                    ys[1] + GRID_PAD,
                    name,
                    "F1",
                    GRID_SIZE,
                    "0.45 g",
                )
            for i, r in enumerate(range(r0, r1)):
                label = str(r + 1)
                pdf.text(
                    MARGIN + head_width - GRID_PAD - width_of(label, "F1", GRID_SIZE),
                    ys[i + 2] + GRID_PAD,
                    label,
                    "F1",
                    GRID_SIZE,
                    "0.45 g",
                )
            # The grid, in grey, then the words, then the borders in black.
            for y in ys:
                pdf.line(MARGIN, y, xs[-1], y, width=0.3, gray=0.75)
            for x in [MARGIN, *xs]:
                pdf.line(x, ys[0], x, ys[-1], width=0.3, gray=0.75)
            for i, r in enumerate(range(r0, r1)):
                for j, c in enumerate(range(c0, c1)):
                    name = cells.ref_name(r, c)
                    if name in shown:
                        text, right = shown[name]
                        text = _fit(text, "F1", GRID_SIZE, widths[c] - 2 * GRID_PAD)
                        x = xs[j] + (widths[c] - GRID_PAD - width_of(text, "F1", GRID_SIZE) if right else GRID_PAD)
                        pdf.text(x, ys[i + 2] + GRID_PAD, text, "F1", GRID_SIZE)
                    sides = sheet.border(name) if name in sheet.format else []
                    x1, x2, y1, y2 = xs[j], xs[j + 1], ys[i + 1], ys[i + 2]
                    if "top" in sides:
                        pdf.line(x1, y1, x2, y1, width=0.9)
                    if "bottom" in sides:
                        pdf.line(x1, y2, x2, y2, width=0.9)
                    if "left" in sides:
                        pdf.line(x1, y1, x1, y2, width=0.9)
                    if "right" in sides:
                        pdf.line(x2, y1, x2, y2, width=0.9)
    return pdf.render()


def is_pdf(data: bytes) -> bool:
    return data[:5] == b"%PDF-"
