"""{{name}}'s tests: the real record store and gate, and quill.py, on this machine.

`cm quill test` runs them; `cm quill test --sandbox` runs the same tests
with quill.py in the sandbox, as a server runs it.
"""

import pytest

from cloudmorrow.quill.testing import Harness


@pytest.fixture()
def q():
    with Harness(".") as harness:
        yield harness


def test_adding_an_item_shows_it_in_the_overview(q):
    done = q.act("add", name="Milk")
    assert done.ok and done.toast == "Added Milk"
    view = q.view("overview")
    assert "Milk" in view.text()
    assert view.find("stat")[0]["value"] == "1"


def test_an_item_needs_a_name(q):
    assert q.act("add").error == "Name is needed"


def test_clearing_takes_only_what_is_done(q):
    q.seed("{{id}}.item", name="Milk", done=True)
    q.seed("{{id}}.item", name="Bread")
    assert q.act("clear-done").toast == "Cleared 1"
    assert [item["name"] for item in q.list("{{id}}.item")] == ["Bread"]
