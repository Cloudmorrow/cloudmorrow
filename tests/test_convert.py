"""Export: a document as Word, PDF, Markdown or .docs, a sheet as Excel, PDF,
CSV or .cell (quill/convert.py), and the Excel and PDF files made by hand
(quill/xlsx.py, quill/pdf.py)."""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from cloudmorrow.quill import cells, convert, docs, docx, pdf, xlsx

LETTER = docs.Doc(
    [
        {"kind": "heading", "level": 1, "runs": [{"text": "A letter to Ørsted"}]},
        {
            "kind": "paragraph",
            "runs": [
                {"text": "Dear "},
                {"text": "you", "bold": True},
                {"text": ", a line with a "},
                {"text": "link", "link": "https://example.org/x"},
                {"text": " and "},
                {"text": "strike", "strike": True},
                {"text": " and "},
                {"text": "under", "underline": True},
                {"text": "."},
            ],
        },
        {"kind": "bullet", "runs": [{"text": "one"}]},
        {"kind": "bullet", "level": 1, "runs": [{"text": "under it"}]},
        {"kind": "numbered", "runs": [{"text": "first"}]},
        {"kind": "numbered", "runs": [{"text": "second"}]},
        {"kind": "quote", "runs": [{"text": "as they say"}]},
        {"kind": "paragraph", "align": "center", "runs": [{"text": "the end"}]},
        {"kind": "table", "rows": [[{"runs": [{"text": "a"}]}, {"runs": [{"text": "b"}]}]]},
    ]
)


def budget() -> cells.Sheet:
    sheet = cells.Sheet(
        {
            "A1": "Rent",
            "B1": "1200",
            "A2": "Food",
            "B2": "450.5",
            "A3": "Total",
            "B3": "=SUM(B1:B2)",
            "C1": "TRUE",
            "D1": "=1/0",
            "E1": "'007",
            "F1": '="x"&"y"',
            "G1": "10%",
        }
    )
    sheet.set_border("A3", ["top", "bottom"])
    sheet.set_border("B3", ["all"])
    return sheet


# -- Excel ---------------------------------------------------------------------------------
def test_a_sheet_goes_to_excel_and_comes_back_the_same():
    sheet = budget()
    data = xlsx.write_xlsx(sheet)
    assert xlsx.is_xlsx(data) and not docx.is_docx(b"nope")
    back = xlsx.read_xlsx(data)
    # A percentage is the number Excel keeps; everything else is as typed.
    assert back.cells == {**sheet.cells, "G1": "0.1"}
    assert back.format == {"A3": {"border": "top bottom"}, "B3": {"border": "top right bottom left"}}
    assert back.shown("B3") == "1650.5" and back.shown("D1") == "#DIV/0!" and back.shown("E1") == "007"


def test_the_excel_file_is_a_plain_package_with_cached_values():
    archive = zipfile.ZipFile(io.BytesIO(xlsx.write_xlsx(budget())))
    assert sorted(archive.namelist()) == [
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/_rels/workbook.xml.rels",
        "xl/styles.xml",
        "xl/workbook.xml",
        "xl/worksheets/sheet1.xml",
    ]
    sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert '<c r="B3" s="2"><f>SUM(B1:B2)</f><v>1650.5</v></c>' in sheet
    assert '<c r="D1" t="e"><f>1/0</f><v>#DIV/0!</v></c>' in sheet
    assert '<c r="C1" t="b"><v>1</v></c>' in sheet
    assert '<c r="E1" t="inlineStr"><is><t xml:space="preserve">007</t></is></c>' in sheet
    assert '<c r="F1" t="str"><f>"x"&amp;"y"</f><v>xy</v></c>' in sheet
    styles = archive.read("xl/styles.xml").decode()
    assert styles.count("<border>") == 3 and 'applyBorder="1"' in styles


def test_excel_files_from_elsewhere_are_read_through_shared_strings_and_styles():
    """A file as Excel writes it: shared strings, rich text, a style with a border, a date-like number."""
    content_types = xlsx._CONTENT_TYPES.replace(
        "</Types>",
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
    )
    strings = (
        f'<sst xmlns="{xlsx.MAIN}" count="2" uniqueCount="2"><si><t>Hello</t></si>'
        "<si><r><t>Ri</t></r><r><rPr><b/></rPr><t>ch</t></r></si></sst>"
    )
    styles = (
        f'<styleSheet xmlns="{xlsx.MAIN}"><borders count="2"><border/><border><left style="thin"/>'
        '<right/><top/><bottom style="medium"/></border></borders>'
        '<cellXfs count="2"><xf borderId="0"/><xf borderId="1"/></cellXfs></styleSheet>'
    )
    worksheet = (
        f'<worksheet xmlns="{xlsx.MAIN}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
        '<c r="B1" t="s" s="1"><v>1</v></c><c r="C1"><v>12.0</v></c><c r="D1" t="b"><v>0</v></c>'
        '<c r="E1"><f>C1*2</f><v>24</v></c><c r="F1" t="s"><v>99</v></c></row></sheetData></worksheet>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", xlsx._RELS)
        archive.writestr("xl/workbook.xml", xlsx._WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", xlsx._WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        archive.writestr("xl/styles.xml", styles)
        archive.writestr("xl/sharedStrings.xml", strings)
    sheet = xlsx.read_xlsx(out.getvalue())
    assert sheet.cells == {"A1": "Hello", "B1": "Rich", "C1": "12", "D1": "FALSE", "E1": "=C1*2"}
    assert sheet.border("B1") == ["bottom", "left"]
    with pytest.raises(xlsx.XlsxError):
        xlsx.read_xlsx(b"not a zip")
    with pytest.raises(xlsx.XlsxError):
        xlsx.read_xlsx(docx.write_docx(LETTER))


# -- PDF -----------------------------------------------------------------------------------
def _pages(data: bytes) -> int:
    return data.count(b"/Type /Page ")


def test_a_document_is_pages_of_helvetica_with_its_links():
    data = pdf.document_pdf(LETTER, "A letter")
    assert pdf.is_pdf(data) and data.endswith(b"%%EOF\n")
    assert _pages(data) == 1
    assert b"/BaseFont /Helvetica-Bold" in data and b"/Encoding /WinAnsiEncoding" in data
    # The words are there, WinAnsi-encoded: Ø is one byte, in octal.
    assert b"(\\330rsted)" in data and b"(letter)" in data
    assert b"(you)" in data and b"(1.)" in data and b"(\\225)" in data  # the bullet
    assert b"/Subtype /Link" in data and b"/URI (https://example.org/x)" in data
    assert b"/Title <FEFF004100200" in data
    # Long documents go on to more pages.
    long = docs.Doc([{"kind": "paragraph", "runs": [{"text": f"Paragraph {i} " * 12}]} for i in range(60)])
    assert _pages(pdf.document_pdf(long)) >= 3


def test_words_flow_within_the_width_and_break_on_newlines():
    lines = pdf.flow([{"text": "one two three four five six seven"}], 60, 11)
    assert all(sum(p["width"] for p in line) <= 60 for line in lines)
    assert [[p["text"] for p in line if "text" in p] for line in lines][0] == ["one", "two"]
    broken = pdf.flow([{"text": "a\nb"}], 500, 11)
    assert len(broken) == 2
    assert pdf.width_of("iii", "F1", 10) < pdf.width_of("WWW", "F1", 10)
    assert pdf.width_of("a", "F2", 10) == pdf.width_of("a", "F1", 10)
    assert pdf.encode("Ørsted – ‘quoted’ 😀") == "Ørsted – ‘quoted’ ?".encode("cp1252")


def test_a_sheet_is_a_ruled_grid_landscape_when_wide_and_more_pages_when_wider():
    data = pdf.sheet_pdf(budget(), "Budget")
    assert pdf.is_pdf(data) and _pages(data) == 1
    assert b"/MediaBox [0 0 595 842]" in data
    assert b"(Budget)" in data and b"(1650.5)" in data and b"(#DIV/0!)" in data and b"(007)" in data
    # Column headings and row numbers in grey; borders drawn in black over the grey grid.
    assert b"0.45 g /F1 9 Tf" in data and b"0.75 G 0.3 w" in data and b"0 G 0.9 w" in data
    wide = cells.Sheet({cells.ref_name(r, c): f"{r}-{c}" for r in range(70) for c in range(30)})
    data = pdf.sheet_pdf(wide)
    assert b"/MediaBox [0 0 842 595]" in data
    assert _pages(data) == 3 * 2
    assert _pages(pdf.sheet_pdf(cells.Sheet())) == 1


# -- the shapes -----------------------------------------------------------------------------
def test_a_document_goes_out_in_four_shapes():
    assert docx.read_docx(convert.document_bytes(LETTER, "docx")).blocks == LETTER.blocks
    assert convert.document_bytes(LETTER, ".PDF", "x").startswith(b"%PDF-")
    assert convert.document_bytes(LETTER, "md").decode().startswith("# A letter to Ørsted\n")
    assert convert.document_bytes(LETTER, ".docs").decode() == LETTER.to_text()
    with pytest.raises(convert.ConvertError, match="not xlsx"):
        convert.document_bytes(LETTER, "xlsx")
    assert list(convert.DOCUMENT_FORMATS) == [".docx", ".pdf", ".md", ".docs"]


def test_a_sheet_goes_out_in_four_shapes():
    sheet = budget()
    assert xlsx.read_xlsx(convert.sheet_bytes(sheet, "xlsx")).raw("B3") == "=SUM(B1:B2)"
    assert convert.sheet_bytes(sheet, "pdf").startswith(b"%PDF-")
    assert convert.sheet_bytes(sheet, ".csv").decode() == (
        "Rent,1200,TRUE,#DIV/0!,007,xy,0.1\nFood,450.5,,,,,\nTotal,1650.5,,,,,\n"
    )
    assert convert.sheet_bytes(sheet, "cell").decode() == sheet.to_text()
    with pytest.raises(convert.ConvertError, match="not docx"):
        convert.sheet_bytes(sheet, "docx")
    assert list(convert.SHEET_FORMATS) == [".xlsx", ".pdf", ".csv", ".cell"]
    assert re.match(r"^\.[a-z]+$", convert.suffix_of(" PDF "))
