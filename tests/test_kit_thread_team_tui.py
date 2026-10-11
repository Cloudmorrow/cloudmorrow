"""The thread's team bindings in the terminal: threads, mentions, reactions and pins.

The same fake server the Chat tests drive, with Chat's screen given the four
bindings Channels has (the tab, the feature and the key stay Chat's, so the
rest of the harness is untouched): a reply is drawn under its line, an @name
is lit, reactions are counted under a line and toggled, a pin is set and
shown — each through the pickers the keys r, x and p open.
"""

from __future__ import annotations

import copy

from textual.widgets import DataTable, Static

from cloudmorrow.tui.panes.kit_thread import EMOJI, PickEmojiModal, PickLineModal, ThreadPane, render_lines, tally
from cloudmorrow.tui.screens.modals import PromptModal
from tests.tui_chat import CHAT_MODELS, CHAT_SCREEN, line_row, space_row
from tests.tui_harness import settle, start
from tests.tui_quills import record_row

REACTION_MODEL = {
    "id": "reaction",
    "version": 1,
    "label": "Reaction",
    "description": "One person's emoji on a message.",
    "domain": "messaging",
    "scopes": ["shared", "public"],
    "title": "emoji",
    "ordered_within": [],
    "source": "foundation",
    "space": False,
    "in_space": "channel",
    "authored": True,
    "notify": [],
    "fields": [
        {"name": "channel", "kind": "link", "label": "Channel", "required": True, "indexed": True, "to": "channel"},
        {"name": "message", "kind": "link", "label": "Message", "required": True, "indexed": True, "to": "message"},
        {"name": "emoji", "kind": "string", "label": "Emoji", "required": True},
    ],
}


def team_models() -> dict:
    models = copy.deepcopy(CHAT_MODELS)
    models["message"]["fields"] += [
        {"name": "reply_to", "kind": "link", "label": "Reply to", "indexed": True, "to": "message"},
        {"name": "pinned", "kind": "bool", "label": "Pinned", "indexed": True, "default": False, "managed": True},
    ]
    models["reaction"] = copy.deepcopy(REACTION_MODEL)
    return models


TEAM_SCREEN = {**CHAT_SCREEN, "reply_to": "reply_to", "pinned": "pinned", "reactions": "reaction", "mentions": True}


def make_team(app) -> None:
    """Chat's Quill in the fake, with the team's four on its screen."""
    for quill in app.client.quill_list:
        if quill["id"] == "chat":
            quill["screens"] = [copy.deepcopy(TEAM_SCREEN)]
            quill["models"] = team_models()
            quill["uses"] = ["channel", "message", "reaction"]
    app.client.record_store.setdefault("reaction", [])


def reaction_row(record_id: str, space: str, line: str, owner: str, emoji: str) -> dict:
    row = record_row("reaction", record_id, 0, channel=space, message=line, emoji=emoji)
    row.update(owner=owner, scope="public")
    return row


async def open_chat(app, pilot):
    screen = await start(app, pilot)
    await pilot.press("f4")
    await settle(app, pilot)
    return screen, screen.query_one(ThreadPane)


def text_of(pane, selector: str) -> str:
    return pane.query_one(selector, Static).visual.plain


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


# -- what a conversation looks like ---------------------------------------------------
def test_a_reply_is_drawn_under_its_line_and_a_pin_is_marked():
    lines = [
        line_row("a", "s", "guest", "lunch?", "2026-09-19T14:00:00+00:00"),
        line_row("b", "s", "bram", "yes", "2026-09-19T14:01:00+00:00"),
        line_row("c", "s", "guest", "where", "2026-09-19T14:02:00+00:00"),
    ]
    lines[1]["fields"]["reply_to"] = "a"
    lines[2]["fields"]["pinned"] = True
    drawn = render_lines(lines, "body", "bram", reply_to="reply_to", pinned="pinned")
    assert drawn.index("lunch?") < drawn.index("↳") < drawn.index("yes") < drawn.index("where")
    assert "📌" in drawn and drawn.index("📌") < drawn.index("where")
    # Without the binding a reply is a line like any other, in its place.
    plain = render_lines(lines, "body", "bram")
    assert "↳" not in plain and plain.index("yes") < plain.index("where")


def test_a_mention_is_lit_and_brackets_stay_brackets():
    lines = [line_row("a", "s", "guest", "@bram look at [this]", "2026-09-19T14:00:00+00:00")]
    drawn = render_lines(lines, "body", "bram", mentions=True)
    assert "]@bram[/]" in drawn and "\\[this]" in drawn
    assert "]@bram[/]" not in render_lines(lines, "body", "bram")


def test_reactions_are_counted_under_a_line_with_yours_marked():
    reactions = [
        reaction_row("r1", "s", "a", "guest", "👍"),
        reaction_row("r2", "s", "a", "bram", "👍"),
        reaction_row("r3", "s", "a", "guest", "🎉"),
        reaction_row("r4", "s", "b", "guest", "👀"),
    ]
    counted = tally(reactions, "message", "bram")
    assert counted["a"] == [("👍", 2, True), ("🎉", 1, False)] and counted["b"] == [("👀", 1, False)]
    lines = [line_row("a", "s", "guest", "shipped", "2026-09-19T14:00:00+00:00")]
    drawn = render_lines(lines, "body", "bram", reactions=counted)
    assert "👍 2" in drawn and "🎉 1" in drawn and drawn.index("shipped") < drawn.index("👍 2")


# -- the pane ---------------------------------------------------------------------------
async def test_the_keys_are_offered_only_with_the_bindings(app):
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        assert {"reply", "react", "pin"} <= pane.refused


async def test_a_reply_goes_in_its_parents_thread(app):
    make_team(app)
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        assert not {"reply", "react", "pin"} & pane.refused
        pane.focus()
        await pilot.press("r")
        await breathe(pilot)
        picker = app.screen
        assert isinstance(picker, PickLineModal)
        assert [line["id"] for line in picker.lines] == ["r_m1", "r_m2"]
        picker.dismiss("r_m1")
        await breathe(pilot)
        assert isinstance(app.screen, PromptModal)
        app.screen.dismiss("turn them off then")
        await settle(app, pilot)
        sent = app.client.record_store["message"][-1]
        assert sent["fields"]["reply_to"] == "r_m1" and sent["fields"]["channel"] == "r_general"
        drawn = text_of(pane, "#conversation-text")
        assert drawn.index("the fans are loud again") < drawn.index("↳") < drawn.index("turn them off then")


async def test_a_reaction_is_toggled_and_shown(app):
    make_team(app)
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("x")
        await breathe(pilot)
        app.screen.dismiss("r_m2")
        await breathe(pilot)
        assert isinstance(app.screen, PickEmojiModal) and app.screen.mine == set()
        app.screen.dismiss(EMOJI[0])
        await settle(app, pilot)
        made = app.client.record_store["reaction"][-1]
        assert made["fields"] == {"channel": "r_general", "message": "r_m2", "emoji": "👍"}
        assert "👍 1" in text_of(pane, "#conversation-text")
        # Yours again takes it back.
        pane.focus()
        await pilot.press("x")
        await breathe(pilot)
        app.screen.dismiss("r_m2")
        await breathe(pilot)
        assert app.screen.mine == {"👍"}
        app.screen.dismiss("👍")
        await settle(app, pilot)
        assert app.client.record_store["reaction"] == []
        assert "👍" not in text_of(pane, "#conversation-text")


async def test_a_line_is_pinned_and_marked(app):
    make_team(app)
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        pane.focus()
        await pilot.press("p")
        await breathe(pilot)
        app.screen.dismiss("r_m2")
        await settle(app, pilot)
        row = next(r for r in app.client.record_store["message"] if r["id"] == "r_m2")
        assert row["fields"]["pinned"] is True
        assert "📌" in text_of(pane, "#conversation-text")


async def test_what_arrives_in_a_thread_is_drawn_on_the_next_poll(app):
    make_team(app)
    app.client.record_store["channel"].append(space_row("r_x", "x", "public", at="2026-08-01T09:00:00+00:00"))
    async with app.run_test(size=(120, 36)) as pilot:
        _, pane = await open_chat(app, pilot)
        reply = line_row("r_new", "r_general", "guest", "under it", "2026-09-21T09:00:00+00:00")
        reply["fields"]["reply_to"] = "r_m1"
        app.client.record_store["message"].append(reply)
        app.client.record_store["reaction"].append(reaction_row("r_r", "r_general", "r_m2", "guest", "✅"))
        pane.catch_up()
        await settle(app, pilot)
        drawn = text_of(pane, "#conversation-text")
        assert "under it" in drawn and "✅ 1" in drawn
        assert pane.query_one("#space-table", DataTable).row_count == 3
