"""What every open app hears that is not about a record: the server going away for
an update (bye), and its Quills moving (quills) — and what the web app does with it."""

from __future__ import annotations

import asyncio
import re
import signal
from pathlib import Path

from cloudmorrow.server.changefeed import ChangeFeed
from tests.conftest import ADMIN, token_for
from tests.test_scaling import events

WEB = Path(__file__).resolve().parent.parent / "src" / "cloudmorrow" / "server" / "web"


def feed_of(client) -> ChangeFeed:
    return client.app.state.cloudmorrow.changes


# -- the feed ------------------------------------------------------------------------------
def test_a_stream_waiting_wakes_for_a_notice_and_for_bye(client):
    feed = feed_of(client)
    base = feed.note

    async def waits() -> tuple[float, float]:
        loop = asyncio.get_running_loop()
        start = loop.time()
        loop.call_later(0.05, feed.tell, "quills")
        await feed.wait(feed.seq, 5.0, note=feed.note)
        told = loop.time() - start
        loop.call_later(0.05, feed.going, "restart")
        await feed.wait(feed.seq, 5.0, note=feed.note)
        return told, loop.time() - start

    told, gone = asyncio.run(waits())
    assert told < 1.0 and gone < 2.0
    assert [name for _, name, _ in feed.notes_since(base)] == ["quills"]
    assert feed.leaving == "restart"


def test_once_the_server_is_going_a_stream_says_bye_and_ends(client):
    feed_of(client).going("restart")
    auth = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    with client.stream("GET", "/api/changes", headers=auth) as response:
        got = events(list(response.iter_lines()))
    assert got == [("hello", {"seq": feed_of(client).seq}), ("bye", {"reason": "restart"})]


def test_the_stop_signal_tells_the_feed_before_uvicorn_stops(client):
    import uvicorn

    from cloudmorrow.server.cli import _serving

    server = _serving(uvicorn.Config(client.app))
    server.handle_exit(signal.SIGTERM, None)
    assert feed_of(client).leaving == "restart"
    assert server.should_exit


# -- what moves the menu --------------------------------------------------------------------
def test_installing_and_removing_a_quill_tells_every_stream(client):
    feed = feed_of(client)
    state = client.app.state.cloudmorrow
    before = feed.note
    state.quills.install_from_catalog("tasks")
    assert feed.note > before
    assert feed.notes_since(before)[-1][1] == "quills"
    before = feed.note
    state.quills.uninstall("tasks")
    assert feed.note > before


def test_switching_a_quill_off_here_or_for_yourself_tells_every_stream(tasks_quill, auth):
    feed = feed_of(tasks_quill)
    before = feed.note
    answer = tasks_quill.patch("/api/server/features/tasks", json={"enabled": False}, headers=auth)
    assert answer.status_code == 200, answer.text
    assert feed.note == before + 1
    tasks_quill.patch("/api/server/features/tasks", json={"enabled": True}, headers=auth)
    answer = tasks_quill.patch("/api/me/features/tasks", json={"enabled": False}, headers=auth)
    assert answer.status_code == 200, answer.text
    assert feed.note == before + 3


def test_a_share_taken_or_taken_back_tells_every_stream(client):
    sharing = client.app.state.cloudmorrow.sharing
    feed = feed_of(client)
    sharing.offer("alice", "budget", "bob", by="alice")
    before = feed.note
    sharing.answer("alice", "budget", "bob", True)
    sharing.revoke("alice", "budget", "bob")
    assert feed.note == before + 2


# -- the web app ------------------------------------------------------------------------------
def test_the_app_listens_for_bye_and_for_quills_whatever_screen_is_up():
    app = (WEB / "app.js").read_text()
    updating = (WEB / "updating.js").read_text()
    changes = (WEB / "changes.js").read_text()
    assert 'import "./updating.js";' in app
    assert "onBye: hold, onNotice: heard" in updating
    assert 'name === "bye"' in changes and "onNotice(name, parsed)" in changes
    # Back by itself: it waits on the deploy fresh.js asks for, and reloads only for a new one.
    assert "await serving()" in updating and "checkForUpdate({ force: true })" in updating
    # Nothing to press, and never the browser's own window.
    assert "<button" not in updating and not re.search(r"\b(alert|confirm|prompt)\(", updating)


def test_the_menu_alone_is_drawn_again_and_a_new_tab_gets_attention():
    quills = (WEB / "quills.js").read_text()
    sheet = (WEB / "updating.css").read_text()
    assert "export function quillsMoved()" in quills and "markArrived(before)" in quills
    assert 'classList.add("tab-arrived")' in quills
    assert "@keyframes tab-arrived" in sheet and "@keyframes updating-hop" in sheet
    assert "prefers-reduced-motion" in sheet
    assert '@import "./updating.css";' in (WEB / "app.css").read_text()
