"""The kit's `document` in the browser: wired in, generic, and speaking the record API.

The page is driven in a browser, not from here. What a test holds on to is
what goes wrong quietly: the kit not drawing a screen the server installs,
a word from the Docs Quill in what draws every document, a call to an
address the server does not answer, a browser popup. The model is
test_docs.py's. The server's side — a listing of two suffixes, a Word file
read and written as a document's text — is tried against the real thing.
"""

from __future__ import annotations

import re

from cloudmorrow.quill import docs, docx
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import ADMIN, js_code, token_for

DOCS_JS = (WEB / "kit_docs.js").read_text(encoding="utf-8")
RULES_JS = (WEB / "kit_docs_rules.js").read_text(encoding="utf-8")
DOCS_CSS = (WEB / "kit_docs.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
EDITOR_JS = (WEB / "kit_editor.js").read_text(encoding="utf-8")
PICK_JS = (WEB / "filepick.js").read_text(encoding="utf-8")


def test_the_document_is_its_own_file_drawn_from_the_kit(client):
    assert 'import { renderDocs, renderDocsPage } from "./kit_docs.js";' in KIT_JS
    assert 'if (kit === "document") return renderDocs(at, arg);' in KIT_JS
    assert 'if (screen.kit === "document" && modelId === screen.model) return renderDocsPage(at, id, arg);' in KIT_JS
    assert '@import "./kit_docs.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("kit_docs.js", "kit_docs.css", "kit_docs_rules.js"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_nothing_in_the_document_is_named_for_one_quill():
    for source, name in ((DOCS_JS, "kit_docs.js"), (RULES_JS, "rules"), (DOCS_CSS, "css")):
        code = js_code(source)
        for word in ("Welcome", "Documents", "my-files", "Letter"):
            assert word not in code, f"{name} names {word!r}"
        assert not re.search(r"(?<![a-z])Docs(?![a-zA-Z])", code.replace("renderDocs", "").replace("kit_docs", "")), (
            name
        )


def test_it_reads_the_bindings_and_writes_only_where_it_may():
    code = js_code(DOCS_JS)
    for binding in ("screen.title", "screen.body", "screen.path", "screen.where", "suffixesOf(screen)"):
        assert binding in code, binding
    assert "writes: mayWrite(model)" in code
    assert ".access" not in code


def test_the_rules_are_pure():
    code = js_code(RULES_JS)
    for word in ("document", "window", "fetch(", "import "):
        assert word not in code, word


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(DOCS_JS))
    assert 'from "./dialog.js"' in DOCS_JS


def test_the_picker_is_generic_and_asks_in_the_sheet():
    """filepick.js opens a file from anywhere: the shares, then folders, then
    files of the suffixes wanted — in dialog.js's sheet, named for no Quill."""
    code = js_code(PICK_JS)
    assert 'from "./dialog.js"' in PICK_JS and "openSheet(" in code
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", code)
    for word in ("Documents", "Docs", "Cells", "Welcome"):
        assert word not in code, word
    assert 'recordsUrl("share")' in code
    assert 'e.fields.kind === "folder"' in code
    assert '@import "./filepick.css";' in (WEB / "app.css").read_text(encoding="utf-8")


def test_the_calls_it_makes_are_the_record_apis():
    code = js_code(DOCS_JS)
    # A document saves its file's text with the revision it read, and shows theirs on a 409.
    assert "{ fields: { [b.body]: text }, rev: ed.rev }" in code
    assert "err.status === 409 && err.detail && err.detail.current" in code
    assert 'api("POST", recordsUrl(b.model.id), { fields })' in code
    assert 'api("DELETE", recordsUrl(b.model.id, ed.id))' in code
    # Export is the record API's /export, through the editor kit's download; Open is the picker's.
    assert "download(ed.b, ed.id, suffix, ed.stem + suffix)" in code
    assert 'from "./filepick.js"' in code and "pickFile({ suffixes: b.suffixes" in code
    assert '"/export?as=" + encodeURIComponent(suffix' in js_code(EDITOR_JS)
    # The list is the editor's, over these files.
    assert "listView(b, await load(b), key)" in code


def test_side_by_side_is_the_computers_split():
    assert 'from "./kit_editor.js"' in DOCS_JS
    assert '<main class="split">' in DOCS_JS


def test_the_record_calls_it_makes_exist(client):
    """What kit_docs.js asks of the record API, for the Docs screen's bindings:
    a listing of two suffixes, the welcome document, a Word file read and
    written as the same text, a rename."""
    client.app.state.cloudmorrow.quills.install_from_catalog("docs")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    quill = next(q for q in client.get("/api/quills", headers=auth).json() if q["id"] == "docs")
    assert quill["screens"][0] == {
        "id": "docs",
        "kit": "document",
        "label": "Docs",
        "model": "file",
        "where": {"share": "my-files", "within": "Documents"},
        "suffix": [".docs", ".docx"],
        "title": "name",
        "body": "text",
        "path": "path",
    }
    listing = "/api/records/file?share=my-files&within=Documents&suffix=.docs,.docx"
    rows = client.get(listing + "&previews=true", headers=auth).json()
    assert [r["fields"]["path"] for r in rows] == ["Documents/Welcome.docs"]
    assert rows[0]["preview"].startswith("A document is a page of headings"), "the preview is the words, not the JSON"
    welcome = client.get(f"/api/records/file/{rows[0]['id']}", headers=auth).json()
    assert docs.Doc.from_text(welcome["fields"]["text"]).blocks[0]["kind"] == "heading"
    # A Word file put in the folder is listed as a document and read as one.
    letter = docs.Doc(
        [
            {"kind": "heading", "level": 2, "runs": [{"text": "Offer"}]},
            {"kind": "paragraph", "runs": [{"text": "Ten percent off."}]},
        ]
    )
    put = client.post(
        "/api/records/file/upload?share=my-files&folder=Documents&name=Offer.docx",
        headers={**auth, "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        content=docx.write_docx(letter),
    )
    assert put.status_code in (200, 201), put.text
    rows = client.get(listing, headers=auth).json()
    assert sorted(r["fields"]["path"] for r in rows) == ["Documents/Offer.docx", "Documents/Welcome.docs"]
    offer = next(r for r in rows if r["fields"]["path"].endswith(".docx"))
    got = client.get(f"/api/records/file/{offer['id']}", headers=auth).json()
    assert docs.Doc.from_text(got["fields"]["text"]).blocks == letter.blocks
    # Written back as text, it is Word's package again, with the change in it.
    changed = docs.Doc(letter.blocks + [{"kind": "bullet", "runs": [{"text": "until Friday"}]}])
    saved = client.patch(
        f"/api/records/file/{offer['id']}",
        headers=auth,
        json={"fields": {"text": changed.to_text()}, "rev": got["rev"]},
    )
    assert saved.status_code == 200, saved.text
    raw = client.get(f"/api/records/file/{offer['id']}/content", headers=auth)
    assert raw.status_code == 200 and raw.content[:2] == b"PK"
    assert docx.read_docx(raw.content).blocks == changed.blocks
    # A search finds words in a Word file too.
    hits = client.get(listing + "&q=friday", headers=auth).json()
    assert [r["fields"]["path"] for r in hits] == ["Documents/Offer.docx"]
    # Export is a new .docx made from a document's text: Word's package comes out.
    made = client.post(
        "/api/records/file",
        headers=auth,
        json={"fields": {"share": "my-files", "path": "Documents/Welcome.docx", "text": welcome["fields"]["text"]}},
    )
    assert made.status_code == 201, made.text
    exported = client.get(f"/api/records/file/{made.json()['id']}/content", headers=auth).content
    assert docx.read_docx(exported).blocks == docs.Doc.from_text(welcome["fields"]["text"]).blocks
    # Renamed, a Word file stays one, under a new id.
    renamed = client.patch(f"/api/records/file/{offer['id']}", headers=auth, json={"fields": {"name": "Deal.docx"}})
    assert renamed.status_code == 200 and renamed.json()["id"] != offer["id"]
    assert sorted(r["fields"]["path"] for r in client.get(listing, headers=auth).json()) == [
        "Documents/Deal.docx",
        "Documents/Welcome.docs",
        "Documents/Welcome.docx",
    ]


def test_export_hands_a_document_over_in_another_shape(client):
    """/export makes Word, PDF, Markdown or .docs from a document's text — and
    hands a Word file over as itself — with a name to save it by."""
    client.app.state.cloudmorrow.quills.install_from_catalog("docs")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    listing = "/api/records/file?share=my-files&within=Documents&suffix=.docs,.docx"
    welcome = client.get(listing, headers=auth).json()[0]
    text = client.get(f"/api/records/file/{welcome['id']}", headers=auth).json()["fields"]["text"]
    base = f"/api/records/file/{welcome['id']}/export"
    word = client.get(base + "?as=docx", headers=auth)
    assert word.status_code == 200, word.text
    assert word.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="Welcome.docx"' in word.headers["content-disposition"]
    assert docx.read_docx(word.content).blocks == docs.Doc.from_text(text).blocks
    pdf = client.get(base + "?as=.pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-") and 'filename="Welcome.pdf"' in pdf.headers["content-disposition"]
    md = client.get(base + "?as=md", headers=auth)
    assert md.status_code == 200 and md.text.startswith("# Welcome to Docs\n")
    same = client.get(base + "?as=docs", headers=auth)
    assert same.status_code == 200 and same.text == text
    # Not a shape a document takes, or no shape at all: said so.
    assert client.get(base + "?as=xlsx", headers=auth).status_code == 400
    assert "goes out as" in client.get(base, headers=auth).json()["detail"]
    # A Word file asked for as Word is its own bytes, untouched.
    package = docx.write_docx(docs.Doc([{"kind": "paragraph", "runs": [{"text": "Hi"}]}]))
    put = client.post(
        "/api/records/file/upload?share=my-files&folder=Documents&name=Hi.docx",
        headers={**auth, "Content-Type": "application/octet-stream"},
        content=package,
    )
    assert put.status_code in (200, 201), put.text
    again = client.get(f"/api/records/file/{put.json()['id']}/export?as=docx", headers=auth)
    assert again.content == package
    # Opened from anywhere: a document in another folder, or another share, is
    # read and written by its record like one under Documents.
    made = client.post(
        "/api/records/file",
        headers=auth,
        json={"fields": {"share": "my-files", "path": "Plans/Offer.docs", "text": text}},
    )
    assert made.status_code == 201, made.text
    away = client.get(f"/api/records/file/{made.json()['id']}", headers=auth).json()
    assert away["fields"]["path"] == "Plans/Offer.docs" and away["fields"]["text"] == text
    assert client.get(f"/api/records/file/{made.json()['id']}/export?as=pdf", headers=auth).status_code == 200
    assert client.get("/api/records/share", headers=auth).json()[0]["fields"]["label"] == "My Files"
