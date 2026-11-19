"""An action's `only`: which records of its datamodel it is for.

The same sums on every surface — cloudmorrow/quill/only.py here, `fits` in
actions.js in the browser — and the server refuses a press on a record the
action is not for, whatever pressed it (docs/QUILLCODE.md).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.quill.only import fits
from cloudmorrow.server.app import create_app
from cloudmorrow.server.quills import QuillError, parse_manifest
from cloudmorrow.tui.kitdata import actions_on
from tests.conftest import ADMIN, token_for

FLEET = Path(__file__).parent / "fixtures" / "quill-fleet"
PHOTOS = {"only": {"kind": "file", "name": ["*.jpg", "*.jpeg", "*.PNG"]}}


def test_a_record_fits_when_every_field_matches_one_of_its_patterns():
    assert fits(PHOTOS, {"kind": "file", "name": "Holiday.JPG"})
    assert fits(PHOTOS, {"kind": "file", "name": "a.png"})
    assert not fits(PHOTOS, {"kind": "folder", "name": "a.jpg"})
    assert not fits(PHOTOS, {"kind": "file", "name": "clip.mp4"})
    assert not fits(PHOTOS, {"kind": "file"})
    # A single pattern, a `?`, and a dot that is a dot.
    assert fits({"only": {"name": "a?c"}}, {"name": "abc"}) and not fits({"only": {"name": "a.c"}}, {"name": "abc"})
    # No `only` is every record.
    assert fits({}, {"kind": "folder"}) and fits({"only": None}, None)


def test_the_terminal_leaves_the_button_off_a_record_that_does_not_fit():
    retouch = {"id": "retouch", "actions": [{"id": "edit-photo", "label": "Edit this photo", "on": "file", **PHOTOS}]}
    clipper = {
        "id": "clipper",
        "actions": [{"id": "edit-video", "label": "Edit this video", "on": "file", "only": {"name": "*.mp4"}}],
    }
    quills = [retouch, clipper]
    assert [a["id"] for _, a in actions_on(quills, "file")] == ["edit-photo", "edit-video"]
    assert [a["id"] for _, a in actions_on(quills, "file", {"kind": "file", "name": "a.jpg"})] == ["edit-photo"]
    assert [a["id"] for _, a in actions_on(quills, "file", {"kind": "file", "name": "a.mp4"})] == ["edit-video"]
    assert actions_on(quills, "file", {"kind": "folder", "name": "Photos"}) == []


def _manifest(extra: str) -> dict:
    import tomllib

    return tomllib.loads('[quill]\nid = "demo"\nname = "Demo"\nversion = "1.0.0"\ncode = "quill.py"\n' + extra)


def test_only_is_a_table_of_field_to_patterns_and_goes_with_on():
    head = '[[actions]]\nid = "a"\nlabel = "A"\n'
    with pytest.raises(QuillError, match="only goes with on"):
        parse_manifest(_manifest(head + 'only = { kind = "file" }\n'))
    for bad in (
        'only = "file"\n',
        "only = {}\n",
        "only = { kind = 1 }\n",
        "only = { kind = [] }\n",
        'only = { "a-b" = "x" }\n',
    ):
        with pytest.raises(QuillError, match="only says which records it is for"):
            parse_manifest(_manifest(head + 'on = "file"\n' + bad))
    (kept,) = parse_manifest(
        _manifest(head + 'on = "file"\nonly = { kind = "file", name = ["*.jpg", "*.png"] }\n')
    ).actions
    assert kept["only"] == {"kind": "file", "name": ["*.jpg", "*.png"]}


def _fleet_with(tmp_path: Path, only: str) -> Path:
    folder = tmp_path / "quill-fleet"
    shutil.copytree(FLEET, folder)
    toml = folder / "quill.toml"
    text = toml.read_text(encoding="utf-8")
    marker = 'id = "log-service"\nlabel = "Log a service"\non = "vehicle"\n'
    assert marker in text
    toml.write_text(text.replace(marker, marker + only + "\n"), encoding="utf-8")
    return folder


def _press(client, headers, action, **body):
    return client.post(f"/api/quills/fleet/actions/{action}", json=body, headers=headers)


def test_the_server_refuses_a_press_on_a_record_the_action_is_not_for(config, users, tmp_path):
    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    folder = _fleet_with(tmp_path, 'only = { name = "Van*" }')
    made = client.post("/api/quills", json={"source": str(folder)}, headers=admin)
    assert made.status_code == 201, made.text
    van = _press(client, admin, "add-van", fields={"name": "Van 1", "registration": "AB 12 345"}).json()["effects"][1][
        "id"
    ]
    bike = _press(client, admin, "add-van", fields={"name": "Bike", "registration": "CD 67 890"}).json()["effects"][1][
        "id"
    ]
    logged = _press(client, admin, "log-service", record=van, fields={"date": "2026-09-28", "km": 1200})
    assert logged.status_code == 200, logged.text
    refused = _press(client, admin, "log-service", record=bike, fields={"date": "2026-09-28", "km": 5})
    assert refused.status_code == 403 and "Log a service is not for this vehicle" in refused.text
    # The manifest the app is drawn from carries `only`, so every surface can leave the button off.
    shown = client.get("/api/quills", headers=admin).json()
    fleet = next(q for q in shown if q["id"] == "fleet")
    action = next(a for a in fleet["actions"] if a["id"] == "log-service")
    assert action["only"] == {"name": "Van*"}


def test_only_names_fields_the_datamodel_has(config, users, tmp_path):
    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    folder = _fleet_with(tmp_path, 'only = { colour = "red" }')
    refused = client.post("/api/quills", json={"source": str(folder)}, headers=admin)
    assert refused.status_code != 201
    assert "only names 'colour', which is no field of vehicle" in refused.text
