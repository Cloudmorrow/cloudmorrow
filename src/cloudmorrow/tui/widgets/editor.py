"""A markdown editor that renders every line except the one you are editing.

Leave a line — move the cursor off it — and it snaps from source to rendered
markdown. The line under the cursor stays raw so the markers are editable.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Region, Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip

from cloudmorrow.tui.markdown_render import (
    DEFAULT_THEME,
    Theme,
    code_fence_states,
    render_line,
    render_raw_line,
)

TAB_WIDTH = 2
UNDO_LIMIT = 400
UNDO_COALESCE_SECONDS = 0.6

_LIST_PREFIX_RE = re.compile(r"^(\s*)(?:([-*+])\s+(\[[ xX]\]\s*)?|(\d+)([.)])\s+)")
_WORD_RE = re.compile(r"\w+|\s+|[^\w\s]+")


@dataclass(slots=True)
class _Snapshot:
    lines: tuple[str, ...]
    row: int
    col: int
    at: float = field(default_factory=time.monotonic)


class LiveMarkdownEditor(ScrollView, can_focus=True):
    """Line-oriented markdown editor with live rendering of unfocused lines."""

    DEFAULT_CSS = """
    LiveMarkdownEditor {
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }
    """

    BINDINGS = [
        ("ctrl+z", "undo", "Undo"),
        ("ctrl+y", "redo", "Redo"),
        ("ctrl+k", "delete_line", "Cut line"),
        ("ctrl+t", "toggle_task", "Toggle task"),
    ]

    cursor_row: reactive[int] = reactive(0)
    cursor_col: reactive[int] = reactive(0)
    read_only: reactive[bool] = reactive(False)

    class Changed(Message):
        """The document was edited."""

        def __init__(self, editor: LiveMarkdownEditor) -> None:
            self.editor = editor
            super().__init__()

        @property
        def control(self) -> LiveMarkdownEditor:
            return self.editor

    class CursorMoved(Message):
        def __init__(self, editor: LiveMarkdownEditor, row: int, col: int) -> None:
            self.editor = editor
            self.row = row
            self.col = col
            super().__init__()

    class SaveRequested(Message):
        def __init__(self, editor: LiveMarkdownEditor) -> None:
            self.editor = editor
            super().__init__()

    def __init__(self, text: str = "", *, theme: Theme = DEFAULT_THEME, **kwargs) -> None:
        super().__init__(**kwargs)
        self.theme_colors = theme
        self._lines: list[str] = text.split("\n") or [""]
        self._fence_states: list[bool] = code_fence_states(self._lines)
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._cursor_style = Style.parse("on #1d1f2b")
        self._cursor_cell = Style.parse("reverse")

    # -- document ----------------------------------------------------------
    @property
    def text(self) -> str:
        return "\n".join(self._lines)

    @text.setter
    def text(self, value: str) -> None:
        self.load_text(value)

    def load_text(self, value: str, *, cursor: tuple[int, int] = (0, 0)) -> None:
        """Replace the document without recording undo history."""
        self._lines = value.split("\n") or [""]
        if not self._lines:
            self._lines = [""]
        self._undo.clear()
        self._redo.clear()
        self._after_change(record=False)
        self.cursor_row, self.cursor_col = self._clamp(*cursor)
        self.scroll_to(0, 0, animate=False)
        self.refresh()

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def current_line(self) -> str:
        return self._lines[self.cursor_row]

    def word_count(self) -> int:
        return sum(len(line.split()) for line in self._lines)

    # -- geometry ----------------------------------------------------------
    def _recalc_virtual_size(self) -> None:
        longest = max((len(line) for line in self._lines), default=0)
        self.virtual_size = Size(longest + 2, len(self._lines))

    def _clamp(self, row: int, col: int) -> tuple[int, int]:
        row = max(0, min(row, len(self._lines) - 1))
        col = max(0, min(col, len(self._lines[row])))
        return row, col

    def _after_change(self, *, record: bool = True) -> None:
        self._fence_states = code_fence_states(self._lines)
        self._recalc_virtual_size()
        if record:
            self.post_message(self.Changed(self))
        self.refresh()

    # -- undo --------------------------------------------------------------
    def _snapshot(self) -> _Snapshot:
        return _Snapshot(tuple(self._lines), self.cursor_row, self.cursor_col)

    def _record(self, *, coalesce: bool = False) -> None:
        now = time.monotonic()
        if coalesce and self._undo and now - self._undo[-1].at < UNDO_COALESCE_SECONDS:
            self._undo[-1].at = now
            return
        self._undo.append(self._snapshot())
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def _restore(self, snapshot: _Snapshot) -> None:
        self._lines = list(snapshot.lines)
        self._after_change()
        self.cursor_row, self.cursor_col = self._clamp(snapshot.row, snapshot.col)
        self._scroll_to_cursor()

    def action_undo(self) -> None:
        if not self._undo:
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())

    def action_redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())

    # -- rendering ---------------------------------------------------------
    def _display_text(self, row: int) -> Text:
        """What line *row* looks like on screen: the source while it is being
        edited, the rendered markdown otherwise."""
        raw = self._lines[row]
        if self._is_editing(row):
            return render_raw_line(raw, self.theme_colors)
        in_code = self._fence_states[row] if row < len(self._fence_states) else False
        return render_line(
            raw,
            in_code_block=in_code,
            width=max(self.size.width, 20),
            theme=self.theme_colors,
        )

    def _is_editing(self, row: int) -> bool:
        return row == self.cursor_row and self.has_focus and not self.read_only

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        row = y + scroll_y
        width = self.size.width
        # Every strip gets an explicit background, so rendered lines, blank
        # lines and the padding past end-of-line all look like one surface.
        base = self.rich_style
        if row >= len(self._lines):
            return Strip.blank(width, base)

        raw = self._lines[row]
        in_code = self._fence_states[row] if row < len(self._fence_states) else False
        text = self._display_text(row)
        if self._is_editing(row):
            base += self._cursor_style
            col = min(self.cursor_col, len(raw))
            if col >= len(text.plain):
                text.append(" ")
            text.stylize(self._cursor_cell, col, col + 1)
        elif in_code:
            base += Style.parse(self.theme_colors.code_block)

        strip = Strip(list(text.render(self.app.console)))
        strip = strip.apply_style(base).extend_cell_length(width + scroll_x, base)
        strip = self._highlight_selection(strip, row)
        # Each cell says which character of the line it shows, which is how a
        # mouse sweep across the editor knows what it swept.
        return strip.crop(scroll_x, scroll_x + width).apply_offsets(scroll_x, row)

    def _highlight_selection(self, strip: Strip, row: int) -> Strip:
        """Paint the part of *row* a mouse sweep has selected, if any."""
        selection = self.text_selection
        if selection is None:
            return strip
        span = selection.get_span(row)
        if span is None:
            return strip
        start, end = span
        length = strip.cell_length
        end = length if end == -1 else min(end, length)
        start = min(start, end)
        # Only the background: the text keeps its own colour, the way a
        # selection looks everywhere else. Laid over the line, not under it —
        # every cell already has a background, which would otherwise win.
        highlight = Style(
            bgcolor=self.screen.get_component_rich_style("screen--selection").bgcolor
        )
        selected = Strip(
            list(Segment.apply_style(list(strip.crop(start, end)), post_style=highlight))
        )
        return Strip.join([strip.crop(0, start), selected, strip.crop(end, length)])

    def _scroll_to_cursor(self) -> None:
        self.scroll_to_region(
            Region(self.cursor_col, self.cursor_row, 2, 1), animate=False, force=True
        )

    def watch_cursor_row(self) -> None:
        # Leaving a line is what flips it from source to rendered markdown.
        self.refresh()
        self._notify_cursor()

    def watch_cursor_col(self) -> None:
        self.refresh()
        self._notify_cursor()

    def _notify_cursor(self) -> None:
        if self.is_mounted:
            self.post_message(self.CursorMoved(self, self.cursor_row, self.cursor_col))

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def on_mount(self) -> None:
        self._recalc_virtual_size()

    def on_resize(self, event: events.Resize) -> None:  # noqa: ARG002
        self.refresh()

    # -- mouse -------------------------------------------------------------
    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """What a mouse sweep across the editor copies: the lines as shown.

        The highlight lands on what is on screen, so that is what goes to the
        clipboard — the line being edited as source, every other line as it
        renders. Textual's offsets are rows and columns of those lines, which
        `render_line` stamped on every cell.
        """
        shown = "\n".join(self._display_text(row).plain for row in range(len(self._lines)))
        return selection.extract(shown), "\n"

    def on_mouse_down(self, event: events.MouseDown) -> None:
        scroll_x, scroll_y = self.scroll_offset
        row = event.y + scroll_y
        # Rendered lines are shorter than their source, so clicking a rendered
        # line puts the cursor near — not exactly at — the clicked glyph.
        col = event.x + scroll_x
        self.cursor_row, self.cursor_col = self._clamp(row, col)
        self.focus()
        event.stop()

    # -- editing primitives ------------------------------------------------
    def insert_text(self, value: str) -> None:
        if self.read_only:
            return
        self._record(coalesce=len(value) == 1)
        row, col = self.cursor_row, self.cursor_col
        line = self._lines[row]
        if "\n" in value:
            chunks = value.split("\n")
            head, tail = line[:col], line[col:]
            new_lines = [head + chunks[0], *chunks[1:-1], chunks[-1] + tail]
            self._lines[row : row + 1] = new_lines
            self.cursor_row = row + len(chunks) - 1
            self.cursor_col = len(chunks[-1])
        else:
            self._lines[row] = line[:col] + value + line[col:]
            self.cursor_col = col + len(value)
        self._after_change()
        self._scroll_to_cursor()

    def _delete_range(self, row: int, start: int, end: int) -> None:
        line = self._lines[row]
        self._lines[row] = line[:start] + line[end:]
        self.cursor_col = start

    def action_backspace(self) -> None:
        if self.read_only:
            return
        row, col = self.cursor_row, self.cursor_col
        if col == 0 and row == 0:
            return
        self._record(coalesce=True)
        if col == 0:
            previous = self._lines[row - 1]
            self._lines[row - 1] = previous + self._lines[row]
            del self._lines[row]
            self.cursor_row = row - 1
            self.cursor_col = len(previous)
        else:
            line = self._lines[row]
            # Backspacing through soft-tab indentation removes the whole stop.
            head = line[:col]
            all_indent = not head.strip()
            on_stop = col % TAB_WIDTH == 0 and col >= TAB_WIDTH
            step = TAB_WIDTH if (all_indent and on_stop) else 1
            self._delete_range(row, col - step, col)
        self._after_change()
        self._scroll_to_cursor()

    def action_delete(self) -> None:
        if self.read_only:
            return
        row, col = self.cursor_row, self.cursor_col
        line = self._lines[row]
        if col >= len(line):
            if row == len(self._lines) - 1:
                return
            self._record()
            self._lines[row] = line + self._lines[row + 1]
            del self._lines[row + 1]
        else:
            self._record(coalesce=True)
            self._delete_range(row, col, col + 1)
        self._after_change()

    def action_newline(self) -> None:
        """Enter: split the line, continuing a list when we are inside one."""
        if self.read_only:
            return
        self._record()
        row, col = self.cursor_row, self.cursor_col
        line = self._lines[row]
        head, tail = line[:col], line[col:]
        prefix = ""
        match = _LIST_PREFIX_RE.match(line)
        if match and col >= len(match.group(0)):
            indent, bullet, task, number, delim = match.groups()
            if head.strip() == match.group(0).strip():
                # Empty list item: Enter ends the list instead of continuing it.
                self._lines[row] = indent + tail
                self.cursor_col = len(indent)
                self._after_change()
                return
            if bullet:
                prefix = f"{indent}{bullet} " + ("[ ] " if task else "")
            else:
                prefix = f"{indent}{int(number) + 1}{delim} "
        self._lines[row] = head
        self._lines.insert(row + 1, prefix + tail)
        self.cursor_row = row + 1
        self.cursor_col = len(prefix)
        self._after_change()
        self._scroll_to_cursor()

    def action_indent(self) -> None:
        if self.read_only:
            return
        self._record()
        row = self.cursor_row
        self._lines[row] = " " * TAB_WIDTH + self._lines[row]
        self.cursor_col += TAB_WIDTH
        self._after_change()

    def action_dedent(self) -> None:
        if self.read_only:
            return
        row = self.cursor_row
        line = self._lines[row]
        removed = len(line) - len(line.lstrip(" "))
        if removed == 0:
            return
        self._record()
        removed = min(TAB_WIDTH, removed)
        self._lines[row] = line[removed:]
        self.cursor_col = max(0, self.cursor_col - removed)
        self._after_change()

    def action_delete_line(self) -> None:
        if self.read_only:
            return
        self._record()
        row = self.cursor_row
        if len(self._lines) == 1:
            self._lines[0] = ""
        else:
            del self._lines[row]
        self.cursor_row, self.cursor_col = self._clamp(row, self.cursor_col)
        self._after_change()

    def action_duplicate_line(self) -> None:
        if self.read_only:
            return
        self._record()
        row = self.cursor_row
        self._lines.insert(row + 1, self._lines[row])
        self.cursor_row = row + 1
        self._after_change()

    def action_move_line_up(self) -> None:
        row = self.cursor_row
        if self.read_only or row == 0:
            return
        self._record()
        self._lines[row - 1], self._lines[row] = self._lines[row], self._lines[row - 1]
        self.cursor_row = row - 1
        self._after_change()

    def action_move_line_down(self) -> None:
        row = self.cursor_row
        if self.read_only or row >= len(self._lines) - 1:
            return
        self._record()
        self._lines[row + 1], self._lines[row] = self._lines[row], self._lines[row + 1]
        self.cursor_row = row + 1
        self._after_change()

    def action_toggle_task(self) -> None:
        """Turn the current line into a task, or tick/untick it."""
        if self.read_only:
            return
        self._record()
        row = self.cursor_row
        line = self._lines[row]
        indent = line[: len(line) - len(line.lstrip(" "))]
        body = line.strip()
        if body.startswith(("- [ ] ", "- [x] ", "- [X] ")):
            done = body[3].lower() == "x"
            updated = f"{indent}- [{' ' if done else 'x'}] {body[6:]}"
        elif body.startswith(("- ", "* ", "+ ")):
            updated = f"{indent}- [ ] {body[2:]}"
        else:
            updated = f"{indent}- [ ] {body}"
        # Keep the cursor next to the same character it was on.
        self.cursor_col = max(0, min(len(updated), self.cursor_col + len(updated) - len(line)))
        self._lines[row] = updated
        self._after_change()

    # -- movement ----------------------------------------------------------
    def _move(self, row: int, col: int) -> None:
        self.cursor_row, self.cursor_col = self._clamp(row, col)
        self._scroll_to_cursor()

    def action_cursor_left(self) -> None:
        if self.cursor_col == 0:
            if self.cursor_row:
                self._move(self.cursor_row - 1, len(self._lines[self.cursor_row - 1]))
        else:
            self._move(self.cursor_row, self.cursor_col - 1)

    def action_cursor_right(self) -> None:
        if self.cursor_col >= len(self.current_line):
            if self.cursor_row < len(self._lines) - 1:
                self._move(self.cursor_row + 1, 0)
        else:
            self._move(self.cursor_row, self.cursor_col + 1)

    def action_cursor_up(self) -> None:
        self._move(self.cursor_row - 1, self.cursor_col)

    def action_cursor_down(self) -> None:
        self._move(self.cursor_row + 1, self.cursor_col)

    def action_cursor_home(self) -> None:
        line = self.current_line
        indent = len(line) - len(line.lstrip())
        # Home toggles between the first non-space character and column zero.
        self._move(self.cursor_row, 0 if self.cursor_col == indent else indent)

    def action_cursor_end(self) -> None:
        self._move(self.cursor_row, len(self.current_line))

    def action_page_up(self) -> None:
        self._move(self.cursor_row - max(1, self.size.height - 1), self.cursor_col)

    def action_page_down(self) -> None:
        self._move(self.cursor_row + max(1, self.size.height - 1), self.cursor_col)

    def action_document_start(self) -> None:
        self._move(0, 0)

    def action_document_end(self) -> None:
        self._move(len(self._lines) - 1, len(self._lines[-1]))

    def _word_boundaries(self, line: str) -> list[int]:
        return [match.start() for match in _WORD_RE.finditer(line)] + [len(line)]

    def action_word_left(self) -> None:
        boundaries = [b for b in self._word_boundaries(self.current_line) if b < self.cursor_col]
        if boundaries:
            self._move(self.cursor_row, boundaries[-1])
        else:
            self.action_cursor_left()

    def action_word_right(self) -> None:
        boundaries = [b for b in self._word_boundaries(self.current_line) if b > self.cursor_col]
        if boundaries:
            self._move(self.cursor_row, boundaries[0])
        else:
            self.action_cursor_right()

    # -- key dispatch ------------------------------------------------------
    _KEY_ACTIONS = {
        "up": "action_cursor_up",
        "down": "action_cursor_down",
        "left": "action_cursor_left",
        "right": "action_cursor_right",
        "home": "action_cursor_home",
        "end": "action_cursor_end",
        "pageup": "action_page_up",
        "pagedown": "action_page_down",
        "ctrl+home": "action_document_start",
        "ctrl+end": "action_document_end",
        "ctrl+left": "action_word_left",
        "ctrl+right": "action_word_right",
        "enter": "action_newline",
        "backspace": "action_backspace",
        "delete": "action_delete",
        "tab": "action_indent",
        "shift+tab": "action_dedent",
        "ctrl+d": "action_duplicate_line",
        "alt+up": "action_move_line_up",
        "alt+down": "action_move_line_down",
    }

    def on_paste(self, event: events.Paste) -> None:
        """Text from the terminal's clipboard.

        A paste is one event carrying the whole lot — the keypresses it would
        have taken to type it never happen — so without this, pasting into a
        note does nothing at all.

        Line endings are normalised, because what is on the clipboard came
        from wherever it came from, and tabs become spaces: this editor only
        ever writes soft tabs, and a document should not end up with both.
        """
        event.stop()
        event.prevent_default()
        text = event.text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(TAB_WIDTH)
        if text:
            # One insert, so one undo takes the whole paste back out.
            self.insert_text(text)

    async def on_key(self, event: events.Key) -> None:
        handler = self._KEY_ACTIONS.get(event.key)
        if handler is not None:
            event.stop()
            event.prevent_default()
            getattr(self, handler)()
            return
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            self.post_message(self.SaveRequested(self))
            return
        if event.is_printable and event.character:
            event.stop()
            event.prevent_default()
            self.insert_text(event.character)


def segment_text(segments: list[Segment]) -> str:
    """Plain text of a rendered strip — used by the tests."""
    return "".join(segment.text for segment in segments)
