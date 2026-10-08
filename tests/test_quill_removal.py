"""Removing a Quill asks about its data: what it brought stays unless the administrator says."""

from __future__ import annotations

import pytest

from cloudmorrow.server.quills import QuillError, QuillRegistry, removal
from cloudmorrow.server.records import Principal, RecordStore
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for
from tests.test_quills import FLEET, VISIT, models_source, write_quill


@pytest.fixture()
def fleet(tmp_path):
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))
    registry.install(write_quill(tmp_path / "src", FLEET, visit=VISIT), models_source())
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    bram = Principal.person("bram")
    van = store.create(bram, "vehicle", {"name": "The van", "fleet.odometer": 120_000})
    store.create(bram, "vehicle", {"name": "The bike"})
    store.create(bram, "fleet.visit", {"vehicle": van.id, "what": "MOT"})
    store.create(bram, "fleet.visit", {"vehicle": van.id, "what": "Tyres"})
    return registry, store, bram


def test_what_a_quill_brought_is_listed_with_how_many_records_hold_it(fleet):
    registry, store, _ = fleet
    assert removal.brought(registry, store, "fleet") == [
        {"id": "fleet.visit", "kind": "datamodel", "label": "Service visit", "model": "fleet.visit", "records": 2},
        {"id": "fleet.odometer", "kind": "field", "label": "Odometer on Vehicle", "model": "vehicle", "records": 1},
    ]
    with pytest.raises(QuillError):
        removal.brought(registry, store, "nope")


def test_removed_with_nothing_dropped_everything_stays(fleet, tmp_path):
    registry, store, bram = fleet
    assert removal.remove(registry, store, "fleet") == {"dropped": {}}
    assert registry.quills == {}
    # The vans are there, odometer and all, under the foundational datamodel.
    vans = {v.fields["name"]: v.fields for v in store.list(bram, "vehicle")}
    assert vans["The van"].get("fleet.odometer") == 120_000
    # The visits are rows still, to be read again the day Fleet comes back.
    assert store.count_all("fleet.visit") == 2


def test_dropping_takes_the_records_and_the_field_away_for_good(fleet):
    registry, store, bram = fleet
    gone = removal.remove(registry, store, "fleet", ["fleet.visit", "fleet.odometer"])
    assert gone == {"dropped": {"fleet.odometer": 1, "fleet.visit": 2}}
    assert store.count_all("fleet.visit") == 0
    vans = {v.fields["name"]: v.fields for v in store.list(bram, "vehicle")}
    assert "fleet.odometer" not in vans["The van"] and len(vans) == 2


def test_only_what_it_brought_can_be_dropped(fleet):
    registry, store, _ = fleet
    with pytest.raises(QuillError, match="did not bring vehicle"):
        removal.remove(registry, store, "fleet", ["vehicle"])
    assert "fleet" in registry.quills


def test_the_remove_sheet_and_the_drop_are_an_administrators_over_the_api(client, tmp_path):
    state = client.app.state.cloudmorrow
    state.quills.install(write_quill(tmp_path / "src", FLEET, visit=VISIT), QUILL_CATALOG / "datamodels")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    made = client.post("/api/records/vehicle", json={"fields": {"name": "Van", "fleet.odometer": 5}}, headers=auth)
    assert made.status_code == 201, made.text
    brought = client.get("/api/quills/fleet/brought", headers=auth).json()
    assert [(b["id"], b["records"]) for b in brought] == [("fleet.visit", 0), ("fleet.odometer", 1)]
    assert client.get("/api/quills/fleet/brought", headers=guest).status_code == 403
    assert client.delete("/api/quills/fleet?drop=vehicle", headers=auth).status_code == 400
    removed = client.delete("/api/quills/fleet?drop=fleet.odometer", headers=auth)
    assert removed.status_code == 200 and removed.json() == {"dropped": {"fleet.odometer": 1}}
    assert "fleet" not in state.quills.quills
