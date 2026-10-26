"""The document kit's model: one set of cases through the Python and the JavaScript.

quill/docs.py keeps a document for the terminal and the command line (and
reads and writes it as Markdown); kit_docs_rules.js does for the browser.
Both must write the same `.docs` file for the same blocks, and say the same
words for it (docs/DOCS.md). A Word file goes through quill/docx.py and
comes back the same.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

import pytest

from cloudmorrow.quill import docs, docx
from cloudmorrow.server.routes.web import WEB

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# One document, as blocks: everything the kit keeps.
BLOCKS = [
    {"kind": "heading", "level": 1, "runs": [{"text": "A letter"}]},
    {
        "kind": "paragraph",
        "runs": [
            {"text": "Dear "},
            {"text": "you", "bold": True},
            {"text": ", this is "},
            {"text": "italic", "italic": True},
            {"text": " and "},
            {"text": "under", "underline": True},
            {"text": " and "},
            {"text": "gone", "strike": True},
            {"text": " and a "},
            {"text": "link", "link": "https://example.com/a?b=1&c=2"},
            {"text": ".\nA second line."},
        ],
    },
    {"kind": "paragraph", "align": "center", "runs": [{"text": "In the middle"}]},
    {"kind": "bullet", "runs": [{"text": "one"}]},
    {"kind": "bullet", "runs": [{"text": "two"}]},
    {"kind": "bullet", "level": 1, "runs": [{"text": "two and a half"}]},
    {"kind": "numbered", "runs": [{"text": "first"}]},
    {"kind": "numbered", "runs": [{"text": "second ", "bold": True, "italic": True}, {"text": "half"}]},
    {"kind": "quote", "runs": [{"text": "said\ntwice"}]},
    {"kind": "heading", "level": 2, "runs": [{"text": 'Wïde & <odd> "names"'}]},
    {
        "kind": "table",
        "rows": [
            [{"runs": [{"text": "a"}]}, {"runs": [{"text": "b"}]}],
            [{"runs": [{"text": "c", "bold": True}]}, {"runs": [{"text": "d | e"}]}],
        ],
    },
]

WORDS = (
    "A letter\nDear you, this is italic and under and gone and a link.\nA second line.\nIn the middle\n"
    'one\ntwo\ntwo and a half\nfirst\nsecond half\nsaid\ntwice\nWïde & <odd> "names"\na\tb\nc\td | e'
)

MARKDOWN = """# A letter

Dear **you**, this is *italic* and __under__ and ~~gone~~ and a [link](https://example.com/a?b=1&c=2).
A second line.

In the middle

- one
- two
  - two and a half

1. first
2. ***second ***half

> said
> twice

## Wïde & <odd> "names"

| a | b |
| --- | --- |
| **c** | d \\| e |
"""


# -- the file ----------------------------------------------------------------------------
def test_the_file_is_the_blocks_cleaned_and_in_a_fixed_order():
    doc = docs.Doc(BLOCKS)
    assert doc.blocks == BLOCKS, "what is true is kept as it is"
    assert json.loads(doc.to_text()) == {"blocks": BLOCKS}
    assert docs.Doc.from_text(doc.to_text()).blocks == BLOCKS
    assert doc.text == WORDS
    assert doc.words == len(WORDS.split())
    # Neighbouring runs alike are one run; empty runs, unknown kinds and
    # blocks without a kind are left out; flags that are false are not written.
    odd = docs.Doc(
        [
            {
                "kind": "paragraph",
                "runs": [{"text": "a", "bold": True}, {"text": "b", "bold": True, "italic": False}, ""],
            },
            {"kind": "song", "runs": [{"text": "x"}]},
            {"runs": [{"text": "x"}]},
            {"kind": "heading", "level": 9, "runs": "nope"},
            {"kind": "table", "rows": [[{"runs": [{"text": "a"}]}], [{"runs": []}, {"runs": [{"text": "b"}]}]]},
        ]
    )
    assert odd.blocks == [
        {"kind": "paragraph", "runs": [{"text": "ab", "bold": True}]},
        {"kind": "heading", "level": 3, "runs": []},
        {
            "kind": "table",
            "rows": [[{"runs": [{"text": "a"}]}, {"runs": []}], [{"runs": []}, {"runs": [{"text": "b"}]}]],
        },
    ]
    for nothing in ("", "not json", "[1]", None, 3, '{"blocks": 1}'):
        assert docs.Doc.from_text(nothing).blocks == []
    assert docs.Doc.from_text('[{"kind": "paragraph", "runs": [{"text": "bare"}]}]').text == "bare"
    assert docs.file_text([]) == '{\n  "blocks": []\n}\n'


def test_the_preview_is_the_first_words_after_the_title():
    assert docs.preview(docs.Doc(BLOCKS)).startswith("Dear you, this is italic")
    assert docs.preview(docs.Doc(BLOCKS[:1])) == "A letter"
    assert docs.preview(docs.Doc()) == ""
    assert docs.preview(docs.Doc(BLOCKS), chars=12) == "Dear you, t…"


# -- Markdown ------------------------------------------------------------------------------
def test_markdown_says_the_document_and_reads_it_back():
    doc = docs.Doc(BLOCKS)
    assert docs.to_markdown(doc) == MARKDOWN
    back = docs.from_markdown(MARKDOWN)
    # Alignment has no Markdown; everything else comes back as it was.
    expected = [dict(b) for b in BLOCKS]
    expected[2] = {"kind": "paragraph", "runs": [{"text": "In the middle"}]}
    assert back.blocks == expected
    assert docs.to_markdown(docs.Doc()) == ""
    assert docs.from_markdown("").blocks == []


def test_markdown_marks_are_escaped_and_odd_lines_are_paragraphs():
    doc = docs.Doc([{"kind": "paragraph", "runs": [{"text": "2 * 3 = 6, see [1] and a_b"}]}])
    md = docs.to_markdown(doc)
    assert md == "2 \\* 3 = 6, see \\[1\\] and a\\_b\n"
    assert docs.from_markdown(md).blocks == doc.blocks
    loose = docs.from_markdown("just words\nmore words\n\n#not a heading\n* star bullet\n3) third\n")
    assert [b["kind"] for b in loose.blocks] == ["paragraph", "paragraph", "bullet", "numbered"]
    assert loose.blocks[0]["runs"] == [{"text": "just words\nmore words"}]
    assert loose.blocks[1]["runs"] == [{"text": "#not a heading"}]
    assert docs.parse_runs("**bold *and italic* still**") == [
        {"text": "bold ", "bold": True},
        {"text": "and italic", "bold": True, "italic": True},
        {"text": " still", "bold": True},
    ]
    assert docs.parse_runs("[**b**](http://x)") == [{"text": "b", "bold": True, "link": "http://x"}]


# -- Word --------------------------------------------------------------------------------
def _parts(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def test_a_word_file_holds_the_document_and_gives_it_back():
    doc = docs.Doc(BLOCKS)
    data = docx.write_docx(doc)
    parts = _parts(data)
    assert set(parts) == {
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/_rels/document.xml.rels",
    }
    for xml in parts.values():
        ET.fromstring(xml)  # every part is well-formed
    assert 'w:val="Heading1"' in parts["word/document.xml"] and "<w:hyperlink" in parts["word/document.xml"]
    assert "TargetMode=&quot;External&quot;" not in parts["word/_rels/document.xml.rels"]
    assert 'Target="https://example.com/a?b=1&amp;c=2"' in parts["word/_rels/document.xml.rels"]
    assert docx.read_docx(data).blocks == BLOCKS
    assert docx.is_docx(data) and not docx.is_docx(b"hello")


def test_a_second_numbered_list_starts_over():
    doc = docs.Doc(
        [
            {"kind": "numbered", "runs": [{"text": "a"}]},
            {"kind": "paragraph", "runs": [{"text": "between"}]},
            {"kind": "numbered", "runs": [{"text": "b"}]},
        ]
    )
    parts = _parts(docx.write_docx(doc))
    assert parts["word/document.xml"].count("<w:numId") == 2
    assert '<w:numId w:val="2"/>' in parts["word/document.xml"] and '<w:numId w:val="3"/>' in parts["word/document.xml"]
    assert parts["word/numbering.xml"].count("<w:num ") == 3
    assert docx.read_docx(docx.write_docx(doc)).blocks == doc.blocks


def test_a_word_file_from_elsewhere_is_read_for_what_the_kit_keeps():
    """Word's own shapes: Title and Subtitle styles, a list by numbering,
    a run style for bold, text in an insertion, a picture passed over."""
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{docx.W}" xmlns:r="{docx.R}"><w:body>
<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>The Title</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="Subtitle"/><w:jc w:val="center"/></w:pPr><w:r><w:t>Under it</w:t></w:r></w:p>
<w:p><w:pPr><w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="5"/></w:numPr></w:pPr>
<w:r><w:t>numbered</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="6"/></w:numPr></w:pPr><w:r><w:t>bulleted, in</w:t></w:r></w:p>
<w:p><w:r><w:rPr><w:b w:val="true"/><w:u w:val="none"/></w:rPr><w:t xml:space="preserve">bold </w:t></w:r>
<w:ins><w:r><w:t>added</w:t></w:r></w:ins><w:del><w:r><w:delText>gone</w:delText></w:r></w:del>
<w:r><w:drawing/></w:r></w:p>
<w:p><w:hyperlink w:anchor="top"><w:r><w:t>up</w:t></w:r></w:hyperlink></w:p>
<w:p/>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>one</w:t></w:r></w:p><w:p><w:r><w:t>two</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
    numbering = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:numbering xmlns:w="{docx.W}">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>
<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>
<w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>
<w:num w:numId="5"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="6"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/numbering.xml", numbering)
    doc = docx.read_docx(out.getvalue())
    assert doc.blocks == [
        {"kind": "heading", "level": 1, "runs": [{"text": "The Title"}]},
        {"kind": "heading", "level": 2, "align": "center", "runs": [{"text": "Under it"}]},
        {"kind": "numbered", "runs": [{"text": "numbered"}]},
        {"kind": "bullet", "level": 1, "runs": [{"text": "bulleted, in"}]},
        {"kind": "paragraph", "runs": [{"text": "bold ", "bold": True}, {"text": "added"}]},
        {"kind": "paragraph", "runs": [{"text": "up", "link": "#top"}]},
        {"kind": "table", "rows": [[{"runs": [{"text": "one\ntwo"}]}]]},
    ]
    with pytest.raises(docx.DocxError):
        docx.read_docx(b"not a zip")
    with pytest.raises(docx.DocxError):
        empty = BytesIO()
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("hello.txt", "x")
        docx.read_docx(empty.getvalue())


# -- the browser's rules agree ---------------------------------------------------------------
RUNNER = """
import {{ Doc, preview }} from "{rules}";
import {{ readFileSync }} from "node:fs";
const doc = Doc.fromText(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({{ text: doc.toText(), words: doc.text, preview: preview(doc), n: doc.words }}));
"""


@node
def test_javascript_writes_the_same_file_and_says_the_same_words(tmp_path):
    script = tmp_path / "docs.mjs"
    script.write_text(RUNNER.format(rules=(WEB / "kit_docs_rules.js").as_uri()), encoding="utf-8")
    doc = docs.Doc(BLOCKS)
    for typed in (doc.to_text(), json.dumps(BLOCKS), ""):
        done = subprocess.run(["node", str(script)], input=typed, capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stderr
        got = json.loads(done.stdout)
        want = docs.Doc.from_text(typed)
        assert got["text"] == want.to_text(), "byte for byte"
        assert got["words"] == want.text and got["n"] == want.words
        assert got["preview"] == docs.preview(want)
    # The same odd input is cleaned the same way.
    odd = json.dumps(
        [
            {
                "kind": "paragraph",
                "runs": [{"text": "a", "bold": True}, {"text": "b", "bold": True, "italic": False}, ""],
            },
            {"kind": "song", "runs": [{"text": "x"}]},
            {"kind": "heading", "level": 9, "runs": "nope"},
            {"kind": "table", "rows": [[{"runs": [{"text": "a"}]}], [{"runs": []}, {"runs": [{"text": "b"}]}]]},
        ]
    )
    done = subprocess.run(["node", str(script)], input=odd, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["text"] == docs.Doc.from_text(odd).to_text()
