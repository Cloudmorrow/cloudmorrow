"""One cloud under load: the database settings, the bounds on a listing, the
indexes a listing uses, the change feed's retention and its live stream, and
the script that measures it all (scripts/loadtest.py)."""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cloudmorrow.server import schema
from cloudmorrow.server.db import connect
from cloudmorrow.server.quills import jobs
from cloudmorrow.server.routes.web import WEB
from tests.conftest import ADMIN, GUEST, token_for

ROOT = Path(__file__).resolve().parent.parent


def names(db_path: Path, kind: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}
    finally:
        conn.close()


# -- the database ------------------------------------------------------------------------
def test_the_database_runs_in_write_ahead_mode_with_a_busy_wait(tmp_path):
    conn = connect(tmp_path / "cloud.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    conn.close()
    # The log and the shared memory sit beside the file while it is open.
    conn = connect(tmp_path / "cloud.db")
    conn.execute("CREATE TABLE IF NOT EXISTS scratch (x)")
    conn.commit()
    assert (tmp_path / "cloud.db-wal").exists()
    conn.close()


def test_the_clock_folds_the_log_back_into_the_file(tmp_path):
    from cloudmorrow.server.db import checkpoint

    path = tmp_path / "cloud.db"
    conn = connect(path)
    conn.execute("CREATE TABLE scratch (x)")
    conn.executemany("INSERT INTO scratch VALUES (?)", [("y" * 1000,) for _ in range(2000)])
    conn.commit()
    # Still open: the log holds the writes, and is well over a megabyte.
    assert (path.with_name("cloud.db-wal")).stat().st_size > 1_000_000
    assert checkpoint(path) is True
    assert (path.with_name("cloud.db-wal")).stat().st_size == 0
    conn.close()


def test_a_new_database_has_the_indexes_an_open_screen_and_the_sweep_ask(tmp_path):
    conn = connect(tmp_path / "cloud.db")
    assert schema.version_of(conn) == 2
    conn.close()
    assert {"records_model_updated", "record_changes_at"} <= names(tmp_path / "cloud.db", "index")


def test_an_older_database_gets_the_indexes_on_opening(tmp_path):
    path = tmp_path / "cloud.db"
    conn = connect(path)
    conn.execute("DROP INDEX records_model_updated")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    connect(path).close()
    assert "records_model_updated" in names(path, "index")


# -- listings ------------------------------------------------------------------------------
@pytest.fixture()
def api(tasks_quill):
    headers = {"Authorization": f"Bearer {token_for(tasks_quill, *ADMIN)}"}

    def call(method: str, path: str, body: dict | None = None, *, expect: int = 200, as_: dict | None = None):
        response = tasks_quill.request(method, path, json=body, headers=as_ or headers)
        assert response.status_code == expect, response.text
        return response

    call.client = tasks_quill
    call.state = tasks_quill.app.state.cloudmorrow
    return call


def make_tasks(api, board: str, titles: list[str]) -> list[str]:
    made = [api("POST", "/api/records/task", {"fields": {"board": board, "title": t}}, expect=201) for t in titles]
    return [r.json()["id"] for r in made]


def test_listing_a_datamodel_makes_the_indexes_its_filters_use(api):
    api("GET", "/api/records/task")
    db_path = api.state.config.db_path
    # The group fields and the link: what a board asks by.
    assert {"records_task_board", "records_task_lane"} <= names(db_path, "index")
    conn = sqlite3.connect(db_path)
    plan = " ".join(
        row[3]
        for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM records WHERE model = ? AND owner = ?"
            " AND json_extract(indexed, '$.\"board\"') = ?",
            ("task", "bram", "b1"),
        )
    )
    conn.close()
    assert "records_task_board" in plan, plan


def test_a_plain_listing_stops_at_the_cap_and_says_so(api):
    board = api("GET", "/api/records/board").json()[0]["id"]
    made = make_tasks(api, board, [f"Task {n}" for n in range(5)])
    api.state.records.list_cap = 3
    response = api("GET", "/api/records/task")
    assert len(response.json()) == 3
    assert response.headers["X-Records-Capped"] == "3"
    # In order: the first three, not any three.
    assert [r["id"] for r in response.json()] == made[:3]
    # A filter is capped the same way; a page is not.
    assert len(api("GET", "/api/records/task?lane=todo").json()) == 3
    response = api("GET", "/api/records/task?_last=5")
    assert len(response.json()) == 5
    assert "X-Records-Capped" not in response.headers
    response = api("GET", "/api/records/task?_since=2000-01-01T00:00:00+00:00")
    assert len(response.json()) == 5


def test_a_search_stops_at_its_cap(api, monkeypatch):
    from cloudmorrow.server import records

    board = api("GET", "/api/records/board").json()[0]["id"]
    make_tasks(api, board, ["needle one", "hay", "needle two", "needle three"])
    monkeypatch.setattr(records, "SEARCH_CAP", 2)
    found = api("GET", "/api/records/task?q=needle").json()
    assert [r["fields"]["title"] for r in found] == ["needle one", "needle two"]
    # Below the cap, every match comes.
    monkeypatch.setattr(records, "SEARCH_CAP", 200)
    assert len(api("GET", "/api/records/task?q=needle").json()) == 3


# -- the change feed's retention -----------------------------------------------------------
def test_the_sweep_takes_old_lines_of_gone_records_out_of_the_change_feed(api):
    """A living record keeps its whole history (its sheet shows it); a deleted
    record's lines serve the feed a while, then go with the sweep."""
    board = api("GET", "/api/records/board").json()[0]["id"]
    a, b = make_tasks(api, board, ["a", "b"])
    api("DELETE", f"/api/records/task/{a}", expect=204)
    db_path = api.state.config.db_path
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM record_changes").fetchone()[0]
    assert count >= 4  # the board, two tasks, and one deletion
    old = (dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=100)).isoformat(timespec="seconds")
    conn.execute("UPDATE record_changes SET at = ? WHERE record_id IN (?, ?)", (old, board, a))
    conn.commit()
    conn.close()
    jobs.sweep_all(api.state.quills, api.state.records)
    conn = sqlite3.connect(db_path)
    left = {row[0] for row in conn.execute("SELECT record_id FROM record_changes")}
    conn.close()
    assert a not in left and board in left and b in left


# -- two at once ----------------------------------------------------------------------------------
def test_two_asking_for_a_new_webhook_secret_at_once_get_the_same_one(tmp_path):
    """Write-ahead mode lets two readers overlap where the old journal made one
    wait, so a read-then-write has to take the write lock itself. The
    supervisor and a request both ask on a fresh install."""
    from cloudmorrow.server.quills.tokens import QuillTokenStore

    store = QuillTokenStore(tmp_path / "cloud.db")
    got: list[str] = []
    gate = threading.Barrier(8)

    def ask() -> None:
        gate.wait()
        got.append(store.webhook_secret("relay", f"hook{len(got) % 2}"))

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Whatever each thread made or found, what is stored now is what every later asker gets,
    # and every thread's answer is one of the two stored values.
    stored = {store.webhook_secret("relay", "hook0"), store.webhook_secret("relay", "hook1")}
    assert set(got) <= stored, (got, stored)


# -- the live stream -------------------------------------------------------------------------
def events(lines: list[str]) -> list[tuple[str, dict]]:
    """(event, data) for each block of a server-sent events body."""
    import json

    out, name, data = [], None, None
    for line in [*lines, ""]:
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:])
        elif line == "" and name:
            out.append((name, data))
            name, data = None, None
    return out


def stream(client, headers: dict, query: str) -> list[tuple[str, dict]]:
    with client.stream("GET", f"/api/changes?{query}", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return events(list(response.iter_lines()))


def test_the_stream_opens_with_its_position_and_sends_what_you_did(api):
    board = api("GET", "/api/records/board").json()[0]["id"]
    (task,) = make_tasks(api, board, ["one"])
    auth = {"Authorization": f"Bearer {token_for(api.client, *ADMIN)}"}
    got = stream(api.client, auth, "since=0&limit=2")
    assert got[0][0] == "hello" and got[0][1]["seq"] == 2
    assert [(name, d["model"], d["id"], d["action"]) for name, d in got[1:]] == [
        ("change", "board", board, "created"),
        ("change", "task", task, "created"),
    ]
    # Nothing a screen would not be handed: no fields.
    assert "fields" not in got[1][1] and "title" not in got[1][1]


def test_nobody_hears_of_a_personal_record_but_its_owner(api):
    board = api("GET", "/api/records/board").json()[0]["id"]
    make_tasks(api, board, ["mine"])
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}

    def guests_turn() -> None:
        time.sleep(0.3)
        theirs = api("GET", "/api/records/board", as_=guest).json()[0]["id"]
        api("POST", "/api/records/task", {"fields": {"board": theirs, "title": "theirs"}}, expect=201, as_=guest)

    threading.Thread(target=guests_turn).start()
    got = stream(api.client, guest, "since=0&limit=1")
    changes = [d for name, d in got if name == "change"]
    assert len(changes) == 1 and changes[0]["owner"] == "guest" and changes[0]["model"] == "board"


def test_a_member_hears_of_a_line_in_a_shared_space(chat_quill):
    admin = {"Authorization": f"Bearer {token_for(chat_quill, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(chat_quill, *GUEST)}"}
    room = chat_quill.post(
        "/api/records/channel",
        json={"fields": {"name": "us", "kind": "private"}, "scope": "shared", "members": [GUEST[0]]},
        headers=admin,
    )
    assert room.status_code == 201, room.text
    room_id = room.json()["id"]
    said = chat_quill.post(
        "/api/records/message", json={"fields": {"channel": room_id, "body": "hello"}}, headers=admin
    )
    assert said.status_code == 201, said.text
    got = stream(chat_quill, guest, "since=0&limit=2")
    changes = [(d["model"], d["id"], d["space"]) for name, d in got if name == "change"]
    assert changes == [("channel", room_id, room_id), ("message", said.json()["id"], room_id)]


def test_the_browser_listens_through_the_shell_and_falls_back_to_asking():
    core = (WEB / "core.js").read_text(encoding="utf-8")
    changes = (WEB / "changes.js").read_text(encoding="utf-8")
    thread = (WEB / "kit_thread.js").read_text(encoding="utf-8")
    assert "export async function apiStream" in core
    assert 'import { apiStream } from "./core.js";' in changes
    assert "/api/changes" in changes and "?since=" in changes
    assert 'import { listenChanges } from "./changes.js";' in thread
    # The timer stays, as the way back when the stream is down.
    assert not re.search(r"setInterval\(catchUp, POLL\)", thread)
    assert "POLL_FED" in thread and "feed.live" in thread


# -- the measurement -------------------------------------------------------------------------
def test_the_load_script_runs_a_server_and_reports(tmp_path):
    script = ROOT / "scripts" / "loadtest.py"
    run = subprocess.run(
        [
            sys.executable,
            str(script),
            *("--users", "2", "--records", "4", "--messages", "2"),
            *("--concurrency", "2", "--requests", "8"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert run.returncode == 0, run.stderr[-2000:]
    rows = [line for line in run.stdout.splitlines() if line.startswith("| ") and " ms |" in line]
    assert [row.split("|")[1].strip() for row in rows] == ["list", "create", "search", "thread"]
    assert all(row.rstrip("|").rsplit("|", 1)[1].strip() == "0" for row in rows), rows
    assert "accounts, 15 records" in run.stdout  # 2 x (4 + 2) + 2 boards + the channel
