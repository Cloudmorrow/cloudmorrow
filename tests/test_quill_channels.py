"""Channels as a Quill: threads, mentions, reactions and pinned messages through the record API.

Channels replaces Chat over the same channel and message datamodels, with
four more bindings on its thread screen. What they promise is held here the
way Chat's promises are held in test_quill_chat.py: a reply is in its
parent's channel and goes with it; a reaction is one person's, toggled by
them alone; a message is pinned by its author or whoever manages the
channel; and @name tells that person, in its own words.
"""

from __future__ import annotations

import pytest

from cloudmorrow.server import spacenotify
from cloudmorrow.server.datamodels import DatamodelError, parse_datamodel
from cloudmorrow.server.quills import QuillError, load_manifest
from cloudmorrow.server.webpush import PushStore
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for


@pytest.fixture()
def channels(client):
    client.app.state.cloudmorrow.quills.install_from_catalog("channels")
    bram = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}

    def call(method, path, body=None, *, who=bram, expect=200):
        response = client.request(method, path, json=body, headers=who)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.bram, call.guest, call.client = bram, guest, client
    return call


@pytest.fixture(autouse=True)
def pushes_at_once(monkeypatch):
    monkeypatch.setattr(spacenotify, "_later", lambda work: work())


def general(channels) -> dict:
    return next(c for c in channels("GET", "/api/records/channel") if c["fields"]["name"] == "general")


def say(channels, space: dict, text: str, *, who=None, **fields) -> dict:
    body = {"fields": {"channel": space["id"], "body": text, **fields}}
    return channels("POST", "/api/records/message", body, who=who or channels.bram, expect=201)


def react(channels, line: dict, emoji: str, *, who=None, expect=201) -> dict:
    body = {"fields": {"channel": line["fields"]["channel"], "message": line["id"], "emoji": emoji}}
    return channels("POST", "/api/records/reaction", body, who=who or channels.bram, expect=expect)


# -- the manifest ------------------------------------------------------------------------
def test_the_quill_is_a_thread_with_threads_mentions_reactions_and_pins(channels):
    manifest = load_manifest(QUILL_CATALOG / "quill-channels")
    assert manifest.uses == ("channel", "message", "reaction")
    (screen,) = manifest.screens
    assert screen["reply_to"] == "reply_to" and screen["pinned"] == "pinned"
    assert screen["reactions"] == "reaction" and screen["mentions"] is True
    quills = {q["id"]: q for q in channels("GET", "/api/quills")}
    assert "channels" in quills
    fields = {f["name"]: f for f in quills["channels"]["models"]["message"]["fields"]}
    assert fields["pinned"]["managed"] is True and fields["reply_to"]["to"] == "message"


def test_the_bindings_are_checked_against_the_datamodels(channels, tmp_path):
    registry = channels.client.app.state.cloudmorrow.quills
    text = (QUILL_CATALOG / "quill-channels" / "quill.toml").read_text()
    for bad, said in [
        ('reply_to = "reply_to"', 'reply_to = "channel"'),  # a link, but not to a message
        ('pinned = "pinned"', 'pinned = "body"'),  # not a bool
        ('reactions = "reaction"', 'reactions = "channel"'),  # no link to a message, not authored
        ("mentions = true", 'mentions = "yes"'),
        ('datamodels = ["channel", "message", "reaction"]', 'datamodels = ["channel", "message"]'),  # not used
    ]:
        folder = tmp_path / str(abs(hash(said)))
        folder.mkdir(parents=True)
        (folder / "quill.toml").write_text(text.replace(bad, said).replace('id = "channels"', 'id = "channels2"'))
        with pytest.raises(QuillError):
            registry.plan(folder, QUILL_CATALOG / "datamodels")


def test_a_managed_field_is_only_on_a_datamodel_in_a_space():
    with pytest.raises(DatamodelError, match="managed"):
        parse_datamodel(
            {
                "datamodel": {"id": "note", "title": "title"},
                "fields": {"title": {"kind": "string"}, "pinned": {"kind": "bool", "managed": True}},
            }
        )


def test_chat_still_installs_beside_it(channels):
    channels.client.app.state.cloudmorrow.quills.install_from_catalog("chat")
    assert {q["id"] for q in channels("GET", "/api/quills")} >= {"chat", "channels"}
    # One #general between them: Chat's dataset finds Channels' and makes no second.
    names = [c["fields"]["name"] for c in channels("GET", "/api/records/channel")]
    assert names == ["general"]


# -- threads ---------------------------------------------------------------------------
def test_a_reply_is_in_its_parents_channel_and_goes_with_it(channels):
    room = general(channels)
    parent = say(channels, room, "lunch?")
    reply = say(channels, room, "yes", who=channels.guest, reply_to=parent["id"])
    assert reply["fields"]["reply_to"] == parent["id"] and reply["fields"]["channel"] == room["id"]
    thread = channels("GET", f"/api/records/message?reply_to={parent['id']}")
    assert [m["fields"]["body"] for m in thread] == ["yes"]
    # A reply is a line of the channel like any other: the newest thing said in it.
    assert general(channels)["last"]["title"] == "yes"
    channels("DELETE", f"/api/records/message/{parent['id']}", expect=204)
    assert channels("GET", f"/api/records/message?channel={room['id']}") == []


def test_a_reply_cannot_answer_a_message_you_cannot_see(channels):
    club = channels(
        "POST",
        "/api/records/channel",
        {"fields": {"name": "club", "kind": "private"}, "scope": "shared", "members": []},
        expect=201,
    )
    secret = say(channels, club, "members only")
    room = general(channels)
    body = {"fields": {"channel": room["id"], "body": "what?", "reply_to": secret["id"]}}
    channels("POST", "/api/records/message", body, who=channels.guest, expect=400)


# -- reactions -----------------------------------------------------------------------------
def test_a_reaction_is_one_persons_and_theirs_to_take_back(channels):
    room = general(channels)
    line = say(channels, room, "shipped")
    mine = react(channels, line, "🎉", who=channels.guest)
    assert mine["owner"] == "guest" and mine["fields"]["message"] == line["id"]
    listed = channels("GET", f"/api/records/reaction?channel={room['id']}")
    assert [(r["owner"], r["fields"]["emoji"]) for r in listed] == [("guest", "🎉")]
    channels("DELETE", f"/api/records/reaction/{mine['id']}", expect=403)  # bram, not guest
    channels("DELETE", f"/api/records/reaction/{mine['id']}", who=channels.guest, expect=204)
    assert channels("GET", f"/api/records/reaction?message={line['id']}") == []
    # A reaction is not news: nothing unread, and the last line is still the line.
    react(channels, line, "👍", who=channels.guest)
    assert general(channels)["unread"] == 0 and general(channels)["last"]["title"] == "shipped"


def test_reactions_go_with_their_message(channels):
    room = general(channels)
    line = say(channels, room, "gone soon")
    react(channels, line, "👀", who=channels.guest)
    channels("DELETE", f"/api/records/message/{line['id']}", expect=204)
    assert channels("GET", f"/api/records/reaction?channel={room['id']}") == []


# -- pinned ------------------------------------------------------------------------------
def test_a_message_is_pinned_by_its_author_or_whoever_manages_the_channel(channels):
    room = general(channels)  # bram's: seeded as the first to look, and an administrator
    theirs = say(channels, room, "read me", who=channels.guest)
    pinned = channels("PATCH", f"/api/records/message/{theirs['id']}", {"fields": {"pinned": True}})
    assert pinned["fields"]["pinned"] is True and pinned["fields"]["body"] == "read me"
    # The pin alone: the words stay the author's.
    channels("PATCH", f"/api/records/message/{theirs['id']}", {"fields": {"body": "mine now"}}, expect=403)
    channels("PATCH", f"/api/records/message/{theirs['id']}", {"fields": {"pinned": False, "body": "x"}}, expect=403)
    # Its author may, always.
    channels("PATCH", f"/api/records/message/{theirs['id']}", {"fields": {"pinned": False}}, who=channels.guest)
    assert [m["id"] for m in channels("GET", f"/api/records/message?channel={room['id']}&pinned=true")] == []


def test_whoever_manages_a_channel_pins_a_line_of_somebody_elses(channels):
    club = channels(
        "POST",
        "/api/records/channel",
        {"fields": {"name": "club", "kind": "private"}, "scope": "shared", "members": ["bram"]},
        who=channels.guest,
        expect=201,
    )
    line = say(channels, club, "agenda")
    pinned = channels("PATCH", f"/api/records/message/{line['id']}", {"fields": {"pinned": True}}, who=channels.guest)
    assert pinned["fields"]["pinned"] is True
    assert [m["id"] for m in channels("GET", f"/api/records/message?channel={club['id']}&pinned=true")] == [line["id"]]


# -- mentions -------------------------------------------------------------------------------
def test_naming_somebody_tells_them_so(channels, monkeypatch):
    room = general(channels)
    pushed = []
    monkeypatch.setattr(PushStore, "has", lambda self, who: True)
    monkeypatch.setattr(PushStore, "send", lambda self, who, payload: pushed.append((who, payload)) or 1)
    say(channels, room, "@guest can you look at the NAS?")
    assert [who for who, _ in pushed] == [["guest"]]
    assert pushed[0][1]["title"] == "bram mentioned you in general"
    assert pushed[0][1]["body"] == "@guest can you look at the NAS?"
    pushed.clear()
    say(channels, room, "nobody in particular")
    assert pushed[0][1]["title"] == "bram in general"


def test_a_mention_in_a_private_channel_reaches_only_its_people(channels, monkeypatch):
    club = channels(
        "POST",
        "/api/records/channel",
        {"fields": {"name": "club", "kind": "private"}, "scope": "shared", "members": []},
        expect=201,
    )
    pushed = []
    monkeypatch.setattr(PushStore, "has", lambda self, who: True)
    monkeypatch.setattr(PushStore, "send", lambda self, who, payload: pushed.append((who, payload)) or 1)
    say(channels, club, "@guest are you there")
    assert pushed == [], "guest is not in the club, so is not told"


def test_what_counts_as_a_mention():
    assert spacenotify.mentioned("@ada and @bob.smith, not me@example.com or @@x") == ["ada", "bob.smith"]
    assert spacenotify.mentioned("(@ada) [@bob] @ada.") == ["ada", "bob"]
    assert spacenotify.mentioned("") == []
