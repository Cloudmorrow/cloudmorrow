"""The kit's `editor` in the terminal: the Notes Quill's tab, drawn from its screen.

Everything the old Notes pane did, through the record API: the tree with
its folders (empty ones too), new pages and folders, renaming and moving,
deleting a folder and what is in it, search, a page changed elsewhere, and
the workspace opening on it. The modal waits are two `pilot.pause()`s:
`settle()` hangs while a dialog is open.
"""

from __future__ import annotations

from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_editor import EditorPane
from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from cloudmorrow.tui.widgets.note_tree import NoteTree
from tests.tui_harness import settle, start
from tests.tui_notes import NOTES_QUILL, note_id


def _paths(tree: NoteTree) -> list[str]:
    found = []

    def walk(node) -> None:
        for child in node.children:
            found.append(child.data["path"] + ("/" if child.data["is_dir"] else ""))
            walk(child)

    walk(tree.root)
    return found


async def _modal(pilot) -> None:
    await pilot.pause()
    await pilot.pause()


def test_the_notes_screen_is_an_editor_pane():
    pane = pane_for(NOTES_QUILL, NOTES_QUILL["screens"][0], tab_key="f1", id="pane-notes")
    assert isinstance(pane, EditorPane)
    assert (pane.title_field, pane.body_field, pane.path_field) == ("title", "body", "path")
    assert pane.keeps_folders and pane.searches and pane.attaches
    assert [a.id for a in pane.ACTIONS][:3] == ["new_page", "new_folder", "search"]


async def test_the_workspace_opens_on_notes_with_its_folders(app):
    app.client.note_files["Projects/Garden/beds"] = ["raised\n", 1]
    app.client.note_folders.add("Archive")
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert screen.query_one("#panes").current == "pane-notes"
        tree = screen.query_one(NoteTree)
        # Folders first, the empty one too; then the pages.
        assert _paths(tree) == [
            "Archive/", "Projects/", "Projects/Garden/", "Projects/Garden/beds", "architecture",
        ]
        assert str(tree.root.label) == "notes"


async def test_a_new_page_is_made_in_the_folder_selected(app):
    app.client.note_folders.add("Ideas")
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        pane.new_page("Ideas")
        await _modal(pilot)
        await pilot.press(*"garden", "enter")
        await settle(app, pilot)
        assert app.client.note_files["Ideas/garden"][0] == "# garden\n\n"
        assert pane.current_path == "Ideas/garden"
        assert screen.query_one(LiveMarkdownEditor).text == "# garden\n\n"


async def test_typing_saves_with_the_rev_it_read(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        pane.open_page(note_id("architecture"))
        await settle(app, pilot)
        editor = screen.query_one(LiveMarkdownEditor)
        editor.cursor_row, editor.cursor_col = 1, 0
        editor.insert_text("hello")
        await pilot.pause()
        await pane.flush()
        await settle(app, pilot)
        assert app.client.note_files["architecture"][0].startswith("# Architecture\nhello")
        assert not pane.dirty


async def test_a_page_changed_elsewhere_asks_before_writing_over_it(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        pane.open_page(note_id("architecture"))
        await settle(app, pilot)
        app.client.note_files["architecture"] = ["theirs\n", 7]  # somebody else saved
        screen.query_one(LiveMarkdownEditor).insert_text("mine ")
        pane.save_page()
        await _modal(pilot)
        assert app.screen.__class__.__name__ == "ConflictModal"
        await pilot.press("escape")
        await settle(app, pilot)
        assert app.client.note_files["architecture"][0] == "theirs\n"


async def test_a_folder_is_made_renamed_and_deleted(app):
    app.client.note_files["Plans/one"] = ["1", 1]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        pane.new_folder("")
        await _modal(pilot)
        await pilot.press(*"Archive", "enter")
        await settle(app, pilot)
        assert "Archive/" in _paths(screen.query_one(NoteTree))
        pane.rename("Plans", True)
        await _modal(pilot)
        await pilot.press("ctrl+u", *"Later", "enter")
        await settle(app, pilot)
        assert "Later/one" in app.client.note_files
        pane.delete("Later", True)
        await _modal(pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        assert "Later/one" not in app.client.note_files
        assert ("rmdir", "Later") in app.client.note_calls


async def test_a_page_moves_by_its_path(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        pane.open_page(note_id("architecture"))
        await settle(app, pilot)
        pane.rename("architecture", False)
        await _modal(pilot)
        await pilot.press("ctrl+u", *"docs/architecture", "enter")
        await settle(app, pilot)
        assert "docs/architecture" in app.client.note_files
        # The open page follows it: its path and its id are the new ones.
        assert pane.current_path == "docs/architecture"
        assert pane.current_id == note_id("docs/architecture")


async def test_search_finds_a_line_and_opens_the_page(app):
    app.client.note_files["plants"] = ["Tomatoes in June.\n", 1]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        pane = screen.query_one(EditorPane)
        found = await pane._search("tomatoes")
        assert found == {"results": [{"path": "plants", "matches": [{"text": "Tomatoes in June."}]}]}
        pane.search()
        await _modal(pilot)
        await pilot.press(*"tomatoes")
        await _modal(pilot)
        await pilot.press("enter", "enter")
        await settle(app, pilot)
        assert pane.current_path == "plants"


async def test_without_notes_installed_the_workspace_opens_on_the_first_card(app):
    app.client.quill_list = [q for q in app.client.quill_list if q["id"] != "notes"]
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        assert not screen.query("#pane-notes")
        # Tasks is the first card there is now.
        assert screen.query_one("#panes").current == "pane-tasks"
