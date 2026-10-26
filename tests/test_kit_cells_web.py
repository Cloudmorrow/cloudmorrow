"""The kit's `sheet` in the browser: wired in, generic, and speaking the record API.

The grid is driven in a browser, not from here. What a test holds on to is
what goes wrong quietly: the kit not drawing a screen the server installs,
a word from the Cells Quill in what draws every sheet, a call to an address
the server does not answer, a browser popup. The arithmetic is
test_cells.py's.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import ADMIN, js_code, token_for

CELLS_JS = (WEB / "kit_cells.js").read_text(encoding="utf-8")
RULES_JS = (WEB / "kit_cells_rules.js").read_text(encoding="utf-8")
CELLS_CSS = (WEB / "kit_cells.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")


def test_the_sheet_is_its_own_file_drawn_from_the_kit(client):
    assert 'import { renderCells, renderCellsPage } from "./kit_cells.js";' in KIT_JS
    assert 'if (kit === "sheet") return renderCells(at, arg);' in KIT_JS
    # A sheet's record opens on its grid, not on the record sheet.
    assert 'if (screen.kit === "sheet" && modelId === screen.model) return renderCellsPage(at, id, arg);' in KIT_JS
    assert '@import "./kit_cells.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("kit_cells.js", "kit_cells.css", "kit_cells_rules.js"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_nothing_in_the_sheet_is_named_for_one_quill():
    for source, name in ((CELLS_JS, "kit_cells.js"), (RULES_JS, "rules"), (CELLS_CSS, "css")):
        code = js_code(source)
        for word in ("budget", "Budget", "Documents", "my-files"):
            assert word not in code, f"{name} names {word!r}"
        # The Quill is Cells; the kit's own names (parseCells, renderCells) are about cells.
        assert not re.search(r"(?<![a-z])Cells", code), f"{name} names the Cells Quill"


def test_it_reads_the_bindings_and_writes_only_where_it_may():
    code = js_code(CELLS_JS)
    for binding in ("screen.title", "screen.cells", "screen.path", "screen.where", "screen.suffix"):
        assert binding in code, binding
    assert "writes: mayWrite(model)" in code
    assert ".access" not in code


def test_the_rules_are_pure():
    code = js_code(RULES_JS)
    for word in ("document", "window", "fetch(", "import "):
        assert word not in code, word


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(CELLS_JS))
    assert 'from "./dialog.js"' in CELLS_JS


def test_the_calls_it_makes_are_the_record_apis():
    code = js_code(CELLS_JS)
    # A sheet saves its file's text with the revision it read, and shows theirs on a 409.
    assert "{ fields: { [b.cells]: text }, rev: ed.rev }" in code
    assert "err.status === 409 && err.detail && err.detail.current" in code
    assert 'api("POST", recordsUrl(b.model.id), { fields })' in code
    assert 'api("DELETE", recordsUrl(b.model.id, ed.id))' in code
    # Every listing is made within the folder, of the suffix: the editor's query.
    assert 'recordsUrl(b.model.id, "", withQuery(b, ""))' in code
    assert "recordsUrl(b.model.id))" not in code


def test_side_by_side_is_the_computers_split():
    assert 'from "./kit_editor.js"' in CELLS_JS
    assert '<main class="split">' in CELLS_JS


def test_the_record_calls_it_makes_exist(client):
    """What kit_cells.js asks of the record API, for the Cells screen's bindings."""
    client.app.state.cloudmorrow.quills.install_from_catalog("cells")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    quill = next(q for q in client.get("/api/quills", headers=auth).json() if q["id"] == "cells")
    assert quill["screens"][0] == {
        "id": "sheets",
        "kit": "sheet",
        "label": "Cells",
        "model": "file",
        "where": {"share": "my-files", "within": "Documents"},
        "suffix": ".cell",
        "title": "name",
        "cells": "text",
        "path": "path",
    }
    assert next(f for f in quill["models"]["file"]["fields"] if f["name"] == "text")["kind"] == "text"
    # The welcome sheet is seeded the first time the folder is listed; a
    # listing leaves the text out, and reading one file gives it.
    listing = "/api/records/file?share=my-files&within=Documents&suffix=.cell"
    rows = client.get(listing, headers=auth).json()
    assert [r["fields"]["path"] for r in rows] == ["Documents/Budget.cell"]
    assert rows[0]["fields"]["text"] is None
    budget = client.get(f"/api/records/file/{rows[0]['id']}", headers=auth).json()
    assert '"B5": "=SUM(B1:B3)"' in budget["fields"]["text"]
    # A new sheet is a .cell file under the folder; its text is written back with its rev.
    made = client.post(
        "/api/records/file",
        headers=auth,
        json={"fields": {"share": "my-files", "path": "Documents/New sheet.cell", "text": '{\n  "cells": {}\n}\n'}},
    )
    assert made.status_code == 201, made.text
    saved = client.patch(
        f"/api/records/file/{made.json()['id']}",
        headers=auth,
        json={"fields": {"text": '{\n  "cells": {\n    "A1": "1"\n  }\n}\n'}, "rev": made.json()["rev"]},
    )
    assert saved.status_code == 200, saved.text
    # Renamed, it is a new id: the sheet's address moves with it.
    renamed = client.patch(
        f"/api/records/file/{made.json()['id']}", headers=auth, json={"fields": {"name": "Costs.cell"}}
    )
    assert renamed.status_code == 200 and renamed.json()["id"] != made.json()["id"]
    assert sorted(r["fields"]["path"] for r in client.get(listing, headers=auth).json()) == [
        "Documents/Budget.cell",
        "Documents/Costs.cell",
    ]
