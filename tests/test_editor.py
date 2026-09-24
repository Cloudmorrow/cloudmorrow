"""Editor behaviour, driven through a real Textual app."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

pytestmark = pytest.mark.asyncio


class EditorApp(App):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text
        # Every Changed the editor raised, in order. The notes pane autosaves
        # on these, so "did it say so" is a thing worth being able to ask.
        self.changes: list[str] = []

    def compose(self) -> ComposeResult:
        yield LiveMarkdownEditor(self._text, id="editor")

    def on_live_markdown_editor_changed(self, event: LiveMarkdownEditor.Changed) -> None:
        self.changes.append(event.editor.text)


def strip_text(editor: LiveMarkdownEditor, row: int) -> str:
    return editor.render_line(row).text.rstrip()


async def test_typing_inserts_text():
    async with EditorApp().run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("h", "e", "l", "l", "o")
        assert editor.text == "hello"
        assert editor.cursor_col == 5


async def test_cursor_line_is_raw_and_other_lines_render():
    async with EditorApp("# Title\n- **bold** item").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        # Cursor starts on line 0, so line 0 shows source and line 1 is rendered.
        assert strip_text(editor, 0) == "# Title"
        assert strip_text(editor, 1) == "• bold item"
        await pilot.press("down")
        # Leaving line 0 renders it; arriving on line 1 shows its source.
        assert strip_text(editor, 0) == "▎ Title"
        assert strip_text(editor, 1) == "- **bold** item"


async def test_enter_continues_a_bullet_list():
    async with EditorApp("- first").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end", "enter")
        assert editor.text == "- first\n- "
        await pilot.press("s", "e", "c", "o", "n", "d")
        assert editor.text == "- first\n- second"


async def test_enter_continues_a_task_list_unticked():
    async with EditorApp("- [x] done").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end", "enter")
        assert editor.text == "- [x] done\n- [ ] "


async def test_enter_on_empty_list_item_ends_the_list():
    async with EditorApp("- first\n- ").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("down", "end", "enter")
        assert editor.text == "- first\n"


async def test_ordered_lists_increment():
    async with EditorApp("1. one").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end", "enter")
        assert editor.text == "1. one\n2. "


async def test_backspace_joins_lines():
    async with EditorApp("ab\ncd").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("down", "home", "backspace")
        assert editor.text == "abcd"
        assert (editor.cursor_row, editor.cursor_col) == (0, 2)


async def test_backspace_removes_a_whole_indent_stop():
    async with EditorApp("    deep").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("right", "right", "right", "right", "backspace")
        assert editor.text == "  deep"


async def test_toggle_task_cycles_states():
    async with EditorApp("buy milk").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("ctrl+t")
        assert editor.text == "- [ ] buy milk"
        await pilot.press("ctrl+t")
        assert editor.text == "- [x] buy milk"
        await pilot.press("ctrl+t")
        assert editor.text == "- [ ] buy milk"


async def test_undo_and_redo():
    async with EditorApp("start").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end", "!", "ctrl+z")
        assert editor.text == "start"
        await pilot.press("ctrl+y")
        assert editor.text == "start!"


async def test_move_line_and_delete_line():
    async with EditorApp("one\ntwo\nthree").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("down", "alt+up")
        assert editor.text == "two\none\nthree"
        await pilot.press("ctrl+k")
        assert editor.text == "one\nthree"


async def test_code_block_content_is_not_formatted():
    async with EditorApp("```py\nx = '**not bold**'\n```\ntail").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        assert strip_text(editor, 1) == "x = '**not bold**'"
        assert strip_text(editor, 2).startswith("╌╌")


async def test_changed_message_is_posted():
    seen: list[str] = []

    class Watcher(EditorApp):
        def on_live_markdown_editor_changed(self, event: LiveMarkdownEditor.Changed) -> None:
            seen.append(event.editor.text)

    async with Watcher("").run_test() as pilot:
        await pilot.press("x")
        await pilot.pause()
    assert seen == ["x"]


async def test_save_request_message():
    saves: list[int] = []

    class Watcher(EditorApp):
        def on_live_markdown_editor_save_requested(self, _: object) -> None:
            saves.append(1)

    async with Watcher("hi").run_test() as pilot:
        await pilot.press("ctrl+s")
        await pilot.pause()
    assert saves == [1]


async def test_toggle_task_keeps_the_cursor_in_place():
    async with EditorApp("- review PRs").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end", "ctrl+t")
        assert editor.text == "- [ ] review PRs"
        assert editor.cursor_col == len(editor.text)
        await pilot.press("enter")
        assert editor.text == "- [ ] review PRs\n- [ ] "


async def test_ending_a_list_keeps_text_after_the_cursor():
    async with EditorApp("- ").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        editor.cursor_col = 2
        editor.insert_text("tail")
        editor.cursor_col = 2
        await pilot.press("enter")
        assert editor.text == "tail"


async def test_typing_a_list_item_then_toggling_it():
    """The sequence that broke: continue a list, type, toggle, continue again."""
    async with EditorApp("- ship it").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end", "enter")
        for char in "review PRs":
            await pilot.press(char)
        await pilot.press("ctrl+t")
        assert editor.text == "- ship it\n- [ ] review PRs"
        await pilot.press("enter")
        assert editor.text == "- ship it\n- [ ] review PRs\n- [ ] "


# -- pasting -----------------------------------------------------------------
async def paste(pilot, text: str) -> None:
    """What the terminal sends on a bracketed paste."""
    from textual import events

    pilot.app.query_one(LiveMarkdownEditor).post_message(events.Paste(text))
    await pilot.pause()


async def test_pasting_puts_the_text_in():
    async with EditorApp().run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await paste(pilot, "pasted")
        assert editor.text == "pasted"
        assert editor.cursor_col == 6


async def test_pasting_lands_at_the_cursor_not_at_the_end():
    async with EditorApp("before after").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        for _ in range(len("before ")):
            await pilot.press("right")
        await paste(pilot, "MIDDLE ")
        assert editor.text == "before MIDDLE after"


async def test_pasting_several_lines_makes_several_lines():
    async with EditorApp("# Title\n").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("down")
        await paste(pilot, "- one\n- two\n- three")
        assert editor.text == "# Title\n- one\n- two\n- three"
        assert editor.cursor_row == 3
        assert editor.cursor_col == len("- three")


async def test_a_paste_from_anywhere_keeps_this_document_consistent():
    """Windows line endings and hard tabs are not what this editor writes."""
    async with EditorApp().run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await paste(pilot, "one\r\ntwo\rthree\n\tindented")
        assert editor.text == "one\ntwo\nthree\n  indented"


async def test_one_undo_takes_the_whole_paste_back():
    async with EditorApp("kept").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        await pilot.press("end")
        await paste(pilot, " and a long pasted tail")
        assert editor.text == "kept and a long pasted tail"

        await pilot.press("ctrl+z")
        assert editor.text == "kept"


async def test_a_read_only_editor_refuses_a_paste():
    async with EditorApp("locked").run_test() as pilot:
        editor = pilot.app.query_one(LiveMarkdownEditor)
        editor.read_only = True
        await paste(pilot, "nope")
        assert editor.text == "locked"


async def test_pasting_tells_whoever_is_listening_it_changed():
    """The notes pane autosaves on Changed, so a paste has to raise one."""
    async with EditorApp().run_test() as pilot:
        assert pilot.app.changes == []
        await paste(pilot, "something")
        assert pilot.app.changes == ["something"]
