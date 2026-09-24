"""Notifications: what the machines leave on the server, and who can read it."""

from __future__ import annotations

from cloudmorrow.server.notifications import KEEP, NotificationStore
from tests.conftest import GUEST, token_for


def test_they_come_back_newest_first(config):
    config.ensure_dirs()
    store = NotificationStore(config.db_path)
    store.add("bram", title="first")
    store.add("bram", title="second", kind="config.updated", machine="laptop")

    listed = store.list("bram")

    assert [note.title for note in listed] == ["second", "first"]
    assert listed[0].machine == "laptop"
    assert all(note.unread for note in listed)


def test_marking_them_read_is_not_deleting_them(config):
    config.ensure_dirs()
    store = NotificationStore(config.db_path)
    store.add("bram", title="one")
    store.add("bram", title="two")

    assert store.unread_count("bram") == 2
    assert store.mark_read("bram") == 2
    assert store.unread_count("bram") == 0
    assert len(store.list("bram")) == 2
    # Doing it twice marks nothing the second time.
    assert store.mark_read("bram") == 0


def test_one_of_them_can_be_marked_on_its_own(config):
    config.ensure_dirs()
    store = NotificationStore(config.db_path)
    kept = store.add("bram", title="keep me unread")
    marked = store.add("bram", title="mark me")

    assert store.mark_read("bram", [marked.id]) == 1

    unread = [note.id for note in store.list("bram", unread_only=True)]
    assert unread == [kept.id]


def test_the_tail_is_bounded(config):
    """A machine in a loop cannot fill the database with its own noise."""
    config.ensure_dirs()
    store = NotificationStore(config.db_path)
    for index in range(KEEP + 20):
        store.add("bram", title=f"note {index}")

    listed = store.list("bram", limit=KEEP + 50)

    assert len(listed) == KEEP
    assert listed[0].title == f"note {KEEP + 19}"


def test_they_belong_to_one_person(config):
    config.ensure_dirs()
    store = NotificationStore(config.db_path)
    store.add("bram", title="mine")

    assert store.list("guest") == []
    assert store.unread_count("guest") == 0


def test_an_agent_signs_its_own_notifications(client, auth):
    enrolled = client.post(
        "/api/agents/enroll-self", json={"name": "laptop"}, headers=auth
    ).json()
    agent_auth = {"Authorization": f"Bearer {enrolled['agent_token']}"}

    posted = client.post(
        "/api/agent/notifications",
        json={"kind": "config.applied", "title": "wrote the config", "body": "3 files"},
        headers=agent_auth,
    )

    assert posted.status_code == 200, posted.text
    # The machine name is the server's, from the token — not the body's.
    assert posted.json()["machine"] == "laptop"
    listed = client.get("/api/notifications", headers=auth).json()
    assert [note["title"] for note in listed] == ["wrote the config"]


def test_another_user_cannot_read_them(client, auth):
    enrolled = client.post(
        "/api/agents/enroll-self", json={"name": "laptop"}, headers=auth
    ).json()
    client.post(
        "/api/agent/notifications",
        json={"title": "private"},
        headers={"Authorization": f"Bearer {enrolled['agent_token']}"},
    )

    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/notifications", headers=guest).json() == []


def test_they_need_a_credential_at_all(client):
    assert client.get("/api/notifications").status_code == 401
    assert client.post("/api/agent/notifications", json={"title": "hi"}).status_code == 401
