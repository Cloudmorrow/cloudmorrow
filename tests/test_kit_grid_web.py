"""The kit's grid in the browser and on the command line: wired in, generic,
and calling what the server has.

The screens are driven in a browser, not from here (the shots in the report
are). What a test holds on to is what goes wrong quietly: the grid naming
one Quill, the old Files screen coming back by the side door, the desktop
app's mount buttons losing their way in, and `cm files` asking for
something the record API does not answer.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest
import typer

from cloudmorrow.cli.quillrun import Screen, _act_grid
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import QUILL_CATALOG

GRID_JS = (WEB / "kit_grid.js").read_text(encoding="utf-8")
GRID_CSS = (WEB / "kit_grid.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
CORE_JS = (WEB / "core.js").read_text(encoding="utf-8")


def code_of(source: str) -> str:
    """The code without its comments — the ones that start a line, since
    `image/*` in a string is not the start of one."""
    code = re.sub(r"(?ms)^\s*/\*.*?\*/", "", source)
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", code)


# -- wired in ------------------------------------------------------------------
def test_the_grid_is_its_own_file_drawn_from_the_kit(client):
    assert 'import { renderGrid, renderGridItem } from "./kit_grid.js";' in KIT_JS
    assert 'if (kit === "grid") return renderGrid(at, arg);' in KIT_JS
    # A grid's own records open on the grid's page, not the sheet of fields.
    assert 'if (screen.kit === "grid" && modelId === screen.model) return renderGridItem(at, id);' in KIT_JS
    assert '@import "./kit_grid.css";' in (WEB / "app.css").read_text()
    version = asset_version()
    for name in ("kit_grid.js", "kit_grid.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_the_old_files_screen_is_gone():
    assert not (WEB / "files.js").exists() and not (WEB / "files.css").exists()
    for path in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")) + [WEB / "app.html"]:
        text = path.read_text(encoding="utf-8")
        assert "files.js" not in text and "files.css" not in text, path.name
    # The web app reads files through the record API now, not the share file
    # routes. Making a share and saying who has it is still /api/shares.
    for path in sorted(WEB.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for route in ("/ls", "/file?", "/thumb", "/upload"):
            assert not re.search(r"/api/shares/[^\"'`]*" + re.escape(route), text), (path.name, route)


def test_nothing_in_the_grid_is_named_for_one_quill():
    """The grid reads names out of the screen and the datamodel, never its own."""
    for source, name in ((GRID_JS, "kit_grid.js"), (GRID_CSS, "kit_grid.css")):
        # The phone's own share sheet is the browser's word, not a Quill's.
        code = code_of(source).replace("navigator.share", "navigator.send")
        for word in (
            "share",
            "shares",
            "my-files",
            "drive",
            "machine",
            "files",
            "browsable",
            "about",
            "mount",
        ):
            assert not re.search(rf"[\"'.`/]{word}[\"'`\s/?=]", code), f"{name} names {word!r}"


def test_the_record_calls_it_makes_are_the_generic_ones():
    code = code_of(GRID_JS)
    # Its addresses are the shell's one way of saying where records are.
    assert re.search(r'import \{[^}]*\brecordsUrl\b[^}]*\} from "\./core\.js"', code)
    assert '"/api/records/"' in code_of(CORE_JS)
    for call in ('+ "/content"', '+ "/thumb?size="', '+ "/upload"'):
        assert call in code, call
    # Folders are made as records whose kind field says so.
    assert '[b.kind]: "folder"' in code
    # A change is sent with the rev it read.
    assert "rev: entry.rev" in code


def test_what_the_desktop_app_adds_comes_through_a_hook():
    assert "export function registerGridHook(hook)" in GRID_JS
    assert "hook.groups" in GRID_JS
    assert "desktopbridge" not in GRID_JS


# -- the web calls, against the server ------------------------------------------------
def test_the_calls_the_grid_makes_are_answered(client, auth, config):
    client.app.state.cloudmorrow.quills.install_from_catalog("files")
    (config.notes_dir / "bram" / "files").mkdir(parents=True, exist_ok=True)
    groups = client.get("/api/records/share", headers=auth).json()
    assert groups[0]["id"] == "my-files"
    folder = client.post(
        "/api/records/file",
        json={"fields": {"share": "my-files", "folder": "", "name": "Photos", "kind": "folder"}},
        headers=auth,
    )
    assert folder.status_code == 201, folder.text
    put = client.post(
        "/api/records/file/upload?share=my-files&folder=Photos&name=cat.txt",
        content=b"meow",
        headers={**auth, "Content-Type": "text/plain"},
    )
    assert put.status_code == 201, put.text
    listed = client.get("/api/records/file?share=my-files&folder=Photos", headers=auth).json()
    assert [r["fields"]["name"] for r in listed] == ["cat.txt"]
    got = client.get(f"/api/records/file/{listed[0]['id']}/content", headers=auth)
    assert got.content == b"meow"
    assert client.get(f"/api/records/file/{listed[0]['id']}/thumb?size=256", headers=auth).status_code == 415


# -- cm files ---------------------------------------------------------------------------
class FakeApi:
    """The record API, as much of it as `cm files` asks for."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.files = {
            ("my-files", ""): [
                {
                    "id": "f_1",
                    "rev": "1",
                    "fields": {
                        "share": "my-files",
                        "folder": "",
                        "name": "Photos",
                        "kind": "folder",
                        "size": 0,
                        "modified": "",
                    },
                },
                {
                    "id": "f_2",
                    "rev": "1",
                    "fields": {
                        "share": "my-files",
                        "folder": "",
                        "name": "cv.txt",
                        "kind": "file",
                        "size": 2,
                        "modified": "",
                    },
                },
            ],
            ("my-files", "Trash"): [
                {
                    "id": "f_9",
                    "rev": "1",
                    "fields": {
                        "share": "my-files",
                        "folder": "Trash",
                        "name": "old.txt",
                        "kind": "file",
                        "size": 2,
                        "modified": "",
                        "deleted": "2026-10-01T10:00:00+00:00",
                        "deleted_from": "Letters/old.txt",
                    },
                },
            ],
        }

    async def records(self, model, **where):
        self.calls.append(("records", model, where))
        if model == "share":
            return [{"id": "my-files", "fields": {"label": "My Files", "about": "Yours"}}]
        return self.files.get((where["share"], where["folder"]), [])

    async def record_content(self, model, record_id):
        self.calls.append(("content", record_id))
        return b"me"

    async def upload_record(self, model, fields, data):
        self.calls.append(("upload", fields, data))
        return {"id": "f_3", "fields": dict(fields)}

    async def create_record(self, model, fields, index=None):
        self.calls.append(("create", fields))
        return {"id": "f_4", "fields": dict(fields)}

    async def update_record(self, model, record_id, fields, *, rev=None):
        self.calls.append(("change", record_id, dict(fields)))
        return {"id": record_id, "fields": dict(fields)}

    async def delete_record(self, model, record_id):
        self.calls.append(("delete", record_id))

    async def copy_record(self, model, record_id, fields):
        self.calls.append(("copy", record_id, dict(fields)))
        return {"id": "f_5", "fields": {"name": "cv 2.txt", **fields}}


@pytest.fixture()
def screen():
    from cloudmorrow.server.quills import QuillRegistry

    registry = QuillRegistry(QUILL_CATALOG / "none", QUILL_CATALOG / "none")
    plan = registry.plan(QUILL_CATALOG / "quill-files", QUILL_CATALOG / "datamodels")
    quill = {"id": "files", "name": "Files", "models": plan["models"], "screens": plan["screens"]}
    return Screen(quill, quill["screens"][0])


def test_cm_files_lists_gets_and_puts(screen, tmp_path, capsys):
    api = FakeApi()
    asyncio.run(_act_grid(api, screen, "list", ["my-files"], True))
    listed = json.loads(capsys.readouterr().out)
    assert [r["fields"]["name"] for r in listed] == ["Photos", "cv.txt"]
    assert api.calls[-1] == ("records", "file", {"share": "my-files", "folder": ""})
    out = tmp_path / "cv.txt"
    asyncio.run(_act_grid(api, screen, "get", ["my-files", "cv.txt", str(out)], False))
    assert out.read_bytes() == b"me"
    local = tmp_path / "dog.jpg"
    local.write_bytes(b"woof")
    asyncio.run(_act_grid(api, screen, "put", ["my-files", "Photos", str(local)], False))
    assert api.calls[-1] == (
        "upload",
        {"share": "my-files", "folder": "Photos", "name": "dog.jpg"},
        b"woof",
    )
    asyncio.run(_act_grid(api, screen, "add", ["my-files", "Photos/2026"], False))
    assert api.calls[-1] == (
        "create",
        {"share": "my-files", "folder": "Photos", "name": "2026", "kind": "folder"},
    )
    asyncio.run(_act_grid(api, screen, "list", [], True))
    assert json.loads(capsys.readouterr().out)[0]["id"] == "my-files"


def test_cm_files_delete_goes_to_the_trash_and_restore_comes_back(screen, capsys):
    api = FakeApi()
    asyncio.run(_act_grid(api, screen, "delete", ["my-files", "cv.txt"], False))
    assert api.calls[-1] == ("delete", "f_2")
    assert "Moved cv.txt to the Trash" in capsys.readouterr().err
    asyncio.run(_act_grid(api, screen, "restore", ["my-files", "Trash/old.txt"], False))
    assert api.calls[-1] == ("change", "f_9", {"folder": "Letters", "name": "old.txt"})
    assert "Restored old.txt to Letters" in capsys.readouterr().err
    asyncio.run(_act_grid(api, screen, "delete", ["my-files", "Trash/old.txt"], False))
    assert api.calls[-1] == ("delete", "f_9")
    assert "Deleted Trash/old.txt for good" in capsys.readouterr().err
    with pytest.raises(typer.Exit):
        asyncio.run(_act_grid(api, screen, "restore", ["my-files", "cv.txt"], False))


def test_cm_files_copy_duplicates_or_copies_to_a_folder(screen, capsys):
    api = FakeApi()
    asyncio.run(_act_grid(api, screen, "copy", ["my-files", "cv.txt"], False))
    assert api.calls[-1] == ("copy", "f_2", {})
    assert "Copied cv.txt to cv 2.txt" in capsys.readouterr().err
    asyncio.run(_act_grid(api, screen, "copy", ["my-files", "cv.txt", "Letters"], False))
    assert api.calls[-1] == ("copy", "f_2", {"share": "my-files", "folder": "Letters"})
    asyncio.run(_act_grid(api, screen, "copy", ["my-files", "cv.txt", "media:Pets"], False))
    assert api.calls[-1] == ("copy", "f_2", {"share": "media", "folder": "Pets"})


# -- the Trash, in the browser ----------------------------------------------------------
def test_a_deleted_file_has_restore_and_a_delete_for_good():
    """A record whose `deleted` field is set is in the Trash: its page has
    Restore in place of Rename and Move, and Delete is for good; a folder's
    “…” offers the same two. Restore is the generic move, back to
    `deleted_from`."""
    code = code_of(GRID_JS)
    assert 'deleted: screen.deleted || ""' in code and 'deletedFrom: screen.deleted_from || ""' in code
    assert "deleted: (b.deleted && seconds(f[b.deleted])) || 0," in code
    item = code[code.index("export async function renderGridItem(") :]
    assert "const actions = editRows + copyRow + (entry.deleted ? (b.writes ? `" in item
    assert 'actionRow("restore"' in item and "Delete for good" in item
    assert '["Deleted", formatDate(entry.deleted, { long: true })]' in item
    change = code[code.index("async function change(") : code.index("const saidDone")]
    assert "const to = entry.deletedFrom || entry.name;" in change
    assert "{ [b.folder]: folderOf(to), [b.title]: baseName(to) }" in change
    assert "Move “${entry.name}” to the Trash?" in change
    assert "Delete “${entry.name}” for good?" in change
    folder = code[code.index("async function renderFolder(") : code.index("function photoName(")]
    assert 'label: "Restore folder"' in folder and 'label: "Delete folder for good"' in folder


def test_a_picked_file_without_a_suffix_gets_one_from_its_type():
    """A phone's picker can hand a photo over as "1000001234", and the name
    is what the type is read from everywhere. So what is picked, dropped or
    pasted goes up under `fileName`, which adds the suffix the browser's
    type calls for when the name has none and leaves a name with one alone;
    the camera's photos keep their timestamp names."""
    code = code_of(GRID_JS)
    named = code[code.index("function fileName(") : code.index("function photoName(")]
    assert "if (extOf(name)) return name;" in named
    assert '"image/jpeg": "jpg"' in code and '"video/quicktime": "mov"' in code
    assert '["image", "video", "audio"].includes(kind)' in named
    assert "return ext ? `${name}.${ext}` : name;" in named
    assert "picked.map((file) => [file, fileName(file)])" in code
    assert "dropped.map((file) => [file, fileName(file)])" in code
    assert 'file.name !== "image.png" ? fileName(file) : photoName(file)' in code
    assert "taken.map((file) => [file, photoName(file)])" in code


def test_the_trash_is_a_bin_beside_the_plus_and_empties():
    """The screen's `trash` names the folder the server keeps what is
    deleted in. At the top of a group that folder is not listed but a bin
    before the plus; in it, nothing goes in by the plus, a drop or a paste,
    and Empty deletes the folder itself, which the server takes as
    emptying it. Not there to list — never made, or emptied — it is there
    to open, and empty."""
    code = code_of(GRID_JS)
    assert 'trash: screen.trash || ""' in code
    folder = code[code.index("async function renderFolder(") : code.index("function photoName(")]
    assert "const isTrash = Boolean(b.trash) && folder === b.trash;" in folder
    assert "if (isTrash && (err.status === 404 || err.status === 400)) return [];" in folder
    assert "entries.filter((e) => !(e.is_dir && e.name === b.trash))" in folder
    assert 'class="button bin" href="${folderHash(at, group, b.trash)}"' in folder
    assert '<button class="empty-trash" hidden>' in folder
    assert "emptyEl.hidden = !sorted.length;" in folder
    # Nothing is wired to take files in where nothing may go in.
    stop = folder.index("if (!takesIn) return;")
    assert folder.index('emptyEl.addEventListener("click", () => emptyTrash(place, reload))') < stop
    for wired in ('.heading .add").addEventListener', 'addEventListener("drop"', "openFolder = { main: mainEl"):
        assert stop < folder.index(wired), wired
    empty = code[code.index("async function emptyTrash(") : code.index("async function folderEntry(")]
    assert "const trash = await folderEntry(b, group, folder);" in empty
    assert 'await api("DELETE", recordsUrl(b.model.id, trash.id));' in empty
    assert ".heading .bin" in GRID_CSS and ".heading .empty-trash" in GRID_CSS


def test_every_row_and_tile_has_a_menu_and_several_are_picked_at_once():
    """A right-click or a long press (actions.js's menu) on a row or tile:
    Open, the Quills that edit that kind of file, Rename, Duplicate, Copy
    to, Move to, Delete — fewer where less may be done. Select, Shift or
    Ctrl with a click, picks several for one of those; a row dragged onto a
    folder moves there with what is picked; the room around the rows makes
    a folder or an empty text file."""
    code = code_of(GRID_JS)
    assert 'import { contextMenus, editorsFor, menu } from "./actions.js";' in code
    assert 'import { pickFolder } from "./filepick.js";' in code
    folder = code[code.index("async function renderFolder(") : code.index("function photoName(")]
    for label in (
        '"Open"',
        "`Edit with ${e.quill.name}`",
        '"Rename…"',
        '"Duplicate"',
        '"Copy to…"',
        '"Move to…"',
        '"Delete"',
        '"Restore"',
    ):
        assert f"label: {label}" in folder, label
    assert 'contextMenus(mainEl, "[data-id]", (el) => {' in folder and "{ blank }" in folder
    assert 'label: "New folder…"' in folder and 'label: "New text file…"' in folder
    assert "if (!item || !(selecting || event.ctrlKey || event.metaKey || event.shiftKey)) return;" in folder
    assert "for (const one of ids.slice(from, to + 1)) picked.add(one);" in folder
    assert (
        'listingEl.addEventListener("dragstart"' in folder
        and "dragging = picked.has(id) ? chosen() : [byId(id)].filter(Boolean);" in folder
    )
    assert "await moveAll(b, moving, joinPath(folder, over.target.name), over.target.name);" in folder
    # Copying is the record API's copy; a duplicate is one with nothing said.
    change = code[code.index("async function change(") : code.index("const saidDone")]
    assert '+ "/copy", { fields: { [b.group]: to.group, [b.folder]: to.folder } }' in change
    assert '+ "/copy", { fields: {} }' in change
    # The search: the folder and all under it, names and lines, as the record API searches.
    assert "`&within=${encodeURIComponent(folder)}&q=${encodeURIComponent(q)}`" in folder
    assert 'findInput.addEventListener("input"' in folder
    # A folder's tile is the folder itself, filled.
    assert "entry.is_dir ? own.folderFull : own[kind] || own.file" in folder
    assert ".tile.folder .thumb .icon svg { width: 100%; height: auto; }" in GRID_CSS
    # The groups' “…” is what the hooks offer.
    groups = code[code.index("async function renderGroups(") : code.index("async function listFolder(")]
    assert "const choices = extras.flatMap((x) => (x.menu ? x.menu() : []));" in groups


# -- read is drawn as read (docs/CIRCLES.md) -----------------------------------------
def test_a_folder_you_may_only_read_takes_nothing_in():
    code = code_of(GRID_JS)
    assert "writes: mayWrite(model)," in code
    # No plus, no folder menu, no file inputs.
    assert "const takesIn = b.writes && !inTrash;" in code
    assert '(takesIn ? `<button class="add"' in code
    assert "const moreButton = folder && b.writes && !isTrash" in code
    assert '${takesIn ? `<input type="file" class="pick-input"' in code
    # Dropping and pasting are wired after this, and not at all when read.
    folder = code[code.index("async function renderFolder(") : code.index("function photoName(")]
    stop = folder.index("if (!b.writes) return;")
    assert folder.index("openFolder = null;") < stop
    wired_after = ('addEventListener("drop"', "openFolder = { main: mainEl", '.heading .add").addEventListener')
    for wired in wired_after:
        assert stop < folder.index(wired), wired


def test_a_file_you_may_only_read_is_not_renamed_moved_or_deleted():
    code = code_of(GRID_JS)
    item = code[code.index("export async function renderGridItem(") :]
    # Copying, and the Quills that edit it, need only reading; the rest is behind b.writes.
    assert 'const copyRow = entry.deleted ? "" : actionRow("copy"' in item
    for what in ("rename", "duplicate", "move"):
        assert f'actionRow("{what}"' in item[item.index("(b.writes ? `") :], what
    # Sending it on, or saving it, is reading.
    assert 'app.querySelector(".download").addEventListener' in item


def test_a_group_that_may_only_be_read_draws_nothing_that_writes():
    """`group_writes` names a bool on the group; false and the folder and the
    file's page are drawn as for records that may only be read."""
    code = code_of(GRID_JS)
    assert 'groupWrites: screen.group_writes || ""' in code
    assert "record.fields[b.groupWrites] === false" in code
    assert code.count("b.writes = false") == 2
