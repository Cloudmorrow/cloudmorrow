"""The kit's `thread` in the terminal: the spaces on the left, the conversation on the right.

A thread screen binds a `model` that lives in a space (`space`, its link to
the space), the field that is what was said (`body`), and optionally a field
of the space to say under its name (`about`) and how spaces are made
(`made_as`). Everything below is read from those and the datamodels: a
channel and a message are one Quill's words for it, and nothing here says
either.

Side by side, as a terminal has the width for: the spaces with what is
unread in each, the ones made between people named for whoever else is in
them; and the one you are on, a rule for each day, one name over each run of
lines from one person, and a line to type in. Opening one marks it seen.

Read is drawn as read (docs/CIRCLES.md): on what is said that you may only
read there is no line to type in, and on spaces you may only read none is
made, written to, added to, left or edited — you read what is in them.

It polls. An open conversation asks for what changed since the newest thing
it has, every few seconds, and the counts beside the others come with it —
a socket would be a second way for the server to talk to a client, and this
is a house with four machines in it.

A screen may bind four more, a team's (docs/QUILLS.md): `reply_to` draws a
line's replies under it as a thread, and `r` replies to one; `reactions`
draws each line's emoji with their counts, and `x` toggles yours; `pinned`
marks a pinned line and `p` pins or unpins one; `mentions` lights every
@name. Picking the line is a list of the last ones said, by its words.
"""

from __future__ import annotations

import re

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.kitdata import can_write, field_of
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, MUTED, SECOND
from cloudmorrow.tui.widgets.kit_space import (
    NewSpaceModal,
    PickPersonModal,
    is_between,
    made_as,
    people_in,
    space_name,
)
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import escape, plural

# How often an open conversation asks for what it has not got.
POLL_SECONDS = 5.0
# How much of one is read back when it opens.
PAGE = 80
# The reactions on offer: a short, fixed row, the same on every surface.
EMOJI = ("👍", "❤️", "😂", "🎉", "👀", "✅")
# @name in a line: after an @, at the start or after a space or bracket.
MENTION = re.compile(r"(^|[\s(\[])@([a-z0-9][a-z0-9._-]*)")
# How many of the last lines a Reply, React or Pin picks from.
PICK = 20


def _clock(stamp: str | None) -> str:
    """The time of day out of an ISO stamp: 2026-09-19T14:03:21 → 14:03."""
    return (stamp or "")[11:16] or "--:--"


def _day(stamp: str | None) -> str:
    return (stamp or "")[:10]


def _said(text: str, mentions: bool) -> str:
    """Whatever somebody typed is text, not markup; an @name is lit when the screen has mentions."""
    safe = escape(text)
    if not mentions:
        return safe
    return MENTION.sub(lambda m: f"{m.group(1)}[{ACCENT}]@{m.group(2)}[/]", safe)


def tally(reactions: list[dict], link: str, me: str) -> dict[str, list[tuple[str, int, bool]]]:
    """Each line's reactions as (emoji, count, mine), the row's order first."""
    rows: dict[str, dict[str, list]] = {}
    for r in reactions:
        line = str((r.get("fields") or {}).get(link) or "")
        emoji = str((r.get("fields") or {}).get("emoji") or "")
        if not line or not emoji:
            continue
        cell = rows.setdefault(line, {}).setdefault(emoji, [emoji, 0, False])
        cell[1] += 1
        if r.get("owner") == me:
            cell[2] = True

    def order(emoji: str) -> tuple[int, str]:
        return (EMOJI.index(emoji) if emoji in EMOJI else len(EMOJI), emoji)

    return {line: [tuple(c) for c in sorted(cells.values(), key=lambda c: order(c[0]))] for line, cells in rows.items()}


def render_lines(
    lines: list[dict],
    body: str,
    me: str,
    *,
    reply_to: str = "",
    pinned: str = "",
    mentions: bool = False,
    reactions: dict[str, list[tuple[str, int, bool]]] | None = None,
) -> str:
    """The conversation, as one block of markup.

    A run of lines from one person carries one name, and a new day gets a
    rule across the pane — what makes a log read as a conversation. With
    `reply_to`, a reply is drawn under its parent, indented, as a thread.
    """
    if not lines:
        return f"[{MUTED}]Nothing said here yet.[/]"
    replies: dict[str, list[dict]] = {}
    tops = lines
    if reply_to:
        tops = []
        for line in lines:
            parent = str((line.get("fields") or {}).get(reply_to) or "")
            if parent:
                replies.setdefault(parent, []).append(line)
            else:
                tops.append(line)
        # A reply whose parent is off the page is shown where it is.
        shown = {line["id"] for line in tops}
        for parent, rows in list(replies.items()):
            if parent not in shown:
                tops.extend(rows)
                del replies[parent]
        tops.sort(key=lambda line: str(line.get("created_at") or ""))
    out: list[str] = []
    author = day = ""

    def words(line: dict, indent: str) -> None:
        when = str(line.get("created_at") or "")
        edited = f" [{MUTED}](edited)[/]" if line.get("updated_at") not in (None, when) else ""
        mark = f"[{ACCENT}]📌[/] " if pinned and (line.get("fields") or {}).get(pinned) else ""
        for text in str((line.get("fields") or {}).get(body) or "").splitlines() or [""]:
            out.append(f"{indent}{mark}{_said(text, mentions)}{edited}")
            edited = mark = ""
        for emoji, count, mine in (reactions or {}).get(line["id"], []):
            cell = f"{emoji} {count}"
            out[-1:] = [out[-1]]
            out.append(f"{indent}[{ACCENT if mine else MUTED}]{cell}[/]")

    for line in tops:
        when = str(line.get("created_at") or "")
        if _day(when) != day:
            day = _day(when)
            out.append(f"[{MUTED}]── {day} ──[/]")
            author = ""
        if line.get("owner") != author:
            author = str(line.get("owner") or "")
            colour = ACCENT if author == me else SECOND
            who = "you" if author == me else author
            out.append(f"[{colour}]{escape(who)}[/] [{MUTED}]{_clock(when)}[/]")
        words(line, "  ")
        for reply in replies.get(line["id"], []):
            owner = str(reply.get("owner") or "")
            who = "you" if owner == me else owner
            colour = ACCENT if owner == me else SECOND
            at = _clock(str(reply.get("created_at") or ""))
            out.append(f"    [{MUTED}]↳[/] [{colour}]{escape(who)}[/] [{MUTED}]{at}[/]")
            words(reply, "      ")
            author = ""
    return "\n".join(out)


class PickLineModal(Modal[str | None]):
    """One of the last lines said, by its words: which one to reply to, react to, or pin."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    PickLineModal #line-list { height: auto; max-height: 14; margin-bottom: 1; }
    """

    def __init__(self, title: str, lines: list[dict], body: str, *, detail: str = "") -> None:
        super().__init__()
        self._title = title
        self.lines = lines
        self._body = body
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="line-modal"):
            yield Label(self._title, classes="modal-title")
            if self._detail:
                yield Static(self._detail, classes="modal-detail")
            if self.lines:
                yield OptionList(
                    *[Option(self._label(line), id=line["id"]) for line in self.lines],
                    id="line-list",
                )
            else:
                yield Static(f"[{MUTED}]Nothing said here yet.[/]")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")

    def _label(self, line: dict) -> str:
        words = str((line.get("fields") or {}).get(self._body) or "").splitlines() or [""]
        return f"[{MUTED}]{escape(str(line.get('owner') or ''))}:[/] {escape(words[0][:60])}"

    def on_mount(self) -> None:
        if self.lines:
            box = self.query_one("#line-list", OptionList)
            box.highlighted = len(self.lines) - 1
            box.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PickEmojiModal(Modal[str | None]):
    """One of the reactions on offer; the ones already yours are marked."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, mine: set[str]) -> None:
        super().__init__()
        self.mine = mine

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="emoji-modal"):
            yield Label("React", classes="modal-title")
            yield Static(f"[{MUTED}]Yours again takes it back.[/]", classes="modal-detail")
            yield OptionList(
                *[Option(f"{e}" + (f"  [{ACCENT}]yours[/]" if e in self.mine else ""), id=e) for e in EMOJI],
                id="emoji-list",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#emoji-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ThreadPane(KitPane):
    """Spaces on the left; the conversation and the line you type in on the right."""

    DEFAULT_CSS = """
    ThreadPane #thread-body { height: 1fr; padding: 1 0 0 0; }
    ThreadPane #space-side { width: 26; margin-right: 2; }
    ThreadPane #conversation { width: 1fr; }
    ThreadPane #conversation-scroll { height: 1fr; padding: 0 1; }
    ThreadPane #thread-input { margin-top: 1; }
    """

    BINDINGS = [
        # A line is taken back where it was said, not with a key from the list.
        Binding("delete", "fire('nothing')", "Delete", show=False),
        ("n", "fire('new_space')", "New"),
        ("m", "fire('write_to')", "Message"),
        ("a", "fire('add')", "Add people"),
        ("l", "fire('leave')", "Leave"),
        ("e", "fire('edit_space')", "Edit"),
        ("r", "fire('reply')", "Reply"),
        ("x", "fire('react')", "React"),
        ("p", "fire('pin')", "Pin"),
    ]
    # Writing here is saying something — a reply, a pin and a reaction are
    # that too; what is done to the spaces is the space datamodel's to allow.
    WRITING = frozenset({"say", "reply", "react", "pin"})

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        link = field_of(self.model, screen.get("space")) or {"name": "space", "to": ""}
        self.link: str = link["name"]
        self.space_model_id: str = str(link.get("to") or "")
        self.space_model: dict = self.models.get(self.space_model_id) or {"id": self.space_model_id, "fields": []}
        self.body: str = str(screen.get("body") or self.model.get("title") or "body")
        self.about: str = str(screen.get("about") or "")
        # The team's four, each there or not.
        self.reply_to: str = str(screen.get("reply_to") or "")
        self.pinned: str = str(screen.get("pinned") or "")
        self.mentions: bool = bool(screen.get("mentions"))
        self.reactions_model_id: str = str(screen.get("reactions") or "")
        reactions_model = self.models.get(self.reactions_model_id) or {}
        self.reaction_link: str = next(
            (
                f["name"]
                for f in reactions_model.get("fields", [])
                if f.get("kind") == "link" and f.get("to") == self.model_id
            ),
            "",
        )
        self.reaction_space: str = str(reactions_model.get("in_space") or "")
        if not self.reply_to:
            self.refused.add("reply")
        if not self.pinned:
            self.refused.add("pin")
        if not (self.reactions_model_id and self.reaction_link) or not can_write(reactions_model):
            self.refused.add("react")
        if not can_write(self.space_model):
            # Leaving is taking yourself out of it, which is writing it too.
            self.refused |= {"new_record", "new_space", "write_to", "add", "leave", "edit_space"}
        noun = str(self.space_model.get("label") or "space").lower()
        actions = [
            Action("new_space", f"New {noun}", "n", variant="primary", hint="Everybody's, or the people you pick"),
        ]
        if made_as(screen).get("direct"):
            actions.append(Action("write_to", "Message", "m", hint="Write to one person"))
        actions += [
            Action("reply", "Reply", "r", hint="Answer a line, in its thread"),
            Action("react", "React", "x", hint="An emoji on a line; yours again takes it back"),
            Action("pin", "Pin", "p", hint="Keep a line at the top, or let it go"),
            Action("add", "Add people", "a", hint=f"Put somebody in this {noun}"),
            Action("edit_space", "Edit", "e", hint=f"Rename this {noun}, or delete it"),
            Action("leave", "Leave", "l", variant="error"),
        ]
        self.ACTIONS = self.offer(actions)
        self.spaces: list[dict] = []
        self.lines: list[dict] = []
        self.reactions: list[dict] = []
        # Which space should be showing, and which one the lines in hand
        # belong to: between picking one and its lines arriving those are
        # different, and a reply for one you have moved off is not drawn.
        self._open = ""
        self._loaded = ""
        self._timer = None

    # -- layout --------------------------------------------------------------
    def content(self) -> ComposeResult:
        with Horizontal(id="thread-body"):
            with Vertical(id="space-side"):
                yield Static(
                    f"[{MUTED}]{str(self.space_model.get('label') or 'space').lower()}s[/]", classes="pane-title"
                )
                yield DataTable(id="space-table", cursor_type="row")
            with Vertical(id="conversation"):
                yield Static(f"[{MUTED}]pick one[/]", id="conversation-title", classes="pane-title")
                with VerticalScroll(id="conversation-scroll"):
                    yield Static("", id="conversation-text")
                if "say" not in self.refused:
                    yield Input(placeholder="Write a message…", id="thread-input")

    def on_mount(self) -> None:
        self.query_one("#space-table", DataTable).add_columns(
            str(self.space_model.get("label") or "space").upper(), "NEW"
        )
        self._timer = self.set_interval(POLL_SECONDS, self.catch_up, pause=True)

    def on_show(self) -> None:
        self.reload()
        if self._timer:
            self._timer.resume()

    def on_hide(self) -> None:
        # Nothing to poll for while the pane is behind another; the counts
        # are read again when it comes back.
        if self._timer:
            self._timer.pause()

    @property
    def space(self) -> dict | None:
        return next((s for s in self.spaces if s["id"] == self._open), None)

    def label(self, space: dict) -> str:
        """How a space is written in the list: a # for a room, a name for people."""
        name = space_name(self.space_model, space, self.spec, self.me)
        return name if is_between(self.spec, space) else f"#{name}"

    def _row(self, space: dict) -> tuple[str, str]:
        waiting = space.get("unread") or 0
        label = escape(self.label(space))
        return (f"[{ACCENT}]{label}[/]" if waiting else label, f"[{ACCENT}]{waiting}[/]" if waiting else "")

    # -- the spaces ------------------------------------------------------------
    async def _fetch_spaces(self) -> list[dict]:
        spaces = await self.api.records(self.space_model_id)

        def when(space: dict) -> str:
            return str((space.get("last") or {}).get("created_at") or space.get("created_at") or "")

        # The ones with news first, and the ones nobody has written in by
        # when they were made — which is the same question.
        return sorted(spaces, key=when, reverse=True)

    @work(exclusive=True, group="thread-spaces")
    async def reload(self) -> None:
        if self.api is None:
            return
        self.forget_links()
        try:
            self.spaces = await self._fetch_spaces()
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.loaded = True
        table = self.query_one("#space-table", DataTable)
        table.clear()
        for space in self.spaces:
            table.add_row(*self._row(space), key=space["id"])
        noun = str(self.space_model.get("label") or "space").lower()
        if not self.spaces:
            self._open = self._loaded = ""
            self.lines = []
            self.query_one("#conversation-title", Static).update(f"[{MUTED}]no {noun}s yet[/]")
            if "new_space" in self.refused:
                self.query_one("#conversation-text", Static).update("")
                self.status(f"No {noun}s here.", note=True)
                return
            self.query_one("#conversation-text", Static).update(
                f"[{MUTED}]New {noun} asks whether everybody is in it or only the people you pick.[/]"
            )
            self.status(f"No {noun}s yet — press n to make one.", note=True)
            return
        # Stay where you were when the list is only being refreshed, and fall
        # to the first one when where you were has gone.
        if not any(s["id"] == self._open for s in self.spaces):
            self._open = ""
        wanted = self._open or self.spaces[0]["id"]
        table.move_cursor(row=next(i for i, s in enumerate(self.spaces) if s["id"] == wanted))
        self._select(wanted)
        if self._loaded != self._open:
            self.open_space(self._open)
        self.status()

    def _select(self, space_id: str) -> None:
        if not space_id or space_id == self._open:
            return
        self._open = space_id
        self.open_space(space_id)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "space-table":
            return
        # Where the cursor is now, not where it was when this was posted:
        # rebuilding the table queues a highlight for row 0 that arrives
        # after the cursor has been put back where it belongs.
        row = event.data_table.cursor_row
        if 0 <= row < len(self.spaces):
            self._select(self.spaces[row]["id"])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        for box in self.query("#thread-input"):
            box.focus()

    # -- one conversation --------------------------------------------------------
    @work(exclusive=True, group="thread-open")
    async def open_space(self, space_id: str) -> None:
        if self.api is None or not space_id:
            return
        try:
            lines = await self.api.records(self.model_id, last=PAGE, **{self.link: space_id})
            reactions = await self._fetch_reactions(space_id)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        if space_id != self._open:
            return  # moved on while this was in the air
        self.lines = lines
        self.reactions = reactions
        self._loaded = space_id
        space = self.space or {}
        about = "" if is_between(self.spec, space) else str((space.get("fields") or {}).get(self.about) or "")
        self.query_one("#conversation-title", Static).update(
            f"[{ACCENT}]{escape(self.label(space))}[/]" + (f"  [{MUTED}]{escape(about)}[/]" if about else "")
        )
        self._draw()
        await self._seen()

    async def _fetch_reactions(self, space_id: str) -> list[dict]:
        """Every reaction in the space: a handful of small records, read whole,
        because a reaction taken back is not in a `since`."""
        if not self.reactions_model_id or not self.reaction_space or self.api is None:
            return []
        return await self.api.records(self.reactions_model_id, **{self.reaction_space: space_id})

    def _draw(self) -> None:
        self.query_one("#conversation-text", Static).update(
            render_lines(
                self.lines,
                self.body,
                self.me,
                reply_to=self.reply_to,
                pinned=self.pinned,
                mentions=self.mentions,
                reactions=tally(self.reactions, self.reaction_link, self.me) if self.reaction_link else None,
            )
        )
        scroll = self.query_one("#conversation-scroll", VerticalScroll)
        # The newest line is the one you want to be looking at.
        self.call_after_refresh(scroll.scroll_end, animate=False)

    async def _seen(self) -> None:
        if self.api is None or not self._open:
            return
        try:
            await self.api.mark_seen(self.space_model_id, self._open)
        except ApiError:
            return
        for space in self.spaces:
            if space["id"] == self._open:
                space["unread"] = 0
        self._paint_counts()

    def _paint_counts(self) -> None:
        table = self.query_one("#space-table", DataTable)
        for row, space in enumerate(self.spaces):
            if row >= table.row_count:
                break
            name, count = self._row(space)
            table.update_cell_at((row, 0), name)
            table.update_cell_at((row, 1), count)
        # The head says how many are waiting; it moves with the counts.
        self.refresh_head()

    def _merge(self, fresh: list[dict]) -> bool:
        """New lines and edits into what is on screen. True when anything changed."""
        by_id = {line["id"]: line for line in self.lines}
        changed = False
        for line in fresh:
            had = by_id.get(line["id"])
            if had is None or had.get("rev") != line.get("rev"):
                by_id[line["id"]] = line
                changed = True
        if changed:
            self.lines = sorted(by_id.values(), key=lambda line: str(line.get("created_at") or ""))
        return changed

    @work(exclusive=True, group="thread-poll")
    async def catch_up(self) -> None:
        """Ask for what arrived, in this space and in the others."""
        if self.api is None:
            return
        if self._open and self._loaded == self._open:
            newest = max((str(line.get("updated_at") or "") for line in self.lines), default="")
            try:
                fresh = await self.api.records(self.model_id, since=newest or None, **{self.link: self._open})
                reactions = await self._fetch_reactions(self._open)
            except ApiError:
                return
            changed = self._merge(fresh)
            if [(r["id"], r.get("rev")) for r in reactions] != [(r["id"], r.get("rev")) for r in self.reactions]:
                self.reactions = reactions
                changed = True
            if changed:
                self._draw()
                await self._seen()
        try:
            spaces = {s["id"]: s for s in await self._fetch_spaces()}
        except ApiError:
            return
        if set(spaces) != {s["id"] for s in self.spaces}:
            self.reload()
            return
        changed = False
        for space in self.spaces:
            waiting = spaces[space["id"]].get("unread") or 0
            if space.get("unread") != waiting:
                space["unread"] = waiting
                changed = True
        if changed:
            self._paint_counts()

    # -- writing --------------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "thread-input":
            return
        event.stop()
        text = event.value.strip()
        if not text or not self._open or "say" in self.refused:
            return
        event.input.value = ""
        self.send(self._open, text)

    @work(group="thread-send")
    async def send(self, space_id: str, text: str) -> None:
        if self.api is None:
            return
        try:
            sent = await self.api.create_record(self.model_id, {self.link: space_id, self.body: text})
        except ApiError as exc:
            self.status(str(exc), error=True)
            # Put the words back rather than lose them to a dropped call.
            box = self.query_one("#thread-input", Input)
            if not box.value:
                box.value = text
            return
        if space_id == self._open:
            self._merge([sent])
            self._draw()
        self.status()

    # -- a line: reply, react, pin -------------------------------------------------------
    def _line(self, line_id: str) -> dict | None:
        return next((line for line in self.lines if line["id"] == line_id), None)

    async def _pick_line(self, title: str, *, detail: str = "", tops_only: bool = False) -> dict | None:
        """One of the last lines said here, chosen by its words."""
        if not self._open:
            self.status("Pick a conversation first.", error=True)
            return None
        lines = self.lines
        if tops_only and self.reply_to:
            lines = [line for line in lines if not (line.get("fields") or {}).get(self.reply_to)]
        chosen = await self.app.push_screen_wait(PickLineModal(title, lines[-PICK:], self.body, detail=detail))
        return self._line(chosen) if chosen else None

    @work(group="ui")
    async def act_reply(self) -> None:
        if self.api is None or "reply" in self.refused:
            return
        parent = await self._pick_line("Reply to which line?", detail="A reply is a thread under it.", tops_only=True)
        if parent is None:
            return
        said = str((parent.get("fields") or {}).get(self.body) or "").splitlines()[:1]
        text = await self.app.push_screen_wait(
            PromptModal(
                f"Reply to {parent.get('owner', '')}", detail=said[0][:80] if said else "", placeholder="Your reply…"
            )
        )
        text = (text or "").strip()
        if not text:
            return
        try:
            sent = await self.api.create_record(
                self.model_id, {self.link: self._open, self.body: text, self.reply_to: parent["id"]}
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._merge([sent])
        self._draw()
        self.status("Replied.")

    @work(group="ui")
    async def act_react(self) -> None:
        if self.api is None or "react" in self.refused:
            return
        line = await self._pick_line("React to which line?")
        if line is None:
            return
        mine = {
            str((r.get("fields") or {}).get("emoji") or "")
            for r in self.reactions
            if r.get("owner") == self.me and (r.get("fields") or {}).get(self.reaction_link) == line["id"]
        }
        emoji = await self.app.push_screen_wait(PickEmojiModal(mine))
        if not emoji:
            return
        try:
            if emoji in mine:
                own = next(
                    r for r in self.reactions
                    if r.get("owner") == self.me
                    and (r.get("fields") or {}).get(self.reaction_link) == line["id"]
                    and (r.get("fields") or {}).get("emoji") == emoji
                )
                await self.api.delete_record(self.reactions_model_id, own["id"])
                self.reactions = [r for r in self.reactions if r["id"] != own["id"]]
            else:
                made = await self.api.create_record(
                    self.reactions_model_id,
                    {self.reaction_space: self._open, self.reaction_link: line["id"], "emoji": emoji},
                )
                self.reactions.append(made)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._draw()
        self.status()

    @work(group="ui")
    async def act_pin(self) -> None:
        if self.api is None or "pin" in self.refused:
            return
        line = await self._pick_line(
            "Pin or unpin which line?", detail="Its author may, or whoever manages this space."
        )
        if line is None:
            return
        pinned = not (line.get("fields") or {}).get(self.pinned)
        try:
            changed = await self.api.update_record(self.model_id, line["id"], {self.pinned: pinned})
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._merge([changed])
        self._draw()
        self.status("Pinned." if pinned else "Unpinned.")

    # -- the spaces' own actions ------------------------------------------------------
    def act_new_record(self) -> None:
        """^n, as on every kit pane: here the new thing is a space."""
        self.act_new_space()

    async def _people(self) -> list[dict]:
        try:
            return await self.api.people()
        except ApiError as exc:
            # Not being able to list them is no reason not to make a space;
            # it only means nobody can be ticked while making it.
            self.status(str(exc), error=True)
            return []

    @work(group="ui")
    async def act_new_space(self) -> None:
        if self.api is None:
            return
        people = await self._people()
        wanted = await self.app.push_screen_wait(NewSpaceModal(self.space_model, people, screen=self.spec))
        if not wanted:
            return
        try:
            made = await self.api.create_record(
                self.space_model_id, wanted["fields"], scope=wanted["scope"], members=wanted["members"]
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._open = made["id"]
        await self.reload().wait()
        count = len(wanted["members"])
        who = (
            "everybody is in it"
            if wanted["scope"] == "public"
            else "yours alone for now; press a to add people"
            if not count
            else f"{', '.join(wanted['members'])} {'is' if count == 1 else 'are'} in it"
        )
        self.status(f"{self.label(made)} — {who}.")

    @work(group="ui")
    async def act_write_to(self) -> None:
        direct = made_as(self.spec).get("direct")
        if self.api is None or not direct:
            return
        people = await self._people()
        who = await self.app.push_screen_wait(
            PickPersonModal("Message somebody", people, detail="Everyone here can write to everyone.")
        )
        if not who:
            return
        names = sorted({self.me, who})
        title = self.space_model.get("title") or "name"
        try:
            made = await self.api.create_record(
                self.space_model_id,
                {title: " & ".join(names), **direct},
                scope="shared",
                members=[who],
                unique=True,
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._open = made["id"]
        self.reload()
        for box in self.query("#thread-input"):
            box.focus()

    def _refuse(self, space: dict, doing: str) -> bool:
        """Say why a space cannot be added to or left, when it cannot."""
        if is_between(self.spec, space):
            self.status(f"A conversation between people stays as it is; nobody can {doing} it.", error=True)
            return True
        if space.get("scope") == "public":
            self.status(
                "Everybody is already in it." if doing == "add to" else "It is everybody's; nobody leaves it.",
                error=True,
            )
            return True
        return False

    @work(group="ui")
    async def act_add(self) -> None:
        space = self.space
        if self.api is None or space is None or self._refuse(space, "add to"):
            return
        inside = set(people_in(space))
        outside = [p for p in await self._people() if p["username"] not in inside]
        who = await self.app.push_screen_wait(
            PickPersonModal(
                f"Add to {self.label(space)}", outside, detail="They are added, not invited — they will be told."
            )
        )
        if not who:
            return
        try:
            await self.api.add_member(self.space_model_id, space["id"], who)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        await self.reload().wait()
        self.status(f"{who} is in.")

    @work(group="ui")
    async def act_leave(self) -> None:
        space = self.space
        if self.api is None or space is None or self._refuse(space, "leave"):
            return
        if space.get("owner") == self.me:
            self.status("You made it, so it stays yours; delete it with Edit instead.", error=True)
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Leave {self.label(space)}?",
                detail="You will stop getting what is said in it. Somebody can add you back.",
                confirm_label="Leave",
            )
        )
        if not confirmed:
            return
        try:
            await self.api.remove_member(self.space_model_id, space["id"], self.me)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._open = self._loaded = ""
        self.lines = []
        self.reload()

    @work(group="ui")
    async def act_edit_space(self) -> None:
        """The space's own record sheet: its name and fields, and delete."""
        space = self.space
        if self.api is None or space is None:
            return
        if is_between(self.spec, space) or not space.get("can_manage"):
            self.status("Only whoever made it can change it.", error=True)
            return
        taken = {name for fields in made_as(self.spec).values() for name in fields}
        only = [f["name"] for f in self.space_model.get("fields", []) if f["name"] not in taken]
        result = await self.open_sheet(space, model_id=self.space_model_id, only=only)
        if result is None:
            return
        if result == "deleted":
            self._open = self._loaded = ""
            self.lines = []
        self.reload()

    # -- what the card and the bar say ----------------------------------------------------
    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        waiting = sum(s.get("unread") or 0 for s in self.spaces)
        if waiting:
            return "news", f"{waiting} unread"
        count = len(self.spaces)
        noun = str(self.space_model.get("label") or "space").lower()
        return "ok", f"{plural(count, noun)}, all read"

    def status_detail(self) -> str:
        waiting = sum(s.get("unread") or 0 for s in self.spaces)
        if waiting:
            return f"[{BAD}]{waiting}[/] waiting"
        noun = str(self.space_model.get("label") or "space").lower()
        return f"[{MUTED}]{len(self.spaces)} {noun}s[/]"

    def act_refresh(self) -> None:
        self.reload()
