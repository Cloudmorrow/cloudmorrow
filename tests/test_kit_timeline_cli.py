"""`cm <quill> …` for a timeline: projects, pieces cut, trimmed and moved, against a real server.

The Cutter fixture has no frames API, so a piece's length is given, and
`frame` says why there is none; the frames API itself is faked at the end.
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

CUTTER = QUILL_CATALOG / "quill-cutter"


@pytest.fixture()
def cutter(config, users) -> TestClient:
    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    state = client.app.state.cloudmorrow
    state.quills.install_from_catalog("files")
    state.quills.install(CUTTER, QUILL_CATALOG / "datamodels")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    folder = {"share": "my-files", "folder": "", "name": "Videos", "kind": "folder"}
    assert client.post("/api/records/file", json={"fields": folder}, headers=auth).status_code == 201
    for name in ("beach.mp4", "song.mp3"):
        made = client.post(
            f"/api/records/file/upload?share=my-files&folder=Videos&name={name}", content=b"not really", headers=auth
        )
        assert made.status_code == 201, made.text
    return client


@pytest.fixture()
def cm(cutter, monkeypatch):
    def run(*argv: str, **timing) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(cutter, *ADMIN))
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=cutter.app), base_url="http://testserver")

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "cutter", argv[0], list(argv[1:]), timing=timing)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def records(client: TestClient, model: str) -> list[dict]:
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    return client.get(f"/api/records/{model}", headers=auth).json()


def test_a_project_is_made_listed_and_filled(cm, cutter):
    assert "Made Holiday" in cm("add", "Holiday")
    assert "Holiday" in cm("list")
    added = cm("add", "Holiday", "beach.mp4", length="12")
    assert "Added beach.mp4 on V1 0:00.00–0:12.00" in added
    # Without --at, after what is on the track already.
    assert "on V1 0:12.00–0:16.00" in cm("add", "Holiday", "Videos/beach.mp4", length="4")
    # A sound goes on the first audio track; a name may leave its extension off.
    assert "song.mp3 on A1 0:00.00–1:00.00" in cm("add", "Holiday", "song", length="1:00")
    shown = cm("show", "Holiday")
    assert "V1" in shown and "beach.mp4" in shown and "0:12.00–0:16.00" in shown


def test_without_a_length_or_a_frames_api_add_asks_for_one(cm):
    cm("add", "Holiday")
    with pytest.raises(typer.Exit):
        cm("add", "Holiday", "beach.mp4")
    with pytest.raises(typer.Exit):
        cm("frame", "Holiday", at="1")


def test_cut_trim_move_and_rm_on_a_piece(cm, cutter):
    cm("add", "Holiday")
    cm("add", "Holiday", "beach.mp4", length="10", track="V1", at="2")
    piece = records(cutter, "cutter.piece")[0]
    auth = {"Authorization": f"Bearer {token_for(cutter, *ADMIN)}"}
    blur = cutter.post(
        "/api/records/cutter.effect",
        json={
            "fields": {
                "piece": piece["id"],
                "kind": "blur",
                "label": "Face",
                "keyframes": [{"t": 1, "x": 0, "y": 0, "w": 10, "h": 10}, {"t": 6, "x": 50, "y": 0, "w": 10, "h": 10}],
            }
        },
        headers=auth,
    )
    assert blur.status_code == 201, blur.text
    short = piece["id"][2:6]
    assert "Cut beach.mp4 at 0:05.00" in cm("cut", "Holiday", short, "5")
    pieces = sorted(records(cutter, "cutter.piece"), key=lambda p: float(p["fields"]["start"]))
    assert [(float(p["fields"]["start"]), float(p["fields"]["length"])) for p in pieces] == [(2, 3), (5, 7)]
    assert float(pieces[1]["fields"]["offset"]) == 3
    effects = {e["fields"]["piece"]: e["fields"]["keyframes"] for e in records(cutter, "cutter.effect")}
    assert [k["t"] for k in effects[pieces[0]["id"]]] == [1, 3]
    assert [k["t"] for k in effects[pieces[1]["id"]]] == [0, 3]
    second = pieces[1]["id"]
    with pytest.raises(typer.Exit):
        # Two pieces have the name now.
        cm("rm", "Holiday", "beach.mp4")
    assert "Trimmed beach.mp4: 0:06.00–0:12.00" in cm("trim", "Holiday", second[2:8], start="6")
    effects = {e["fields"]["piece"]: e["fields"]["keyframes"] for e in records(cutter, "cutter.effect")}
    assert [k["t"] for k in effects[second]] == [-1, 2]
    assert "0:06.00–0:10.00" in cm("trim", "Holiday", second[2:8], end="10")
    assert "Moved beach.mp4 to V2 0:20.00–0:24.00" in cm("move", "Holiday", second[2:8], at="20", track="V2")
    with pytest.raises(typer.Exit):
        cm("move", "Holiday", second[2:8], track="A1")
    assert "Took out beach.mp4" in cm("rm", "Holiday", second[2:8])
    assert len(records(cutter, "cutter.piece")) == 1 and len(records(cutter, "cutter.effect")) == 1


def test_export_runs_the_screens_action(cm, cutter):
    cm("add", "Holiday")
    assert "Queued" in cm("export", "Holiday", "format=webm")
    project = records(cutter, "cutter.project")[0]["fields"]
    assert (project["status"], project["message"]) == ("queued", "as webm")
    assert "queued — as webm" in cm("list")


def test_frame_saves_the_cut_from_the_frames_api(cm, cutter, monkeypatch, tmp_path):
    cm("add", "Holiday")
    asked = []

    async def quill_api(self, path, params=None):
        asked.append((path, params))
        return httpx.Response(200, content=b"\xff\xd8jpeg")

    original = quillrun.dispatch

    async def with_frames(api, quill, action, args, **kw):
        quills = await api.quills()

        async def listed():
            for q in quills:
                if q["id"] == "cutter":
                    q["apis"] = [{"id": "frames", "service": "render", "prefix": "frames"}]
                    q["screens"][0]["frames"] = "frames"
            return quills

        api.quills = listed
        await original(api, quill, action, args, **kw)

    monkeypatch.setattr(CloudmorrowClient, "quill_api", quill_api)
    monkeypatch.setattr(quillrun, "dispatch", with_frames)
    target = tmp_path / "f.jpg"
    said = cm("frame", "Holiday", at="1:02", out=str(target))
    assert "Saved" in said and target.read_bytes() == b"\xff\xd8jpeg"
    assert asked[0][0] == "/api/q/cutter/frames/frame" and asked[0][1]["t"] == "62.000"


def test_the_check_sketches_the_timeline(tmp_path):
    from cloudmorrow.cli.quill import preview
    from cloudmorrow.server.quills import QuillRegistry

    plan = QuillRegistry(tmp_path / "q", tmp_path / "d").plan(CUTTER, QUILL_CATALOG / "datamodels")
    sketch = preview(plan)
    assert "Editor (timeline of cutter.project)" in sketch
    assert "[ Export e ]" in sketch and "V1  [<name>" in sketch
    assert "no frames API" in sketch and "my-files / Videos" in sketch
    assert max(len(line) for line in sketch.splitlines()) <= 80


def test_the_other_kits_do_not_have_a_timelines_words(tasks_quill, monkeypatch):
    screen_out = Console(file=io.StringIO(), width=200, color_system=None)
    monkeypatch.setattr(quillrun, "console", screen_out)
    api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(tasks_quill, *ADMIN))
    api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=tasks_quill.app), base_url="http://testserver")

    async def go() -> None:
        try:
            await quillrun.dispatch(api, "tasks", "cut", ["x", "1"])
        finally:
            await api.aclose()

    with pytest.raises(typer.Exit):
        asyncio.run(go())


def test_a_new_project_may_say_its_size(cm, cutter):
    cm("add", "Vertical", "size=1080x1920")
    made = next(r for r in records(cutter, "cutter.project") if r["fields"]["name"] == "Vertical")
    assert (made["fields"]["width"], made["fields"]["height"]) == (1080, 1920)
    with pytest.raises(typer.Exit):
        cm("add", "Odd", "size=big")
