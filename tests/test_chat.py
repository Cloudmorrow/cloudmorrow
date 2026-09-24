"""Channels, direct messages, and who is allowed to read them."""

from __future__ import annotations

import pytest

from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def guest(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *GUEST)}"}


def channel(client, auth, name="Homelab", kind="private", **extra):
    response = client.post(
        "/api/chat/channels", json={"name": name, "kind": kind, **extra}, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


def post(client, auth, slug, body):
    response = client.post(
        f"/api/chat/channels/{slug}/messages", json={"body": body}, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


# -- public --------------------------------------------------------------------
def test_a_public_channel_is_everybodys(client, auth, guest):
    made = channel(client, auth, "General", kind="public")
    assert made["kind"] == "public"
    # Both accounts are in it without anybody being invited.
    assert set(made["members"]) == {ADMIN[0], GUEST[0]}

    seen = client.get("/api/chat/channels", headers=guest).json()
    assert [c["slug"] for c in seen] == ["general"]
    # And the guest may write in it, having been asked nothing.
    post(client, guest, "general", "the fans are loud again")
    assert client.get("/api/chat/channels/general/messages", headers=auth).json()[0][
        "author"
    ] == GUEST[0]


def test_a_public_channel_cannot_be_left(client, auth, guest):
    channel(client, auth, "General", kind="public")
    response = client.post("/api/chat/channels/general/leave", headers=guest)
    assert response.status_code == 400
    assert "cannot leave" in response.json()["detail"]


def test_a_second_channel_of_the_same_name_is_refused(client, auth):
    channel(client, auth, "General", kind="public")
    response = client.post(
        "/api/chat/channels", json={"name": "general", "kind": "public"}, headers=auth
    )
    assert response.status_code == 409


# -- private -------------------------------------------------------------------
def test_a_private_channel_is_only_its_members(client, auth, guest):
    channel(client, auth, "Secrets Club")
    assert client.get("/api/chat/channels", headers=guest).json() == []
    assert client.get("/api/chat/channels/secrets-club", headers=guest).status_code == 403
    assert (
        client.post(
            "/api/chat/channels/secrets-club/messages",
            json={"body": "hello?"},
            headers=guest,
        ).status_code
        == 403
    )


def test_being_added_needs_no_accepting_and_leaves_a_notification(client, auth, guest):
    channel(client, auth, "Secrets Club")
    response = client.post(
        "/api/chat/channels/secrets-club/members",
        json={"usernames": [GUEST[0]]},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["added"] == [GUEST[0]]

    # In it immediately — there is nothing to accept.
    assert [c["slug"] for c in client.get("/api/chat/channels", headers=guest).json()] == [
        "secrets-club"
    ]
    notes = client.get("/api/notifications", headers=guest).json()
    assert notes[0]["kind"] == "chat.added"
    assert notes[0]["title"] == f"{ADMIN[0]} added you to #Secrets Club"

    # Adding the same person twice is not news twice.
    again = client.post(
        "/api/chat/channels/secrets-club/members",
        json={"usernames": [GUEST[0]]},
        headers=auth,
    )
    assert again.json()["added"] == []


def test_someone_added_does_not_inherit_the_backlog_as_unread(client, auth, guest):
    channel(client, auth, "Secrets Club")
    post(client, auth, "secrets-club", "said before they arrived")
    client.post(
        "/api/chat/channels/secrets-club/members",
        json={"usernames": [GUEST[0]]},
        headers=auth,
    )
    # The history is there to scroll back through...
    assert len(client.get("/api/chat/channels/secrets-club/messages", headers=guest).json()) == 1
    # ...but it is not a badge for messages sent before they could read them.
    assert client.get("/api/chat/unread", headers=guest).json()["total"] == 0


def test_a_channel_can_be_left(client, auth, guest):
    channel(client, auth, "Secrets Club", members=[GUEST[0]])
    assert client.post("/api/chat/channels/secrets-club/leave", headers=guest).status_code == 204
    assert client.get("/api/chat/channels", headers=guest).json() == []


def test_only_its_maker_may_delete_it(client, users, config):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app
    from cloudmorrow.server.security import hash_password

    users.create("ada", hash_password("adasecret1"))
    client = TestClient(create_app(config))
    ada = {"Authorization": f"Bearer {token_for(client, 'ada', 'adasecret1')}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    slug = channel(client, ada, "Ada's Room", members=[GUEST[0]])["slug"]
    assert slug == "ada-s-room", "punctuation becomes a separator, not nothing"
    assert client.delete(f"/api/chat/channels/{slug}", headers=guest).status_code == 403
    assert client.delete(f"/api/chat/channels/{slug}", headers=ada).status_code == 204


def test_an_admin_may_delete_anybodys(client, auth, guest):
    # The guest makes it; the admin, who is not in it, throws it away.
    response = client.post(
        "/api/chat/channels", json={"name": "Guest Room", "kind": "private"}, headers=guest
    )
    assert response.status_code == 201
    assert client.delete("/api/chat/channels/guest-room", headers=auth).status_code == 204


def test_a_name_with_no_letters_in_it_is_refused(client, auth):
    response = client.post("/api/chat/channels", json={"name": "!!!"}, headers=auth)
    assert response.status_code == 400


# -- direct --------------------------------------------------------------------
def test_a_direct_channel_is_the_same_one_from_either_side(client, auth, guest):
    mine = client.post("/api/chat/direct", json={"username": GUEST[0]}, headers=auth).json()
    theirs = client.post("/api/chat/direct", json={"username": ADMIN[0]}, headers=guest).json()
    assert mine["slug"] == theirs["slug"] == f"dm-{ADMIN[0]}-{GUEST[0]}"
    assert mine["kind"] == "direct"
    # It is called after whoever you are not.
    assert mine["name"] == GUEST[0] and theirs["name"] == ADMIN[0]
    assert mine["other"] == GUEST[0] and theirs["other"] == ADMIN[0]


def test_asking_twice_does_not_make_two(client, auth):
    first = client.post("/api/chat/direct", json={"username": GUEST[0]}, headers=auth).json()
    second = client.post("/api/chat/direct", json={"username": GUEST[0]}, headers=auth).json()
    assert first["slug"] == second["slug"]
    assert len(client.get("/api/chat/channels", headers=auth).json()) == 1


def test_a_direct_channel_resists_being_something_else(client, auth):
    slug = client.post(
        "/api/chat/direct", json={"username": GUEST[0]}, headers=auth
    ).json()["slug"]
    assert client.patch(
        f"/api/chat/channels/{slug}", json={"name": "Nope"}, headers=auth
    ).status_code == 400
    assert client.post(
        f"/api/chat/channels/{slug}/members", json={"usernames": []}, headers=auth
    ).status_code == 400
    assert client.delete(f"/api/chat/channels/{slug}", headers=auth).status_code == 400


def test_a_stranger_cannot_read_someone_elses_direct_channel(client, users, config, auth):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app
    from cloudmorrow.server.security import hash_password

    users.create("ada", hash_password("adasecret1"))
    client = TestClient(create_app(config))
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    ada = {"Authorization": f"Bearer {token_for(client, 'ada', 'adasecret1')}"}
    slug = client.post("/api/chat/direct", json={"username": GUEST[0]}, headers=auth).json()["slug"]
    assert client.get(f"/api/chat/channels/{slug}", headers=ada).status_code == 403


def test_there_is_no_direct_channel_with_a_person_who_is_not_there(client, auth):
    response = client.post("/api/chat/direct", json={"username": "nobody"}, headers=auth)
    assert response.status_code == 400


# -- messages ------------------------------------------------------------------
def test_messages_come_back_oldest_first_and_page_backwards(client, auth):
    channel(client, auth, "General", kind="public")
    ids = [post(client, auth, "general", f"line {n}")["id"] for n in range(5)]
    page = client.get("/api/chat/channels/general/messages?limit=2", headers=auth).json()
    assert [m["id"] for m in page] == ids[-2:], "the newest page, oldest first"
    older = client.get(
        f"/api/chat/channels/general/messages?limit=2&before={ids[-2]}", headers=auth
    ).json()
    assert [m["id"] for m in older] == ids[1:3]
    newer = client.get(
        f"/api/chat/channels/general/messages?after={ids[2]}", headers=auth
    ).json()
    assert [m["id"] for m in newer] == ids[3:]


def test_only_the_author_may_change_what_was_said(client, auth, guest):
    channel(client, auth, "General", kind="public")
    message = post(client, guest, "general", "typpo")
    assert client.patch(
        f"/api/chat/channels/general/messages/{message['id']}",
        json={"body": "typo"},
        headers=auth,
    ).status_code == 403
    edited = client.patch(
        f"/api/chat/channels/general/messages/{message['id']}",
        json={"body": "typo"},
        headers=guest,
    )
    assert edited.status_code == 200
    assert edited.json()["body"] == "typo"
    assert edited.json()["edited_at"]


def test_an_empty_message_is_not_a_message(client, auth):
    channel(client, auth, "General", kind="public")
    assert client.post(
        "/api/chat/channels/general/messages", json={"body": "   "}, headers=auth
    ).status_code == 400


def test_writing_in_a_public_channel_puts_you_in_it(client, auth, guest):
    channel(client, auth, "General", kind="public")
    post(client, guest, "general", "hello")
    seen = client.get("/api/chat/channels/general", headers=guest).json()
    assert seen["member"] is True


# -- what is unread --------------------------------------------------------------
def test_unread_counts_messages_and_not_your_own(client, auth, guest):
    channel(client, auth, "General", kind="public")
    post(client, auth, "general", "one")
    post(client, auth, "general", "two")

    # Two waiting for the guest, and nothing for the person who wrote them.
    assert client.get("/api/chat/unread", headers=guest).json() == {
        "channels": {"general": 2},
        "total": 2,
    }
    assert client.get("/api/chat/unread", headers=auth).json()["total"] == 0


def test_writing_in_a_channel_reads_what_was_above_it(client, auth, guest):
    """The mark is a high-water mark, so replying is reading.

    You cannot answer a channel without having looked at it, and a badge
    that survives your own reply is a badge nobody believes.
    """
    channel(client, auth, "General", kind="public")
    post(client, auth, "general", "one")
    post(client, auth, "general", "two")
    assert client.get("/api/chat/unread", headers=guest).json()["total"] == 2

    post(client, guest, "general", "answering both")
    assert client.get("/api/chat/unread", headers=guest).json()["total"] == 0
    # And the reply is waiting for the other side.
    assert client.get("/api/chat/unread", headers=auth).json()["total"] == 1


def test_reading_clears_it_and_the_mark_never_goes_backwards(client, auth, guest):
    channel(client, auth, "General", kind="public")
    first = post(client, auth, "general", "one")
    post(client, auth, "general", "two")

    read = client.post("/api/chat/channels/general/read", json={}, headers=guest)
    assert read.status_code == 200
    assert read.json()["unread"] == 0 and read.json()["total"] == 0

    # A second client, scrolled back, must not un-read what the first saw.
    back = client.post(
        "/api/chat/channels/general/read", json={"upto": first["id"]}, headers=guest
    )
    assert back.json()["unread"] == 0
    assert client.get("/api/chat/unread", headers=guest).json()["total"] == 0


def test_the_channel_list_leads_with_the_newest_and_carries_the_last_line(client, auth):
    channel(client, auth, "General", kind="public")
    channel(client, auth, "Quiet", kind="public")
    post(client, auth, "general", "something happened")
    listed = client.get("/api/chat/channels", headers=auth).json()
    assert [c["slug"] for c in listed] == ["general", "quiet"]
    assert listed[0]["last_message"]["body"] == "something happened"
    assert listed[1]["last_message"] is None


# -- everyone else ----------------------------------------------------------------
def test_the_people_list_is_everybody_but_you(client, auth):
    people = client.get("/api/chat/people", headers=auth).json()
    assert [p["username"] for p in people] == [GUEST[0]]


def test_a_new_account_joins_the_public_channels_at_the_tip(client, users, config, auth):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app
    from cloudmorrow.server.security import hash_password

    channel(client, auth, "General", kind="public")
    post(client, auth, "general", "said before ada existed")

    users.create("ada", hash_password("adasecret1"))
    fresh = TestClient(create_app(config))
    ada = {"Authorization": f"Bearer {token_for(fresh, 'ada', 'adasecret1')}"}
    listed = fresh.get("/api/chat/channels", headers=ada).json()
    assert [c["slug"] for c in listed] == ["general"]
    assert listed[0]["unread"] == 0, "an account made today is not behind on last year"


# -- the switch ---------------------------------------------------------------------
def test_chat_switched_off_is_off(client, auth):
    assert client.patch(
        "/api/server/features/chat", json={"enabled": False}, headers=auth
    ).status_code == 200
    assert client.get("/api/chat/channels", headers=auth).status_code == 403
    assert "Chat is switched off" in client.get("/api/chat/channels", headers=auth).json()["detail"]
