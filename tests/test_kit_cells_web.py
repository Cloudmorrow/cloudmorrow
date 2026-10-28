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
    for binding in ("screen.title", "screen.cells", "screen.path", "screen.where", "suffixesOf(screen)"):
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
    # Every listing is the editor's: within the folder, of the suffix, folders and all.
    assert "listView(b, await load(b), key)" in code and "listView(b, await load(b), listKey, ed.id)" in code
    assert "recordsUrl(b.model.id))" not in code


def test_the_list_is_the_editors_folders_and_all():
    """The sheets are listed as notes and documents are: the folders, every
    sheet, or one folder's; a new sheet lands in the folder it was started
    in; the way back from a sheet is the list it came from."""
    code = js_code(CELLS_JS)
    assert 'keepsFolders: !!screen.path && can.has("folders")' in code
    assert "renderSheet(b, { isNew: true, folder: arg.slice(NEW.length + 1)" in code
    assert "fields[b.path] = wholePath(b, joinPath(ed.folder, name))" in code
    assert "listHash(b, ed.folder || (previousHash() === listHash(b, TOP) ? TOP : listKey))" in code
    assert "whereNew(b, ed.folder, names)" in code
    assert "const row = (r) =>" not in code, "the sheet draws no rows of its own"


def test_side_by_side_is_the_computers_split():
    assert 'from "./kit_editor.js"' in CELLS_JS
    assert '<main class="split">' in CELLS_JS
    # The line over the list is the editor's: the way to the folders, and the fold.
    assert '<section class="side">${sideHead(view, { fold: false })}${view.html}</section>' in CELLS_JS
    assert '<section class="side">${sideHead(view)}${view.html}</section>' in CELLS_JS
    assert "foldButton" not in CELLS_JS and "side-back" not in CELLS_JS


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
        "suffix": [".cell", ".xlsx"],
        "title": "name",
        "cells": "text",
        "path": "path",
    }
    assert next(f for f in quill["models"]["file"]["fields"] if f["name"] == "text")["kind"] == "text"
    # The welcome sheet is seeded the first time the folder is listed; a
    # listing leaves the text out, and reading one file gives it.
    listing = "/api/records/file?share=my-files&within=Documents&suffix=.cell,.xlsx"
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


def test_an_excel_file_is_a_sheet_and_export_hands_one_over(client):
    """An .xlsx under the folder is listed as a sheet and read as a .cell
    file's text; writing the text writes Excel's package; /export makes
    Excel, PDF or CSV from any sheet."""
    from cloudmorrow.quill import cells, xlsx

    client.app.state.cloudmorrow.quills.install_from_catalog("cells")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    listing = "/api/records/file?share=my-files&within=Documents&suffix=.cell,.xlsx"
    budget = client.get(listing, headers=auth).json()[0]
    trip = cells.Sheet({"A1": "Fuel", "B1": "80", "B2": "=B1*2"})
    trip.set_border("B2", ["top"])
    put = client.post(
        "/api/records/file/upload?share=my-files&folder=Documents&name=Trip.xlsx",
        headers={**auth, "Content-Type": "application/octet-stream"},
        content=xlsx.write_xlsx(trip),
    )
    assert put.status_code in (200, 201), put.text
    rows = client.get(listing + "&previews=true", headers=auth).json()
    assert sorted(r["fields"]["path"] for r in rows) == ["Documents/Budget.cell", "Documents/Trip.xlsx"]
    excel = next(r for r in rows if r["fields"]["path"].endswith(".xlsx"))
    assert excel["preview"] == "Fuel · 80 · 160"
    got = client.get(f"/api/records/file/{excel['id']}", headers=auth).json()
    read = cells.Sheet.from_text(got["fields"]["text"])
    assert read.cells == trip.cells and read.border("B2") == ["top"]
    read.set("A2", "Snacks")
    saved = client.patch(
        f"/api/records/file/{excel['id']}", headers=auth, json={"fields": {"text": read.to_text()}, "rev": got["rev"]}
    )
    assert saved.status_code == 200, saved.text
    raw = client.get(f"/api/records/file/{excel['id']}/content", headers=auth).content
    assert raw[:2] == b"PK" and xlsx.read_xlsx(raw).cells == read.cells
    # A search finds what was typed into an Excel file too.
    hits = client.get(listing + "&q=snacks", headers=auth).json()
    assert [r["fields"]["path"] for r in hits] == ["Documents/Trip.xlsx"]
    # Export: the budget as Excel, PDF and CSV; an Excel file as itself.
    base = f"/api/records/file/{budget['id']}/export"
    out = client.get(base + "?as=xlsx", headers=auth)
    assert out.status_code == 200 and 'filename="Budget.xlsx"' in out.headers["content-disposition"]
    assert xlsx.read_xlsx(out.content).raw("B5") == "=SUM(B1:B3)"
    pdf = client.get(base + "?as=pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    csv = client.get(base + "?as=csv", headers=auth)
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("Rent,")
    assert client.get(base + "?as=docx", headers=auth).status_code == 400
    same = client.get(f"/api/records/file/{excel['id']}/export?as=xlsx", headers=auth)
    assert same.content == raw
