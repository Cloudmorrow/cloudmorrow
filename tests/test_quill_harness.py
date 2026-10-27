"""The harness a Quill's own tests use (`cloudmorrow.quill.testing`), on the fleet fixture.

These are the tests a Quill author writes, run here so the harness itself
is held to what docs/QUILLCODE.md promises of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudmorrow.quill.testing import HandlerFailed, Harness
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


def test_two_quills_with_code_in_one_interpreter_each_run_their_own(tmp_path):
    """In a test (and trusted mode) one Python loads one Quill after another."""
    other = tmp_path / "quill-other"
    other.mkdir()
    (other / "quill.toml").write_text(
        '[quill]\nid = "other"\nname = "Other"\nversion = "0.1.0"\ncode = "quill.py"\n'
        '[[actions]]\nid = "hello"\nlabel = "Hello"\n',
        encoding="utf-8",
    )
    (other / "quill.py").write_text(
        "from cloudmorrow.quill import action, toast\n\n@action\ndef hello(ctx):\n    return toast('other')\n",
        encoding="utf-8",
    )
    with Harness(FLEET, datamodels=DATAMODELS) as fleet, Harness(other, datamodels=DATAMODELS) as q:
        assert q.act("hello").toast == "other"
        assert fleet.act("add-van", name="Van").toast == "Added Van"
        assert q.act("hello").toast == "other"


# -- spaces from code: a thread made shared with its people, and looked in ----------------
def _letters(tmp_path):
    """A Quill whose code makes a shared space with people in it, and writes in it."""
    folder = tmp_path / "quill-letters"
    (folder / "datamodels").mkdir(parents=True)
    (folder / "quill.toml").write_text(
        '[quill]\nid = "letters"\nname = "Letters"\nversion = "0.1.0"\ncode = "quill.py"\n'
        '[[screens]]\nid = "post"\nlabel = "Post"\nview = "post"\nmodel = "letters.letter"\n'
        '[[screens]]\nid = "one"\nlabel = "One"\nview = "one"\nmodel = "letters.letter"\n'
        '[[actions]]\nid = "write"\nlabel = "Write"\n[actions.fields]\n'
        'to = { kind = "string", required = true }\nsubject = { kind = "string", required = true }\n'
        '[[actions]]\nid = "answer"\nlabel = "Answer"\non = "letters.letter"\n'
        '[[actions]]\nid = "looked"\nlabel = "Looked"\non = "letters.letter"\n',
        encoding="utf-8",
    )
    (folder / "datamodels" / "letter.toml").write_text(
        '[datamodel]\nid = "letters.letter"\nversion = 1\nlabel = "Letter"\ndescription = "A letter."\n'
        'scopes = ["personal", "shared"]\ntitle = "subject"\nspace = true\n'
        '[fields]\nsubject = { kind = "string", required = true }\n',
        encoding="utf-8",
    )
    (folder / "datamodels" / "line.toml").write_text(
        '[datamodel]\nid = "letters.line"\nversion = 1\nlabel = "Line"\ndescription = "A line of a letter."\n'
        'scopes = ["personal", "shared"]\ntitle = "body"\nin_space = "letter"\nauthored = true\n'
        '[fields]\nletter = { kind = "link", to = "letters.letter", required = true, indexed = true,'
        ' on_delete = "cascade" }\n'
        'body = { kind = "text", required = true }\n'
        '[[notify]]\nwhen = "created"\nto = "members"\nunread = true\n',
        encoding="utf-8",
    )
    (folder / "quill.py").write_text(
        "from cloudmorrow.quill import action, toast, ui, view\n\n"
        "@action\ndef write(ctx, to, subject):\n"
        "    people = [p for p in to.split(',') if p in ctx.people()]\n"
        "    made = ctx.records.create('letters.letter', subject=subject, scope='shared', members=people)\n"
        "    ctx.records.create('letters.line', letter=made.id, body='hello ' + ', '.join(people))\n"
        "    return toast(f'{made.id}: {len(made.members)} people')\n\n"
        "@action\ndef answer(ctx, letter):\n"
        "    ctx.records.create('letters.line', letter=letter.id, body='and hello back')\n\n"
        "@action\ndef looked(ctx, letter):\n"
        "    ctx.records.seen('letters.letter', letter.id)\n\n"
        "@view\ndef post(ctx):\n"
        "    letters = ctx.records.list('letters.letter')\n"
        "    return ui.stack(\n"
        "        ui.text(', '.join(f'{x[\"subject\"]} {x.unread}' for x in letters)),\n"
        "        ui.table(letters, columns=['subject'], go='one', param='letter'),\n"
        "    )\n\n"
        "@view\ndef one(ctx):\n"
        "    return ui.text(ctx.params.get('letter') or '')\n",
        encoding="utf-8",
    )
    return folder


def test_code_makes_a_shared_space_with_its_people_and_sees_what_is_unread(tmp_path):
    with Harness(_letters(tmp_path), datamodels=DATAMODELS) as q:
        sam = q.as_user("sam")
        kim = q.as_user("kim")
        assert sam.act("write", to="kim,nobody", subject="Lunch").toast.endswith(": 1 people")
        (letter,) = kim.list("letters.letter")
        assert letter["subject"] == "Lunch" and letter.scope == "shared" and sorted(letter.members) == ["kim"]
        assert [line["body"] for line in kim.list("letters.line", letter=letter.id)] == ["hello kim"]
        assert q.list("letters.letter") == []  # the administrator was not written to
        # Written to, and not yet looked at: unread, until the code says the person looked.
        assert "Lunch 1" in kim.view("post").text()
        assert kim.act("looked", letter).ok
        assert "Lunch 0" in kim.view("post").text()
        # An answer in the same space reaches the writer, as news.
        assert kim.act("answer", letter).ok
        assert "Lunch 1" in sam.view("post").text()
        # The table's rows go to the Quill's own screen, with the letter's id.
        (table,) = kim.view("post").find("table")
        assert table["go"] == "one" and table["param"] == "letter"
        assert kim.view("one", letter=letter.id).text().strip() == letter.id


def test_code_lists_everybody_on_the_server_but_the_person(tmp_path):
    with Harness(_letters(tmp_path), datamodels=DATAMODELS) as q:
        q.as_user("sam")
        q.as_user("kim")
        assert q.as_user("sam").act("write", to="kim,sam,admin", subject="Who").toast.endswith("1 people")
