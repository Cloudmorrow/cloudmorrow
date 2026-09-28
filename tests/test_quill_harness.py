"""The harness a Quill's own tests use (`cloudmorrow.quill.testing`), on the fleet fixture.

These are the tests a Quill author writes, run here so the harness itself
is held to what docs/QUILLCODE.md promises of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudmorrow.quill.testing import Harness, HandlerFailed
from tests.conftest import QUILL_CATALOG

FLEET = Path(__file__).parent / "fixtures" / "quill-fleet"
DATAMODELS = QUILL_CATALOG / "datamodels"


@pytest.fixture()
def q():
    with Harness(FLEET, datamodels=DATAMODELS, circles={"Kids": {"vehicle": "read"}}) as harness:
        yield harness


def test_logging_a_service_moves_the_odometer(q):
    van = q.seed("vehicle", name="Van", **{"fleet.odometer": 1000})
    done = q.act("log-service", van, date="2026-09-28", km=1200)
    assert done.ok and done.toast == "Logged Van at 1200 km"
    assert q.get("vehicle", van.id)["fleet.odometer"] == 1200


def test_a_form_it_will_not_take_is_an_error_not_a_crash(q):
    van = q.seed("vehicle", name="Van")
    done = q.act("log-service", van, date="2026-09-28")
    assert not done.ok and done.error == "Km is needed"


def test_a_kid_cannot_log_a_service(q):
    van = q.seed("vehicle", name="Van")
    sam = q.as_user("sam", circles=["Kids"])
    assert sam.act("log-service", van, date="2026-09-28", km=1).refused
    assert sam.act("add-van", name="Mine").refused


def test_the_garage_lists_the_vans(q):
    q.seed("vehicle", name="Van")
    view = q.view("garage")
    assert "Van" in view.text()
    assert view.buttons == ["Add a van"]
    assert view.find("stat")[0]["value"] == "1"


def test_a_webhook_an_api_a_job_and_the_log(q):
    van = q.seed("vehicle", name="Van", registration="AB 1")
    answer = q.webhook("tracker", json={"registration": "AB 1", "km": 77})
    assert answer["status"] == 200 and answer["json"] == {"updated": van.id}
    assert q.api("summary")["json"] == {"vans": 1, "asked_by": "alice"}
    q.run_job("nightly")
    assert any("checked 1 vans" in line for line in q.log)


def test_a_machine_handler_reads_the_folder_it_is_given(q, tmp_path):
    q.seed("vehicle", name="Van", registration="AB 1")
    (tmp_path / "a.csv").write_text("registration,date,km\nAB 1,2026-09-01,10\n", encoding="utf-8")
    assert q.machine("import-exports", folders={"exports": tmp_path}) == {"made": 1}
    assert len(q.list("fleet.visit")) == 1


def test_code_that_raises_fails_the_test_with_its_own_traceback(tmp_path):
    folder = tmp_path / "quill-broken"
    folder.mkdir()
    (folder / "quill.toml").write_text(
        '[quill]\nid = "broken"\nname = "Broken"\nversion = "0.1.0"\ncode = "quill.py"\n'
        '[[actions]]\nid = "go"\nlabel = "Go"\n',
        encoding="utf-8",
    )
    (folder / "quill.py").write_text(
        "from cloudmorrow.quill import action\n\n@action\ndef go(ctx):\n    return 1 / 0\n", encoding="utf-8"
    )
    with Harness(folder, datamodels=DATAMODELS) as q, pytest.raises(HandlerFailed) as failed:
        q.act("go")
    assert "ZeroDivisionError" in str(failed.value) and "quill.py" in str(failed.value)


def test_fetch_is_answered_by_the_test_and_bound_by_the_manifest(tmp_path):
    folder = tmp_path / "quill-weather"
    folder.mkdir()
    (folder / "quill.toml").write_text(
        '[quill]\nid = "weather"\nname = "Weather"\nversion = "0.1.0"\ncode = "quill.py"\n'
        '[[actions]]\nid = "look"\nlabel = "Look"\n[actions.fields]\nurl = "string"\n'
        '[[fetch]]\nhost = "api.example.com"\nwhy = "the forecast"\n',
        encoding="utf-8",
    )
    (folder / "quill.py").write_text(
        "from cloudmorrow.quill import action, toast\n\n"
        "@action\ndef look(ctx, url):\n    return toast(str(ctx.fetch(url).json()['sky']))\n",
        encoding="utf-8",
    )
    with Harness(folder, datamodels=DATAMODELS) as q:
        q.fetch.add("https://api.example.com/today", json={"sky": "blue"})
        assert q.act("look", url="https://api.example.com/today").toast == "blue"
        assert q.act("look", url="https://elsewhere.example.org/").refused
