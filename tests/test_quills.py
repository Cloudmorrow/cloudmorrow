"""Quills: the catalog, the install sheet, installing, removing, and the move from the old tasks."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from cloudmorrow.server.db import connect
from cloudmorrow.server.quilljobs import boot, install_foundation, move_legacy_tasks
from cloudmorrow.server.quills import QuillError, QuillRegistry, load_catalog, tarball_url
from cloudmorrow.server.records import Principal, RecordStore
from tests.conftest import GUEST, QUILL_CATALOG, token_for


def write_quill(folder: Path, manifest: str, **datamodels: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "quill.toml").write_text(manifest, encoding="utf-8")
    if datamodels:
        (folder / "datamodels").mkdir(exist_ok=True)
        for name, text in datamodels.items():
            (folder / "datamodels" / f"{name}.toml").write_text(text, encoding="utf-8")
    return folder


FLEET = """
[quill]
id = "fleet"
name = "Fleet"
version = "1.2.0"
summary = "The cars, and when each was last serviced."
category = "business"

[uses]
datamodels = ["vehicle"]

[[extends]]
model = "vehicle"
[extends.fields]
odometer = { kind = "int", indexed = true }

[[grants]]
model = "contact"
access = "read"
why = "to show who drives each car"

[[screens]]
id = "cars"
kit = "list"
label = "Cars"
model = "vehicle"
title = "name"
subtitle = "registration"

[[screens]]
id = "visits"
kit = "list"
label = "Services"
model = "fleet.visit"
title = "what"

[[services]]
id = "dvla"
command = ["python", "services/dvla.py"]
always = true
"""

VISIT = """
[datamodel]
id = "fleet.visit"
label = "Service visit"
title = "what"

[fields]
vehicle = { kind = "link", to = "vehicle", required = true, on_delete = "cascade" }
what = { kind = "string", required = true }
on = { kind = "date", indexed = true }
"""


@pytest.fixture()
def registry(tmp_path) -> QuillRegistry:
    return QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))


def models_source() -> Path:
    return QUILL_CATALOG / "datamodels"


def test_the_catalog_is_read_with_its_categories(registry):
    catalog = load_catalog(str(QUILL_CATALOG))
    assert [c["id"] for c in catalog.categories] == ["personal"]
    assert catalog.entry("tasks")["foundation"] is True
    with pytest.raises(QuillError):
        catalog.entry("nope")


def test_the_install_sheet_says_everything_a_quill_adds(registry, tmp_path):
    folder = write_quill(tmp_path / "src", FLEET, visit=VISIT)
    plan = registry.plan(folder, models_source())
    data = {row["id"]: row for row in plan["data"]}
    assert data["vehicle"] == {
        "id": "vehicle",
        "label": "Vehicle",
        "how": "extends",
        "foundation": True,
        "new": True,
        "fields": ["fleet.odometer"],
    }
    assert data["fleet.visit"]["how"] == "introduces" and data["fleet.visit"]["new"]
    assert (
        data["contact"]["how"] == "asks for"
        and data["contact"]["why"] == "to show who drives each car"
    )
    assert [s["label"] for s in plan["screens"]] == ["Cars", "Services"]
    assert plan["surfaces"] == ["phone", "web", "terminal", "command line", "assistant"]
    assert plan["not_running_yet"] == ["service dvla"]
    # Planning installs nothing.
    assert registry.quills == {} and not (tmp_path / "datamodels").exists()


def test_installing_brings_the_datamodels_and_the_links_they_need(registry, tmp_path):
    folder = write_quill(tmp_path / "src", FLEET, visit=VISIT)
    registry.install(folder, models_source())
    assert set(registry.quills) == {"fleet"}
    # contact links to organisation, so both came.
    assert {p.stem for p in (tmp_path / "datamodels").glob("*.toml")} == {
        "vehicle",
        "contact",
        "organisation",
    }
    vehicle = registry.datamodels["vehicle"]
    assert vehicle.by_name["fleet.odometer"].added_by == "fleet"
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    bram = Principal.person("bram")
    car = store.create(bram, "vehicle", {"name": "The van", "fleet.odometer": 120_000})
    store.create(bram, "fleet.visit", {"vehicle": car.id, "what": "MOT"})
    assert store.list(bram, "vehicle", {"fleet.odometer": 120000})[0].id == car.id


def test_removing_a_quill_keeps_its_records(registry, tmp_path):
    folder = write_quill(tmp_path / "src", FLEET, visit=VISIT)
    registry.install(folder, models_source())
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    bram = Principal.person("bram")
    store.create(bram, "vehicle", {"name": "The van"})
    registry.uninstall("fleet")
    assert registry.quills == {}
    # The foundational datamodel stays, and so does the van.
    assert [v.fields["name"] for v in store.list(bram, "vehicle")] == ["The van"]


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (
            lambda m: m.replace('kit = "list"\nlabel = "Cars"', 'kit = "calendar"\nlabel = "Cars"'),
            "does not draw",
        ),
        (lambda m: m.replace('title = "name"', 'title = "colour"'), "does not have"),
        (lambda m: m.replace('why = "to show who drives each car"', 'why = ""'), "says why"),
        (lambda m: m.replace('version = "1.2.0"', 'version = "one"'), "major.minor.patch"),
        (
            lambda m: m.replace(
                'odometer = { kind = "int", indexed = true }',
                'odometer = { kind = "int", required = true }',
            ),
            "cannot be required",
        ),
        (
            lambda m: m.replace('datamodels = ["vehicle"]', 'datamodels = ["spaceship"]'),
            "spaceship",
        ),
    ],
)
def test_a_quill_that_does_not_fit_is_refused_in_plain_words(registry, tmp_path, change, says):
    folder = write_quill(tmp_path / "src", change(FLEET), visit=VISIT)
    with pytest.raises(QuillError, match=says):
        registry.plan(folder, models_source())
    assert registry.quills == {}


def test_a_quill_introduces_only_under_its_own_name(registry, tmp_path):
    folder = write_quill(tmp_path / "src", FLEET, visit=VISIT.replace("fleet.visit", "visit"))
    with pytest.raises(QuillError, match="introduces is named fleet"):
        registry.plan(folder, models_source())


def test_a_broken_quill_on_disk_is_left_out_not_fatal(registry, tmp_path):
    registry.install_from_catalog("tasks")
    (tmp_path / "quills" / "tasks" / "quill.toml").write_text("[quill]\nid = 'tasks'\n")
    registry.reload()
    assert registry.quills == {} and "tasks" in registry.broken


def test_github_releases_are_fetched_as_tarballs():
    assert tarball_url("https://github.com/Cloudmorrow/quill-tasks", "v1.0.0") == (
        "https://codeload.github.com/Cloudmorrow/quill-tasks/tar.gz/v1.0.0"
    )
    with pytest.raises(QuillError):
        tarball_url("https://example.com/somewhere", "v1")


# -- the API ---------------------------------------------------------------------------
def test_an_administrator_installs_from_the_catalog_and_the_tabs_follow(client, auth):
    catalog = client.get("/api/quills/catalog", headers=auth).json()
    assert catalog["quills"][0]["installed_version"] is None
    plan = client.post("/api/quills/plan", headers=auth, json={"id": "tasks"}).json()
    assert [row["id"] for row in plan["data"]] == ["board", "task"]
    assert all(row["new"] for row in plan["data"])
    assert client.get("/api/quills", headers=auth).json() == []
    installed = client.post("/api/quills", headers=auth, json={"id": "tasks"})
    assert installed.status_code == 201, installed.text
    quills = client.get("/api/quills", headers=auth).json()
    assert [(q["id"], q["enabled"]) for q in quills] == [("tasks", True)]
    assert set(quills[0]["models"]) == {"board", "task"}
    assert (
        client.get("/api/quills/catalog", headers=auth).json()["quills"][0]["installed_version"]
        == "1.1.0"
    )
    # A Quill is one more feature to switch.
    mine = {row["key"] for row in client.get("/api/me/features", headers=auth).json()}
    assert "tasks" in mine
    assert client.delete("/api/quills/tasks", headers=auth).status_code == 204
    assert client.get("/api/quills", headers=auth).json() == []


def test_only_an_administrator_installs(client):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.post("/api/quills", headers=guest, json={"id": "tasks"}).status_code == 403
    assert client.post("/api/quills/plan", headers=guest, json={"id": "tasks"}).status_code == 403
    assert client.get("/api/quills/catalog", headers=guest).status_code == 200


def test_a_bad_request_is_a_400_with_the_reason(client, auth):
    both = client.post("/api/quills", headers=auth, json={"id": "tasks", "source": "/tmp"})
    assert both.status_code == 400
    unknown = client.post("/api/quills", headers=auth, json={"id": "nope"})
    assert unknown.status_code == 400 and "not in the catalog" in unknown.json()["detail"]


# -- boot ------------------------------------------------------------------------------
def test_a_fresh_server_gets_the_foundation_quills_once(config, users, registry, tmp_path):
    db = config.db_path
    assert install_foundation(db, registry) == ["tasks"]
    registry.uninstall("tasks")
    # Removed by an administrator, it stays removed.
    assert install_foundation(db, registry) == []
    assert registry.quills == {}


def test_boards_and_tasks_from_before_move_into_records(config, users, registry):
    db = config.db_path
    yesterday = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1)).isoformat(timespec="seconds")
    with connect(db) as conn:
        seal = conn.seal
        conn.execute(
            "INSERT INTO boards (owner, slug, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                "bram",
                "home",
                seal("boards", "title", ("bram",), "Home"),
                "2026-09-01T10:00:00+00:00",
                "2026-09-01T10:00:00+00:00",
            ),
        )
        for title, lane, done_at in [("Fix the NAS", "doing", None), ("Buy bulbs", "done", yesterday)]:
            conn.execute(
                "INSERT INTO tasks (owner, board, title, body, lane, position, created_at, updated_at, done_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "bram",
                    "home",
                    seal("tasks", "title", ("bram",), title),
                    seal("tasks", "body", ("bram",), "- [ ] one"),
                    lane,
                    0,
                    "2026-09-02T10:00:00+00:00",
                    "2026-09-02T10:00:00+00:00",
                    done_at,
                ),
            )
    conn.close()
    store = RecordStore(db, registry.models, registry.expiries)
    # Not even installed yet: moving them installs Tasks first.
    boot(db, registry, store)
    assert "tasks" in registry.quills
    bram = Principal.person("bram")
    boards = store.list(bram, "board")
    assert [b.fields["title"] for b in boards] == ["Home"]
    tasks = sorted(
        store.list(bram, "task", {"board": boards[0].id}), key=lambda t: t.fields["title"]
    )
    assert [(t.fields["title"], t.fields["lane"], t.fields["body"]) for t in tasks] == [
        ("Buy bulbs", "done", "- [ ] one"),
        ("Fix the NAS", "doing", "- [ ] one"),
    ]
    assert tasks[0].fields["done_at"] == yesterday
    assert tasks[0].created_at == "2026-09-02T10:00:00+00:00"
    # Once.
    assert move_legacy_tasks(db, registry, store) == 0
    assert len(store.list(bram, "task")) == 2
