"""The kit's `timeline` in the terminal: a video editor, without the sound.

It opens on the projects, newest first, with New. A project opens the
editor (docs/TIMELINE.md, *The editor*): the material from the drive on the
left, the viewer in the middle, the selected piece's effects on the right,
and under them the tracks, a row each, the pieces drawn to scale as blocks
of text with the playhead through them.

The viewer is the Quill's frames API's `frame` at the playhead, drawn by
textual-image — the real picture where the terminal speaks Kitty or Sixel,
half-cells elsewhere — and played as a few frames a second: the playhead
moves with the clock, and a frame is asked for whenever none is on its way,
so a slow service skips frames rather than falling behind. Without a frames
API the viewer says in words what is at the playhead, and Add asks how long
the file is, since nothing here can read a video.

Everything is a key (the spec's): space plays, ←/→ step a frame (with
shift a second), [ and ] trim the selected piece to the playhead, s splits
it there, m moves it there, ↑/↓ to another track of its kind, x deletes it,
b puts a blur on it, k sets the blur's keyframe at the playhead from four
typed numbers, c crops, e exports, and tab goes between the material, the
tracks and the effects. On the tracks, enter picks the piece at the
playhead (again for the one under it), a click picks one, and a drag moves
it, snapping to the edges near it.

The sums are cloudmorrow.quill.timeline's and the writes client/timeline.py's,
which the command line uses too: a split here and `cm <quill> cut` share a
piece's blurs out the same way.
"""

from __future__ import annotations

import asyncio
import time
from io import BytesIO

from rich.console import Group
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import ContentSwitcher, DataTable, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.client.timeline import Timeline
from cloudmorrow.quill import timeline as tl
from cloudmorrow.quill.screens import tracks_of
from cloudmorrow.tui.kitdata import title_of
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.quill_actions import run_action
from cloudmorrow.tui.screens.modals import PromptModal
from cloudmorrow.tui.theme import ACCENT, ACTION, BAD, FAINT, GOOD, LENS, MUTED, PANEL, SKY, TEXT
from cloudmorrow.tui.widgets.picture import TerminalImage
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import escape, plural

# How many frames a second playing asks for: a picture, not a film.
PLAY_FPS = 4
# How often the header asks after an export that is queued or rendering.
POLL_SECONDS = 2.0
# Seconds a cell of the tracks is, from close in to far out.
ZOOMS = (0.04, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
# The track's name at the start of each row.
LABEL = 5
# How a status is toned in the header.
STATUS_TONE = {"queued": LENS, "rendering": LENS, "done": GOOD, "failed": BAD}
# What a piece looks like on a track of each kind, two shades so that pieces
# that touch can be told apart; the selected one is amber.
BLOCK = {"video": ("#1f4e6b", "#2a6386"), "audio": ("#1f5a46", "#28705a")}

# Which actions each of the two places has: the projects, and the editor.
IN_LIST = frozenset({"new_record", "open", "delete_record", "refresh"})
IN_EDITOR = frozenset(
    {
        "back",
        "play",
        "add",
        "trim_start",
        "trim_end",
        "split",
        "move_here",
        "delete_record",
        "blur",
        "keyframe",
        "crop",
        "reset_crop",
        "export",
        "open_output",
        "mute",
        "volume",
        "refresh",
    }
)


def ruler(first: float, per_cell: float, width: int) -> Text:
    """The times along the top of the tracks, one about every ten cells."""
    step = next((z for z in (0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if z / per_cell >= 10), 600)
    line = [" "] * width
    t = (int(first / step) + (first % step > 1e-9)) * step
    while (cell := int(round((t - first) / per_cell))) < width:
        label = tl.timecode(t).rstrip("0").rstrip(".") if step < 1 else tl.timecode(t)[:-3]
        mark = "╵" + label
        for i, ch in enumerate(mark):
            if cell + i < width:
                line[cell + i] = ch
        t += step
    return Text(" " * LABEL + "".join(line), style=FAINT)


def track_lines(
    tracks: list[dict],
    pieces: list[dict],
    *,
    first: float,
    per_cell: float,
    width: int,
    playhead: float,
    selected: str = "",
) -> list[Text]:
    """The ruler and a row per track: each piece a block to scale with its name in it,
    the selected one amber, the playhead a bar down through them all."""
    lines = [ruler(first, per_cell, width)]
    head = int((playhead - first) / per_cell)
    for track in tracks:
        kind = str(track.get("kind") or "video")
        row = Text(no_wrap=True, overflow="crop")
        row.append(f"{track['id']:<{LABEL - 1}} ", style=f"bold {SKY if kind == 'video' else GOOD}")
        cells: list[tuple[str, str]] = [("·" if c % 10 == 0 else " ", FAINT) for c in range(width)]
        shades = BLOCK.get(kind, BLOCK["video"])
        for n, (a, b, piece) in enumerate(tl.spans(tl.on_track(pieces, track["id"]), first, per_cell, width)):
            chosen = piece.get("id") == selected
            ink = "#11161c" if chosen else TEXT
            colour = ACTION if chosen else shades[n % 2]
            muted = " ✕" if piece.get("muted") else ""
            name = f"▏{piece.get('name') or ''}{muted}"
            for c in range(a, b):
                ch = name[c - a] if c - a < len(name) else " "
                cells[c] = (ch, f"{'bold ' if chosen else ''}{ink} on {colour}")
        if 0 <= head < width:
            ch, style = cells[head]
            background = style.split(" on ", 1)[1] if " on " in style else PANEL
            cells[head] = ("┃", f"bold {BAD} on {background}")
        for ch, style in cells:
            row.append(ch, style=style)
        lines.append(row)
    return lines


def viewer_words(
    tracks: list[dict], pieces: list[dict], effects: dict[str, list[dict]], playhead: float, crop: dict
) -> str:
    """What the viewer says without a picture: each piece playing at the playhead,
    how far into its source, and the effects on it there."""
    lines = []
    for track, piece in tl.pieces_at(pieces, tracks, playhead):
        into = playhead - tl.seconds(piece.get("start"))
        source = tl.seconds(piece.get("offset")) + into
        glyph = "▶" if track.get("kind") == "video" else "♪"
        sound = f"  [{MUTED}]muted[/]" if piece.get("muted") else ""
        lines.append(
            f"[b {SKY if glyph == '▶' else GOOD}]{track['id']}[/] {glyph} {escape(str(piece.get('name') or ''))}"
            f"  [{MUTED}]{tl.timecode(source)} into it[/]{sound}"
        )
        for effect in effects.get(str(piece.get("id")), []):
            ef = effect.get("fields") or {}
            if not tl.effect_on(ef.get("keyframes"), into):
                continue
            box = tl.box_at(ef.get("keyframes"), into)
            lines.append(
                f"   [{LENS}]{escape(str(ef.get('kind') or ''))}[/] {escape(str(ef.get('label') or ''))}"
                + (f"  [{MUTED}]{tl.box_said(box)}[/]" if box else "")
            )
    if not lines:
        lines.append(f"[{MUTED}]Nothing at the playhead.[/]")
    if crop != tl.WHOLE:
        lines.append(f"[{MUTED}]cropped to {tl.box_said(crop)}[/]")
    return "\n".join(lines)


class TrackRows(Widget, can_focus=True):
    """The tracks, drawn by `track_lines` from the pane's state; the keys and the mouse
    that move about them are handed to the pane."""

    DEFAULT_CSS = """
    TrackRows { height: auto; min-height: 6; padding: 0 1; background: $surface; }
    TrackRows:focus { background: $panel; }
    """

    BINDINGS = [
        Binding("left", "step(-1)", "Back a frame", show=False),
        Binding("right", "step(1)", "On a frame", show=False),
        Binding("shift+left", "second(-1)", "Back a second", show=False),
        Binding("shift+right", "second(1)", "On a second", show=False),
        Binding("home", "jump(0)", "Start", show=False),
        Binding("end", "jump(1)", "End", show=False),
        Binding("up", "track(-1)", "Track up", show=False),
        Binding("down", "track(1)", "Track down", show=False),
        Binding("enter", "pick", "Pick", show=False),
        Binding("plus,equals_sign", "zoom(-1)", "Zoom in", show=False),
        Binding("minus", "zoom(1)", "Zoom out", show=False),
    ]

    def __init__(self, pane: TimelinePane, **kwargs) -> None:
        super().__init__(**kwargs)
        self.pane = pane
        # Where a drag began: the piece, and where on the screen it was picked up.
        self._drag: tuple[dict, int, int] | None = None

    @property
    def cells(self) -> int:
        return max((self.content_size.width or 80) - LABEL, 10)

    def render(self) -> Group:
        p = self.pane
        return Group(
            *track_lines(
                p.tracks,
                p.flat,
                first=p.first,
                per_cell=p.per_cell,
                width=self.cells,
                playhead=p.playhead,
                selected=p.selected_id,
            )
        )

    def get_content_height(self, container, viewport, width: int) -> int:
        return len(self.pane.tracks) + 1

    def action_step(self, frames: int) -> None:
        self.pane.step(frames / tl.fps_of(self.pane.project_fields))

    def action_second(self, seconds: int) -> None:
        self.pane.step(float(seconds))

    def action_jump(self, end: int) -> None:
        self.pane.seek(tl.duration(self.pane.flat) if end else 0.0)

    def action_track(self, step: int) -> None:
        self.pane.fire("track_up" if step < 0 else "track_down")

    def action_pick(self) -> None:
        self.pane.pick_at_playhead()

    def action_zoom(self, step: int) -> None:
        self.pane.zoom(step)

    # -- the mouse -----------------------------------------------------------------
    def _where(self, event: events.MouseEvent) -> tuple[dict | None, float, int] | None:
        """The track a row is, the time a column is, and the row; None off the content."""
        p = self.pane
        offset = event.get_content_offset(self)
        if offset is None:
            return None
        row = offset.y - 1
        t = max(p.first + (offset.x - LABEL) * p.per_cell, 0.0)
        track = p.tracks[row] if 0 <= row < len(p.tracks) else None
        return track, t, row

    def on_mouse_down(self, event: events.MouseDown) -> None:
        where = self._where(event)
        if where is None:
            return
        track, t, row = where
        if track is None:
            # The ruler: the playhead goes where it was clicked.
            self.pane.seek(t)
            return
        piece = tl.piece_at(self.pane.flat, track["id"], t)
        self.pane.choose(piece["id"] if piece else "")
        self.pane.seek(t)
        if piece is not None and "move_here" not in self.pane.refused:
            self._drag = (piece, event.screen_x, event.screen_y)
            self.capture_mouse()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag is None:
            return
        piece, x, row = self._drag
        self._drag = None
        self.capture_mouse(False)
        moved = (event.screen_x - x) * self.pane.per_cell
        rows = event.screen_y - row
        if moved or rows:
            self.pane.dragged(piece, moved, rows)


class TimelinePane(KitPane):
    """The projects; then one of them, cut on its tracks."""

    BINDINGS = [
        *KitPane.BINDINGS,
        Binding("n", "fire('new_record')", "New", show=False),
        Binding("r", "fire('refresh')", "Refresh", show=False),
        Binding("escape,backspace", "fire('back')", "Projects", show=False),
        Binding("space", "fire('play')", "Play", show=False),
        Binding("a", "fire('add')", "Add", show=False),
        Binding("left_square_bracket", "fire('trim_start')", "Trim start", show=False),
        Binding("right_square_bracket", "fire('trim_end')", "Trim end", show=False),
        Binding("s", "fire('split')", "Split", show=False),
        Binding("m", "fire('move_here')", "Move here", show=False),
        Binding("x", "fire('delete_record')", "Delete", show=False),
        Binding("b", "fire('blur')", "Blur", show=False),
        Binding("k", "fire('keyframe')", "Keyframe", show=False),
        Binding("c", "fire('crop')", "Crop", show=False),
        Binding("C", "fire('reset_crop')", "Whole picture", show=False),
        Binding("e", "fire('export')", "Export", show=False),
        Binding("o", "fire('open_output')", "Open the export", show=False),
        Binding("u", "fire('mute')", "Mute", show=False),
        Binding("v", "fire('volume')", "Volume", show=False),
        Binding("tab", "cycle(1)", "Next panel", show=False),
        Binding("shift+tab", "cycle(-1)", "Last panel", show=False),
    ]
    WRITING = KitPane.WRITING | {
        "add",
        "trim_start",
        "trim_end",
        "split",
        "move_here",
        "track_up",
        "track_down",
        "blur",
        "keyframe",
        "crop",
        "reset_crop",
        "mute",
        "volume",
    }

    DEFAULT_CSS = """
    TimelinePane {
        #tl-views { height: 1fr; }
        #tl-list, #tl-editor { height: 1fr; }
        #tl-projects { height: 1fr; margin: 1 2 0 2; }
        #tl-head { height: 1; padding: 0 2; }
        #tl-top { height: 1fr; }
        #tl-material-col { width: 30; padding: 0 1; }
        #tl-viewer { width: 1fr; padding: 0 1; border-left: solid $line; border-right: solid $line; }
        #tl-viewer-caption { height: 1; }
        #tl-picture { width: auto; height: auto; }
        #tl-viewer-words { height: 1fr; }
        #tl-effects-col { width: 34; padding: 0 1; }
        #tl-material { height: 1fr; }
        #tl-effects { height: 6; }
        #tl-keys { height: 1fr; }
        .tl-title { height: 1; color: $muted; }
        #tl-tracks { border-top: solid $line; }
    }
    """

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.line = Timeline(None, quill, screen)
        self.projects: list[dict] = []
        # The project open in the editor, and what is on its tracks.
        self.project: dict | None = None
        self.pieces: list[dict] = []
        self.effects: dict[str, list[dict]] = {}
        self.material: list[dict] = []
        # What the frames API said of each file, by id; None when it could not say.
        self.infos: dict[str, dict | None] = {}
        self.playhead = 0.0
        self.selected_id = ""
        # The tracks' view: the time at their left edge and the seconds a cell is,
        # None until it is fitted to the first project drawn.
        self.first = 0.0
        self._zoom: float | None = None
        self.playing = False
        self._played_at = 0.0
        # What a Quill's `go` asked for: `project` opens that one's editor.
        self.params: dict = {}
        # One frame on its way at a time; a playhead that moved meanwhile asks again once it lands.
        self._fetching = False
        self._again = False
        actions = [
            Action("new_record", "New project", "n", variant="primary"),
            Action("open", "Open", "enter"),
            Action("back", "Projects", "esc"),
            Action("play", "Play", "space", variant="primary"),
            Action("add", "Add", "a", hint="The highlighted file, at the playhead"),
            Action("split", "Split", "s", hint="The selected piece, at the playhead"),
            Action("blur", "Blur", "b", hint="A blur on the selected piece, at the playhead"),
            Action("keyframe", "Keyframe", "k", hint="The blur's box at the playhead, as x y w h"),
            Action("crop", "Crop", "c", hint="The part of the picture kept; shift-c keeps all of it"),
        ]
        if self.line.export is not None:
            actions.append(Action("export", str(self.line.export.get("label") or "Export"), "e"))
        actions += [
            Action("delete_record", "Delete", "del"),
            Action("refresh", "Refresh", "r"),
        ]
        self.ACTIONS = self.offer(actions)

    # -- where we are ----------------------------------------------------------------
    @property
    def editing(self) -> bool:
        return self.project is not None

    @property
    def project_fields(self) -> dict:
        return (self.project or {}).get("fields") or {}

    @property
    def tracks(self) -> list[dict]:
        return tracks_of(self.project_fields)

    @property
    def flat(self) -> list[dict]:
        """The pieces as the sums take them: their fields, with their ids."""
        return [dict(p.get("fields") or {}, id=p["id"]) for p in self.pieces]

    @property
    def selected(self) -> dict | None:
        return next((p for p in self.pieces if p["id"] == self.selected_id), None)

    @property
    def per_cell(self) -> float:
        return self._zoom or 1.0

    def fire(self, name: str) -> None:
        # Each place has its own actions; the other's keys do nothing here.
        if name not in (IN_EDITOR | {"track_up", "track_down"} if self.editing else IN_LIST):
            return
        super().fire(name)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "fire" and parameters:
            name = str(parameters[0])
            if name not in (IN_EDITOR | {"track_up", "track_down"} if self.editing else IN_LIST):
                return False
        return super().check_action(action, parameters)

    # -- layout -----------------------------------------------------------------------
    def content(self) -> ComposeResult:
        with ContentSwitcher(id="tl-views", initial="tl-list"):
            with Vertical(id="tl-list"):
                yield DataTable(id="tl-projects", cursor_type="row", zebra_stripes=True)
            with Vertical(id="tl-editor"):
                yield Static("", id="tl-head")
                with Horizontal(id="tl-top"):
                    with Vertical(id="tl-material-col"):
                        yield Static("Material", classes="tl-title")
                        yield DataTable(id="tl-material", cursor_type="row", show_header=False)
                    with Vertical(id="tl-viewer"):
                        yield Static("", id="tl-viewer-caption")
                        if TerminalImage is not None and self.line.frames:
                            yield TerminalImage(id="tl-picture")
                        yield Static("", id="tl-viewer-words")
                    with Vertical(id="tl-effects-col"):
                        yield Static("Effects", classes="tl-title", id="tl-effects-title")
                        yield DataTable(id="tl-effects", cursor_type="row", show_header=False)
                        yield Static("Keyframes", classes="tl-title")
                        yield DataTable(id="tl-keys", cursor_type="row", show_header=False)
                yield TrackRows(self, id="tl-tracks")

    def on_mount(self) -> None:
        self.query_one("#tl-projects", DataTable).add_columns("NAME", "PICTURE", "STATUS", "MADE")
        self.query_one("#tl-material", DataTable).add_columns("file", "length")
        self.query_one("#tl-effects", DataTable).add_columns("effect", "kind", "keys")
        self.query_one("#tl-keys", DataTable).add_columns("at", "box")
        self._clock = self.set_interval(1 / PLAY_FPS, self._tick, pause=True)
        self._poll = self.set_interval(POLL_SECONDS, self._poll_status, pause=True)

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        busy = [p for p in self.projects if (p.get("fields") or {}).get("status") in ("queued", "rendering")]
        if busy:
            return "news", f"{len(busy)} exporting"
        return "ok", plural(len(self.projects), "project")

    def status_detail(self) -> str:
        if self.editing:
            return f"[{MUTED}]{plural(len(self.pieces), 'piece')}[/]"
        return f"[{MUTED}]{plural(len(self.projects), 'project')}[/]"

    # -- loading -----------------------------------------------------------------------
    def reload(self) -> None:
        self.line.api = self.api
        if self.api is None:
            return
        wanted = str(self.params.pop("project", "") or "")
        if wanted and wanted != (self.project or {}).get("id"):
            # go("editor", project=…): straight into its editor; the editor reads the rest.
            self.stop()
            self.open_project({"id": wanted, "fields": {}})
            return
        if self.editing:
            self.load_editor()
        else:
            self.load_projects()

    @work(exclusive=True, group="timeline")
    async def load_projects(self, keep: str = "") -> None:
        try:
            self.projects = await self.line.projects()
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.loaded = True
        self.draw_projects(keep)
        self.status("" if self.projects else "No projects yet — New project starts one.", note=True)

    def draw_projects(self, keep: str = "") -> None:
        self._show("tl-list")
        table = self.query_one("#tl-projects", DataTable)
        row = table.cursor_row
        table.clear()
        for record in self.projects:
            f = record.get("fields") or {}
            status = str(f.get("status") or "")
            size = f"{f.get('width')}×{f.get('height')}" if f.get("width") else ""
            if size and f.get("fps"):
                size += f" · {tl.seconds(f.get('fps')):g} fps"
            table.add_row(
                Text(title_of(record, self.model), style="bold"),
                Text(size, style=MUTED),
                Text(status, style=STATUS_TONE.get(status, MUTED)),
                Text(str(record.get("created_at") or "")[:16].replace("T", " "), style=MUTED),
                key=record["id"],
            )
        if keep:
            row = next((i for i, r in enumerate(self.projects) if r["id"] == keep), row)
        if self.projects:
            table.move_cursor(row=min(max(row, 0), len(self.projects) - 1))
        table.focus()

    @work(exclusive=True, group="timeline")
    async def load_editor(self) -> None:
        if not await self._fetch_editor():
            return
        self.draw_editor()

    async def _fetch_editor(self) -> bool:
        """The project, its pieces and their effects again. False when it failed."""
        assert self.project is not None
        try:
            self.project = await self.api.record(self.line.project_model, self.project["id"])
            self.pieces = await self.line.pieces(self.project["id"])
            self.effects = await self.line.effects(self.pieces)
        except ApiError as exc:
            if exc.status_code == 404:
                # Gone from under us: back to the list.
                self.project = None
                self.load_projects()
                self.status(str(exc), error=True)
                return False
            await self.went_wrong(exc)
            return False
        if self.selected is None:
            self.selected_id = ""
        return True

    @work(exclusive=True, group="timeline-material")
    async def load_material(self) -> None:
        try:
            self.material = await self.line.material()
        except ApiError as exc:
            self.material = []
            self.status(f"The material could not be read: {exc}", error=True)
        self.draw_material()
        if not self.line.frames:
            return
        gate = asyncio.Semaphore(4)

        async def one(file: dict) -> None:
            if file["id"] in self.infos:
                return
            async with gate:
                try:
                    self.infos[file["id"]] = await self.line.info(file["id"])
                except ApiError:
                    self.infos[file["id"]] = None

        await asyncio.gather(*(one(f) for f in self.material))
        self.draw_material()

    # -- drawing the editor ----------------------------------------------------------------
    def _show(self, view: str) -> None:
        self.query_one("#tl-views", ContentSwitcher).current = view
        for button in self.query(".toolbar Button"):
            action = (button.id or "")[len("do-") :]
            button.display = action in (IN_EDITOR if view == "tl-editor" else IN_LIST)
        self.refresh_bindings()

    def draw_editor(self) -> None:
        self._show("tl-editor")
        if self._zoom is None:
            self.fit()
        self.draw_head()
        self.draw_effects()
        self.draw_now()

    def draw_head(self) -> None:
        f = self.project_fields
        parts = [f"[b {ACCENT}]{escape(title_of(self.project, self.model))}[/]"]
        if f.get("width"):
            parts.append(f"[{MUTED}]{f['width']}×{f.get('height')} · {tl.fps_of(f):g} fps[/]")
        else:
            parts.append(f"[{MUTED}]no size yet: the first piece gives it one[/]")
        crop = tl.crop_of(f)
        if crop != tl.WHOLE:
            parts.append(f"[{MUTED}]crop {tl.box_said(crop)}[/]")
        status = str(f.get("status") or "")
        if status:
            said = f"[{STATUS_TONE.get(status, MUTED)}]{escape(status)}[/]"
            if f.get("message"):
                said += f" [{MUTED}]{escape(str(f['message']))}[/]"
            parts.append(said)
        if f.get("output"):
            parts.append(f"[{GOOD}]exported[/] [{MUTED}]o opens it[/]")
        self.query_one("#tl-head", Static).update("   ".join(parts))

    def draw_material(self) -> None:
        table = self.query_one("#tl-material", DataTable)
        row = table.cursor_row
        table.clear()
        for file in self.material:
            f = file.get("fields") or {}
            glyph = "▶" if file["kind"] == "video" else "♪"
            folder = str(f.get("folder") or "")
            within = str(self.line.media.get("within") or "").strip("/")
            folder = folder.strip("/").removeprefix(within).strip("/")
            name = Text(f"{glyph} ", style=SKY if glyph == "▶" else GOOD)
            if folder:
                name.append(f"{folder}/", style=MUTED)
            name.append(str(f.get("name") or ""))
            info = self.infos.get(file["id"])
            length = tl.timecode(tl.seconds(info.get("duration"))) if info and info.get("duration") else ""
            table.add_row(name, Text(length, style=MUTED), key=file["id"])
        if self.material:
            table.move_cursor(row=min(max(row, 0), len(self.material) - 1))
        else:
            where = " / ".join(str(v) for v in self.line.media.values()) or "the drive"
            table.add_row(Text(f"No videos or sounds in {where}.", style=MUTED), "")

    def draw_effects(self) -> None:
        piece = self.selected
        title = self.query_one("#tl-effects-title", Static)
        table = self.query_one("#tl-effects", DataTable)
        row = table.cursor_row
        table.clear()
        if piece is None:
            title.update(f"[{MUTED}]Effects — pick a piece[/]")
        else:
            name = escape(str((piece.get("fields") or {}).get("name") or ""))
            title.update(f"[{MUTED}]Effects of[/] {name}")
            for effect in self.effects.get(piece["id"], []):
                ef = effect.get("fields") or {}
                table.add_row(
                    escape(str(ef.get("label") or "")),
                    Text(str(ef.get("kind") or ""), style=LENS),
                    Text(str(len(tl.keyframes_of(ef.get("keyframes")))), style=MUTED),
                    key=effect["id"],
                )
            if table.row_count:
                table.move_cursor(row=min(max(row, 0), table.row_count - 1))
        self.draw_keys()

    @property
    def effect(self) -> dict | None:
        """The effect the effects' cursor is on, of the selected piece."""
        piece = self.selected
        if piece is None:
            return None
        effects = self.effects.get(piece["id"], [])
        row = self.query_one("#tl-effects", DataTable).cursor_row
        return effects[row] if 0 <= row < len(effects) else (effects[0] if effects else None)

    def draw_keys(self) -> None:
        table = self.query_one("#tl-keys", DataTable)
        row = table.cursor_row
        table.clear()
        effect = self.effect
        if effect is None:
            return
        start = tl.seconds((self.selected or {}).get("fields", {}).get("start"))
        for kf in tl.keyframes_of((effect.get("fields") or {}).get("keyframes")):
            table.add_row(Text(tl.timecode(start + kf["t"]), style=MUTED), tl.box_said(kf))
        if table.row_count:
            table.move_cursor(row=min(max(row, 0), table.row_count - 1))

    def draw_now(self) -> None:
        """What changes with the playhead: the tracks, the caption, the picture or the words."""
        total = tl.duration(self.flat)
        tracks = self.query_one(TrackRows)
        span = tracks.cells * self.per_cell
        if not self.first <= self.playhead < self.first + span:
            # Keep the playhead in sight: a quarter of the way in.
            self.first = max(0.0, self.playhead - span / 4)
        tracks.refresh(layout=True)
        state = f"[{GOOD}]▶ playing[/]" if self.playing else f"[{MUTED}]❚❚[/]"
        self.query_one("#tl-viewer-caption", Static).update(
            f"{state}  [b]{tl.timecode(self.playhead)}[/] [{MUTED}]/ {tl.timecode(total)}[/]"
        )
        words = self.query_one("#tl-viewer-words", Static)
        if self.line.frames and TerminalImage is not None:
            words.display = False
            self.want_frame()
        else:
            words.display = True
            crop = tl.crop_of(self.project_fields)
            words.update(viewer_words(self.tracks, self.flat, self.effects, self.playhead, crop))

    # -- the picture -------------------------------------------------------------------------
    def want_frame(self) -> None:
        """A frame of the cut at the playhead: now, or as soon as the one on its way lands."""
        if self.project is None or not self.line.frames:
            return
        if self._fetching:
            self._again = True
            return
        self._fetching = True
        self.fetch_frame()

    @work(group="timeline-frame")
    async def fetch_frame(self) -> None:
        try:
            while self.project is not None:
                self._again = False
                at = self.playhead
                viewer = self.query_one("#tl-viewer")
                width = max(160, min(1280, (viewer.content_size.width or 60) * 10))
                try:
                    data = await self.line.frame(self.project["id"], at, width)
                except ApiError as exc:
                    self.query_one("#tl-viewer-words", Static).update(f"[{MUTED}]no frame: {escape(str(exc))}[/]")
                    self.query_one("#tl-viewer-words", Static).display = True
                    return
                self.show_frame(data)
                if not self._again:
                    return
        finally:
            self._fetching = False

    def show_frame(self, data: bytes) -> None:
        try:
            from PIL import Image as PILImage

            opened = PILImage.open(BytesIO(data))
            opened.load()
        except Exception as exc:  # not a picture after all
            words = self.query_one("#tl-viewer-words", Static)
            words.update(f"[{MUTED}]cannot draw the frame: {escape(str(exc))}[/]")
            words.display = True
            return
        self.query_one("#tl-picture").image = opened

    # -- the playhead ----------------------------------------------------------------------------
    def seek(self, t: float) -> None:
        self.playhead = max(0.0, t)
        self.draw_now()

    def step(self, by: float) -> None:
        if self.project is None:
            return
        self.seek(self.playhead + by)

    def act_play(self) -> None:
        if self.playing:
            self.stop()
            return
        if self.playhead >= tl.duration(self.flat):
            self.playhead = 0.0
        self.playing = True
        self._played_at = time.monotonic()
        self._clock.resume()
        self.draw_now()

    def stop(self) -> None:
        self.playing = False
        self._clock.pause()
        if self.project is not None:
            self.draw_now()

    def _tick(self) -> None:
        """Playing: the playhead keeps up with the clock, whatever the frames manage."""
        now = time.monotonic()
        self.playhead += now - self._played_at
        self._played_at = now
        end = tl.duration(self.flat)
        if self.playhead >= end:
            self.playhead = end
            self.stop()
            return
        self.draw_now()

    def zoom(self, step: int) -> None:
        index = min(range(len(ZOOMS)), key=lambda i: abs(ZOOMS[i] - self.per_cell))
        self._zoom = ZOOMS[min(max(index + step, 0), len(ZOOMS) - 1)]
        self.first = 0.0
        self.draw_now()

    def fit(self) -> None:
        """The zoom that shows the whole cut, with room after it to add more."""
        total = max(tl.duration(self.flat) * 1.2, 10.0)
        cells = self.query_one(TrackRows).cells
        self._zoom = next((z for z in ZOOMS if total / z <= cells), ZOOMS[-1])

    # -- picking a piece ---------------------------------------------------------------------------
    def choose(self, piece_id: str) -> None:
        self.selected_id = piece_id
        self.query_one("#tl-effects", DataTable).move_cursor(row=0)
        self.draw_effects()
        self.query_one(TrackRows).refresh()
        piece = self.selected
        if piece is not None:
            f = piece.get("fields") or {}
            self.status(
                f"{f.get('name')} on {f.get('track')}: {tl.timecode(tl.seconds(f.get('start')))}"
                f"–{tl.timecode(tl.end_of(f))}",
                note=True,
            )

    def pick_at_playhead(self) -> None:
        """Enter on the tracks: the piece at the playhead, top track first; again, the next one down."""
        here = [piece for _, piece in tl.pieces_at(self.flat, self.tracks, self.playhead)]
        if not here:
            self.choose("")
            return
        ids = [p["id"] for p in here]
        at = ids.index(self.selected_id) + 1 if self.selected_id in ids else 0
        self.choose(ids[at % len(ids)])

    def _need_piece(self) -> dict | None:
        piece = self.selected
        if piece is None:
            self.status("Pick a piece first: enter on the tracks, or a click.", error=True)
        return piece

    def _playhead_on(self, piece: dict) -> float | None:
        """How far into *piece* the playhead is, or None (said) when it is not on it."""
        f = piece.get("fields") or {}
        into = self.playhead - tl.seconds(f.get("start"))
        if not 0 <= into <= tl.seconds(f.get("length")):
            self.status(f"The playhead is not on {f.get('name')}.", error=True)
            return None
        return into

    # -- the panels ----------------------------------------------------------------------------------
    def action_cycle(self, step: int) -> None:
        """Tab: the material, the tracks, the effects and their keyframes, round again."""
        if not self.editing:
            self.app.action_focus_next() if step > 0 else self.app.action_focus_previous()
            return
        stops = [
            self.query_one("#tl-material"),
            self.query_one(TrackRows),
            self.query_one("#tl-effects"),
            self.query_one("#tl-keys"),
        ]
        focused = self.screen.focused
        at = next((i for i, w in enumerate(stops) if w is focused), -1)
        stops[(at + step) % len(stops)].focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "tl-effects":
            self.draw_keys()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        which = event.data_table.id
        if which == "tl-projects":
            self.act_open()
        elif which == "tl-material":
            self.fire("add")
        elif which == "tl-effects":
            effect = self.effect
            if effect is not None:
                self.edit_effect(effect)
        elif which == "tl-keys":
            # Enter on a keyframe: the playhead goes to it.
            effect, piece = self.effect, self.selected
            kfs = tl.keyframes_of((effect or {}).get("fields", {}).get("keyframes"))
            row = event.cursor_row
            if piece is not None and 0 <= row < len(kfs):
                self.seek(tl.seconds(piece["fields"].get("start")) + kfs[row]["t"])

    # -- the projects ----------------------------------------------------------------------------------
    def act_open(self) -> None:
        table = self.query_one("#tl-projects", DataTable)
        if not self.projects or not 0 <= table.cursor_row < len(self.projects):
            return
        self.open_project(self.projects[table.cursor_row])

    def open_project(self, project: dict) -> None:
        self.project = project
        self.pieces, self.effects = [], {}
        self.playhead, self.first, self._zoom, self.selected_id = 0.0, 0.0, None, ""
        self._show("tl-editor")
        self.load_editor()
        self.load_material()
        self.call_after_refresh(lambda: self.query_one(TrackRows).focus())

    def act_back(self) -> None:
        self.stop()
        self._poll.pause()
        keep = (self.project or {}).get("id", "")
        self.project = None
        self.load_projects(keep)

    def act_refresh(self) -> None:
        if self.editing:
            self.load_material()
        self.reload()

    def act_new_record(self) -> None:
        self.new_project()

    @work(group="ui")
    async def new_project(self) -> None:
        name = await self.app.push_screen_wait(PromptModal("New project", placeholder="Holiday 2026"))
        if not name:
            return
        try:
            made = await self.line.new_project(name)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.status(f"{name} is made.")
        self.open_project(made)

    def act_delete_record(self) -> None:
        if not self.editing:
            table = self.query_one("#tl-projects", DataTable)
            if 0 <= table.cursor_row < len(self.projects):
                self.delete_project(self.projects[table.cursor_row])
            return
        focused = self.screen.focused
        if focused is self.query_one("#tl-keys"):
            self.remove_keyframe()
        elif focused is self.query_one("#tl-effects"):
            if self.effect is not None:
                self.remove_effect(self.effect)
        else:
            piece = self._need_piece()
            if piece is not None:
                self.remove_piece(piece)

    @work(group="ui")
    async def delete_project(self, project: dict) -> None:
        if await self.confirm_delete(project):
            self.status(f"Deleted {title_of(project, self.model)}.")
            self.load_projects()

    # -- editing ---------------------------------------------------------------------------------------
    async def edited(self, said: str, *, select: str | None = None) -> None:
        """After a write: everything read again and drawn, *said* in the log."""
        if select is not None:
            self.selected_id = select
        if await self._fetch_editor():
            self.draw_editor()
            self.status(said)

    async def _try(self, write) -> bool:
        """Run *write*; a refusal is said, and False."""
        try:
            await write
        except ApiError as exc:
            await self.went_wrong(exc)
            if self.editing:
                self.load_editor()
            return False
        return True

    def act_add(self) -> None:
        table = self.query_one("#tl-material", DataTable)
        if not self.material or not 0 <= table.cursor_row < len(self.material):
            self.status("No file to add: the material is empty.", error=True)
            return
        self.add_file(self.material[table.cursor_row])

    @work(group="ui")
    async def add_file(self, file: dict) -> None:
        name = str((file.get("fields") or {}).get("name") or "")
        info = self.infos.get(file["id"])
        if info is None and self.line.frames:
            try:
                info = self.infos[file["id"]] = await self.line.info(file["id"])
            except ApiError:
                info = None
        length = tl.seconds((info or {}).get("duration"))
        if not length:
            asked = await self.app.push_screen_wait(
                PromptModal(
                    f"How long is {name}?",
                    placeholder="12.5, or 1:02",
                    detail=f"[{MUTED}]In seconds, or m:ss. Nothing here can read a video to find out.[/]",
                )
            )
            if not asked:
                return
            try:
                length = tl.parse_time(asked)
            except ValueError as exc:
                self.status(str(exc), error=True)
                return
        try:
            made = await self.line.add(self.project, file, at=self.playhead, length=length, info=info)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        f = made["fields"]
        await self.edited(f"Added {name} to {f['track']} at {tl.timecode(self.playhead)}.", select=made["id"])

    def act_trim_start(self) -> None:
        if (piece := self._need_piece()) is not None:
            self.trim(piece, start=True)

    def act_trim_end(self) -> None:
        if (piece := self._need_piece()) is not None:
            self.trim(piece, start=False)

    @work(group="ui")
    async def trim(self, piece: dict, *, start: bool) -> None:
        f = piece["fields"]
        info = self.infos.get(str(f.get("source") or ""))
        source = tl.seconds((info or {}).get("duration")) or None
        effects = self.effects.get(piece["id"], [])
        at = {"start": self.playhead} if start else {"end": self.playhead}
        if await self._try(self.line.trim(piece, effects, source_length=source, **at)):
            await self.edited(f"Trimmed the {'start' if start else 'end'} of {f.get('name')}.")

    def act_split(self) -> None:
        if (piece := self._need_piece()) is not None:
            self.split(piece)

    @work(group="ui")
    async def split(self, piece: dict) -> None:
        name = piece["fields"].get("name")
        try:
            made = await self.line.cut(piece, self.effects.get(piece["id"], []), self.playhead)
        except ApiError as exc:
            await self.went_wrong(exc)
            self.load_editor()
            return
        if made is None:
            self.status(f"The playhead is not inside {name}: nothing to split.", error=True)
            return
        await self.edited(f"Split {name} at {tl.timecode(self.playhead)}.", select=made["id"])

    def act_move_here(self) -> None:
        if (piece := self._need_piece()) is not None:
            self.move(piece, tl.moved(self.playhead))

    def act_track_up(self) -> None:
        self._to_track(-1)

    def act_track_down(self) -> None:
        self._to_track(1)

    def _to_track(self, step: int) -> None:
        piece = self._need_piece()
        if piece is None:
            return
        target = tl.next_track(self.tracks, str(piece["fields"].get("track")), step)
        if target is None:
            self.status(f"No other {tl.kind_of_track(self.tracks, piece['fields'].get('track'))} track that way.")
            return
        self.move(piece, {"track": target})

    def dragged(self, piece: dict, by: float, rows: int) -> None:
        """A drag on the tracks let go: *by* seconds along, *rows* tracks down, snapped to the edges near."""
        changes: dict = {}
        if by:
            whole = next(p for p in self.flat if p["id"] == piece["id"])
            start = tl.seconds(whole.get("start")) + by
            near = tl.edges(self.flat, leave=whole, playhead=self.playhead)
            changes.update(tl.moved(tl.snap_start(start, tl.seconds(whole.get("length")), near, 1.5 * self.per_cell)))
        if rows:
            ids = [t["id"] for t in self.tracks]
            here = ids.index(piece["track"]) if piece.get("track") in ids else 0
            wanted = ids[min(max(here + rows, 0), len(ids) - 1)]
            if tl.kind_of_track(self.tracks, wanted) == tl.kind_of_track(self.tracks, piece.get("track", "")):
                changes["track"] = wanted
        record = next((p for p in self.pieces if p["id"] == piece["id"]), None)
        if changes and record is not None:
            self.move(record, changes)

    @work(group="ui")
    async def move(self, piece: dict, changes: dict) -> None:
        if await self._try(self.line.update(piece, changes)):
            where = changes.get("track") or piece["fields"].get("track")
            start = tl.seconds(changes.get("start", piece["fields"].get("start")))
            await self.edited(f"Moved {piece['fields'].get('name')} to {where} at {tl.timecode(start)}.")

    @work(group="ui")
    async def remove_piece(self, piece: dict) -> None:
        if await self._try(self.line.remove(piece)):
            await self.edited(f"Took {piece['fields'].get('name')} out.", select="")

    def act_mute(self) -> None:
        piece = self._need_piece()
        if piece is not None and "muted" in {f["name"] for f in self.models[self.line.piece_model]["fields"]}:
            self.move(piece, {"muted": not piece["fields"].get("muted")})

    def act_volume(self) -> None:
        if (piece := self._need_piece()) is not None:
            self.set_volume(piece)

    @work(group="ui")
    async def set_volume(self, piece: dict) -> None:
        now = tl.seconds(piece["fields"].get("volume"), 1.0)
        asked = await self.app.push_screen_wait(
            PromptModal("Volume", value=f"{now:g}", detail=f"[{MUTED}]0 to 2; 1 is as it was recorded.[/]")
        )
        if not asked:
            return
        try:
            volume = min(max(float(asked), 0.0), 2.0)
        except ValueError:
            self.status("A volume is a number, 0 to 2.", error=True)
            return
        if await self._try(self.line.update(piece, {"volume": volume})):
            await self.edited(f"{piece['fields'].get('name')} at volume {volume:g}.")

    # -- effects ---------------------------------------------------------------------------------------
    def act_blur(self) -> None:
        piece = self._need_piece()
        if piece is None or not self.line.effect_model:
            return
        into = self._playhead_on(piece)
        if into is not None:
            self.add_blur(piece, into)

    @work(group="ui")
    async def add_blur(self, piece: dict, into: float) -> None:
        try:
            await self.line.add_blur(piece, into)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        await self.edited(f"A blur on {piece['fields'].get('name')}: k sets its box, enter names it.")
        table = self.query_one("#tl-effects", DataTable)
        table.move_cursor(row=table.row_count - 1)

    def act_keyframe(self) -> None:
        piece = self._need_piece()
        if piece is None:
            return
        effect = self.effect
        if effect is None:
            self.status(f"{piece['fields'].get('name')} has no blur yet: b puts one on.", error=True)
            return
        into = self._playhead_on(piece)
        if into is not None:
            self.set_keyframe(effect, into)

    @work(group="ui")
    async def set_keyframe(self, effect: dict, into: float) -> None:
        box = tl.box_at(effect["fields"].get("keyframes"), into) or tl.MIDDLE
        asked = await self.app.push_screen_wait(
            PromptModal(
                f"The box at {tl.timecode(self.playhead)}",
                value=tl.box_said(box),
                detail=f"[{MUTED}]x y w h, in percent of the project's picture, before the crop.[/]",
            )
        )
        if not asked:
            return
        try:
            box = tl.box_from(asked)
        except ValueError as exc:
            self.status(str(exc), error=True)
            return
        if await self._try(self.line.keyframe(effect, into, box, tl.fps_of(self.project_fields))):
            await self.edited(f"Keyframe at {tl.timecode(self.playhead)}: {tl.box_said(box)}.")

    def remove_keyframe(self) -> None:
        effect = self.effect
        row = self.query_one("#tl-keys", DataTable).cursor_row
        kfs = tl.keyframes_of((effect or {}).get("fields", {}).get("keyframes"))
        if effect is None or not 0 <= row < len(kfs):
            return
        if len(kfs) == 1:
            self.status("The last keyframe goes with the effect: del on the effect removes it.", error=True)
            return
        self.unkeyframe(effect, row)

    @work(group="ui")
    async def unkeyframe(self, effect: dict, index: int) -> None:
        if await self._try(self.line.unkeyframe(effect, index)):
            await self.edited("Keyframe removed.")

    @work(group="ui")
    async def remove_effect(self, effect: dict) -> None:
        if await self._try(self.api.delete_record(self.line.effect_model, effect["id"])):
            await self.edited(f"Took {effect['fields'].get('label')} off.")

    @work(group="ui")
    async def edit_effect(self, effect: dict) -> None:
        """Enter on an effect: its sheet, to name what it hides and say how strong."""
        result = await self.open_sheet(effect, model_id=self.line.effect_model, only=["label", "kind", "strength"])
        if result is not None:
            await self.edited("Changed." if result != "deleted" else "Effect removed.")

    # -- the crop ----------------------------------------------------------------------------------------
    def act_crop(self) -> None:
        self.crop()

    def act_reset_crop(self) -> None:
        self.set_crop(None)

    @work(group="ui")
    async def crop(self) -> None:
        asked = await self.app.push_screen_wait(
            PromptModal(
                "Crop",
                value=tl.box_said(tl.crop_of(self.project_fields)),
                detail=f"[{MUTED}]The part kept: x y w h, in percent. `all` keeps the whole picture.[/]",
            )
        )
        if not asked:
            return
        if asked.strip().lower() in ("all", "reset", "whole"):
            self.set_crop(None)
            return
        try:
            box = tl.box_from(asked)
        except ValueError as exc:
            self.status(str(exc), error=True)
            return
        self.set_crop(box)

    @work(group="ui")
    async def set_crop(self, box: dict | None) -> None:
        if await self._try(self.line.crop(self.project, box)):
            await self.edited("The whole picture." if box is None else f"Cropped to {tl.box_said(box)}.")

    # -- the export ------------------------------------------------------------------------------------
    def act_export(self) -> None:
        if self.line.export is None:
            self.status("This timeline has no export.", error=True)
            return
        self.export()

    @work(group="ui")
    async def export(self) -> None:
        self.stop()
        ran = await run_action(self.app, self.quill, self.line.export, record=self.project)
        if ran:
            await self.edited("Exporting.")
            self._poll.resume()

    async def _poll_status(self) -> None:
        """While an export is queued or rendering, the header follows it."""
        if self.project is None:
            self._poll.pause()
            return
        try:
            self.project = await self.api.record(self.line.project_model, self.project["id"])
        except ApiError:
            return
        self.draw_head()
        if self.project_fields.get("status") not in ("queued", "rendering"):
            self._poll.pause()

    def act_open_output(self) -> None:
        output = self.project_fields.get("output")
        if not output:
            self.status("Nothing exported yet.", error=True)
            return
        self.open_output(str(output))

    @work(group="ui")
    async def open_output(self, file_id: str) -> None:
        if "file" not in self.models:
            self.status(f"The export is file {file_id}.")
            return
        try:
            record = await self.api.record("file", file_id)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        await self.open_sheet(record, model_id="file")


__all__ = ["TimelinePane", "TrackRows", "ruler", "track_lines", "viewer_words"]
