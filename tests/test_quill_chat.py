"""Chat as a Quill: channels and messages through the record API, and the move.

What the old chat tests held (tests of `/api/chat`, gone with it) is held
here through the generic record API the kit and `cm chat` use: public
channels are everybody's and nobody leaves them, private ones are their
people's, a direct one is the same one from either side, a message is its
author's, unread counts and clears, the badge adds it up, a push opens the
right conversation — and the old tables move into records once, at boot.
"""

from __future__ import annotations

import sqlite3

import pytest

from cloudmorrow.server import spacenotify
from cloudmorrow.server.db import connect
from cloudmorrow.server.quilljobs import LEGACY_CHAT, boot, move_legacy_chat, read_meta
from cloudmorrow.server.quills import QuillError, QuillRegistry, load_manifest, parse_manifest
from cloudmorrow.server.records import Principal, RecordStore
from cloudmorrow.server.webpush import PushStore
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for


@pytest.fixture()
def chat(chat_quill):
    bram = {"Authorization": f"Bearer {token_for(chat_quill, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(chat_quill, *GUEST)}"}

    def call(method, path, body=None, *, who=bram, expect=200):
        response = chat_quill.request(method, path, json=body, headers=who)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.bram, call.guest, call.client = bram, guest, chat_quill
    return call


@pytest.fixture(autouse=True)
def pushes_at_once(monkeypatch):
    """A push goes on a thread in a server; here it goes before the call returns."""
    monkeypatch.setattr(spacenotify, "_later", lambda work: work())


def channel(chat, name: str, *, scope: str = "public", kind: str | None = None,
            members: list[str] | None = None, who=None) -> dict:
    kind = kind or {"public": "public", "shared": "private"}[scope]
    body = {"fields": {"name": name, "kind": kind}, "scope": scope, "members": members or []}
    return chat("POST", "/api/records/channel", body, who=who or chat.bram, expect=201)


def say(chat, space: dict, text: str, *, who=None) -> dict:
    return chat("POST", "/api/records/message", {"fields": {"channel": space["id"], "body": text}},
                who=who or chat.bram, expect=201)


def listed(chat, who=None) -> dict[str, dict]:
    return {c["fields"]["name"]: c for c in chat("GET", "/api/records/channel", who=who or chat.bram)}


# -- the Quill -------------------------------------------------------------------
def test_the_quill_is_a_thread_over_channel_and_message(chat_quill):
    manifest = load_manifest(QUILL_CATALOG / "quill-chat")
    assert manifest.uses == ("channel", "message")
    (screen,) = manifest.screens
    assert screen["kit"] == "thread" and screen["space"] == "channel" and screen["body"] == "body"
    assert screen["made_as"]["direct"] == {"kind": "direct"}
    quills = chat_quill.get("/api/quills", headers={
        "Authorization": f"Bearer {token_for(chat_quill, *GUEST)}"}).json()
    assert "chat" in [q["id"] for q in quills]


def test_a_thread_screen_is_checked_against_its_datamodels(chat_quill, tmp_path):
    registry = chat_quill.app.state.cloudmorrow.quills
    text = (QUILL_CATALOG / "quill-chat" / "quill.toml").read_text()
    for bad, said in [
        ('space = "channel"', 'space = "body"'),
        ('direct = { kind = "direct" }', 'direct = { kind = "sideways" }'),
        ('shared = { kind = "private" }', 'personal = { kind = "private" }'),
    ]:
        folder = tmp_path / said.split()[0] / str(abs(hash(said)))
        folder.mkdir(parents=True)
        (folder / "quill.toml").write_text(text.replace(bad, said).replace('id = "chat"', 'id = "chat2"'))
        with pytest.raises(QuillError):
            registry.plan(folder, QUILL_CATALOG / "datamodels")


def test_general_is_made_once_for_everybody(chat):
    mine = listed(chat)
    assert list(mine) == ["general"]
    general = mine["general"]
    assert general["scope"] == "public" and general["fields"]["kind"] == "public"
    theirs = listed(chat, chat.guest)
    assert theirs["general"]["id"] == general["id"]
    assert len(chat("GET", "/api/records/channel")) == 1


# -- the three kinds ---------------------------------------------------------------
def test_a_public_channel_is_everybodys_and_nobody_leaves_it(chat):
    room = channel(chat, "homelab")
    assert "homelab" in listed(chat, chat.guest)
    say(chat, room, "anyone about?", who=chat.guest)
    chat("DELETE", f"/api/records/channel/{room['id']}/members/guest", who=chat.guest, expect=400)
    chat("DELETE", f"/api/records/channel/{room['id']}/members/bram", expect=400)


def test_a_private_channel_is_made_with_its_people_who_are_told(chat):
    room = channel(chat, "club", scope="shared", members=["guest"])
    assert room["members"] == ["guest"] and room["fields"]["kind"] == "private"
    assert "club" in listed(chat, chat.guest)
    bell = chat("GET", "/api/notifications", who=chat.guest)
    assert any("bram added you to the channel club" in n["title"] for n in bell)
    # They may leave, and then it is gone for them.
    chat("DELETE", f"/api/records/channel/{room['id']}/members/guest", who=chat.guest, expect=204)
    assert "club" not in listed(chat, chat.guest)


def test_a_private_channel_is_only_its_people(chat):
    room = channel(chat, "secret", scope="shared")
    said = say(chat, room, "just me")
    assert "secret" not in listed(chat, chat.guest)
    chat("GET", f"/api/records/message/{said['id']}", who=chat.guest, expect=404)
    chat("POST", "/api/records/message", {"fields": {"channel": room["id"], "body": "let me in"}},
         who=chat.guest, expect=400)


def test_nobody_is_put_in_a_public_channel_by_name(chat):
    chat("POST", "/api/records/channel", {"fields": {"name": "x", "kind": "public"},
                                          "scope": "public", "members": ["guest"]}, expect=400)
    chat("POST", "/api/records/channel", {"fields": {"name": "x", "kind": "private"},
                                          "scope": "shared", "members": ["nobody"]}, expect=404)


def direct(chat, other: str, *, who=None, expect=201) -> dict:
    me = "bram" if (who or chat.bram) is chat.bram else "guest"
    return chat("POST", "/api/records/channel", {
        "fields": {"name": " & ".join(sorted({me, other})), "kind": "direct"},
        "scope": "shared", "members": [other], "unique": True,
    }, who=who or chat.bram, expect=expect)


def test_a_direct_channel_is_the_same_one_from_either_side(chat):
    made = direct(chat, "guest")
    assert made["members"] == ["guest"] and made["fields"]["kind"] == "direct"
    again = direct(chat, "guest", expect=200)
    theirs = direct(chat, "bram", who=chat.guest, expect=200)
    assert made["id"] == again["id"] == theirs["id"]
    assert len([c for c in chat("GET", "/api/records/channel") if c["fields"]["kind"] == "direct"]) == 1
    # Nobody is told they were "added" to a conversation; the first line tells them.
    assert chat("GET", "/api/notifications", who=chat.guest) == []


def test_a_private_channel_of_the_same_two_is_not_their_direct_one(chat):
    channel(chat, "pair", scope="shared", members=["guest"])
    made = direct(chat, "guest")
    assert made["fields"]["kind"] == "direct"


def test_there_is_no_direct_channel_with_nobody(chat):
    chat("POST", "/api/records/channel", {
        "fields": {"name": "x", "kind": "direct"}, "scope": "shared",
        "members": ["nobody"], "unique": True}, expect=404)


# -- messages ----------------------------------------------------------------------
def test_only_the_author_may_change_or_delete_what_was_said(chat):
    general = listed(chat)["general"]
    said = say(chat, general, "helo", who=chat.guest)
    chat("PATCH", f"/api/records/message/{said['id']}", {"fields": {"body": "x"}}, expect=403)
    chat("DELETE", f"/api/records/message/{said['id']}", expect=403)
    edited = chat("PATCH", f"/api/records/message/{said['id']}", {"fields": {"body": "hello"}},
                  who=chat.guest)
    assert edited["fields"]["body"] == "hello" and edited["rev"] == 2
    chat("DELETE", f"/api/records/message/{said['id']}", who=chat.guest, expect=204)


def test_an_empty_message_is_not_a_message(chat):
    general = listed(chat)["general"]
    chat("POST", "/api/records/message", {"fields": {"channel": general["id"], "body": ""}},
         expect=400)


def test_a_conversation_comes_back_in_order_and_its_newest_page_first(chat):
    general = listed(chat)["general"]
    for n in range(5):
        say(chat, general, f"line {n}")
    everything = chat("GET", f"/api/records/message?channel={general['id']}")
    assert [m["fields"]["body"] for m in everything] == [f"line {n}" for n in range(5)]
    newest = chat("GET", f"/api/records/message?channel={general['id']}&_last=2")
    assert [m["fields"]["body"] for m in newest] == ["line 3", "line 4"]
    since = chat("GET", f"/api/records/message?channel={general['id']}&_since={everything[-1]['updated_at']}")
    assert "line 4" in [m["fields"]["body"] for m in since]
    chat("GET", "/api/records/message?_last=lots", expect=400)


def test_the_topic_and_the_words_are_sealed(chat, config):
    room = chat("POST", "/api/records/channel", {"fields": {"name": "ops", "kind": "public",
                "topic": "the pager rota"}, "scope": "public"}, expect=201)
    say(chat, room, "who has the pager")
    with sqlite3.connect(config.db_path) as conn:
        rows = [r[0] + (r[1] or "") for r in conn.execute("SELECT indexed, body FROM records")]
    assert not any("pager" in row for row in rows)
    assert chat("GET", f"/api/records/channel/{room['id']}")["fields"]["topic"] == "the pager rota"


# -- unread, the badge and the push ------------------------------------------------------
def test_unread_counts_other_peoples_lines_until_looked_at(chat):
    general = listed(chat)["general"]
    say(chat, general, "one")
    say(chat, general, "two")
    assert listed(chat, chat.guest)["general"]["unread"] == 2
    assert listed(chat)["general"]["unread"] == 0, "your own words are never unread"
    last = listed(chat, chat.guest)["general"]["last"]
    assert last["owner"] == "bram" and last["title"] == "two"
    chat("POST", f"/api/records/channel/{general['id']}/seen", who=chat.guest, expect=204)
    assert listed(chat, chat.guest)["general"]["unread"] == 0


def test_writing_in_a_channel_reads_what_was_above_it(chat):
    general = listed(chat)["general"]
    say(chat, general, "question", who=chat.guest)
    assert listed(chat)["general"]["unread"] == 1
    say(chat, general, "answer")
    assert listed(chat)["general"]["unread"] == 0


def test_the_badge_counts_every_unread_line_plus_notifications(chat):
    general = listed(chat)["general"]
    say(chat, general, "one")
    say(chat, general, "two")
    channel(chat, "club", scope="shared", members=["guest"])
    assert chat("GET", "/api/push/badge", who=chat.guest) == {
        "messages": 2, "notifications": 1, "badge": 3}
    chat("POST", f"/api/records/channel/{general['id']}/seen", who=chat.guest, expect=204)
    chat("POST", "/api/notifications/read", {}, who=chat.guest)
    assert chat("GET", "/api/push/badge", who=chat.guest)["badge"] == 0


def test_the_badge_follows_the_switches(chat):
    general = listed(chat)["general"]
    say(chat, general, "morning", who=chat.guest)
    assert chat("GET", "/api/push/badge")["messages"] == 1
    chat("PATCH", "/api/me/features/chat", {"enabled": False})
    assert chat("GET", "/api/push/badge")["messages"] == 0
    chat("PATCH", "/api/me/features/chat", {"enabled": True})
    chat("PATCH", "/api/server/features/chat", {"enabled": False})
    assert chat("GET", "/api/push/badge")["messages"] == 0


def test_a_line_pushes_everybody_else_and_opens_the_conversation(chat, monkeypatch):
    general = listed(chat)["general"]
    pushed = []
    monkeypatch.setattr(PushStore, "send", lambda self, who, payload: pushed.append((who, payload)) or 1)
    say(chat, general, "hello")
    assert [who for who, _ in pushed] == [["guest"]], "the writer does not push themselves"
    payload = pushed[0][1]
    assert payload["title"] == "bram in general"
    assert payload["body"] == "hello"
    assert payload["url"] == f"#/q/chat/chat/{general['id']}"
    assert payload["tag"] == f"channel-{general['id']}", "one notification per channel, replaced"
    assert payload["badge"] == 1


def test_a_direct_line_is_titled_with_the_person(chat, monkeypatch):
    made = direct(chat, "guest")
    pushed = []
    monkeypatch.setattr(PushStore, "send", lambda self, who, payload: pushed.append(payload) or 1)
    say(chat, made, "are you up")
    assert pushed[0]["title"] == "bram"
    assert pushed[0]["body"] == "are you up"
    assert pushed[0]["url"] == f"#/q/chat/chat/{made['id']}"


def test_the_people_are_everybody_but_you(chat):
    assert chat("GET", "/api/people") == [{"username": "guest", "display_name": "guest"}]


# -- the move from the old tables ------------------------------------------------------------
def _old_chat(db) -> None:
    """Rows as the built-in chat wrote them: a public room, a private one, a direct line."""
    with connect(db) as conn:
        def room(slug, name, kind, by, topic=""):
            return conn.execute(
                "INSERT INTO chat_channels (slug, name, topic, kind, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (slug, name, conn.seal("chat_channels", "topic", (slug,), topic), kind, by,
                 "2026-09-01T10:00:00+00:00", "2026-09-01T10:00:00+00:00"),
            ).lastrowid

        def member(cid, who, last_read=0):
            conn.execute(
                "INSERT INTO chat_members (channel_id, username, added_by, joined_at, last_read)"
                " VALUES (?, ?, 'bram', '2026-09-01T10:00:00+00:00', ?)", (cid, who, last_read))

        def line(cid, who, body, at, edited=None):
            return conn.execute(
                "INSERT INTO chat_messages (channel_id, author, body, created_at, edited_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (cid, who, conn.seal("chat_messages", "body", (cid,), body), at, edited),
            ).lastrowid

        pub = room("homelab", "Homelab", "public", "bram", "the rack")
        priv = room("club", "Club", "private", "bram")
        dm = room("dm-bram-guest", "", "direct", "guest")
        first = line(pub, "bram", "rack is up", "2026-09-02T09:00:00+00:00")
        line(pub, "guest", "nice", "2026-09-02T09:05:00+00:00", edited="2026-09-02T09:06:00+00:00")
        line(pub, "bram", "thanks", "2026-09-02T09:10:00+00:00")
        member(pub, "bram", 3)
        member(pub, "guest", first)
        member(priv, "bram")
        member(priv, "guest")
        line(priv, "guest", "members only", "2026-09-03T09:00:00+00:00")
        member(dm, "guest")
        member(dm, "bram")
        line(dm, "guest", "psst", "2026-09-04T09:00:00+00:00")
    conn.close()


def test_the_old_chat_moves_into_records_once(config, users, tmp_path):
    db = config.db_path
    _old_chat(db)
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "models", str(QUILL_CATALOG))
    store = RecordStore(db, registry.models, registry.expiries)
    boot(db, registry, store)
    assert "chat" in registry.quills, "a server that had chat gets the Quill"
    bram, guest = Principal.person("bram"), Principal.person("guest")

    spaces = {c.fields["name"]: c for c in store.list(bram, "channel")}
    assert set(spaces) == {"Homelab", "Club", "bram & guest"}
    homelab = spaces["Homelab"]
    assert (homelab.scope, homelab.owner, homelab.fields["kind"], homelab.fields["topic"]) == (
        "public", "bram", "public", "the rack")
    assert (spaces["Club"].scope, spaces["Club"].members) == ("shared", ["guest"])
    dm = spaces["bram & guest"]
    assert (dm.scope, dm.owner, dm.members, dm.fields["kind"]) == ("shared", "guest", ["bram"], "direct")

    lines = store.list(guest, "message", {"channel": homelab.id})
    assert [(m.owner, m.fields["body"]) for m in lines] == [
        ("bram", "rack is up"), ("guest", "nice"), ("bram", "thanks")]
    assert lines[0].created_at == "2026-09-02T09:00:00+00:00"
    assert lines[1].updated_at == "2026-09-02T09:06:00+00:00", "an edit keeps its time"
    # Guest had read the first line only: the one after, not theirs, is unread.
    assert {c.fields["name"]: c.unread for c in store.list(guest, "channel")}["Homelab"] == 1
    assert {c.fields["name"]: c.unread for c in store.list(bram, "channel")}["Homelab"] == 0
    # The members-only line reaches its members and nobody else.
    assert [m.fields["body"] for m in store.list(bram, "message", {"channel": spaces["Club"].id})] == [
        "members only"]

    # Once: a second boot moves nothing again.
    assert move_legacy_chat(db, registry, store) == 0
    assert len(store.list(bram, "message")) == 5
    assert read_meta(db, LEGACY_CHAT) == "8"


def test_a_server_nobody_uses_yet_is_not_given_chat(config, tmp_path):
    config.ensure_dirs()
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "models", str(QUILL_CATALOG))
    store = RecordStore(config.db_path, registry.models, registry.expiries)
    # The tables exist on every server; a fresh one has no accounts and no rows.
    with connect(config.db_path):
        pass
    from cloudmorrow.server.db import UserStore

    UserStore(config.db_path)
    assert move_legacy_chat(config.db_path, registry, store) == 0
    assert "chat" not in registry.quills
    assert read_meta(config.db_path, LEGACY_CHAT) == "-"


def test_the_manifest_parses_on_its_own():
    import tomllib

    data = tomllib.loads((QUILL_CATALOG / "quill-chat" / "quill.toml").read_text())
    assert parse_manifest(data).datasets[0]["seed"] == "once"
