"""Administration → Quills in the terminal: what a Quill's code is doing, and the buttons."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from cloudmorrow.tui.panes.admin_quill_services import QuillServicesModal, services_text
from cloudmorrow.tui.panes.admin_quills import QuillsView
from tests.tui_harness import settle, start

RUNNING = {
    "id": "tasks",
    "name": "Tasks",
    "runs_as": "bram",
    "enabled": True,
    "reach": ["board", "task"],
    "token": {"issued_at": "2026-09-26T08:00:00+00:00", "last_used_at": ""},
    "services": [{
        "id": "sync", "command": ["python", "services/sync.py"], "always": True,
        "scheduled": False, "state": "restarting", "since": "2026-09-26T08:01:00+00:00",
        "problem": "exited with 1; again in 2s", "pid": None, "port": None,
        "last_exit": 1, "last_exit_at": "2026-09-26T08:01:00+00:00", "restarts": 2,
        "log": ["-- started python services/sync.py", "Traceback: [boom]"],
    }],
    "jobs": [{"id": "nightly", "service": "sync", "every": "1d", "running": False,
              "last_started": "", "last_exit": None}],
    "webhooks": [{"id": "inbound", "path": "inbound", "model": "task", "forward": "",
                  "signature": "", "secret": "s3cret",
                  "url": "https://cloud.example/hooks/tasks/inbound"}],
    "apis": [],
}


def test_what_runs_is_said_with_its_state_log_and_webhook_address():
    text = Text.from_markup(services_text(RUNNING)).plain
    assert "runs as bram" in text and "can read and write only: board, task" in text
    assert "restarting" in text and "exited with 1; again in 2s" in text
    assert "python services/sync.py" in text and "restarts 2" in text
    # The log is shown as written: brackets are not markup.
    assert "Traceback: [boom]" in text
    assert "runs sync every 1d; last never yet" in text
    assert "https://cloud.example/hooks/tasks/inbound?token=s3cret" in text


def test_a_quill_nobody_can_run_as_says_so():
    text = Text.from_markup(services_text(dict(RUNNING, runs_as="", enabled=False))).plain
    assert "runs as nobody" in text and "Switched off" in text


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


async def test_running_opens_what_a_quills_code_is_doing_and_rotates(app):
    app.client.running = [RUNNING]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.press("f9")
        await settle(app, pilot)
        await pilot.click("#nav-admin-quills")
        await settle(app, pilot)
        view = screen.query_one(QuillsView)
        view.query_one("#admin-quill-table").focus()
        await pilot.press("r")
        await breathe(pilot)
        assert isinstance(app.screen, QuillServicesModal)
        shown = str(app.screen.query_one("#quill-services-text", Static).render())
        assert "restarting" in shown
        await pilot.click("#token")
        await breathe(pilot)
        await pilot.click("#secrets")
        await breathe(pilot)
        assert ("token", "tasks") in app.client.quill_calls
        assert ("secret", "tasks", "inbound") in app.client.quill_calls
        await pilot.click("#close")
        await breathe(pilot)
        assert not isinstance(app.screen, QuillServicesModal)
