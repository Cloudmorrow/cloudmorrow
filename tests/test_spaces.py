"""Spaces: calendars and channels that more than one person is in, and what is in them."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cloudmorrow.server.crypto import SealError
from cloudmorrow.server.records import Principal
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for

CAL = """
[quill]
id = "cal"
name = "Cal"
version = "0.1.0"
[uses]
datamodels = ["calendar", "event"]
[[screens]]
id = "days"
kit = "list"
model = "event"
title = "title"
[[datasets]]
id = "mine"
model = "calendar"
seed = "per-owner"
scope = "personal"
records = [{ name = "{owner}" }]
[[datasets]]
id = "everybody"
model = "calendar"
seed = "once"
scope = "public"
records = [{ name = "Everybody" }]
"""

CHAT = """
[quill]
id = "talk"
name = "Talk"
version = "0.1.0"
[uses]
datamodels = ["channel", "message"]
[[screens]]
id = "channels"
kit = "list"
model = "channel"
title = "name"
"""


def install(client, text: str, tmp_path: Path, name: str) -> None:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "quill.toml").write_text(text)
    client.app.state.cloudmorrow.quills.install(folder, QUILL_CATALOG / "datamodels")


@pytest.fixture()
def spaces(client, tmp_path):
    install(client, CAL, tmp_path, "cal")
    install(client, CHAT, tmp_path, "talk")
    bram = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}

    def call(method, path, body=None, *, who=bram, expect=200):
        response = client.request(method, path, json=body, headers=who)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.bram, call.guest, call.client = bram, guest, client
    return call


def titles(records, field="name"):
    return sorted(r["fields"][field] for r in records)


def test_everybody_gets_their_own_calendar_and_the_public_one(spaces):
    mine = spaces("GET", "/api/records/calendar")
    assert titles(mine) == ["Everybody", "bram"]
    theirs = spaces("GET", "/api/records/calendar", who=spaces.guest)
    assert titles(theirs) == ["Everybody", "guest"]
    public = next(c for c in theirs if c["scope"] == "public")
    # The public one was seeded once, by whoever came first, and is one calendar.
    assert public["id"] == next(c for c in mine if c["scope"] == "public")["id"]


def test_a_shared_calendar_is_its_members_and_nobody_elses(spaces):
    house = spaces("POST", "/api/records/calendar", {"fields": {"name": "House"}}, expect=201)
    assert house["scope"] == "shared" and house["members"] == [] and house["can_manage"]
    event = spaces("POST", "/api/records/event", {"fields": {
        "calendar": house["id"], "title": "Plumber", "starts_at": "2026-10-01T10:00"}}, expect=201)
    # Not in it: the guest cannot see the calendar, the event, or put anything in it.
    assert "House" not in titles(spaces("GET", "/api/records/calendar", who=spaces.guest))
    spaces("GET", f"/api/records/event/{event['id']}", who=spaces.guest, expect=404)
    spaces("POST", "/api/records/event", {"fields": {
        "calendar": house["id"], "title": "x", "starts_at": "2026-10-01T10:00"}}, who=spaces.guest, expect=400)
    # Added: they see it, and may write in it, but not manage it.
    added = spaces("POST", f"/api/records/calendar/{house['id']}/members", {"username": "guest"})
    assert added["members"] == ["guest"]
    seen = spaces("GET", "/api/records/calendar", who=spaces.guest)
    shared = next(c for c in seen if c["fields"]["name"] == "House")
    assert shared["can_manage"] is False
    assert [e["fields"]["title"] for e in spaces("GET", "/api/records/event", who=spaces.guest)] == ["Plumber"]
    # What somebody else wrote is theirs, or the calendar's maker's, to change.
    spaces("PATCH", f"/api/records/event/{event['id']}", {"fields": {"title": "Plumber at 10"}}, who=spaces.guest,
           expect=403)
    spaces("PATCH", f"/api/records/calendar/{house['id']}", {"fields": {"name": "Mine now"}}, who=spaces.guest, expect=403)
    # Leaving: and it is gone again.
    spaces("DELETE", f"/api/records/calendar/{house['id']}/members/guest", who=spaces.guest, expect=204)
    spaces("GET", f"/api/records/event/{event['id']}", who=spaces.guest, expect=404)


def test_a_personal_calendar_cannot_be_shared_and_nobody_leaves_a_public_one(spaces):
    mine = next(c for c in spaces("GET", "/api/records/calendar") if c["scope"] == "personal")
    spaces("POST", f"/api/records/calendar/{mine['id']}/members", {"username": "guest"}, expect=400)
    public = next(c for c in spaces("GET", "/api/records/calendar") if c["scope"] == "public")
    spaces("DELETE", f"/api/records/calendar/{public['id']}/members/bram", expect=400)
    spaces("POST", f"/api/records/calendar/{public['id']}/members", {"username": "nobody"}, expect=404)


def test_everybody_writes_in_a_public_space_and_its_owner_and_admins_manage_it(spaces):
    public = spaces("POST", "/api/records/channel", {"fields": {"name": "general"}, "scope": "public"}, expect=201)
    said = spaces("POST", "/api/records/message", {"fields": {"channel": public["id"], "body": "hello"}},
                  who=spaces.guest, expect=201)
    # A message is its author's to change.
    spaces("PATCH", f"/api/records/message/{said['id']}", {"fields": {"body": "edited"}}, expect=403)
    spaces("DELETE", f"/api/records/message/{said['id']}", expect=403)
    spaces("PATCH", f"/api/records/message/{said['id']}", {"fields": {"body": "hi"}}, who=spaces.guest)
    # And the channel its maker's: the guest may not rename it.
    spaces("PATCH", f"/api/records/channel/{public['id']}", {"fields": {"name": "mine"}}, who=spaces.guest, expect=403)


def test_a_message_is_unread_until_looked_at_and_its_members_are_told(spaces):
    told = []
    spaces.client.app.state.cloudmorrow.records.on_notify.append(
        lambda record, rule, people: told.append((record.fields["body"], rule["push"], people)))
    room = spaces("POST", "/api/records/channel", {"fields": {"name": "house"}}, expect=201)
    spaces("POST", f"/api/records/channel/{room['id']}/members", {"username": "guest"})
    spaces("POST", "/api/records/message", {"fields": {"channel": room["id"], "body": "dinner?"}}, expect=201)
    assert told == [("dinner?", True, ["guest"])]
    theirs = next(c for c in spaces("GET", "/api/records/channel", who=spaces.guest) if c["id"] == room["id"])
    assert theirs["unread"] == 1
    # Your own words are never unread to you.
    assert next(c for c in spaces("GET", "/api/records/channel") if c["id"] == room["id"])["unread"] == 0
    spaces("POST", f"/api/records/channel/{room['id']}/seen", who=spaces.guest, expect=204)
    theirs = next(c for c in spaces("GET", "/api/records/channel", who=spaces.guest) if c["id"] == room["id"])
    assert theirs["unread"] == 0


def test_deleting_a_space_takes_everybodys_things_in_it(spaces):
    room = spaces("POST", "/api/records/channel", {"fields": {"name": "tmp"}, "scope": "public"}, expect=201)
    spaces("POST", "/api/records/message", {"fields": {"channel": room["id"], "body": "a"}}, who=spaces.guest, expect=201)
    spaces("DELETE", f"/api/records/channel/{room['id']}", expect=204)
    assert spaces("GET", "/api/records/message", who=spaces.guest) == []


def test_a_message_is_sealed_to_its_channel(spaces, config):
    room = spaces("POST", "/api/records/channel", {"fields": {"name": "a"}, "scope": "public"}, expect=201)
    other = spaces("POST", "/api/records/channel", {"fields": {"name": "b"}, "scope": "public"}, expect=201)
    said = spaces("POST", "/api/records/message", {"fields": {"channel": room["id"], "body": "secret"}}, expect=201)
    with sqlite3.connect(config.db_path) as conn:
        conn.execute(
            "UPDATE records SET indexed = json_set(indexed, '$.channel', ?) WHERE id = ?",
            (other["id"], said["id"]),
        )
    store = spaces.client.app.state.cloudmorrow.records
    with pytest.raises(SealError):
        store.get(Principal.person("bram"), "message", said["id"])


def test_a_space_that_is_not_a_space_has_no_scope_to_choose(spaces):
    spaces("POST", "/api/records/event", {"fields": {"calendar": "x", "title": "t", "starts_at": "2026-10-01"},
                                          "scope": "public"}, expect=400)


def test_being_added_leaves_a_line_behind_the_bell(spaces):
    house = spaces("POST", "/api/records/calendar", {"fields": {"name": "House"}}, expect=201)
    spaces("POST", f"/api/records/calendar/{house['id']}/members", {"username": "guest"})
    bell = spaces("GET", "/api/notifications", who=spaces.guest)
    assert any("bram added you to the calendar House" in n["title"] for n in bell)
