"""The workspace, driven the way it is meant to be: with a mouse.

Every one of these clicks something rather than pressing a key, because that
is the claim the TUI makes — the pointer is a first-class way to use it, and
the shortcuts are the accelerator.
"""

from __future__ import annotations

from cloudmorrow.tui.panes.notes import NotesPane
from cloudmorrow.tui.panes.secrets import SecretsPane
from cloudmorrow.tui.widgets.note_tree import NoteTree
from cloudmorrow.tui.widgets.sidebar import NavCard
from cloudmorrow.tui.widgets.vault_list import VaultList
from tests.tui_harness import PRESS_ANIMATION, open_secrets, settle, start


async def test_the_workspace_opens_on_notes(app):
    """Notes is the first tab, and the one you land on: it is what you open this for."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#panes").current == "pane-notes"
        assert isinstance(screen.active_pane, NotesPane)
        # Landed, and the tree is already there to be clicked.
        assert [node.data["path"] for node in screen.query_one(NoteTree).root.children] == [
            "architecture.md"
        ]
        # Up top: whose cloud this is, and what it is — and the dev marker
        # when it is the checkout running. No vault: there is none the app is "in".
        top = screen.query_one("#topbar-left").visual.plain
        # A `dev` badge follows when the checkout is what runs.
        assert top.strip().startswith("BRAM'S CLOUD · cloudmorrow")
        assert "verticore" not in top
        # And the Notes card is the one lit.
        assert screen.query_one("#nav-notes", NavCard).active


async def test_the_top_bar_says_when_it_is_the_checkout_running(app, monkeypatch):
    """`--dev` and the installed client look identical otherwise."""
    from cloudmorrow.cli import dev

    # The tests are the checkout's own code, so the marker is telling the truth.
    monkeypatch.setenv(dev.ENV, str(dev.find_checkout()))
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert "cloudmorrow dev" in screen.query_one("#topbar-left").visual.plain


async def test_the_top_bar_says_nothing_when_it_is_the_installed_one(app, monkeypatch):
    from cloudmorrow.cli import dev

    monkeypatch.delenv(dev.ENV, raising=False)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert "dev" not in screen.query_one("#topbar-left").visual.plain


async def test_clicking_a_tab_switches_pane(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-secrets")
        await settle(app, pilot)
        assert screen.query_one("#panes").current == "pane-secrets"
        assert isinstance(screen.active_pane, SecretsPane)
        listing = screen.query_one(VaultList)
        # Every vault that holds something, alphabetically, and the one the
        # config names is the one picked.
        assert [row.vault for row in listing.query("VaultRow")] == ["homelab", "verticore"]
        assert screen.query_one(SecretsPane).selected_vault == "verticore"

        await pilot.click("#nav-notes")
        await settle(app, pilot)
        assert isinstance(screen.active_pane, NotesPane)


async def test_secrets_is_a_card_of_its_own(app):
    """A secret is yours, so it is reached the way notes are: from the sidebar."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        # Each card carries the key that brings it here, which is why the
        # footer does not repeat them; your cloud first, then the Quills.
        cards = [
            (card.name_text, card.tag)
            for card in screen.query(NavCard)
            if card.display and not card.has_class("admin-card")
        ]
        assert cards == [
            ("Notes", "f1"),
            ("Calendar", "f7"),
            ("Chat", "f6"),
            ("Secrets", "f3"),
            ("Tasks", "f2"),
            ("Files", "f5"),
        ]


async def test_a_card_says_how_its_place_is(app):
    """The Quill's card counts its first lane; a built-in says what it is until loaded."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#nav-tasks", NavCard).status_line == "2 to do"
        assert screen.query_one("#nav-secrets", NavCard).status_line == "keys, sealed"


async def test_the_sidebar_narrows_on_a_narrow_terminal(app):
    async with app.run_test(size=(84, 30)) as pilot:
        screen = await start(app, pilot)
        assert screen.has_class("-narrow")
        assert screen.query_one("#nav-notes", NavCard).has_class("-line")


async def test_what_is_said_goes_in_the_log_with_the_time(app):
    from cloudmorrow.tui.widgets.logstrip import LogStrip

    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        screen.set_status("saved it")
        await pilot.pause()
        log = screen.query_one(LogStrip)
        assert [line.text for line in log.lines][-1] == "saved it"
        # And the machines' notifications are in there too.
        assert "omarchy config changed on desktop" in [line.text for line in log.lines]


async def test_clicking_a_vault_moves_nothing_but_the_pane(app):
    """Picking one shows it here. It is not a mode the app goes into."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(SecretsPane)
        rows = list(screen.query("VaultRow"))
        await pilot.click(rows[0])  # homelab
        await settle(app, pilot)
        assert pane.selected_vault == "homelab"
        assert screen.query_one("#vault-name").visual.plain.strip() == "homelab"
        assert [secret["key"] for secret in pane._secrets] == ["WIFI_PASSWORD"]
        # Nothing outside the pane heard about it: no scope on the client,
        # the CLI's own default left exactly as it was, nothing up top.
        assert app.client.vault is None
        assert app.client_config.vault == "verticore"
        assert "homelab" not in screen.query_one("#topbar-left").visual.plain


async def test_a_new_vault_is_a_row_before_it_holds_anything(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(SecretsPane)
        pane.select("work")
        await settle(app, pilot)
        assert pane.selected_vault == "work"
        assert [row.vault for row in screen.query("VaultRow")] == ["homelab", "verticore", "work"]
        assert pane._secrets == []
        assert "work · local" in screen.query_one("#secret-empty").visual.plain


async def test_clicking_an_environment_shows_that_environment(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(SecretsPane)
        assert pane.environment == "local"

        await pilot.click("#env-production")
        await settle(app, pilot)
        assert pane.environment == "production"
        assert [secret["key"] for secret in pane._secrets] == ["STRIPE_KEY"]


async def test_a_value_is_only_fetched_when_it_is_asked_for(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_secrets(app, pilot)
        pane = screen.query_one(SecretsPane)
        # Listing a whole environment reads no values at all.
        assert app.client.read_keys == []

        await pilot.click("#do-reveal")
        await settle(app, pilot)
        assert app.client.read_keys == [("API_URL", "local", "verticore")]
        assert pane._revealed == {"API_URL": "the-actual-value"}

        # Revealing again puts it away, without another round trip.
        await settle(app, pilot, delay=PRESS_ANIMATION)
        await pilot.click("#do-reveal")
        await settle(app, pilot)
        assert pane._revealed == {}
        assert len(app.client.read_keys) == 1


async def test_clicking_a_note_opens_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(NotesPane)
        await pilot.click("#note-tree", offset=(4, 2))
        await settle(app, pilot)
        assert pane.current_path == "architecture.md"
        assert pane.query_one("#editor").text.startswith("# Architecture")


async def test_picking_a_vault_leaves_the_open_note_alone(app):
    """Notes are the user's. Which vault you are looking at is not their business."""
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(NotesPane)
        await pilot.click("#note-tree", offset=(4, 2))
        await settle(app, pilot)
        assert pane.current_path == "architecture.md"

        await pilot.click("#nav-secrets")
        await settle(app, pilot)
        rows = list(screen.query("VaultRow"))
        await pilot.click(rows[0])
        await settle(app, pilot)
        assert screen.query_one(SecretsPane).selected_vault == "homelab"
        assert pane.current_path == "architecture.md"
        assert pane.query_one("#editor").text.startswith("# Architecture")
