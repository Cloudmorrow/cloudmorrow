"""Where a file is, in the lists and under an open page: Notes, Docs, Cells.

A row says where its file is the way Files says it — `My Files/Notes/ideas/
garden.md` — on one line that loses its start, not its end, when it is too
long; an open page says it whole at the bottom, with a way to its folder in
Files when Files is installed.
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "cloudmorrow" / "server" / "web"
EDITOR_JS = (WEB / "kit_editor.js").read_text(encoding="utf-8")
DOCS_JS = (WEB / "kit_docs.js").read_text(encoding="utf-8")
CELLS_JS = (WEB / "kit_cells.js").read_text(encoding="utf-8")
ACTIONS_JS = (WEB / "actions.js").read_text(encoding="utf-8")
EDITOR_CSS = (WEB / "kit_editor.css").read_text(encoding="utf-8")


def test_where_a_file_is_is_said_as_files_says_it():
    """The share by the name Files shows (My Files), then the path in it,
    suffix and all — from the one call the picker makes, kept for a minute."""
    assert 'api("GET", recordsUrl("share"))' in EDITOR_JS
    assert "names: new Map(shares.map((s) => [s.id, String(s.fields.label || s.id)]))" in EDITOR_JS
    assert "Date.now() - shareNames.at < 60_000" in EDITOR_JS
    where = EDITOR_JS.split("export function whereIs", 1)[1].split("\n}", 1)[0]
    assert "record.fields[b.path || b.title]" in where
    assert 'String(record.fields.share || b.where.share || "")' in where
    assert "`${name}/${path}`" in EDITOR_JS
    # A page not written yet says the folder it will land in, with a slash after it.
    new = EDITOR_JS.split("export function whereNew", 1)[1].split("\n}", 1)[0]
    assert 'said(share, under, names) + "/"' in new


def test_every_row_has_the_path_under_its_title():
    """The editor's rows (Notes, Docs) and the sheet's (Cells): a `.path`
    line, the words isolated so the start is what the browser cuts."""
    editor_row = EDITOR_JS.split("const row = (p) =>", 1)[1].split("</a>`", 1)[0]
    assert '<span class="path"><bdi>${esc(p.place)}</bdi></span>' in editor_row
    assert "place: whereIs(b, r, names).said" in EDITOR_JS
    # The folder chip the All list had is gone: the path says it, on every list.
    assert 'class="where"' not in editor_row and "folderSmall" not in editor_row
    # The sheet's rows are the editor's.
    assert "listView(b, await load(b)" in CELLS_JS and "const row = (r) =>" not in CELLS_JS


def test_a_path_too_long_for_its_line_loses_its_start():
    """Right to left outside, left to right inside: the ellipsis lands at the left."""
    rule = EDITOR_CSS.split(".row .path {", 1)[1].split("}", 1)[0]
    assert "direction: rtl;" in rule and "text-align: left;" in rule
    assert "text-overflow: ellipsis;" in rule and "white-space: nowrap;" in rule
    assert ".row .path bdi { direction: ltr; unicode-bidi: isolate; }" in EDITOR_CSS
    # The old chip's rules went with the chip.
    assert ".row .title-line .where" not in EDITOR_CSS


def test_an_open_page_says_where_its_file_is_whole():
    """At the bottom of a note, a document and a sheet; said again when the
    file is made or renamed; wrapping rather than cut."""
    for source, name in ((EDITOR_JS, "editor"), (DOCS_JS, "docs"), (CELLS_JS, "cells")):
        assert "${whereabouts(ed.isNew ? whereNew(b, " in source, name
        assert ": whereIs(b, record, names))}" in source, name
        moved = source.split("function moved(ed, record) {", 1)[1].split("\n}", 1)[0]
        assert "showWhereabouts(whereIs(ed.b, record));" in moved, name
    rule = EDITOR_CSS.split(".editor .whereabouts {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap: anywhere;" in rule


def test_the_whole_path_is_a_way_to_its_folder_in_files():
    """A link to the folder in the first installed screen that shows files by
    share — the grid's own address — and plain words when nothing here does."""
    assert 'import { folderInFiles } from "./actions.js";' in EDITOR_JS
    link = EDITOR_JS.split("const placeLink = (where) =>", 1)[1].split("\n};", 1)[0]
    assert 'where.share ? folderInFiles(where.share, where.folder) : ""' in link
    assert 'title="Open the folder in Files"' in link
    found = ACTIONS_JS.split("export function folderInFiles", 1)[1].split("\n}", 1)[0]
    assert 'screen.kit !== "grid" || screen.group !== "share"' in found
    assert "`#/q/${encodeURIComponent(quill.id)}/${encodeURIComponent(screen.id)}/" in found
    assert "${encodeURIComponent(share)}`" in found
    assert '(folder ? "/" + encodePath(folder) : "")' in found
    grid = (WEB / "kit_grid.js").read_text(encoding="utf-8")
    assert '`${at.base}/${encodeURIComponent(group)}` + (folder ? "/" + encodePath(folder) : "")' in grid
