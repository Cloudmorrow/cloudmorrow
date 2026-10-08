"""`cm circle …` and `cm access`: circles on the command line, against a real server."""

from __future__ import annotations

import httpx
import pytest
import typer
from typer.testing import CliRunner

from cloudmorrow.cli import circle as circle_cli
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from tests.conftest import ADMIN, GUEST, token_for

runner = CliRunner()


@pytest.fixture()
def cm(tasks_quill, monkeypatch):
    """`cm` signed in as whoever `cm.who` names, the administrator to start with."""
    client = tasks_quill
    tokens = {who[0]: token_for(client, *who) for who in (ADMIN, GUEST)}

    def api_for():
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=tokens[invoke.who])
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver")
        return None, api

    monkeypatch.setattr(circle_cli, "client", api_for)
    app = typer.Typer()
    app.add_typer(circle_cli.app, name="circle")
    app.command("access")(circle_cli.access)

    def invoke(*argv: str):
        return runner.invoke(app, list(argv))

    invoke.who = ADMIN[0]
    invoke.circles = client.app.state.cloudmorrow.circles
    return invoke


def test_a_circle_is_made_given_data_and_people(cm):
    made = cm("circle", "add", "Kids")
    assert made.exit_code == 0, made.output
    assert "Made Kids" in made.output
    assert cm("circle", "rule", "Kids", "task", "write").exit_code == 0
    ruled = cm("circle", "rule", "kids", "board", "read")
    assert ruled.exit_code == 0 and "task write" in ruled.output
    assert cm("circle", "join", "Kids", GUEST[0]).exit_code == 0
    kids = cm.circles.get("kids")
    assert kids.rules == {"task": "write", "board": "read"}
    assert kids.members == [GUEST[0]]
    listed = cm("circle", "list")
    assert listed.exit_code == 0
    assert "Kids" in listed.output and "Members" in listed.output


def test_a_rule_of_none_on_star_takes_it_away_and_a_bad_access_is_refused(cm):
    assert cm("circle", "rule", "Members", "secret", "none").exit_code == 0
    assert cm.circles.get("members").rules == {"*": "write", "secret": "none"}
    assert cm("circle", "rule", "Members", "*", "none").exit_code == 0
    assert cm.circles.get("members").rules == {"secret": "none"}
    bad = cm("circle", "rule", "Members", "task", "sometimes")
    assert bad.exit_code == 1 and "write, read or none" in bad.output


def test_leaving_the_last_circle_says_what_that_means(cm):
    left = cm("circle", "leave", "Members", GUEST[0])
    assert left.exit_code == 0, left.output
    assert "in no circle" in left.output
    listed = cm("circle", "list")
    assert "reaching no data" in listed.output and GUEST[0] in listed.output


def test_default_and_delete(cm):
    cm("circle", "add", "Kids")
    assert cm("circle", "default", "Kids").exit_code == 0
    assert cm.circles.get("kids").is_default
    assert cm("circle", "default", "Kids", "--off").exit_code == 0
    assert not cm.circles.get("kids").is_default
    assert cm("circle", "delete", "Kids").exit_code == 0
    gone = cm("circle", "delete", "Kids")
    assert gone.exit_code == 1 and "no circle called" in gone.output


def test_access_is_anybodys_own_and_changing_circles_is_not(cm):
    cm.circles.leave("members", GUEST[0])
    cm.circles.create("Kids", {"task": "read"}, [GUEST[0]])
    cm.who = GUEST[0]
    mine = cm("access")
    assert mine.exit_code == 0, mine.output
    assert "Kids" in mine.output and "task" in mine.output and "read" in mine.output
    refused = cm("circle", "list")
    assert refused.exit_code == 1


def test_somebody_in_no_circle_is_told_so(cm):
    cm.circles.leave("members", GUEST[0])
    cm.who = GUEST[0]
    mine = cm("access")
    assert mine.exit_code == 0 and "no circle" in mine.output


def test_an_administrator_gives_one_person_a_rule_of_their_own(cm):
    cm.circles.leave("members", GUEST[0])
    given = cm("access", GUEST[0], "task", "read")
    assert given.exit_code == 0, given.output
    assert "own rules" in given.output and "task" in given.output and "read" in given.output
    assert cm.circles.rules_of(GUEST[0]) == {"task": "read"}
    theirs = cm("access", GUEST[0])
    assert theirs.exit_code == 0 and "guest's access" in theirs.output
    assert cm("access", GUEST[0], "task", "maybe").exit_code != 0
    assert cm("access", GUEST[0], "task").exit_code != 0
    taken = cm("access", GUEST[0], "task", "-")
    assert taken.exit_code == 0 and "in no circle" in taken.output
    assert cm.circles.rules_of(GUEST[0]) == {}
    # Not for everybody: the guest may look at their own, not give.
    cm.who = GUEST[0]
    assert cm("access", ADMIN[0], "task", "read").exit_code != 0
