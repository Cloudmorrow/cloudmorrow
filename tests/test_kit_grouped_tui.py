"""The kit's list, picked through, in the terminal: groups, a subgroup, and a hidden field.

Drawn for the Secrets Quill in the fake server (tests/tui_quills.py) — a
`list` of `secret` grouped by vault and then environment, whose value is a
`secret` field — but nothing the pane does is about secrets: these are the
promises the kit makes for any list with a group and a hidden field.

A dialog open holds its worker open, so while one is up these wait with two
pauses rather than `settle()`.
"""

from __future__ import annotations

from textual.widgets import Input

from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_grouped import MASK, GroupedListPane
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from tests.tui_harness import open_secrets, settle
from tests.tui_quills import READING_QUILL, SECRETS_QUILL


async def breathe(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def test_only_a_grouped_or_hiding_list_is_drawn_here():
    assert isinstance(pane_for(SECRETS_QUILL, SECRETS_QUILL["screens"][0]), GroupedListPane)
    assert not isinstance(pane_for(READING_QUILL, READING_QUILL["screens"][0]), GroupedListPane)


async def test_a_new_record_goes_into_the_group_and_subgroup_on_screen(app):
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(GroupedListPane)
        pane.stand(0, "verticore")
        await settle(app, pilot)
        await pilot.click("#sub-production")
        await settle(app, pilot)

        await pilot.click("#pane-secrets #do-new_record")
        await breathe(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        # The screen names its fields, so the sheet shows those, in that order.
        rows = [row.query_one(".sheet-label").visual.plain for row in sheet.query(".sheet-row")]
        assert rows == ["Key *", "Value", "Vault *", "Environment *"]
        assert sheet.query_one("#field-vault", Input).value == "verticore"
        assert sheet.query_one("#field-environment", Input).value == "production"
        value = sheet.query_one("#field-value", Input)
        assert value.password is True
        sheet.query_one("#field-key", Input).value = "DATABASE_URL"
        value.value = "postgres://db "
        await pilot.press("ctrl+s")
        await breathe(pilot)
        await settle(app, pilot)

        made = app.client.record_store["secret"][-1]["fields"]
        # Exactly as typed: a secret's trailing space is part of it.
        assert (made["vault"], made["environment"], made["key"], made["value"]) == (
            "verticore", "production", "DATABASE_URL", "postgres://db ")
        assert [r["fields"]["key"] for r in pane.records] == ["STRIPE_KEY", "DATABASE_URL"]


async def test_the_sheet_shows_a_hidden_field_only_on_ctrl_r(app):
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(GroupedListPane)
        assert app.client.record_reads == []
        pane.query_one("#kit-table").focus()
        await pilot.press("enter")
        await breathe(pilot)
        sheet = app.screen
        assert isinstance(sheet, RecordSheet)
        # The listing had no value; the sheet asked for the one record.
        assert app.client.record_reads == [("secret", "s_wifi")]
        box = sheet.query_one("#field-value", Input)
        assert box.value == "hunter2" and box.password is True
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert box.password is False
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert box.password is True
        sheet.action_cancel()
        await settle(app, pilot)


async def test_copy_fetches_the_value_without_showing_it(app):
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(GroupedListPane)
        pane.query_one("#kit-table").focus()
        await pilot.press("c")
        await settle(app, pilot)
        assert app._clipboard == "hunter2"
        assert pane.revealed == {}
        assert MASK in str(pane.query_one("#kit-table").get_row_at(0)[1])


async def test_a_new_environment_is_a_button_before_it_holds_anything(app):
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(GroupedListPane)
        await pilot.click("#sub-new")
        await breathe(pilot)
        for key in "staging":
            await pilot.press(key)
        await pilot.press("enter")
        await breathe(pilot)
        await settle(app, pilot)
        assert pane.chosen == ["homelab", "staging"]
        assert pane.query("#sub-staging")
        assert pane.records == []
