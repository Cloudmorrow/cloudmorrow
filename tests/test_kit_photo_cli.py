"""`cm <quill> …` for a photo editor: edits started, turned, cropped, sized, written on and saved, on a real server.

The Cropper fixture has no pictures API, so an edit's size is what the
record says, and `picture` says why there is none; the pictures API itself
is faked at the end.
"""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
import typer
from fastapi.testclient import TestClient
from rich.console import Console

from cloudmorrow.cli import quillrun
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server.app import create_app
from tests.conftest import ADMIN, QUILL_CATALOG, token_for

CROPPER = QUILL_CATALOG / "quill-cropper"


@pytest.fixture()
def cropper(config, users) -> TestClient:
    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("files")
    state.quills.install(CROPPER, QUILL_CATALOG / "datamodels")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    folder = {"share": "my-files", "folder": "", "name": "Photos", "kind": "folder"}
    assert client.post("/api/records/file", json={"fields": folder}, headers=auth).status_code == 201
    for name in ("beach.jpg", "dog.png", "notes.txt"):
        made = client.post(
            f"/api/records/file/upload?share=my-files&folder=Photos&name={name}", content=b"not really", headers=auth
        )
        assert made.status_code == 201, made.text
    return client


@pytest.fixture()
def cm(cropper, monkeypatch):
    def run(*argv: str, **timing) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(cropper, *ADMIN))
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=cropper.app), base_url="http://testserver")

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "cropper", argv[0], list(argv[1:]), timing=timing)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def records(client: TestClient, model: str) -> list[dict]:
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    return client.get(f"/api/records/{model}", headers=auth).json()


def set_size(client: TestClient, edit_id: str) -> None:
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    done = client.patch(
        f"/api/records/cropper.edit/{edit_id}", json={"fields": {"width": 4000, "height": 3000}}, headers=auth
    )
    assert done.status_code == 200, done.text


def test_an_edit_is_started_from_a_photo_listed_and_shown(cm, cropper):
    assert "Started beach" in cm("add", "beach.jpg")
    assert "Started Pup" in cm("add", "dog", "Pup")
    with pytest.raises(typer.Exit):
        cm("add", "notes.txt")
    listed = cm("list")
    assert "beach" in listed and "Pup" in listed
    shown = cm("show", "beach")
    assert "size not known yet" in shown and "nothing on it" in shown


def test_turn_mirror_crop_and_size(cm, cropper):
    cm("add", "beach.jpg")
    edit = records(cropper, "cropper.edit")[0]
    set_size(cropper, edit["id"])
    assert "90° clockwise" in cm("turn", "beach")
    assert "0° clockwise" in cm("turn", "beach", "left")
    assert "180° clockwise" in cm("turn", "beach", "180")
    with pytest.raises(typer.Exit):
        cm("turn", "beach", "sideways")
    assert "Mirrored beach" in cm("mirror", "beach")
    assert "As taken again beach" in cm("mirror", "beach")
    assert "Cropped beach to 10 10 80 80" in cm("crop", "beach", "10", "10", "80", "80")
    assert "Cropped beach to 0 0 50 50" in cm("crop", "beach", "0 0 50 50")
    with pytest.raises(typer.Exit):
        cm("crop", "beach", "1 2 3")
    assert "comes out 1000 × 750" in cm("size", "beach", "1000")
    assert "comes out 400 × 300" in cm("size", "beach", "20%")
    assert "comes out 2000 × 1500" in cm("size", "beach", "as is")
    with pytest.raises(typer.Exit):
        cm("size", "beach", "huge")
    assert "The whole picture of beach" in cm("crop", "beach", "all")
    shown = cm("show", "beach")
    assert "turned 180°" in shown and "4000 × 3000 as taken" in shown


def test_layers_are_laid_on_moved_listed_and_taken_off(cm, cropper):
    cm("add", "beach.jpg")
    said = cm("text", "beach", "Summer", "2026", at="10 80", size="8", colour="amber")
    assert "'Summer 2026' at 10 80, 8% tall, #f0a81e" in said
    assert "'Hi' at 6 6, 6% tall, #ffffff" in cm("text", "beach", "Hi")
    with pytest.raises(typer.Exit):
        cm("text", "beach", "Bad", colour="mauve")
    assert "Moved 'Hi' at 50 50, 6% tall, #ffffff" in cm("move", "beach", "Hi", at="50 50")
    with pytest.raises(typer.Exit):
        cm("move", "beach", "Hi")
    # Stacked as they were made: the last on top, so first in the listing.
    shown = cm("layers", "beach")
    assert shown.index("Hi") < shown.index("Summer 2026") and "10 80" in shown and "#f0a81e" in shown
    orders = [t["fields"]["order"] for t in records(cropper, "cropper.layer")]
    assert sorted(orders) == [0, 1]
    assert "Took off 'Hi'" in cm("rm", "beach", "Hi")
    assert [t["fields"]["text"] for t in records(cropper, "cropper.layer")] == ["Summer 2026"]


def test_save_writes_over_the_photo_or_beside_it(cm, cropper):
    cm("add", "beach.jpg")
    assert "Saving beach over beach.jpg" in cm("save", "beach")
    edit = records(cropper, "cropper.edit")[0]["fields"]
    assert (edit["status"], edit["message"]) == ("queued", "over the photo")
    assert "Saving beach as beach edited.png" in cm("save", "beach", "beach edited.png")
    assert records(cropper, "cropper.edit")[0]["fields"]["message"] == "as beach edited.png"
    assert "queued — as beach edited.png" in cm("list")


def test_export_runs_the_screens_action(cm, cropper):
    cm("add", "beach.jpg")
    assert "Queued" in cm("export", "beach", "format=png")
    edit = records(cropper, "cropper.edit")[0]["fields"]
    assert (edit["status"], edit["message"]) == ("queued", "as png")


def test_picture_saves_the_edit_from_the_pictures_api(cm, cropper, monkeypatch, tmp_path):
    cm("add", "beach.jpg")
    with pytest.raises(typer.Exit):
        cm("picture", "beach")
    asked = []

    async def quill_api(self, path, params=None):
        asked.append((path, params))
        return httpx.Response(200, content=b"\xff\xd8jpeg")

    original = quillrun.dispatch

    async def with_pictures(api, quill, action, args, **kw):
        quills = await api.quills()

        async def listed():
            for q in quills:
                if q["id"] == "cropper":
                    q["apis"] = [{"id": "pictures", "service": "draw", "prefix": "pictures"}]
                    q["screens"][0]["pictures"] = "pictures"
            return quills

        api.quills = listed
        await original(api, quill, action, args, **kw)

    monkeypatch.setattr(CloudmorrowClient, "quill_api", quill_api)
    monkeypatch.setattr(quillrun, "dispatch", with_pictures)
    target = tmp_path / "p.jpg"
    said = cm("picture", "beach", out=str(target))
    assert "Saved" in said and target.read_bytes() == b"\xff\xd8jpeg"
    assert asked[-1][0] == "/api/q/cropper/pictures/picture" and asked[-1][1]["w"] == 1280


def test_the_check_sketches_the_photo_editor(tmp_path):
    from cloudmorrow.cli.quill import preview
    from cloudmorrow.server.quills import QuillRegistry

    plan = QuillRegistry(tmp_path / "q", tmp_path / "d").plan(CROPPER, QUILL_CATALOG / "datamodels")
    sketch = preview(plan)
    assert "Editor (photo of cropper.edit)" in sketch
    assert "[ Save w ]" in sketch and "Layers, top first" in sketch
    assert "no pictures API" in sketch and "my-files / Photos" in sketch
    assert max(len(line) for line in sketch.splitlines()) <= 80


def test_the_other_kits_do_not_have_a_photo_editors_words(tasks_quill, monkeypatch):
    screen_out = Console(file=io.StringIO(), width=200, color_system=None)
    monkeypatch.setattr(quillrun, "console", screen_out)
    api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(tasks_quill, *ADMIN))
    api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=tasks_quill.app), base_url="http://testserver")

    async def go() -> None:
        try:
            await quillrun.dispatch(api, "tasks", "crop", ["x", "1 1 1 1"])
        finally:
            await api.aclose()

    with pytest.raises(typer.Exit):
        asyncio.run(go())
