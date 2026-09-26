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

from cloudmorrow.cli.quillrun import Screen, _act_grid
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import QUILL_CATALOG

GRID_JS = (WEB / "kit_grid.js").read_text(encoding="utf-8")
GRID_CSS = (WEB / "kit_grid.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")


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
    assert (
        'if (screen.kit === "grid" && modelId === screen.model) return renderGridItem(at, id);'
        in KIT_JS
    )
    assert '@import "./kit_grid.css";' in (WEB / "app.css").read_text()
    version = asset_version()
    for name in ("kit_grid.js", "kit_grid.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_the_old_files_screen_is_gone():
    assert not (WEB / "files.js").exists() and not (WEB / "files.css").exists()
    for path in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")) + [WEB / "app.html"]:
        text = path.read_text(encoding="utf-8")
        assert "files.js" not in text and "files.css" not in text, path.name
    # The web app reads files through the record API now, not the share routes.
    for path in sorted(WEB.glob("*.js")):
        assert "/api/shares/" not in path.read_text(encoding="utf-8"), path.name


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
    assert '"/api/records/"' in code
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
    assert (
        client.get(f"/api/records/file/{listed[0]['id']}/thumb?size=256", headers=auth).status_code
        == 415
    )


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

    async def delete_record(self, model, record_id):
        self.calls.append(("delete", record_id))


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
