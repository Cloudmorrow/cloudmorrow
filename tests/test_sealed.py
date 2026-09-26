"""Content at rest is ciphertext, and comes back as what was written."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from cloudmorrow.server import sealed
from cloudmorrow.server.chat import ChatStore
from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.crypto import SealError, load_or_create_key
from cloudmorrow.server.db import connect
from cloudmorrow.server.notes import NoteStore
from cloudmorrow.server.notifications import NotificationStore
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.server.records import Principal, RecordStore
from cloudmorrow.server.sealed import FILE_MAGIC, Sealer, rotate, seal_tree, use_key
from tests.conftest import ADMIN, QUILL_CATALOG, token_for


def raw(db_path: Path, sql: str, *args: object) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_a_record_is_ciphertext_in_the_database_and_text_through_the_store(tmp_path):
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels", str(QUILL_CATALOG))
    registry.install_from_catalog("tasks")
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    bram = Principal.person("bram")
    board = store.create(bram, "board", {"title": "Home Lab"})
    task = store.create(bram, "task", {"board": board.id, "title": "Fix the NAS", "body": "It beeps."})
    body = raw(tmp_path / "cm.db", "SELECT body FROM records WHERE id = ?", task.id)[0][0]
    assert body.startswith("s1:") and "Fix the NAS" not in body and "beeps" not in body
    assert store.get(bram, "task", task.id).fields["body"] == "It beeps."
    assert [b.fields["title"] for b in store.list(bram, "board")] == ["Home Lab"]


def test_a_value_moved_to_another_row_does_not_open(tmp_path):
    db = tmp_path / "cm.db"
    store = NotificationStore(db)
    store.add("bram", title="Backup done")
    store.add("guest", title="Their own")
    sealed_title = raw(db, "SELECT title FROM notifications WHERE owner = 'bram'")[0][0]
    conn = sqlite3.connect(db)
    conn.execute("UPDATE notifications SET title = ? WHERE owner = 'guest'", (sealed_title,))
    conn.commit()
    conn.close()
    with pytest.raises(SealError):
        store.list("guest")


def test_a_database_from_before_sealing_is_sealed_on_first_connect(tmp_path):
    db = tmp_path / "cm.db"
    # What an older version left: plain rows, and no sealing version.
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'info', machine TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, read_at TEXT);
        INSERT INTO notifications (owner, title, body, created_at)
            VALUES ('bram', 'Plain title', 'Plain body', '2026-01-01T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()
    connect(db).close()
    assert raw(db, "SELECT title FROM notifications")[0][0].startswith("s1:")
    assert raw(db, "SELECT value FROM schema_meta WHERE key = 'sealed'") == [
        (str(sealed.SEALED_VERSION),)
    ]
    got = NotificationStore(db).list("bram")
    assert (got[0].title, got[0].body) == ("Plain title", "Plain body")


def test_a_note_is_ciphertext_on_disk_and_a_plain_one_is_sealed_by_the_sweep(tmp_path):
    sealer = Sealer(os.urandom(32))
    store = NoteStore(tmp_path / "notes", sealer)
    store.write("plan", "# plan\n\nbuy milk\n")
    on_disk = (store.root / "plan.md").read_bytes()
    assert on_disk.startswith(FILE_MAGIC) and b"milk" not in on_disk
    assert store.read("plan").content == "# plan\n\nbuy milk\n"
    assert store.read("plan").size == len("# plan\n\nbuy milk\n")
    # A plain file from an older version reads as itself, and the sweep seals it.
    (store.root / "old.md").write_text("still readable\n", encoding="utf-8")
    assert store.read("old").content == "still readable\n"
    assert seal_tree(store.root, sealer) == 1
    assert seal_tree(store.root, sealer) == 0
    assert (store.root / "old.md").read_bytes().startswith(FILE_MAGIC)
    assert store.read("old").content == "still readable\n"
    assert store.search("milk")[0]["path"] == "plan.md"
    assert store.tree(previews=True).children[1].preview == "buy milk"


def test_the_key_file_can_live_elsewhere(tmp_path, monkeypatch):
    toml = tmp_path / "server.toml"
    toml.write_text(
        f'[server]\nnotes_dir = "{tmp_path}/notes"\ndata_dir = "{tmp_path}/data"\n'
        f'key_file = "{tmp_path}/etc/cm.key"\n',
        encoding="utf-8",
    )
    config = load_config(toml)
    assert config.secrets_key_path == tmp_path / "etc" / "cm.key"
    monkeypatch.setenv("CLOUDMORROW_KEY_FILE", str(tmp_path / "other.key"))
    assert load_config(toml).secrets_key_path == tmp_path / "other.key"
    # And the stores seal under it once it is registered for the database.
    use_key(config.db_path, config.secrets_key_path)
    assert config.secrets_key_path.is_file()
    assert oct(config.secrets_key_path.stat().st_mode & 0o777) == "0o600"
    assert sealed.key_for(config.db_path) == load_or_create_key(config.secrets_key_path)
    assert not (config.data_dir / "secrets.key").exists()


def test_the_default_key_sits_beside_the_database():
    config = ServerConfig(data_dir=Path("/var/lib/cm"))
    assert config.secrets_key_path == Path("/var/lib/cm/secrets.key")


def test_boot_seals_every_users_notes(client, config, auth):
    """A server starting on notes from before sealing seals them."""
    from cloudmorrow.server.app import create_app

    notes = config.notes_root(ADMIN[0])
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "legacy.md").write_text("from before\n", encoding="utf-8")
    create_app(config)
    assert (notes / "legacy.md").read_bytes().startswith(FILE_MAGIC)
    got = client.get("/api/notes/file/legacy.md", headers=auth)
    assert got.status_code == 200 and got.json()["content"] == "from before\n"


def test_rotating_the_key_reseals_everything(tmp_path, config, users):
    db = config.db_path
    old_path = tmp_path / "old.key"
    old = use_key(db, old_path)
    chat = ChatStore(db)
    chat.create("bram", name="homelab", kind="public", topic="the rack")
    chat.post("bram", "homelab", "hello there")
    notes = NoteStore(tmp_path / "notes", old)
    notes.write("plan", "rotate me\n")
    notes.save_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    new = Sealer(os.urandom(32))
    counts = rotate(db, [notes.root], old, new)
    assert counts == {"rows": 2, "files": 2}

    # The old sealer cannot open a row any more; the new one can.
    with pytest.raises(SealError):
        chat.messages("bram", "homelab")
    sealed._keys.clear()
    sealed._sealers.clear()
    old_path.write_bytes(b"")  # not read again: the new key is registered below
    sealed._keys[db.resolve()] = new.master
    assert chat.messages("bram", "homelab")[0]["body"] == "hello there"
    assert NoteStore(notes.root, new).read("plan").content == "rotate me\n"
    with pytest.raises(SealError):
        NoteStore(notes.root, old).read("plan")


def test_the_api_round_trips_sealed_content(client, auth):
    """Through the API nothing looks different: what you post is what you get."""
    made = client.post(
        "/api/chat/channels", json={"name": "ops", "kind": "public", "topic": "on call"},
        headers=auth,
    )
    assert made.status_code in (200, 201), made.text
    slug = made.json()["slug"]
    posted = client.post(
        f"/api/chat/channels/{slug}/messages", json={"body": "the pager"}, headers=auth
    )
    assert posted.status_code in (200, 201), posted.text
    listed = client.get(f"/api/chat/channels/{slug}/messages", headers=auth).json()
    assert [m["body"] for m in listed] == ["the pager"]
    assert client.get(f"/api/chat/channels/{slug}", headers=auth).json()["topic"] == "on call"


def test_editing_part_of_an_event_keeps_the_rest_readable(client, auth):
    """An edit that leaves the title alone must not seal the sealed title again."""
    mine = client.get("/api/calendar/calendars", headers=auth).json()[0]["slug"]
    made = client.post(
        f"/api/calendar/calendars/{mine}/events",
        json={"title": "Dentist", "starts_at": "2026-10-01T09:00", "ends_at": "2026-10-01T10:00",
              "notes": "bring the card", "location": "town"},
        headers=auth,
    )
    assert made.status_code in (200, 201), made.text
    event_id = made.json()["id"]
    moved = client.patch(
        f"/api/calendar/events/{event_id}", json={"starts_at": "2026-10-01T11:00"}, headers=auth
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()["title"], moved.json()["notes"], moved.json()["location"]) == (
        "Dentist", "bring the card", "town"
    )
    again = client.get(f"/api/calendar/events/{event_id}", headers=auth).json()
    assert again["title"] == "Dentist"


@pytest.fixture()
def auth(client):
    return {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
