"""A record's history: who did what to it, when, and which fields — never a value.

Every write to the record store leaves a line; a living record keeps its
whole history, and its sheet shows it, so people act under responsibility
and responsibility is visible. The lines are read through the same door as
the record: somebody who cannot see the record cannot see its history.
"""

from __future__ import annotations

import datetime as dt

import pytest

from cloudmorrow.quill.screens import history_said
from cloudmorrow.server.records import Principal, UnknownRecordError
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def api(tasks_quill):
    client = tasks_quill
    headers = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}

    def call(method, path, body=None, *, expect=200, who=headers):
        response = client.request(method, path, json=body, headers=who)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.client = client
    return call


def board_of(api) -> str:
    return api("GET", "/api/records/board")[0]["id"]


def test_every_write_leaves_a_line_with_who_what_and_which_fields(api):
    board = board_of(api)
    made = api("POST", "/api/records/task", {"fields": {"board": board, "title": "Fix the NAS"}}, expect=201)
    api("PATCH", f"/api/records/task/{made['id']}", {"fields": {"title": "Fix the NAS!", "body": "swap the disk"}})
    api("POST", f"/api/records/task/{made['id']}/move", {"fields": {"lane": "doing"}, "index": 0})
    # A change that changes nothing names no field.
    api("PATCH", f"/api/records/task/{made['id']}", {"fields": {"body": "swap the disk"}})
    lines = api("GET", f"/api/records/task/{made['id']}/history")
    assert [(line["action"], line["fields"], line["rev"]) for line in lines] == [
        ("changed", [], 4),
        ("moved", ["lane"], 3),
        ("changed", ["title", "body"], 2),
        ("created", ["board", "title"], 1),
    ]
    assert all(line["by"] == ADMIN[0] and line["by_kind"] == "person" and line["at"] for line in lines)
    # Never a value: the line says which fields, and the record says what they are.
    assert not any("Fix" in str(line) or "disk" in str(line) for line in lines)


def test_history_is_read_through_the_same_door_as_the_record(api):
    board = board_of(api)
    made = api("POST", "/api/records/task", {"fields": {"board": board, "title": "Private"}}, expect=201)
    guest = {"Authorization": f"Bearer {token_for(api.client, *GUEST)}"}
    api("GET", f"/api/records/task/{made['id']}/history", who=guest, expect=404)
    api("GET", "/api/records/task/r_nothing/history", expect=404)


def test_a_living_record_keeps_its_history_and_a_deleted_one_lets_it_go(api):
    store = api.client.app.state.cloudmorrow.records
    board = board_of(api)
    made = api("POST", "/api/records/task", {"fields": {"board": board, "title": "Keep"}}, expect=201)
    api("PATCH", f"/api/records/task/{made['id']}", {"fields": {"title": "Kept"}})
    # The sweep that used to take every old line leaves a living record's alone.
    # (A sweep with a horizon in the future, so every line is old enough to go.)
    assert store.prune_changes(keep=dt.timedelta(seconds=-5)) == 0
    assert len(api("GET", f"/api/records/task/{made['id']}/history")) == 2
    api("DELETE", f"/api/records/task/{made['id']}", expect=204)
    # Gone, its lines serve the feed a while, then go with the sweep.
    assert store.prune_changes(keep=dt.timedelta(seconds=-5)) >= 3
    assert [c for c in store.changes(ADMIN[0]) if c["record_id"] == made["id"]] == []
    with pytest.raises(UnknownRecordError):
        store.history(Principal.person(ADMIN[0], admin=True), "task", made["id"])


def test_the_lines_are_said_in_words_never_values():
    model = {"fields": [{"name": "title", "label": "Title"}, {"name": "lane", "label": "Lane"}, {"name": "body"}]}
    assert history_said({"by": "bram", "by_kind": "person", "action": "created"}, model, me="bram") == "you made it"
    assert history_said({"by": "bram", "by_kind": "person", "action": "created"}, model, me="guest") == "bram made it"
    line = {"by": "bram", "by_kind": "person", "action": "changed", "fields": ["title", "body"]}
    assert history_said(line, model) == "bram changed title and body"
    assert history_said({**line, "fields": ["title", "lane", "body"]}, model) == "bram changed title, lane and body"
    assert history_said({**line, "fields": []}, model) == "bram changed it"
    assert history_said({"by": "bram", "by_kind": "person", "action": "moved", "fields": ["lane"]}, model) == (
        "bram changed lane"
    )
    assert history_said({"by": "bram", "by_kind": "person", "action": "moved"}, model) == "bram moved it"
    assert history_said({"by": "tasks", "by_kind": "quill", "action": "created"}, model) == "the tasks Quill made it"
    assert history_said({"by": "tasks", "by_kind": "dataset", "action": "created"}, model) == "the tasks Quill made it"
    assert history_said({"by": "bram", "by_kind": "assistant", "action": "deleted"}, model) == (
        "an assistant, as bram deleted it"
    )
