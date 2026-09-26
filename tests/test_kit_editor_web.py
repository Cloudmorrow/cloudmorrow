"""The kit's `editor` in the browser: wired in, generic, and speaking the record API.

The screens are driven in a browser, not from here (see the screenshots in
the change that made it). What a test holds on to is what goes wrong
quietly: the old notes screen coming back by the side door, a word from
Notes in what draws every editor, a call to an address that is not there.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB, asset_version

EDITOR_JS = (WEB / "kit_editor.js").read_text(encoding="utf-8")
EDITOR_CSS = (WEB / "kit_editor.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
PICTURES_JS = (WEB / "pictures.js").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")


def _code(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def test_the_editor_is_its_own_file_drawn_from_the_kit(client):
    assert 'from "./kit_editor.js"' in KIT_JS
    assert 'if (kit === "editor") return renderEditor(at, arg);' in KIT_JS
    # An editor's record opens on its page, not on the sheet.
    assert "renderEditorPage(at, id, arg)" in KIT_JS
    assert '@import "./kit_editor.css";' in APP_CSS
    version = asset_version()
    for name in ("kit_editor.js", "kit_editor.css", "pictures.js", "pictures.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_the_old_notes_screen_is_gone():
    assert not (WEB / "notes.js").exists()
    assert not (WEB / "notes.css").exists()
    for path in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")):
        text = path.read_text(encoding="utf-8")
        assert "notes.js" not in text and "notes.css" not in text, path.name
        # The editor speaks the record API; /api/notes is for cm note and WebDAV.
        assert "/api/notes" not in text, path.name
    assert 'name: "notes"' not in (WEB / "app.js").read_text() + KIT_JS + EDITOR_JS


def test_nothing_in_the_editor_is_named_for_notes():
    for source, name in ((EDITOR_JS, "kit_editor.js"), (EDITOR_CSS, "kit_editor.css"),
                         (PICTURES_JS, "pictures.js")):
        code = _code(source)
        for word in ("note", "notes"):
            assert not re.search(rf"[\"'.`/]{word}[\"'`\s/]", code), f"{name} names {word!r}"


def test_it_reads_the_bindings_and_what_the_model_can_do():
    for binding in ("screen.title", "screen.body", "screen.path"):
        assert binding in EDITOR_JS, binding
    for capability in ('can.has("folders")', 'can.has("search")', 'can.has("attachments")'):
        assert capability in EDITOR_JS, capability


def test_the_calls_it_makes_are_the_record_apis():
    code = _code(EDITOR_JS)
    assert '"?previews=true"' in code
    assert '"?q=" + encodeURIComponent(query)' in code
    assert '"/_folders"' in code and '"/_attachments"' in code
    # A page saves with the revision it read, and shows theirs on a 409.
    assert "rev: ed.rev }" in code
    assert "err.status === 409 && err.detail && err.detail.current" in code
    # Pictures go where the datamodel keeps them, and nowhere without that.
    assert "uploadImage(ed.attachments, file)" in PICTURES_JS
    assert "if (!ed.attachments) return;" in PICTURES_JS


def test_side_by_side_is_the_computer_only(client):
    assert "min-width: 900px) and (min-height: 600px)" in EDITOR_JS
    assert '<main class="split">' in EDITOR_JS
    media = _code(EDITOR_CSS).split("@media (min-width: 900px) and (min-height: 600px)", 1)
    assert len(media) == 2 and "main.split {" in media[1]
    assert "main.split" not in media[0]


def test_the_record_calls_it_makes_exist(notes_quill, auth):
    client = notes_quill
    rows = client.get("/api/records/note?previews=true", headers=auth).json()
    assert all("preview" in r for r in rows)
    assert client.get("/api/records/note?q=welcome", headers=auth).status_code == 200
    assert client.get("/api/records/note/_folders", headers=auth).status_code == 200
    made = client.post("/api/records/note", headers=auth,
                       json={"fields": {"path": "a/New note", "body": "# New note\n\n"}})
    assert made.status_code == 201
    note = made.json()
    renamed = client.patch(f"/api/records/note/{note['id']}", headers=auth,
                           json={"fields": {"title": "Better"}}).json()
    assert renamed["fields"]["path"] == "a/Better" and renamed["id"] != note["id"]
    saved = client.patch(f"/api/records/note/{renamed['id']}", headers=auth,
                         json={"fields": {"body": "x"}, "rev": renamed["rev"]})
    assert saved.status_code == 200
    stale = client.patch(f"/api/records/note/{renamed['id']}", headers=auth,
                         json={"fields": {"body": "y"}, "rev": renamed["rev"]})
    assert stale.status_code == 409 and stale.json()["detail"]["current"]["fields"]["body"] == "x"
