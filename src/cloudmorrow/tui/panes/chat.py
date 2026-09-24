"""Chat in the terminal: the channels on the left, the one you are in on the right.

The same two lists the phone shows, side by side instead of behind a switch —
a terminal has the width for both, and the whole point of having chat here is
not having to reach for the phone while you are working.

It polls. A channel that is open asks for anything after the last id it has,
every few seconds, which is what the web app does and for the same reason: a
socket would be a second way for the server to talk to a client, and this is
a house with four machines in it. What arrives while you are reading another
channel shows up as a count beside that channel's name.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Input, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.channel import NewChannelModal
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, MUTED, SECOND
from cloudmorrow.tui.widgets.toolbar import Action

# How often an open channel asks for what it has not got.
POLL_SECONDS = 5.0
# How much of a channel is read back when you open it.
PAGE = 80


def _clock(stamp: str | None) -> str:
    """The time of day out of an ISO stamp: 2026-09-19T14:03:21 → 14:03."""
    return (stamp or "")[11:16] or "--:--"


def _day(stamp: str | None) -> str:
    return (stamp or "")[:10]


def render_messages(messages: list[dict], me: str) -> str:
    """The thread, as one block of markup.

    A run of lines from one person carries one name, and a new date gets a
    rule across the pane — the two things that make a log readable as a
    conversation rather than as a log.
    """
    if not messages:
        return f"[{MUTED}]Nothing said here yet.[/]"
    lines: list[str] = []
    last_author = ""
    last_day = ""
    for message in messages:
        day = _day(message["created_at"])
        if day != last_day:
            lines.append(f"[{MUTED}]── {day} ──[/]")
            last_day = day
            last_author = ""
        if message["author"] != last_author:
            colour = ACCENT if message["author"] == me else SECOND
            who = "you" if message["author"] == me else message["author"]
            lines.append(f"[{colour}]{who}[/] [{MUTED}]{_clock(message['created_at'])}[/]")
            last_author = message["author"]
        edited = f" [{MUTED}](edited)[/]" if message.get("edited_at") else ""
        # Whatever somebody typed is text, not markup: a message with square
        # brackets in it is a message, not a colour tag.
        for line in str(message["body"]).splitlines() or [""]:
            lines.append(f"  {_escape(line)}{edited}")
            edited = ""
    return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("[", r"\[")


def _row_for(channel: dict) -> tuple[str, str]:
    """A channel's two cells: its name, and what is waiting in it."""
    waiting = channel.get("unread") or 0
    label = channel_label(channel)
    return (
        f"[{ACCENT}]{label}[/]" if waiting else label,
        f"[{ACCENT}]{waiting}[/]" if waiting else "",
    )


def who_is_in(wanted: dict) -> str:
    """What to say in the bar about a channel just made.

    A public channel has everybody in it and needs no list. A private one is
    worth naming the people of while there are few enough to read, because
    the whole point of the dialog was picking them.
    """
    if wanted["kind"] == "public":
        return "everybody is in it."
    people = wanted["members"]
    if not people:
        return "yours alone for now; press a to add people."
    if len(people) == 1:
        return f"{people[0]} is in it."
    if len(people) == 2:
        return f"{people[0]} and {people[1]} are in it."
    return f"{len(people)} other people are in it."


def channel_label(channel: dict) -> str:
    """How a channel is written in the list: a # for a room, a name for a person."""
    return channel["name"] if channel["kind"] == "direct" else f"#{channel['name']}"


class ChatPane(Pane):
    """Channels on the left, the conversation and the box you type in on the right."""

    TAB_LABEL = "Chat"
    TAB_KEY = "f6"
    BINDINGS = [
        ("n", "fire('channel')", "New channel"),
        ("m", "fire('direct')", "Message"),
        ("a", "fire('add')", "Add people"),
        ("l", "fire('leave')", "Leave"),
    ]
    ACTIONS = (
        Action("channel", "New channel", "n", variant="primary",
               hint="Everybody's, or the people you pick"),
        Action("direct", "Message", "m", hint="Write to one person"),
        Action("add", "Add people", "a", hint="Put somebody in this channel"),
        Action("leave", "Leave", "l", variant="error"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._channels: list[dict] = []
        self._messages: list[dict] = []
        # Which channel should be showing, and which one the messages in
        # hand actually belong to. Two fields rather than one because the
        # fetch is a worker: between picking a channel and its history
        # arriving, those are different answers, and a reply for the channel
        # you have already moved off must not be drawn.
        self._slug = ""
        self._loaded = ""
        self._timer = None

    def content(self) -> ComposeResult:
        with Horizontal(id="chat-body"):
            with Vertical(id="channel-pane"):
                yield Static(f"[{MUTED}]channels[/]", classes="pane-title")
                yield DataTable(id="channel-table", cursor_type="row")
            with Vertical(id="thread-pane"):
                yield Static(f"[{MUTED}]pick a channel[/]", id="thread-title",
                             classes="pane-title")
                with VerticalScroll(id="thread-body"):
                    yield Static("", id="thread-text")
                yield Input(placeholder="Write a message…", id="chat-input")

    def on_mount(self) -> None:
        self.query_one("#channel-table", DataTable).add_columns("channel", "new")
        self._timer = self.set_interval(POLL_SECONDS, self.catch_up, pause=True)

    def on_show(self) -> None:
        self.reload()
        if self._timer:
            self._timer.resume()

    def on_hide(self) -> None:
        # Nothing to poll for while the pane is behind another one; the
        # counts are picked up again when it comes back.
        if self._timer:
            self._timer.pause()

    @property
    def me(self) -> str:
        return getattr(self.app, "username", "") or ""

    @property
    def channel(self) -> dict | None:
        return next((c for c in self._channels if c["slug"] == self._slug), None)

    def _select(self, slug: str) -> None:
        """Show a channel from now on, and go and fetch it."""
        if not slug or slug == self._slug:
            return
        self._slug = slug
        self.open_channel(slug)

    # -- the channel list ----------------------------------------------------
    @work(exclusive=True, group="chat-channels")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self._channels = await client.channels()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        table = self.query_one("#channel-table", DataTable)
        table.clear()
        for channel in self._channels:
            table.add_row(*_row_for(channel))
        if not self._channels:
            self._slug = ""
            self.query_one("#thread-title", Static).update(f"[{MUTED}]no channels yet[/]")
            self.query_one("#thread-text", Static).update(
                f"[{MUTED}]New channel asks whether everybody is in it or only the "
                f"people you pick; Message writes to one person.[/]"
            )
            self.status("No channels yet — press n to make one.")
            return
        # Stay where you were when the list is only being refreshed, and
        # fall to the first channel when where you were has gone.
        if not any(c["slug"] == self._slug for c in self._channels):
            self._slug = ""
        wanted = self._slug or self._channels[0]["slug"]
        table.move_cursor(
            row=next(i for i, c in enumerate(self._channels) if c["slug"] == wanted)
        )
        self._select(wanted)
        if self._loaded != self._slug:
            self.open_channel(self._slug)
        self.status()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "channel-table":
            return
        # Where the cursor is now, not where it was when this was posted:
        # rebuilding the table queues a highlight for row 0 that arrives
        # after the cursor has already been put back where it belongs.
        row = event.data_table.cursor_row
        if 0 <= row < len(self._channels):
            self._select(self._channels[row]["slug"])

    # -- one channel -----------------------------------------------------------
    @work(exclusive=True, group="chat-thread")
    async def open_channel(self, slug: str) -> None:
        client = self.api
        if client is None:
            return
        try:
            messages = await client.messages(slug, limit=PAGE)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if slug != self._slug:
            return   # moved on while this was in the air
        self._messages = messages
        self._loaded = slug
        channel = self.channel or {}
        topic = channel.get("topic") or ""
        self.query_one("#thread-title", Static).update(
            f"[{ACCENT}]{channel_label(channel)}[/]"
            + (f"  [{MUTED}]{topic}[/]" if topic else "")
        )
        self._draw()
        await self._mark_read()

    def _draw(self) -> None:
        self.query_one("#thread-text", Static).update(
            render_messages(self._messages, self.me)
        )
        body = self.query_one("#thread-body", VerticalScroll)
        # The newest line is the one you want to be looking at.
        self.call_after_refresh(body.scroll_end, animate=False)

    async def _mark_read(self) -> None:
        client = self.api
        if client is None or not self._slug:
            return
        top = self._messages[-1]["id"] if self._messages else None
        try:
            await client.mark_channel_read(self._slug, top)
        except ApiError:
            return
        for channel in self._channels:
            if channel["slug"] == self._slug:
                channel["unread"] = 0
        self._paint_counts()

    def _paint_counts(self) -> None:
        table = self.query_one("#channel-table", DataTable)
        for row, channel in enumerate(self._channels):
            if row >= table.row_count:
                break
            name, count = _row_for(channel)
            table.update_cell_at((row, 0), name)
            table.update_cell_at((row, 1), count)

    @work(exclusive=True, group="chat-poll")
    async def catch_up(self) -> None:
        """Ask for what arrived, in this channel and in the others."""
        client = self.api
        if client is None:
            return
        if self._slug:
            after = self._messages[-1]["id"] if self._messages else 0
            try:
                fresh = await client.messages(self._slug, after=after)
            except ApiError:
                return
            if fresh:
                self._messages.extend(fresh)
                self._draw()
                await self._mark_read()
        try:
            unread = (await client.chat_unread())["channels"]
        except ApiError:
            return
        changed = False
        for channel in self._channels:
            waiting = unread.get(channel["slug"], 0)
            if channel.get("unread") != waiting:
                channel["unread"] = waiting
                changed = True
        if changed:
            self._paint_counts()

    # -- writing ------------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "chat-input":
            return
        event.stop()
        body = event.value.strip()
        if not body or not self._slug:
            return
        event.input.value = ""
        self.send(self._slug, body)

    @work(group="chat-send")
    async def send(self, slug: str, body: str) -> None:
        client = self.api
        if client is None:
            return
        try:
            sent = await client.send_message(slug, body)
        except ApiError as exc:
            self.status(str(exc), error=True)
            # Put the words back rather than lose them to a dropped call.
            box = self.query_one("#chat-input", Input)
            if not box.value:
                box.value = body
            return
        if slug == self._slug:
            self._messages.append(sent)
            self._draw()
        self.status()

    # -- the actions -----------------------------------------------------------------
    @work(group="chat-make")
    async def act_channel(self) -> None:
        """Ask what the channel is, then make it.

        The people to tick come with the dialog rather than being fetched
        inside it, so the list is there the moment the box is: a form that
        fills itself in a second later is a form you have already answered.
        """
        client = self.api
        if client is None:
            return
        try:
            people = await client.chat_people()
        except ApiError as exc:
            # Not being able to list the people is no reason not to make a
            # channel; it only means nobody can be ticked while making it.
            self.status(str(exc), error=True)
            people = []
        wanted = await self.app.push_screen_wait(NewChannelModal(people))
        if not wanted:
            return
        try:
            made = await client.create_channel(
                wanted["name"],
                kind=wanted["kind"],
                topic=wanted["topic"],
                members=wanted["members"],
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._slug = made["slug"]
        # Said once the list has come back, not before: reload finishes by
        # putting the ordinary count in the bar, and would wipe this on its
        # way past.
        await self.reload().wait()
        self.status(f"#{made['name']} — {who_is_in(wanted)}")

    def act_direct(self) -> None:
        self.app.push_screen(
            PromptModal(
                "Message somebody",
                placeholder="username",
                detail="Their account name. Everyone here can write to everyone.",
            ),
            self._open_direct,
        )

    @work(group="chat-direct")
    async def _open_direct(self, username: str | None) -> None:
        client = self.api
        if client is None or not username or not username.strip():
            return
        try:
            made = await client.direct_channel(username.strip().lower())
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._slug = made["slug"]
        self.reload()

    def act_add(self) -> None:
        channel = self.channel
        if channel is None:
            return
        if channel["kind"] != "private":
            self.status(
                "Everybody is already in a public channel."
                if channel["kind"] == "public"
                else "A direct channel is the two of you.",
                error=True,
            )
            return
        self.app.push_screen(
            PromptModal(
                f"Add to #{channel['name']}",
                placeholder="username",
                detail="They are added, not invited — they will be told.",
            ),
            self._add_member,
        )

    @work(group="chat-add")
    async def _add_member(self, username: str | None) -> None:
        client = self.api
        if client is None or not username or not username.strip():
            return
        try:
            added = await client.add_channel_members(
                self._slug, [username.strip().lower()]
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        who = added.get("added") or []
        self.status(f"{who[0]} is in." if who else "They were already in it.")
        self.reload()

    def act_leave(self) -> None:
        channel = self.channel
        if channel is None:
            return
        if channel["kind"] != "private":
            self.status(
                "A public channel is everybody's; you cannot leave it."
                if channel["kind"] == "public"
                else "A direct channel stays.",
                error=True,
            )
            return
        self.app.push_screen(
            ConfirmModal(
                f"Leave #{channel['name']}?",
                detail="You will stop getting its messages. Somebody can add you back.",
                confirm_label="Leave",
            ),
            self._leave,
        )

    @work(group="chat-leave")
    async def _leave(self, confirmed: bool | None) -> None:
        client = self.api
        if client is None or not confirmed:
            return
        try:
            await client.leave_channel(self._slug)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._slug = ""
        self._loaded = ""
        self._messages = []
        self.reload()

    def act_refresh(self) -> None:
        self.reload()

    # -- what the bottom bar says ----------------------------------------------------
    def status_detail(self) -> str:
        waiting = sum(c.get("unread") or 0 for c in self._channels)
        if waiting:
            return f"[{BAD}]{waiting}[/] waiting"
        return f"[{MUTED}]{len(self._channels)} channels[/]"
