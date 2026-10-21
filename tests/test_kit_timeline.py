"""The timeline kit's server side: what a manifest must say, and media links (docs/TIMELINE.md)."""

from __future__ import annotations

import pytest

from cloudmorrow.quill.screens import TRACKS, frames_path, timeline_fields, tracks_of
from cloudmorrow.server.security import (
    TokenError,
    create_access_token,
    create_media_token,
    decode_access_token,
    decode_media_token,
)

KEY = "k" * 48


def test_a_media_token_is_not_an_access_token():
    issued = create_media_token("ana", "file", "f1", KEY)
    assert decode_media_token(issued.token, KEY) == ("ana", "file", "f1")
    with pytest.raises(TokenError):
        decode_access_token(issued.token, KEY)


def test_an_access_token_is_not_a_media_token():
    issued = create_access_token("ana", KEY, 1)
    with pytest.raises(TokenError):
        decode_media_token(issued.token, KEY)


def test_tracks_default_to_two_of_each():
    assert tracks_of({}) == TRACKS
    assert tracks_of({"tracks": [{"id": "V1"}]}) == [{"id": "V1", "kind": "video", "name": "V1"}]


def test_frames_path_is_the_apis_prefix():
    quill = {"id": "vid", "apis": [{"id": "frames", "service": "render", "prefix": "frames"}]}
    assert frames_path(quill, {"frames": "frames"}) == "/api/q/vid/frames"
    assert frames_path(quill, {}) is None


def test_timeline_fields_find_the_links():
    models = {
        "v.piece": {"id": "v.piece", "fields": [{"name": "project", "kind": "link", "to": "v.project"}]},
        "v.effect": {"id": "v.effect", "fields": [{"name": "piece", "kind": "link", "to": "v.piece"}]},
    }
    screen = {"model": "v.project", "pieces": "v.piece", "effects": "v.effect", "media": {"share": "my-files"}}
    bound = timeline_fields(screen, {"id": "v.project", "title": "name", "fields": []}, models)
    assert bound["piece_project"] == "project" and bound["effect_piece"] == "piece"
    assert bound["media"] == {"share": "my-files"}


# -- the manifest ------------------------------------------------------------------------
import shutil  # noqa: E402

from cloudmorrow.server.quills import QuillError, QuillRegistry  # noqa: E402
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for  # noqa: E402

CUTTER = QUILL_CATALOG / "quill-cutter"


def cutter_copy(tmp_path, **replace: str):
    folder = tmp_path / "cutter"
    shutil.copytree(CUTTER, folder)
    for name, (old, new) in replace.items():
        path = folder / name
        text = path.read_text(encoding="utf-8")
        assert old in text
        path.write_text(text.replace(old, new), encoding="utf-8")
    return folder


@pytest.fixture()
def registry(tmp_path) -> QuillRegistry:
    return QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))


def test_the_cutter_plans(registry):
    plan = registry.plan(CUTTER, QUILL_CATALOG / "datamodels")
    assert plan["id"] == "cutter"


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"datamodels/piece.toml": ('length = { kind = "decimal", required = true }', "")}, "length"),
        ({"datamodels/piece.toml": ('start = { kind = "decimal"', 'start = { kind = "int"')}, "start"),
        ({"datamodels/project.toml": ('tracks = { kind = "json" }', "")}, "tracks"),
        ({"datamodels/effect.toml": ('keyframes = { kind = "json", default = [] }', "")}, "keyframes"),
        ({"quill.toml": ('pieces = "cutter.piece"\n', "")}, "pieces"),
        ({"quill.toml": ('export = "export"', 'export = "nope"')}, "export"),
        ({"quill.toml": ('export = "export"', 'frames = "frames"')}, "frames"),
        (
            {"datamodels/piece.toml": ("track = {", 'again = { kind = "link", to = "cutter.project" }\ntrack = {')},
            "exactly one link",
        ),
    ],
)
def test_a_timeline_says_what_is_missing(registry, tmp_path, change, said):
    with pytest.raises(QuillError, match=said):
        registry.plan(cutter_copy(tmp_path, **change), QUILL_CATALOG / "datamodels")


# -- media links -------------------------------------------------------------------------
@pytest.fixture()
def drive_file(client, config):
    client.app.state.cloudmorrow.quills.install_from_catalog("files")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    made = client.post("/api/records/file/upload?share=my-files&name=clip.mp4", content=b"0123456789", headers=auth)
    assert made.status_code == 201, made.text
    return made.json()["id"], auth


def test_a_media_link_serves_ranges_without_a_token(client, drive_file):
    file_id, auth = drive_file
    link = client.post(f"/api/records/file/{file_id}/media", headers=auth)
    assert link.status_code == 200, link.text
    url = link.json()["url"]
    assert url.startswith("/api/media/")
    whole = client.get(url)
    assert whole.status_code == 200 and whole.content == b"0123456789"
    part = client.get(url, headers={"Range": "bytes=2-4"})
    assert part.status_code == 206 and part.content == b"234"


def test_a_media_link_is_not_a_sign_in(client, drive_file):
    file_id, auth = drive_file
    token = client.post(f"/api/records/file/{file_id}/media", headers=auth).json()["url"].rsplit("/", 1)[1]
    assert client.get("/api/records/file", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/media/not-a-token").status_code == 401


def test_nobody_gets_a_link_to_what_they_cannot_read(client, drive_file):
    file_id, _ = drive_file
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.post(f"/api/records/file/{file_id}/media", headers=guest).status_code in (403, 404)
