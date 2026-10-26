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


def test_the_calls_it_makes_are_the_record_apis():
    code = js_code(DOCS_JS)
    # A document saves its file's text with the revision it read, and shows theirs on a 409.
    assert "{ fields: { [b.body]: text }, rev: ed.rev }" in code
    assert "err.status === 409 && err.detail && err.detail.current" in code
    assert 'api("POST", recordsUrl(b.model.id), { fields })' in code
    assert 'api("DELETE", recordsUrl(b.model.id, ed.id))' in code
    # Export fetches the Word file's bytes the way the files grid does.
    assert 'apiRaw("GET", recordsUrl(b.model.id, target.id) + "/content"' in code
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
