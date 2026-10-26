"""A document as a Word file: reading a .docx into blocks, and writing one back.

A .docx is a zip of XML; what the document kit keeps (quill/docs.py) is read
out of `word/document.xml` — paragraphs with their style (Heading 1 to 3,
Quote, a list's numbering), runs with bold, italic, underline and strike,
hyperlinks, tables — and everything else is passed over: pictures,
headers and footers, fonts, sizes, colours, comments. Writing makes a
small, plain package Word opens as it is: the same blocks, with styles for
the headings and the quote, numbering for the lists, a grid for a table.

Nothing here is Word's own library: the standard library's zipfile and
ElementTree are enough for the shape a document keeps.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from cloudmorrow.quill.docs import Doc, block, run

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R}


class DocxError(ValueError):
    """Not a Word file the kit can read."""


# -- reading ------------------------------------------------------------------------------
def _tag(name: str) -> str:
    return f"{{{W}}}{name}"


def _rels(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
    try:
        root = ET.fromstring(archive.read(name))
    except KeyError:
        return {}
    except ET.ParseError:
        return {}
    return {rel.get("Id", ""): rel.get("Target", "") for rel in root.iter(f"{{{PKG}}}Relationship")}


def _numbering(archive: zipfile.ZipFile) -> dict[str, dict[int, str]]:
    """numId -> {level: numFmt}: which lists are bullets and which are numbered."""
    try:
        root = ET.fromstring(archive.read("word/numbering.xml"))
    except (KeyError, ET.ParseError):
        return {}
    abstracts: dict[str, dict[int, str]] = {}
    for abstract in root.findall("w:abstractNum", NS):
        levels: dict[int, str] = {}
        for lvl in abstract.findall("w:lvl", NS):
            fmt = lvl.find("w:numFmt", NS)
            try:
                levels[int(lvl.get(_tag("ilvl"), "0"))] = (
                    fmt.get(_tag("val"), "bullet") if fmt is not None else "bullet"
                )
            except ValueError:
                continue
        abstracts[abstract.get(_tag("abstractNumId"), "")] = levels
    nums: dict[str, dict[int, str]] = {}
    for num in root.findall("w:num", NS):
        ref = num.find("w:abstractNumId", NS)
        if ref is not None:
            nums[num.get(_tag("numId"), "")] = abstracts.get(ref.get(_tag("val"), ""), {})
    return nums


def _on(rpr: ET.Element | None, name: str) -> bool:
    if rpr is None:
        return False
    el = rpr.find(f"w:{name}", NS)
    if el is None:
        return False
    val = el.get(_tag("val"))
    return val not in ("0", "false", "none", "off")


def _runs_of(parent: ET.Element, rels: dict[str, str], link: str = "") -> list[dict]:
    """The runs under a paragraph (or a hyperlink, an insertion): text and what is true of it."""
    runs: list[dict] = []
    for child in parent:
        if child.tag == _tag("r"):
            rpr = child.find("w:rPr", NS)
            style = {
                "bold": _on(rpr, "b"),
                "italic": _on(rpr, "i"),
                "underline": _on(rpr, "u"),
                "strike": _on(rpr, "strike") or _on(rpr, "dstrike"),
                "link": link,
            }
            text = []
            for part in child:
                if part.tag == _tag("t"):
                    text.append(part.text or "")
                elif part.tag == _tag("br"):
                    text.append("\n")
                elif part.tag == _tag("tab"):
                    text.append("\t")
                elif part.tag in (_tag("sym"), _tag("noBreakHyphen")):
                    text.append("-" if part.tag == _tag("noBreakHyphen") else "")
            if text:
                runs.append(run("".join(text), **style))
        elif child.tag == _tag("hyperlink"):
            target = rels.get(child.get(f"{{{R}}}id", ""), "")
            anchor = child.get(_tag("anchor"))
            runs.extend(_runs_of(child, rels, target or (f"#{anchor}" if anchor else "")))
        elif child.tag in (_tag("ins"), _tag("smartTag"), _tag("sdt"), _tag("sdtContent"), _tag("fldSimple")):
            runs.extend(_runs_of(child, rels, link))
    return runs


def _paragraph(p: ET.Element, rels: dict[str, str], numbering: dict[str, dict[int, str]]) -> dict | None:
    ppr = p.find("w:pPr", NS)
    runs = _runs_of(p, rels)
    kind, level, align = "paragraph", 0, ""
    if ppr is not None:
        style = ppr.find("w:pStyle", NS)
        name = (style.get(_tag("val"), "") if style is not None else "").lower().replace(" ", "")
        if m := re.match(r"^heading(\d)$", name):
            kind, level = "heading", min(3, int(m.group(1)))
        elif name == "title":
            kind, level = "heading", 1
        elif name == "subtitle":
            kind, level = "heading", 2
        elif name in ("quote", "intensequote", "blockquote"):
            kind = "quote"
        numpr = ppr.find("w:numPr", NS)
        if numpr is not None and kind == "paragraph":
            ilvl = numpr.find("w:ilvl", NS)
            numid = numpr.find("w:numId", NS)
            try:
                level = int(ilvl.get(_tag("val"), "0")) if ilvl is not None else 0
            except ValueError:
                level = 0
            fmt = numbering.get(numid.get(_tag("val"), "") if numid is not None else "", {}).get(level, "bullet")
            kind = "bullet" if fmt == "bullet" else "numbered"
        jc = ppr.find("w:jc", NS)
        if jc is not None:
            align = {
                "center": "center",
                "right": "right",
                "end": "right",
                "both": "justify",
                "distribute": "justify",
            }.get(jc.get(_tag("val"), ""), "")
    if not runs and kind == "paragraph":
        return None
    return block(kind, runs, level=level, align=align)


def _table(tbl: ET.Element, rels: dict[str, str], numbering: dict) -> dict | None:
    rows = []
    for tr in tbl.findall("w:tr", NS):
        cells = []
        for tc in tr.findall("w:tc", NS):
            runs: list[dict] = []
            for p in tc.findall("w:p", NS):
                if runs:
                    runs.append(run("\n"))
                runs.extend(_runs_of(p, rels))
            cells.append({"runs": runs})
        if cells:
            rows.append(cells)
    return block("table", rows=rows) if rows else None


def read_docx(data: bytes) -> Doc:
    """The document in a Word file's bytes."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        root = ET.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise DocxError("not a Word file") from exc
    body = root.find("w:body", NS)
    if body is None:
        raise DocxError("not a Word file")
    rels = _rels(archive, "word/_rels/document.xml.rels")
    numbering = _numbering(archive)
    blocks = []
    for child in body:
        if child.tag == _tag("p"):
            one = _paragraph(child, rels, numbering)
        elif child.tag == _tag("tbl"):
            one = _table(child, rels, numbering)
        elif child.tag in (_tag("sdt"), _tag("sdtContent")):
            inner = child.find("w:sdtContent", NS) if child.tag == _tag("sdt") else child
            for p in inner if inner is not None else []:
                if p.tag == _tag("p") and (b := _paragraph(p, rels, numbering)):
                    blocks.append(b)
            continue
        else:
            continue
        if one is not None:
            blocks.append(one)
    return Doc(blocks)


# -- writing ------------------------------------------------------------------------------
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml"
 ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_BORDER = '<w:{side} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults>
<w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/>
<w:lang w:val="en-US"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/>
<w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/>
<w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/>
<w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/>
<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:ind w:left="720" w:right="720"/></w:pPr>
<w:rPr><w:i/><w:color w:val="404040"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
<w:qFormat/><w:pPr><w:ind w:left="720"/><w:contextualSpacing/></w:pPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>
<w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
{"".join(_BORDER.format(side=side) for side in ("top", "left", "bottom", "right", "insideH", "insideV"))}
</w:tblBorders><w:tblCellMar><w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar>
</w:tblPr></w:style>
</w:styles>"""

_BULLETS = ("\u2022", "\u25e6", "\u25aa")


def _numbering_xml(numbered_lists: int) -> str:
    """Two kinds of list: bullets (num 1), and a numbered list that starts
    over for every run of numbered items (num 2 onwards)."""

    def levels(fmt: str) -> str:
        out = []
        for lvl in range(3):
            text = _BULLETS[lvl] if fmt == "bullet" else f"%{lvl + 1}."
            font = '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/></w:rPr>' if fmt == "bullet" else ""
            out.append(
                f'<w:lvl w:ilvl="{lvl}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{720 * (lvl + 1)}" w:hanging="360"/></w:pPr>'
                f"{font}</w:lvl>"
            )
        return "".join(out)

    nums = ['<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>']
    for n in range(numbered_lists):
        nums.append(
            f'<w:num w:numId="{n + 2}"><w:abstractNumId w:val="1"/>'
            '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
        )
    kind = '<w:multiLevelType w:val="hybridMultilevel"/>'
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering xmlns:w="{W}">'
        f'<w:abstractNum w:abstractNumId="0">{kind}{levels("bullet")}</w:abstractNum>'
        f'<w:abstractNum w:abstractNumId="1">{kind}{levels("decimal")}</w:abstractNum>'
        + "".join(nums)
        + "</w:numbering>"
    )


def _run_xml(r: dict, links: dict[str, str]) -> str:
    props = []
    if r.get("bold"):
        props.append("<w:b/>")
    if r.get("italic"):
        props.append("<w:i/>")
    if r.get("underline"):
        props.append('<w:u w:val="single"/>')
    if r.get("strike"):
        props.append("<w:strike/>")
    if r.get("link"):
        props.insert(0, '<w:rStyle w:val="Hyperlink"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    parts = []
    for piece in re.split(r"(\n|\t)", r["text"]):
        if piece == "\n":
            parts.append("<w:br/>")
        elif piece == "\t":
            parts.append("<w:tab/>")
        elif piece:
            parts.append(f'<w:t xml:space="preserve">{escape(piece)}</w:t>')
    xml = f"<w:r>{rpr}{''.join(parts)}</w:r>"
    if r.get("link"):
        rid = links.setdefault(r["link"], f"rId{100 + len(links)}")
        return f'<w:hyperlink r:id="{rid}">{xml}</w:hyperlink>'
    return xml


_JC = {"center": "center", "right": "right", "justify": "both"}


def _paragraph_xml(b: dict, links: dict[str, str], num_id: int = 0) -> str:
    props = []
    kind = b["kind"]
    if kind == "heading":
        props.append(f'<w:pStyle w:val="Heading{b["level"]}"/>')
    elif kind == "quote":
        props.append('<w:pStyle w:val="Quote"/>')
    elif kind in ("bullet", "numbered"):
        level = min(2, b.get("level", 0))
        number = 1 if kind == "bullet" else num_id
        props.append('<w:pStyle w:val="ListParagraph"/>')
        props.append(f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{number}"/></w:numPr>')
    if b.get("align"):
        props.append(f'<w:jc w:val="{_JC[b["align"]]}"/>')
    ppr = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    return f"<w:p>{ppr}{''.join(_run_xml(r, links) for r in b['runs'])}</w:p>"


def _table_xml(b: dict, links: dict[str, str]) -> str:
    width = max(len(row) for row in b["rows"])
    col = 9000 // max(1, width)
    grid = "".join(f'<w:gridCol w:w="{col}"/>' for _ in range(width))
    rows = []
    for row in b["rows"]:
        cells = []
        for cell in row:
            paragraphs = []
            current: list[dict] = []
            for r in [*cell["runs"], None]:
                if r is None or r["text"] == "\n":
                    paragraphs.append(f"<w:p>{''.join(_run_xml(x, links) for x in current)}</w:p>")
                    current = []
                else:
                    current.append(r)
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{col}" w:type="dxa"/></w:tcPr>{"".join(paragraphs)}</w:tc>')
        rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(rows)}</w:tbl>"
    )


_SECTION = (
    '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
    'w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
)


def write_docx(doc: Doc) -> bytes:
    """A Word file's bytes, holding the document."""
    links: dict[str, str] = {}
    body = []
    numbered_lists = 0
    previous = ""
    for b in doc.blocks:
        if b["kind"] == "table":
            body.append(_table_xml(b, links))
        elif b["kind"] == "numbered":
            if previous != "numbered":
                numbered_lists += 1
            body.append(_paragraph_xml(b, links, num_id=numbered_lists + 1))
        else:
            body.append(_paragraph_xml(b, links))
        previous = b["kind"]
    if not body:
        body.append("<w:p/>")
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
        + "".join(body)
        + _SECTION
        + "</w:body></w:document>"
    )
    rels = [
        f'<Relationship Id="rId1" Type="{_REL}/styles" Target="styles.xml"/>',
        f'<Relationship Id="rId2" Type="{_REL}/numbering" Target="numbering.xml"/>',
    ]
    for target, rid in links.items():
        rels.append(
            f'<Relationship Id="{rid}" Type="{_REL}/hyperlink" Target={quoteattr(target)} TargetMode="External"/>'
        )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", _STYLES)
        archive.writestr("word/numbering.xml", _numbering_xml(numbered_lists))
        archive.writestr("word/_rels/document.xml.rels", document_rels)
    return out.getvalue()


def is_docx(data: bytes) -> bool:
    return data[:2] == b"PK"
