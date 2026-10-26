"""A sheet as an Excel file: reading an .xlsx into cells, and writing one back.

An .xlsx is a zip of XML; what the sheet kit keeps (quill/cells.py) is read
out of the first worksheet — each cell's text, number or formula, and the
borders its style gives it — and everything else is passed over: other
sheets, fonts, colours, number formats, charts, column widths. Writing
makes a small, plain package Excel opens as it is: the same cells, a
formula with the value it came to, and the borders.

Nothing here is Excel's own library: the standard library's zipfile and
ElementTree are enough for the shape a sheet keeps.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from cloudmorrow.quill import cells
from cloudmorrow.quill.cells import SIDES, Error, Sheet

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN}

EXCEL_SUFFIX = ".xlsx"
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class XlsxError(ValueError):
    """Not an Excel file this can read."""


# -- reading ------------------------------------------------------------------------------
def _tag(name: str) -> str:
    return f"{{{MAIN}}}{name}"


def _rels(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
    try:
        root = ET.fromstring(archive.read(name))
    except KeyError:
        return {}
    return {r.get("Id", ""): r.get("Target", "") for r in root.iter(f"{{{PKG}}}Relationship")}


def _first_sheet(archive: zipfile.ZipFile) -> str:
    """The name in the archive of the first worksheet."""
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    except KeyError:
        raise XlsxError("no workbook") from None
    rels = _rels(archive, "xl/_rels/workbook.xml.rels")
    for sheet in workbook.iter(_tag("sheet")):
        target = rels.get(sheet.get(f"{{{REL}}}id", ""), "")
        if target:
            return target.lstrip("/") if target.startswith("/") else "xl/" + target
    # No sheets list worth reading: the usual place.
    if "xl/worksheets/sheet1.xml" in archive.namelist():
        return "xl/worksheets/sheet1.xml"
    raise XlsxError("no worksheet")


def _text_in(node: ET.Element | None) -> str:
    """The text of a shared or inline string: its `t` parts, rich runs and all."""
    if node is None:
        return ""
    return "".join(t.text or "" for t in node.iter(_tag("t")))


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [_text_in(si) for si in root.iter(_tag("si"))]


def _borders(archive: zipfile.ZipFile) -> list[list[str]]:
    """Per cell style (cellXfs index), the sides it draws a border on."""
    try:
        root = ET.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return []
    sides_of: list[list[str]] = []
    borders = root.find("m:borders", NS)
    for border in borders.findall("m:border", NS) if borders is not None else []:
        sides = []
        for side in SIDES:
            one = border.find(f"m:{side}", NS)
            if one is not None and (one.get("style") or "none") != "none":
                sides.append(side)
        sides_of.append(sides)
    styles: list[list[str]] = []
    xfs = root.find("m:cellXfs", NS)
    for xf in xfs.findall("m:xf", NS) if xfs is not None else []:
        try:
            index = int(xf.get("borderId") or 0)
        except ValueError:
            index = 0
        styles.append(sides_of[index] if 0 <= index < len(sides_of) else [])
    return styles


def _number_text(raw: str) -> str:
    """Excel's `<v>` for a number, as a cell would hold it: 12.0 is 12."""
    try:
        value = float(raw)
    except ValueError:
        return raw
    return cells.number_text(value)


def read_xlsx(data: bytes) -> Sheet:
    """The first worksheet of an Excel file, as a sheet."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise XlsxError("not an Excel file") from None
    with archive:
        try:
            root = ET.fromstring(archive.read(_first_sheet(archive)))
        except (KeyError, ET.ParseError):
            raise XlsxError("not an Excel file") from None
        strings = _shared_strings(archive)
        styles = _borders(archive)
    sheet = Sheet()
    for c in root.iter(_tag("c")):
        name = c.get("r", "")
        if cells.parse_ref(name) is None:
            continue
        kind = c.get("t", "")
        formula = c.find("m:f", NS)
        value = c.find("m:v", NS)
        raw = ""
        typed = False
        if formula is not None and (formula.text or "").strip():
            raw = "=" + formula.text.strip()
        elif kind == "s":
            typed = True
            try:
                raw = strings[int((value.text or "").strip())]
            except (ValueError, IndexError):
                raw = ""
        elif kind == "inlineStr":
            typed = True
            raw = _text_in(c.find("m:is", NS))
        elif kind == "b":
            raw = "TRUE" if (value.text or "").strip() == "1" else "FALSE"
        elif kind in ("str", "e"):
            typed = kind == "str"
            raw = (value.text or "") if value is not None else ""
        elif value is not None:
            raw = _number_text((value.text or "").strip())
        # Text that would be taken for a number or a formula stays text.
        if typed and raw and (raw.startswith("=") or cells.literal(raw) != raw):
            raw = "'" + raw
        if raw.strip():
            sheet.set(name, raw)
        try:
            style = int(c.get("s") or 0)
        except ValueError:
            style = 0
        if 0 <= style < len(styles) and styles[style]:
            sheet.set_border(name, styles[style])
    return sheet


# -- writing ------------------------------------------------------------------------------
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG}">
<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{MAIN}" xmlns:r="{REL}">
<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

_WORKBOOK_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG}">
<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="{REL}/styles" Target="styles.xml"/>
</Relationships>"""

# What a formula's error is called in Excel; one Excel does not know is a #VALUE!.
_EXCEL_ERRORS = {"#DIV/0!", "#REF!", "#NAME?", "#VALUE!", "#N/A"}


def _styles_xml(border_sets: list[tuple[str, ...]]) -> str:
    borders = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
    for sides in border_sets:
        parts = []
        for side in ("left", "right", "top", "bottom"):
            parts.append(f'<{side} style="thin"><color auto="1"/></{side}>' if side in sides else f"<{side}/>")
        borders.append(f"<border>{''.join(parts)}<diagonal/></border>")
    xfs = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
    for index in range(1, len(borders)):
        xfs.append(f'<xf numFmtId="0" fontId="0" fillId="0" borderId="{index}" xfId="0" applyBorder="1"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<styleSheet xmlns="{MAIN}">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        f'<borders count="{len(borders)}">{"".join(borders)}</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _value_xml(sheet: Sheet, name: str, raw: str) -> tuple[str, str]:
    """(the `t` attribute, the inside of the cell) for what a cell holds."""
    value = sheet.value(name)
    if cells.is_formula(raw):
        formula = f"<f>{escape(raw[1:])}</f>"
        if isinstance(value, Error):
            code = value.code if value.code in _EXCEL_ERRORS else "#VALUE!"
            return ' t="e"', f"{formula}<v>{escape(code)}</v>"
        if isinstance(value, bool):
            return ' t="b"', f"{formula}<v>{int(value)}</v>"
        if isinstance(value, float):
            return "", f"{formula}<v>{cells.number_text(value)}</v>"
        if value is None:
            return "", formula
        return ' t="str"', f"{formula}<v>{escape(str(value))}</v>"
    if isinstance(value, bool):
        return ' t="b"', f"<v>{int(value)}</v>"
    if isinstance(value, float):
        return "", f"<v>{cells.number_text(value)}</v>"
    text = raw[1:] if raw.startswith("'") else raw
    return ' t="inlineStr"', f'<is><t xml:space="preserve">{escape(text)}</t></is>'


def write_xlsx(sheet: Sheet) -> bytes:
    """An Excel file's bytes, holding the sheet: its cells on one worksheet,
    formulas with the values they come to, and the borders."""
    border_sets: list[tuple[str, ...]] = []
    style_of: dict[str, int] = {}
    for name in sheet.format:
        sides = tuple(sheet.border(name))
        if not sides:
            continue
        if sides not in border_sets:
            border_sets.append(sides)
        style_of[name] = border_sets.index(sides) + 1
    names = sorted(set(sheet.cells) | set(style_of), key=cells.sort_key)
    rows: dict[int, list[str]] = {}
    for name in names:
        row, _col = cells.parse_ref(name)  # type: ignore[misc]
        style = f' s="{style_of[name]}"' if name in style_of else ""
        raw = sheet.raw(name)
        if raw:
            kind, inside = _value_xml(sheet, name, raw)
            rows.setdefault(row, []).append(f'<c r="{name}"{kind}{style}>{inside}</c>')
        else:
            rows.setdefault(row, []).append(f'<c r="{name}"{style}/>')
    data = "".join(f'<row r="{row + 1}">{"".join(rows[row])}</row>' for row in sorted(rows))
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}"><sheetData>{data}</sheetData></worksheet>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("xl/workbook.xml", _WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        archive.writestr("xl/styles.xml", _styles_xml(border_sets))
    return out.getvalue()


def is_xlsx(data: bytes) -> bool:
    return data[:2] == b"PK" and b"xl/workbook.xml" in data
