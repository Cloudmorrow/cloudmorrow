"""What a screen's bindings mean: the rules the terminal and the command line share."""

from __future__ import annotations

from cloudmorrow.quill import screens

LANES = [("todo", "ToDo"), ("doing", "Doing"), ("done", "Done")]


def test_a_named_done_lane_is_the_done_lane():
    assert screens.done_lane({"done": "doing"}, LANES) == "doing"


def test_without_done_the_last_lane_is_done_as_on_the_web():
    assert screens.done_lane({}, LANES) == "done"
    assert screens.done_lane({"done": "nowhere"}, LANES) == "done"
    assert screens.done_lane({}, []) is None


def test_record_lanes_are_done_by_what_the_finished_one_says():
    rows = [{"id": "r1", "fields": {"won": False}}, {"id": "r2", "fields": {"won": True}}, {"id": "r3", "fields": {}}]
    lanes = [(row["id"], row["id"]) for row in rows]
    assert screens.done_lane({"done": {"won": True}}, lanes, rows) == "r2"


def test_lanes_are_filtered_to_the_group_shown_and_kept_in_order():
    lane_model = {"fields": [{"name": "pipeline", "kind": "link", "to": "pipeline"}]}
    assert screens.lane_filter(lane_model, "pipeline", "p1") == {"pipeline": "p1"}
    assert screens.lane_filter(lane_model, "pipeline", None) == {}
    assert screens.lane_filter(lane_model, "board", "b1") == {}
    rows = [{"id": "b", "position": 2}, {"id": "a", "position": 1}, {"id": "c"}]
    assert [row["id"] for row in screens.in_order(rows)] == ["c", "a", "b"]


def test_a_space_is_called_by_its_title_or_by_the_others_in_it():
    screen = {"made_as": {"direct": {"kind": "dm"}}}
    dm = {"owner": "bram", "members": ["guest"], "fields": {"kind": "dm", "name": ""}}
    room = {"owner": "bram", "members": [], "fields": {"kind": "room", "name": " homelab "}}
    bare = {"owner": "bram", "members": [], "fields": {"kind": "room"}}
    assert screens.space_name(dm, "name", screen, "bram") == "guest"
    assert screens.space_name(dm, "name", screen, "guest") == "bram"
    assert screens.space_name(room, "name", screen, "bram") == "homelab"
    assert screens.space_name(bare, "name", screen, "bram") == "Untitled"


def test_calendar_and_grid_fields_come_from_the_screen():
    model = {"title": "summary", "fields": [{"name": "calendar", "kind": "link", "to": "calendar"}]}
    bound = screens.calendar_fields({"starts": "from", "ends": "to", "space": "calendar"}, model)
    assert (bound["starts"], bound["ends"], bound["space"], bound["title"]) == ("from", "to", "calendar", "summary")
    grid = screens.grid_fields({"folder": "dir", "kind": "type", "size": "bytes"}, {"title": "name"})
    assert (grid["folder"], grid["kind"], grid["size"], grid["title"]) == ("dir", "type", "bytes", "name")
