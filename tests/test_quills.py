"""Quills: the catalog, the install sheet, installing, removing, and the move from the old tasks."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from cloudmorrow.server.database import connect
from cloudmorrow.server.quills import QuillError, QuillRegistry, load_catalog, tarball_url
from cloudmorrow.server.quills.jobs import boot, install_foundation, move_legacy_tasks
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
    assert [c["id"] for c in catalog.categories] == ["personal", "home", "business", "developer"]
    assert catalog.entry("tasks")["foundation"] is True
    with pytest.raises(QuillError):
        catalog.entry("nope")


def test_the_quills_are_shelved_by_the_catalogs_categories(registry, tmp_path):
    """A client's rail stands each Quill's tabs on the shelf of its category:
    the server says the catalog's label for it and the order of the shelves,
    from the last time it read the catalog, so no client has to."""
    # Nothing read yet: a category's own name, and every shelf alike.
    assert registry.shelf("personal") == ("Personal", 0)
    assert registry.shelf("home_office") == ("Home office", 0)
    assert registry.shelf("") == ("Other", 1)
    registry.install_from_catalog("crm")
    registry.install_from_catalog("tasks")
    told = {q["id"]: q for q in registry.installed()}
    assert (told["tasks"]["category_label"], told["tasks"]["category_rank"]) == ("Personal", 0)
    assert (told["crm"]["category_label"], told["crm"]["category_rank"]) == ("Business", 2)
    # One the catalog does not name comes after every shelf it does; Other last.
    assert registry.shelf("garden") == ("Garden", 4)
    assert registry.shelf("") == ("Other", 5)
    # Remembered beside the Quills: a server started again knows without the catalog.
    assert (tmp_path / "quill-categories.json").is_file()
    again = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", "")
    assert again.shelf("business") == ("Business", 2)


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
    assert data["contact"]["how"] == "asks for" and data["contact"]["why"] == "to show who drives each car"
    assert [s["label"] for s in plan["screens"]] == ["Cars", "Services"]
    assert plan["surfaces"] == ["phone", "web", "terminal", "command line", "assistant"]
    # What it would run on this server, and all it could reach there.
    assert plan["runs_code"] == ["python services/dvla.py"]
    assert plan["reach"] == ["contact", "fleet.visit", "vehicle"]
    # Planning installs nothing.
    assert registry.quills == {} and not (tmp_path / "datamodels").exists()


def test_installing_brings_the_datamodels_and_the_links_they_need(registry, tmp_path):
    folder = write_quill(tmp_path / "src", FLEET, visit=VISIT)
    registry.install(folder, models_source())
    assert set(registry.quills) == {"fleet"}
    # contact links to organisation, and both are kept in a book, so all three came.
    assert {p.stem for p in (tmp_path / "datamodels").glob("*.toml")} == {
        "vehicle",
        "contact",
        "organisation",
        "book",
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
            lambda m: m.replace('kit = "list"\nlabel = "Cars"', 'kit = "spreadsheet"\nlabel = "Cars"'),
            "kit is one of",
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
    entry = {q["id"]: q for q in catalog["quills"]}
    assert entry["tasks"]["installed_version"] is None
    plan = client.post("/api/quills/plan", headers=auth, json={"id": "tasks"}).json()
    assert [row["id"] for row in plan["data"]] == ["board", "task"]
    assert all(row["new"] for row in plan["data"])
    # Nothing installed: only Data, which the server composes for everybody (dataview.py).
    assert [q["id"] for q in client.get("/api/quills", headers=auth).json()] == ["data"]
    installed = client.post("/api/quills", headers=auth, json={"id": "tasks"})
    assert installed.status_code == 201, installed.text
    quills = client.get("/api/quills", headers=auth).json()
    assert [(q["id"], q["enabled"]) for q in quills] == [("tasks", True), ("data", True)]
    assert set(quills[0]["models"]) == {"board", "task"}
    # Its tabs stand on the shelf of its category, the first in the catalog.
    assert (quills[0]["category_label"], quills[0]["category_rank"]) == ("Personal", 0)
    after = {q["id"]: q for q in client.get("/api/quills/catalog", headers=auth).json()["quills"]}
    assert after["tasks"]["installed_version"] == "1.2.0"
    # The fixture catalog names no release, so there is no telling whether a
    # newer one is out: installing again is the update.
    assert after["tasks"]["installed_ref"] == "" and after["tasks"]["update_available"] is None
    # A Quill is one more feature to switch.
    mine = {row["key"] for row in client.get("/api/me/features", headers=auth).json()}
    assert "tasks" in mine
    assert client.delete("/api/quills/tasks", headers=auth).status_code == 200
    assert [q["id"] for q in client.get("/api/quills", headers=auth).json()] == ["data"]


def test_the_catalog_says_when_a_newer_release_is_out():
    """A Quill installed from the catalog at one release, with the catalog now
    naming another, has an update; at the same release it is up to date; and
    one from a source of its own, or an entry without a release, is neither."""
    from types import SimpleNamespace

    from cloudmorrow.server.routes.quills import _standing

    entry = {"id": "tasks", "repo": "quill-tasks", "ref": "v1.3.0"}
    at = lambda **origin: SimpleNamespace(version="1.2.0", origin=origin)  # noqa: E731
    assert _standing(entry, None) == {"installed_version": None, "installed_ref": None, "update_available": None}
    assert _standing(entry, at(catalog=True, ref="v1.2.0"))["update_available"] is True
    assert _standing(entry, at(catalog=True, ref="v1.3.0"))["update_available"] is False
    assert _standing(entry, at(catalog=False, repo="/somewhere", ref="main"))["update_available"] is None
    assert _standing({"id": "tasks", "repo": "quill-tasks"}, at(catalog=True, ref=""))["update_available"] is None
    assert _standing(entry, at(catalog=True, ref="v1.2.0"))["installed_ref"] == "v1.2.0"


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
    assert install_foundation(db, registry) == [
        "notes",
        "tasks",
        "files",
        "calendar",
        "chat",
        "secrets",
    ]
    for quill in ("notes", "tasks", "files", "calendar", "chat", "secrets"):
        registry.uninstall(quill)
    # Removed by an administrator, they stay removed.
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
    tasks = sorted(store.list(bram, "task", {"board": boards[0].id}), key=lambda t: t.fields["title"])
    assert [(t.fields["title"], t.fields["lane"], t.fields["body"]) for t in tasks] == [
        ("Buy bulbs", "done", "- [ ] one"),
        ("Fix the NAS", "doing", "- [ ] one"),
    ]
    assert tasks[0].fields["done_at"] == yesterday
    assert tasks[0].created_at == "2026-09-02T10:00:00+00:00"
    # Once.
    assert move_legacy_tasks(db, registry, store) == 0
    assert len(store.list(bram, "task")) == 2


def test_a_grids_deleted_names_a_datetime_and_deleted_from_a_string(registry, tmp_path):
    """The Files Quill's Trash bindings: checked like size and mime."""
    files = (QUILL_CATALOG / "quill-files" / "quill.toml").read_text(encoding="utf-8")
    assert 'deleted = "deleted"' in files and 'deleted_from = "deleted_from"' in files
    registry.plan(QUILL_CATALOG / "quill-files", QUILL_CATALOG / "datamodels")
    bad = write_quill(tmp_path / "bad", files.replace('deleted = "deleted"', 'deleted = "size"'))
    with pytest.raises(QuillError, match="deleted"):
        registry.plan(bad, QUILL_CATALOG / "datamodels")
    bad = write_quill(tmp_path / "bad2", files.replace('deleted_from = "deleted_from"', 'deleted_from = "size"'))
    with pytest.raises(QuillError, match="deleted_from"):
        registry.plan(bad, QUILL_CATALOG / "datamodels")


def test_a_grids_group_writes_names_a_bool_on_the_group(registry, tmp_path):
    """The Files Quill's `group_writes`: checked like `group_open`, against the share datamodel."""
    files = (QUILL_CATALOG / "quill-files" / "quill.toml").read_text(encoding="utf-8")
    assert 'group_writes = "writable"' in files
    good = write_quill(tmp_path / "good", files)
    assert registry.plan(good, models_source())
    bad = write_quill(tmp_path / "bad", files.replace('group_writes = "writable"', 'group_writes = "owner"'))
    with pytest.raises(QuillError, match="group_writes"):
        registry.plan(bad, models_source())


def test_a_list_of_projects_names_a_string_vault_and_needs_one_for_its_repo(registry, tmp_path):
    """`vault`, `repo` and `env_files` on a list (checkout.py): checked against the datamodel."""
    devlist = QUILL_CATALOG / "quill-devlist"
    manifest = (devlist / "quill.toml").read_text(encoding="utf-8")
    project = (devlist / "datamodels" / "project.toml").read_text(encoding="utf-8")
    assert registry.plan(devlist, QUILL_CATALOG / "datamodels")
    for change, says in (
        (('vault = "vault"', 'vault = "env_files"'), "vault"),
        (('repo = "repo"', 'repo = "env_files"'), "repo"),
        (('env_files = "env_files"', 'env_files = "name"'), "env_files"),
        (('vault = "vault"\n', ""), "needs the vault"),
    ):
        bad = write_quill(tmp_path / says.replace(" ", "-"), manifest.replace(*change), project=project)
        with pytest.raises(QuillError, match=says):
            registry.plan(bad, QUILL_CATALOG / "datamodels")
