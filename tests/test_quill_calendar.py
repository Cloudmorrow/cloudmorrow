"""Calendar, as a Quill: the record API, the kit's `calendar`, and the move from the old tables.

What the built-in calendar promised, kept: everybody has one of their own
named after them, there is one everybody sees, shared ones are for the
people in them, times are the wall clock, whole days are dates, and one
call asks for everything overlapping a window of days across every
calendar you can see.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cloudmorrow.cli import quillrun
from cloudmorrow.server import standard
from cloudmorrow.server.db import connect
from cloudmorrow.server.quilljobs import (
    LEGACY_CALENDAR,
    boot,
    move_legacy_calendar,
    read_meta,
)
from cloudmorrow.server.quills import QuillError, QuillRegistry
from cloudmorrow.server.records import Principal, RecordStore
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for

WEEK = {"starts_at__lte": "2026-10-07T23:59", "ends_at__gte": "2026-10-01"}


@pytest.fixture()
def cal(client):
    """The Calendar Quill from the local catalog, and a way to call it as bram or guest."""
    client.app.state.cloudmorrow.quills.install_from_catalog("calendar")
    bram = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}

    def call(method, path, body=None, *, who=bram, expect=200, params=None):
        response = client.request(method, path, json=body, headers=who, params=params)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.bram, call.guest, call.client = bram, guest, client
    return call


def mine(cal, who=None) -> dict:
    return next(c for c in cal("GET", "/api/records/calendar", who=who or cal.bram) if c["scope"] == "personal")


def event(cal, calendar: str, title: str, starts: str, ends: str | None = None, **more) -> dict:
    who = more.pop("who", cal.bram)
    fields = {"calendar": calendar, "title": title, "starts_at": starts, **more}
    if ends is not None:
        fields["ends_at"] = ends
    return cal("POST", "/api/records/event", {"fields": fields}, who=who, expect=201)


# -- what the Quill seeds ----------------------------------------------------------
def test_everybody_has_their_own_named_after_them_and_one_for_everybody(cal):
    bram = cal("GET", "/api/records/calendar")
    assert sorted((c["scope"], c["fields"]["name"]) for c in bram) == [
        ("personal", "bram"), ("public", "Everybody")]
    guest = cal("GET", "/api/records/calendar", who=cal.guest)
    assert sorted(c["fields"]["name"] for c in guest) == ["Everybody", "guest"]
    # Each sees their own and nobody else's.
    assert mine(cal)["id"] not in {c["id"] for c in guest}
    # Asking again makes nothing more.
    assert len(cal("GET", "/api/records/calendar")) == 2
    # And each has a colour of the five, by name.
    assert {c["fields"]["colour"] for c in bram} <= {"cyan", "violet", "green", "amber", "rose"}


def test_the_quill_is_a_standard_one_from_the_catalog_not_a_built_in(config):
    options, _catalog, problem = standard.choices(config)
    assert problem == ""
    kinds = {c.id: c.kind for c in options}
    assert kinds["calendar"] == "quill"


# -- the wall clock ------------------------------------------------------------------
def test_a_time_is_the_wall_clock_and_a_whole_day_is_a_date(cal):
    home = mine(cal)["id"]
    timed = event(cal, home, "Dentist", "2026-10-01T10:00", "2026-10-01T11:00")
    assert (timed["fields"]["starts_at"], timed["fields"]["ends_at"]) == ("2026-10-01T10:00", "2026-10-01T11:00")
    whole = event(cal, home, "Holiday", "2026-10-12", "2026-10-16", all_day=True)
    assert (whole["fields"]["starts_at"], whole["fields"]["ends_at"]) == ("2026-10-12", "2026-10-16")
    # A zone, when one is sent, is kept: that is a moment, not a wall clock.
    zoned = event(cal, home, "Call", "2026-10-01T10:00:00+02:00")
    assert zoned["fields"]["starts_at"] == "2026-10-01T10:00:00+02:00"
    cal("POST", "/api/records/event", {"fields": {"calendar": home, "title": "x", "starts_at": "soon"}},
        expect=400)


# -- one call for a window of days -------------------------------------------------------
def test_the_window_is_everything_that_overlaps_it_across_every_calendar(cal):
    home = mine(cal)["id"]
    everybody = next(c for c in cal("GET", "/api/records/calendar") if c["scope"] == "public")["id"]
    event(cal, home, "Before", "2026-09-29T10:00", "2026-09-29T11:00")
    event(cal, home, "Runs in", "2026-09-30", "2026-10-02", all_day=True)
    event(cal, everybody, "Inside", "2026-10-03T09:00", "2026-10-03T10:00", who=cal.guest)
    event(cal, home, "Late on the last day", "2026-10-07T23:30", "2026-10-08T00:30")
    event(cal, home, "After", "2026-10-08", "2026-10-08", all_day=True)
    found = cal("GET", "/api/records/event", params=WEEK)
    assert sorted(e["fields"]["title"] for e in found) == ["Inside", "Late on the last day", "Runs in"]


def test_a_range_is_on_indexed_fields_only_and_says_so(cal):
    cal("GET", "/api/records/event", params={"title__gte": "a"}, expect=400)
    cal("GET", "/api/records/event", params={"starts_at__gte": "not a date"}, expect=400)
    # A suffix that is not a range is a field name, and there is no such field.
    cal("GET", "/api/records/event", params={"starts_at__near": "2026-10-01"}, expect=400)


def test_a_range_works_for_any_indexed_field_of_any_datamodel(tasks_quill, auth):
    board = tasks_quill.get("/api/records/board", headers=auth).json()[0]["id"]
    for title, due in (("early", "2026-10-01"), ("late", "2026-10-20"), ("none", None)):
        tasks_quill.post("/api/records/task", json={"fields": {"board": board, "title": title, "due": due}},
                         headers=auth)
    found = tasks_quill.get("/api/records/task", params={"due__lt": "2026-10-10"}, headers=auth).json()
    assert [t["fields"]["title"] for t in found] == ["early"]


# -- the calendars themselves --------------------------------------------------------------
def test_a_shared_calendar_is_its_peoples_and_they_are_told(cal):
    house = cal("POST", "/api/records/calendar", {"fields": {"name": "House", "colour": "green"},
                                                  "scope": "shared"}, expect=201)
    plumber = event(cal, house["id"], "Plumber", "2026-10-02T08:00", "2026-10-02T09:00")
    assert cal("GET", "/api/records/event", who=cal.guest, params=WEEK) == []
    cal("POST", f"/api/records/calendar/{house['id']}/members", {"username": "guest"})
    bell = cal("GET", "/api/notifications", who=cal.guest)
    assert any("bram added you to the calendar House" in n["title"] for n in bell)
    theirs = cal("GET", "/api/records/event", who=cal.guest, params=WEEK)
    assert [e["id"] for e in theirs] == [plumber["id"]]
    # In it, they write in it; its name and colour are its maker's, and so
    # is what somebody else wrote in it.
    event(cal, house["id"], "Boiler", "2026-10-03T08:00", "2026-10-03T09:00", who=cal.guest)
    cal("PATCH", f"/api/records/event/{plumber['id']}", {"fields": {"title": "x"}}, who=cal.guest,
        expect=403)
    cal("PATCH", f"/api/records/calendar/{house['id']}", {"fields": {"colour": "rose"}}, who=cal.guest,
        expect=403)
    cal("PATCH", f"/api/records/calendar/{house['id']}", {"fields": {"colour": "rose"}})
    # Its maker cannot leave it; the others can, and it is gone for them.
    cal("DELETE", f"/api/records/calendar/{house['id']}/members/bram", expect=400)
    cal("DELETE", f"/api/records/calendar/{house['id']}/members/guest", who=cal.guest, expect=204)
    assert cal("GET", "/api/records/event", who=cal.guest, params=WEEK) == []


def test_an_event_moves_to_another_calendar_and_a_deleted_calendar_takes_its_events(cal):
    house = cal("POST", "/api/records/calendar", {"fields": {"name": "House"}, "scope": "shared"},
                expect=201)
    dentist = event(cal, mine(cal)["id"], "Dentist", "2026-10-01T10:00", "2026-10-01T11:00",
                    location="town", notes="bring the card")
    moved = cal("PATCH", f"/api/records/event/{dentist['id']}", {"fields": {"calendar": house["id"]}})
    assert moved["fields"]["calendar"] == house["id"]
    assert (moved["fields"]["location"], moved["fields"]["notes"]) == ("town", "bring the card")
    cal("DELETE", f"/api/records/calendar/{house['id']}", expect=204)
    cal("GET", f"/api/records/event/{dentist['id']}", expect=404)


def test_an_event_is_its_writers_or_its_calendars_makers_to_change(cal):
    """Everybody in a shared calendar writes in it; only the writer, or whoever
    manages the calendar, changes or deletes what somebody wrote."""
    house = cal("POST", "/api/records/calendar", {"fields": {"name": "House"}, "scope": "shared"},
                expect=201)
    cal("POST", f"/api/records/calendar/{house['id']}/members", {"username": "guest"})
    mine = event(cal, house["id"], "Mine", "2026-10-01T10:00", "2026-10-01T11:00")
    theirs = event(cal, house["id"], "Theirs", "2026-10-02T10:00", "2026-10-02T11:00", who=cal.guest)
    # The guest cannot change bram's; bram made the calendar, so may change the guest's.
    cal("PATCH", f"/api/records/event/{mine['id']}", {"fields": {"title": "x"}}, who=cal.guest,
        expect=403)
    cal("DELETE", f"/api/records/event/{mine['id']}", who=cal.guest, expect=403)
    cal("PATCH", f"/api/records/event/{theirs['id']}", {"fields": {"title": "Theirs, moved"}})
    cal("PATCH", f"/api/records/event/{theirs['id']}", {"fields": {"title": "Back"}}, who=cal.guest)
    cal("DELETE", f"/api/records/event/{theirs['id']}", expect=204)


def test_authored_is_true_false_or_or_manager_and_or_manager_is_in_a_space():
    from cloudmorrow.server.datamodels import DatamodelError, parse_datamodel

    def model(authored, in_space=True):
        head = {"id": "thing", "authored": authored}
        fields = {"name": {"kind": "string"}}
        if in_space:
            head["in_space"] = "room"
            fields["room"] = {"kind": "link", "to": "room"}
        return parse_datamodel({"datamodel": head, "fields": fields})

    assert model("or-manager").authored == "or-manager"
    assert model(True).authored is True
    for bad, in_space in (("sometimes", True), (1, True), ("or-manager", False)):
        with pytest.raises(DatamodelError, match="authored"):
            model(bad, in_space)


def test_nobody_puts_a_thing_in_a_calendar_they_cannot_see(cal):
    theirs = mine(cal, cal.guest)["id"]
    cal("POST", "/api/records/event", {"fields": {"calendar": theirs, "title": "x",
                                                  "starts_at": "2026-10-01T10:00"}}, expect=400)


def test_the_people_a_space_could_be_shared_with(cal):
    people = cal("GET", "/api/people")
    assert [p["username"] for p in people] == ["guest"]


# -- the kit's bindings ----------------------------------------------------------------------
CALENDAR_SCREEN = """
[quill]
id = "diary"
name = "Diary"
version = "0.1.0"
[uses]
datamodels = ["calendar", "event"]
[[screens]]
id = "days"
kit = "calendar"
model = "event"
space = "calendar"
starts = "starts_at"
ends = "ends_at"
"""


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda m: m, None),
        (lambda m: m.replace('ends = "ends_at"', 'ends = "location"'), "wants datetime or date"),
        (lambda m: m.replace('starts = "starts_at"\n', ""), "starts names None"),
        (lambda m: m.replace('space = "calendar"', 'space = "title"'), "wants link"),
        (lambda m: m + 'all_day = "title"\n', "wants bool"),
        (lambda m: m + 'colour = "nothing"\n', "calendar does not have"),
    ],
)
def test_a_calendar_screen_binds_two_moments_and_a_space(tmp_path, change, says):
    folder = tmp_path / "diary"
    folder.mkdir()
    (folder / "quill.toml").write_text(change(CALENDAR_SCREEN))
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    if says is None:
        assert registry.plan(folder, QUILL_CATALOG / "datamodels")["screens"][0]["kit"] == "calendar"
    else:
        with pytest.raises(QuillError, match=says):
            registry.plan(folder, QUILL_CATALOG / "datamodels")


# -- `cm calendar` ------------------------------------------------------------------------------
class FakeApi:
    """The record calls `cm <quill>` makes, answered from a list."""

    def __init__(self, quill: dict) -> None:
        self.quill = quill
        self.made: list[dict] = []
        self.asked: list[tuple[str, dict]] = []
        self.rows = {
            "calendar": [
                {"id": "r_mine", "scope": "personal", "fields": {"name": "bram", "colour": "cyan"}},
                {"id": "r_house", "scope": "shared", "fields": {"name": "House", "colour": "green"}},
            ],
            "event": [],
        }

    async def records(self, model: str, **where) -> list[dict]:
        self.asked.append((model, where))
        return list(self.rows[model])

    async def create_record(self, model: str, fields: dict, *, index=None) -> dict:
        self.made.append(fields)
        return {"id": "r_made00", "fields": fields}


@pytest.fixture()
def cli_screen(cal):
    quill = next(q for q in cal("GET", "/api/quills") if q["id"] == "calendar")
    return quillrun.Screen(quill, quill["screens"][0])


def test_cm_calendar_lists_a_window_and_adds_with_its_moments(cli_screen):
    api = FakeApi(cli_screen.quill)
    asyncio.run(quillrun._act(api, cli_screen, "list", [], "", None, True, ("2026-10-01", "2026-10-31")))
    assert ("event", {"starts_at__lte": "2026-10-31T23:59", "ends_at__gte": "2026-10-01"}) in api.asked
    asyncio.run(quillrun._act(api, cli_screen, "add", ["Dentist", "starts=2026-10-01T10:00"], "", None,
                              False))
    assert api.made[-1] == {"title": "Dentist", "starts_at": "2026-10-01T10:00",
                            "ends_at": "2026-10-01T11:00", "all_day": False, "calendar": "r_mine"}
    asyncio.run(quillrun._act(api, cli_screen, "add", ["Holiday", "starts_at=2026-10-12",
                                                       "ends_at=2026-10-16", "calendar=House"], "", None,
                              False))
    assert api.made[-1] == {"title": "Holiday", "starts_at": "2026-10-12", "ends_at": "2026-10-16",
                            "all_day": True, "calendar": "r_house"}


# -- from the old tables ------------------------------------------------------------------------
OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS calendars (
    id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'shared', colour TEXT NOT NULL DEFAULT 'cyan',
    owner TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calendar_members (
    calendar_id INTEGER NOT NULL, username TEXT NOT NULL, added_by TEXT NOT NULL DEFAULT '',
    joined_at TEXT NOT NULL, PRIMARY KEY (calendar_id, username));
CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, calendar_id INTEGER NOT NULL, title TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '', starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""
THEN = "2026-09-01T10:00:00+00:00"


def old_calendar(conn, slug, name, kind, colour, owner, members) -> int:
    cursor = conn.execute(
        "INSERT INTO calendars (slug, name, kind, colour, owner, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)", (slug, name, kind, colour, owner, THEN, THEN))
    for who in members:
        conn.execute("INSERT INTO calendar_members (calendar_id, username, joined_at) VALUES (?, ?, ?)",
                     (cursor.lastrowid, who, THEN))
    return int(cursor.lastrowid)


def old_event(conn, calendar_id, title, starts, ends, *, all_day=False, by="bram", notes="", where=""):
    seal = conn.seal
    conn.execute(
        "INSERT INTO calendar_events (calendar_id, title, notes, location, starts_at, ends_at, all_day,"
        " created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (calendar_id, seal("calendar_events", "title", (calendar_id,), title),
         seal("calendar_events", "notes", (calendar_id,), notes),
         seal("calendar_events", "location", (calendar_id,), where),
         starts, ends, int(all_day), by, THEN, "2026-09-02T10:00:00+00:00"))


@pytest.fixture()
def registry(config) -> QuillRegistry:
    return QuillRegistry(config.quills_dir, config.datamodels_dir, str(QUILL_CATALOG))


@pytest.fixture()
def records(config, registry) -> RecordStore:
    return RecordStore(config.db_path, registry.models, registry.expiries)


@pytest.fixture()
def old(config, users):
    """A database the built-in calendar wrote: three calendars, their people, their events."""
    with connect(config.db_path) as conn:
        conn.executescript(OLD_SCHEMA)
        mine_id = old_calendar(conn, "my-bram", "Jimmi", "personal", "cyan", "bram", ["bram"])
        house = old_calendar(conn, "house", "House", "shared", "green", "bram", ["bram", "guest"])
        everybody = old_calendar(conn, "holidays", "Holidays", "public", "violet", "guest",
                                 ["bram", "guest"])
        old_event(conn, mine_id, "Dentist", "2026-10-01T10:00", "2026-10-01T11:00",
                  notes="bring the card", where="town")
        old_event(conn, house, "Plumber", "2026-10-02T08:00", "2026-10-02T09:00", by="guest")
        old_event(conn, everybody, "Autumn break", "2026-10-12", "2026-10-16", all_day=True)
    conn.close()
    return config


def test_the_old_calendars_move_into_records_once(old, registry, records):
    db = old.db_path
    assert move_legacy_calendar(db, registry, records) == 6
    assert "calendar" in registry.quills   # installed for them, from the catalog
    assert move_legacy_calendar(db, registry, records) == 0
    assert read_meta(db, LEGACY_CALENDAR) == "6"

    bram, guest = Principal.person("bram"), Principal.person("guest")
    calendars = {c.fields["name"]: c for c in records.list(bram, "calendar")}
    assert set(calendars) == {"Jimmi", "House", "Holidays"}
    assert calendars["Jimmi"].scope == "personal" and calendars["Jimmi"].members == []
    assert calendars["House"].scope == "shared" and calendars["House"].members == ["guest"]
    assert calendars["Holidays"].scope == "public" and calendars["Holidays"].owner == "guest"
    assert calendars["House"].fields["colour"] == "green"
    assert calendars["House"].created_at == THEN

    events = {e.fields["title"]: e for e in records.list(bram, "event")}
    dentist = events["Dentist"]
    assert (dentist.fields["starts_at"], dentist.fields["ends_at"]) == ("2026-10-01T10:00", "2026-10-01T11:00")
    assert (dentist.fields["notes"], dentist.fields["location"]) == ("bring the card", "town")
    assert dentist.fields["calendar"] == calendars["Jimmi"].id
    assert events["Plumber"].owner == "guest"
    whole = events["Autumn break"]
    assert (whole.fields["starts_at"], whole.fields["ends_at"], whole.fields["all_day"]) == (
        "2026-10-12", "2026-10-16", True)
    # Who sees what is as it was: the guest has the shared one and everybody's, not bram's own.
    assert {e.fields["title"] for e in records.list(guest, "event")} == {"Plumber", "Autumn break"}
    # And listing makes no second calendar of anybody's own, nor a second one for everybody.
    assert records.seed(bram, "calendar", [{"name": "bram"}], "calendar", scope="personal") == []
    assert records.seed(bram, "calendar", [{"name": "x"}], "calendar", once=True, scope="public") == []


def test_a_server_that_never_had_the_old_calendar_moves_nothing(config, users, registry, records):
    assert move_legacy_calendar(config.db_path, registry, records) == 0
    assert "calendar" not in registry.quills


def test_a_calendar_switched_off_and_empty_is_not_installed(config, users, registry, records):
    with connect(config.db_path) as conn:
        conn.executescript(OLD_SCHEMA)
        conn.execute("CREATE TABLE IF NOT EXISTS features (key TEXT PRIMARY KEY, enabled INTEGER,"
                     " changed_by TEXT, updated_at TEXT)")
        conn.execute("INSERT OR REPLACE INTO features VALUES ('calendar', 0, 'bram', ?)", (THEN,))
    conn.close()
    assert move_legacy_calendar(config.db_path, registry, records) == 0
    assert "calendar" not in registry.quills


def test_boot_installs_it_for_a_server_that_had_the_calendar_on(config, users, registry, records):
    with connect(config.db_path) as conn:
        conn.executescript(OLD_SCHEMA)
        # Tasks was installed already, so the foundation step stands aside.
        conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('quills_seeded', 'tasks')")
    conn.close()
    boot(config.db_path, registry, records)
    assert "calendar" in registry.quills


def test_the_old_code_is_gone():
    root = Path(__file__).parent.parent / "src" / "cloudmorrow"
    for gone in ("server/calendar.py", "server/routes/calendar.py", "server/web/calendar.js",
                 "server/web/calendar.css", "tui/panes/calendar.py"):
        assert not (root / gone).exists(), gone
    from cloudmorrow.server.features import FEATURE_KEYS

    assert "calendar" not in FEATURE_KEYS
