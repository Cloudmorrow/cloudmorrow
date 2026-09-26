"""The kit's `grid` in the terminal: records that are files, the way a file manager shows them.

A grid screen binds a datamodel whose records have bytes beside their
fields, and names which of its fields say what: the `group` each record is
in (a link — the places to pick from first), its `folder`, whether it is a
folder (the `kind` enum's "folder"), its `size`, when it was `modified` and
its `mime` type. Nothing here knows what the groups or the records are
called; the screen and the datamodels say.

At the top, the groups in a table: each one's title, and the line the
screen's `group_subtitle` names; one whose `group_open` field is false is
listed but not opened — the server cannot show what is in it. Enter opens a
group, and it is its folders and records, sorted the way the web app sorts
them — name, date, size or type, folders first — as a list, or as tiles
with the picture drawn, since the terminal can draw one. The picture the
cursor is on is shown beside, the way a note's picture is.

In a folder: put a file in from this machine, get one onto it, make a
folder, rename, move and delete. Something else in the terminal app may add
to the groups — a column, and actions on the group the cursor is on — with
`register_group_extension`, without this file knowing what it adds.

The server makes the thumbnails small, so a tile is a few kilobytes and not
the photo. The panel asks for a bigger one, which is still not the whole
photo: a terminal has no use for twelve megapixels.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, ContentSwitcher, DataTable, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.kit import field_of
from cloudmorrow.tui.widgets.picture import Picture, TerminalImage
from cloudmorrow.tui.widgets.toolbar import Action

# -- what a file is ----------------------------------------------------------------
# The same kinds, by the same extensions, as the web app's kit_grid.js: the
# two should agree about what a thing is and where it sorts.
KINDS = ("folder", "image", "video", "audio", "document", "text", "archive", "file")
BY_EXT = {
    "image": (
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "heic",
        "heif",
        "avif",
        "bmp",
        "svg",
        "tif",
        "tiff",
    ),
    "video": ("mp4", "m4v", "mov", "mkv", "webm", "avi", "wmv"),
    "audio": ("mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "aiff"),
    "document": (
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "odt",
        "ods",
        "odp",
        "pages",
        "numbers",
        "key",
        "epub",
    ),
    "text": (
        "txt",
        "md",
        "json",
        "csv",
        "xml",
        "yaml",
        "yml",
        "toml",
        "log",
        "py",
        "js",
        "ts",
        "html",
        "css",
        "sh",
        "ini",
        "conf",
    ),
    "archive": ("zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "dmg", "iso"),
}
KIND_OF_EXT = {ext: kind for kind, exts in BY_EXT.items() for ext in exts}
KIND_LABEL = {
    "folder": "Folder",
    "image": "Picture",
    "video": "Video",
    "audio": "Audio",
    "document": "Document",
    "text": "Text",
    "archive": "Archive",
    "file": "File",
}
# What a tile shows until it has a picture, or when it will never have one.
GLYPH = {
    "folder": "▰▰▰",
    "image": "▣",
    "video": "▶",
    "audio": "♪",
    "document": "≡",
    "text": "≡",
    "archive": "▤",
    "file": "▢",
}


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[1].lower() if "." in name else ""


def kind_of(entry: dict) -> str:
    if entry.get("is_dir"):
        return "folder"
    mime = entry.get("mime") or ""
    for kind in ("image", "video", "audio"):
        if mime.startswith(kind + "/"):
            return kind
    return KIND_OF_EXT.get(ext_of(entry["name"]), "text" if mime.startswith("text/") else "file")


def type_label(entry: dict) -> str:
    """What the row says a file is: its extension, or the kind when it has none."""
    kind = kind_of(entry)
    ext = ext_of(entry["name"])
    return "Folder" if kind == "folder" else (ext.upper() if ext else KIND_LABEL[kind])


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{round(value)} {unit}" if value >= 10 else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_date(stamp: float) -> str:
    return dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M") if stamp else ""


def _seconds(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    try:
        return dt.datetime.fromisoformat(str(value)).timestamp() if value else 0.0
    except ValueError:
        return 0.0


# -- sorting --------------------------------------------------------------------------
# Name, date, size or type; folders come first whichever it is. A key's
# natural way: names up, newest and largest first.
SORTS = (("name", "Name"), ("date", "Date"), ("size", "Size"), ("type", "Type"))
DESCENDING_BY_DEFAULT = {"name": False, "date": True, "size": True, "type": False}


def _sort_key(key: str, entry: dict) -> tuple:
    name = entry["name"].casefold()
    if key == "date":
        return (entry.get("modified", 0), name)
    if key == "size":
        return (entry.get("size", 0), name)
    if key == "type":
        return (KINDS.index(kind_of(entry)), ext_of(entry["name"]), name)
    return (name,)


def sort_entries(entries: list[dict], key: str, descending: bool) -> list[dict]:
    folders = [e for e in entries if e.get("is_dir")]
    files = [e for e in entries if not e.get("is_dir")]
    folders.sort(key=lambda e: _sort_key(key, e), reverse=descending)
    files.sort(key=lambda e: _sort_key(key, e), reverse=descending)
    return folders + files


# -- what else may add to the groups ------------------------------------------------------
@dataclass(frozen=True)
class GroupExtension:
    """More on a grid's groups, from outside the kit.

    *applies* is asked with the group datamodel. *columns* are added to the
    groups table, filled by *cells* for each group record; *actions* are
    buttons (and keys) at the top, run by *run* with the pane and the group
    the cursor is on. An action with the id `new_group` is what ctrl+n does
    there. *detail* is what the header says about the group the cursor is on.
    """

    applies: Callable[[dict], bool]
    columns: tuple[str, ...] = ()
    cells: Callable[[dict], tuple[str, ...]] = lambda _record: ()
    actions: tuple[Action, ...] = ()
    run: Callable[[GridPane, str, dict | None], Awaitable[None]] | None = None
    detail: Callable[[dict], str] | None = None
    keys: dict[str, str] = field(default_factory=dict)


EXTENSIONS: list[GroupExtension] = []


def register_group_extension(extension: GroupExtension) -> None:
    EXTENSIONS.append(extension)


# -- the tiles ------------------------------------------------------------------------------
class Tile(Vertical, can_focus=True):
    """One thing in the tiles: its picture or its glyph, and its name under it."""

    class Opened(Message):
        def __init__(self, tile: Tile) -> None:
            self.tile = tile
            super().__init__()

    def __init__(self, index: int, entry: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.index = index
        self.entry = entry
        self.kind = kind_of(entry)
        self.add_class(f"tile-{self.kind}")

    def compose(self) -> ComposeResult:
        yield Static(GLYPH[self.kind], classes="tile-face")
        yield Static(self.entry["name"], classes="tile-name")

    async def show(self, data: bytes) -> None:
        """The picture in place of the glyph. A file that is not one keeps the glyph."""
        if TerminalImage is None:
            return
        try:
            from PIL import Image as PILImage

            opened = PILImage.open(BytesIO(data))
            opened.load()
        except Exception:
            return
        picture = TerminalImage(opened, classes="tile-face tile-picture")
        await self.query(".tile-face").remove()
        await self.mount(picture, before=self.query_one(".tile-name"))

    def on_focus(self) -> None:
        self.scroll_visible()

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        if event.chain >= 2:
            self.post_message(self.Opened(self))


class TileGrid(Grid):
    """The tiles, as many across as fit; the arrows walk them."""

    TILE_WIDTH = 22

    BINDINGS = [
        Binding("left", "move(-1)", "Left", show=False),
        Binding("right", "move(1)", "Right", show=False),
        Binding("up", "move_row(-1)", "Up", show=False),
        Binding("down", "move_row(1)", "Down", show=False),
        Binding("home", "jump(0)", "First", show=False),
        Binding("end", "jump(-1)", "Last", show=False),
        Binding("enter", "open", "Open", show=False),
    ]

    @property
    def columns(self) -> int:
        return max(1, self.size.width // self.TILE_WIDTH) if self.size.width else 4

    def on_resize(self) -> None:
        self.styles.grid_size_columns = self.columns

    @property
    def focused_tile(self) -> Tile | None:
        focused = self.screen.focused
        return focused if isinstance(focused, Tile) and focused in self.children else None

    def _go(self, index: int) -> None:
        tiles = list(self.query(Tile))
        if tiles:
            tiles[max(0, min(index, len(tiles) - 1))].focus()

    def action_move(self, delta: int) -> None:
        tile = self.focused_tile
        self._go((tile.index if tile else 0) + delta)

    def action_move_row(self, delta: int) -> None:
        tile = self.focused_tile
        self._go((tile.index if tile else 0) + delta * self.columns)

    def action_jump(self, index: int) -> None:
        self._go(index if index >= 0 else len(self.children) - 1)

    def action_open(self) -> None:
        tile = self.focused_tile
        if tile is not None:
            self.post_message(Tile.Opened(tile))


# -- the pane ----------------------------------------------------------------------------------
# Which buttons are there where: at the top, among the groups; or in a folder.
AT_TOP = frozenset({"open", "refresh"})
# Open and Up are enter and backspace in a folder, and need no button there.
IN_FOLDER = frozenset(
    {
        "put",
        "new_record",
        "rename",
        "delete_record",
        "toggle_view",
        "sort",
        "refresh",
    }
)


class GridPane(KitPane):
    """The groups, then a folder in one: as a list or tiles, with the picture beside."""

    BINDINGS = [
        *KitPane.BINDINGS,
        ("backspace", "fire('up')", "Up"),
        ("v", "fire('toggle_view')", "List or thumbnails"),
        ("s", "fire('sort')", "Sort"),
        ("S", "fire('reverse')", "Turn the sort around"),
        ("r", "fire('refresh')", "Refresh"),
        ("p", "fire('put')", "Put a file here"),
        ("g", "fire('get')", "Get a file"),
        ("e", "fire('rename')", "Rename"),
        ("M", "fire('move')", "Move"),
    ]

    DEFAULT_CSS = """
    GridPane {
        #grid-crumb { height: 1; padding: 0 3; color: $muted; }
        #grid-row { height: 1fr; }
        #grid-views { height: 1fr; width: 1fr; padding: 1 2; }
        #grid-tiles {
            layout: grid;
            grid-size: 4;
            grid-gutter: 0 1;
            grid-rows: auto;
            height: 1fr;
            overflow-y: auto;
            padding: 0 1;
            background: $surface;
            border: round $line;
            scrollbar-size: 1 1;
        }
        #grid-tiles:focus-within { border: round $primary; }
        Tile { width: 100%; height: auto; border: round transparent; }
        Tile:focus { border: round $primary; }
        Tile .tile-face {
            width: 100%;
            height: 6;
            content-align: center middle;
            background: $panel;
            color: $primary;
            text-style: bold;
        }
        Tile .tile-picture { width: 100%; height: 6; background: $panel; }
        Tile .tile-name {
            width: 100%;
            height: 1;
            text-align: center;
            text-wrap: nowrap;
            text-overflow: ellipsis;
        }
        Tile.tile-folder .tile-name { text-style: bold; }
        Tile:focus .tile-name { background: $primary 25%; }
        #grid-picture {
            width: 40%;
            height: 1fr;
            padding: 1 2;
            background: $surface;
            border-left: solid $line;
        }
        #grid-picture #picture-caption { height: auto; margin-bottom: 1; }
        #grid-picture .picture-image { width: auto; height: auto; }
    }
    """

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        group = field_of(self.model, screen.get("group")) or {}
        self.group_field: str = group.get("name", "")
        self.group_model: dict = self.models.get(group.get("to", "")) or {"fields": []}
        self.group_title: str = self.group_model.get("title") or "title"
        self.group_subtitle: str = screen.get("group_subtitle") or ""
        self.group_open: str = screen.get("group_open") or ""
        self.title_field: str = screen.get("title") or self.model.get("title") or "name"
        self.folder_field: str = screen.get("folder") or "folder"
        self.kind_field: str = screen.get("kind") or "kind"
        self.size_field: str = screen.get("size") or ""
        self.modified_field: str = screen.get("modified") or ""
        self.mime_field: str = screen.get("mime") or ""
        self.extensions = [ext for ext in EXTENSIONS if ext.applies(self.group_model)]
        extra = [action for ext in self.extensions for action in ext.actions]
        group_noun = str(self.group_model.get("label") or "group").lower()
        self.ACTIONS = (
            *extra,
            Action(
                "put",
                "Put a file here",
                "p",
                variant="primary",
                hint="A file from this machine, into the folder you are in",
            ),
            Action("new_record", "New folder", "^n"),
            Action(
                "open",
                "Open",
                "enter",
                hint=f"Into the {group_noun} or folder, or the picture beside",
            ),
            Action("up", "Up", "bksp", hint=f"The folder above; the {group_noun}s at the top"),
            Action("rename", "Rename", "e", hint="Rename it; M moves it to another folder"),
            Action("delete_record", "Delete", "del", variant="error"),
            Action(
                "toggle_view", "Thumbnails", "v", hint="Show the folder as pictures, or as a list"
            ),
            Action(
                "sort", "Sort: Name", "s", hint="Name, date, size or type; shift-s turns it around"
            ),
            Action("refresh", "Refresh", "r"),
        )
        self.top_actions = AT_TOP | {a.id for a in extra}
        # None at the top, where the groups are; then a group and a folder in it.
        self.group: str | None = None
        self.folder = ""
        self.groups: list[dict] = []
        self.entries: list[dict] = []
        self.sort_key = "name"
        self.descending = False
        self.view = "list"
        # Pictures already fetched: thumbnails by (id, rev), and the bigger
        # ones the panel shows.
        self._thumbs: dict[tuple[str, str], bytes] = {}
        self._pictures: dict[tuple[str, str], bytes] = {}

    def content(self) -> ComposeResult:
        yield Static("", id="grid-crumb")
        with Horizontal(id="grid-row"):
            with ContentSwitcher(id="grid-views", initial="grid-table"):
                yield DataTable(id="grid-table", cursor_type="row")
                yield TileGrid(id="grid-tiles")
            yield Picture(id="grid-picture")

    def on_mount(self) -> None:
        self._columns()

    # -- where we are -------------------------------------------------------
    @property
    def at_top(self) -> bool:
        return self.group is None

    def group_label(self, record: dict | None) -> str:
        if record is None:
            return self.group or ""
        return str((record.get("fields") or {}).get(self.group_title) or record["id"])

    def opens(self, record: dict) -> bool:
        return not self.group_open or (record.get("fields") or {}).get(self.group_open) is not False

    @property
    def current_group(self) -> dict | None:
        return next((g for g in self.groups if g["id"] == self.group), None)

    def go_to(self, group: str, folder: str = "") -> None:
        """Stand in *folder* of *group*; the next reload lists it."""
        if group != self.group:
            self._thumbs.clear()
            self._pictures.clear()
        self.group, self.folder = group, folder

    def open_group(self, group: str) -> None:
        self.go_to(group)
        self.reload()

    def reload(self) -> None:
        self.load()

    def _entry(self, record: dict) -> dict:
        f = record.get("fields") or {}
        return {
            "id": record["id"],
            "rev": str(record.get("rev", "")),
            "record": record,
            "name": str(f.get(self.title_field) or ""),
            "folder": str(f.get(self.folder_field) or ""),
            "is_dir": f.get(self.kind_field) == "folder",
            "size": int(f.get(self.size_field) or 0) if self.size_field else 0,
            "modified": _seconds(f.get(self.modified_field)) if self.modified_field else 0.0,
            "mime": str(f.get(self.mime_field) or "") if self.mime_field else "",
        }

    @work(exclusive=True, group="grid")
    async def load(self, notice: str = "") -> None:
        """List where we stand. *notice* is said afterwards, in red: why we
        are here rather than where we were."""
        client = self.api
        if client is None:
            return
        self.query_one(Picture).hide()
        try:
            self.groups = await client.records(self.group_model.get("id", ""))
            if not self.at_top:
                found = await client.records(
                    self.model_id, **{self.group_field: self.group, self.folder_field: self.folder}
                )
                self.entries = [self._entry(r) for r in found]
            else:
                self.entries = []
        except ApiError as exc:
            if exc.status_code in (400, 404) and not self.at_top:
                # Gone from under us, or somewhere the server cannot show: back up.
                self.group, self.folder = None, ""
                self.load(str(exc))
                return
            await self.signed_out(exc)
            return
        self.loaded = True
        self.draw()
        self.status(notice, error=bool(notice))

    # -- drawing -------------------------------------------------------------
    @property
    def rows(self) -> list[dict]:
        """What is listed, in order: the groups at the top, else the folder."""
        if self.at_top:
            return self.groups
        return sort_entries(self.entries, self.sort_key, self.descending)

    def _columns(self) -> None:
        """The table's columns for where we are: the groups', or a folder's."""
        level = "top" if self.at_top else "folder"
        if getattr(self, "_columns_for", None) == level:
            return
        self._columns_for = level
        table = self.query_one("#grid-table", DataTable)
        table.clear(columns=True)
        if self.at_top:
            columns = [str(self.group_model.get("label") or "").upper()]
            if self.group_subtitle:
                columns.append("")
            columns += [c for ext in self.extensions for c in ext.columns]
            table.add_columns(*columns)
        else:
            table.add_columns("NAME", "MODIFIED", "SIZE", "TYPE")

    def draw(self) -> None:
        crumb = self.query_one("#grid-crumb", Static)
        noun = str(self.group_model.get("label") or "group")
        if self.at_top:
            crumb.update(f"[{MUTED}]{escape(noun)}s[/]")
        else:
            trail = self.group_label(self.current_group)
            if self.folder:
                trail += " / " + self.folder.replace("/", " / ")
            crumb.update(f"[b]{escape(trail)}[/]")
        for button in self.query(".toolbar Button"):
            action = (button.id or "")[len("do-") :]
            button.display = action in (self.top_actions if self.at_top else IN_FOLDER)
        self._label("toggle_view", "List" if self.view == "grid" else "Thumbnails")
        self._label("sort", f"Sort: {dict(SORTS)[self.sort_key]} {'↓' if self.descending else '↑'}")
        showing = "grid-tiles" if self.view == "grid" and not self.at_top else "grid-table"
        self.query_one("#grid-views", ContentSwitcher).current = showing
        self._columns()
        if showing == "grid-tiles":
            self.draw_tiles()
        else:
            self.draw_table()
        self.highlighted_changed()

    def _label(self, action: str, text: str) -> None:
        button = self.query_one(f"#do-{action}", Button)
        key = next(a.key for a in self.ACTIONS if a.id == action)
        label = Text(text)
        label.append(f" {key}", style="dim")
        button.label = label

    def draw_table(self) -> None:
        table = self.query_one("#grid-table", DataTable)
        row = table.cursor_row
        table.clear()
        if self.at_top:
            for record in self.groups:
                fields = record.get("fields") or {}
                title = self.group_label(record)
                cells: list = [Text(title, style="bold" if self.opens(record) else MUTED)]
                if self.group_subtitle:
                    cells.append(Text(str(fields.get(self.group_subtitle) or ""), style=MUTED))
                for ext in self.extensions:
                    cells += list(ext.cells(record))
                table.add_row(*cells)
        else:
            for entry in self.rows:
                if entry["is_dir"]:
                    when = format_date(entry["modified"])
                    table.add_row(Text(entry["name"] + "/", style="bold"), when, "", "Folder")
                else:
                    table.add_row(
                        entry["name"],
                        format_date(entry["modified"]),
                        format_size(entry["size"]) if self.size_field else "",
                        type_label(entry),
                    )
        if table.row_count:
            table.move_cursor(row=min(max(row, 0), table.row_count - 1))
        if self.screen.focused is None or self in self.screen.focused.ancestors_with_self:
            table.focus()

    def draw_tiles(self) -> None:
        grid = self.query_one(TileGrid)
        grid.remove_children()
        tiles = [Tile(index, entry) for index, entry in enumerate(self.rows)]
        grid.mount(*tiles)
        grid.styles.grid_size_columns = grid.columns
        if tiles:
            wanted = min(self.query_one("#grid-table", DataTable).cursor_row, len(tiles) - 1)
            tiles[max(wanted, 0)].focus()
        self.fill_thumbs()

    @work(exclusive=True, group="grid-thumbs")
    async def fill_thumbs(self) -> None:
        """Every picture tile gets its picture, a few at a time, in order."""
        client = self.api
        if client is None:
            return
        tiles = [tile for tile in self.query_one(TileGrid).query(Tile) if tile.kind == "image"]
        gate = asyncio.Semaphore(4)

        async def one(tile: Tile) -> None:
            key = (tile.entry["id"], tile.entry["rev"])
            data = self._thumbs.get(key)
            if data is None:
                async with gate:
                    try:
                        data = await client.record_thumb(self.model_id, tile.entry["id"], size=256)
                    except ApiError:
                        return  # the glyph stays
                self._thumbs[key] = data
            if tile.is_attached:
                await tile.show(data)

        await asyncio.gather(*(one(tile) for tile in tiles))

    # -- what the cursor is on ------------------------------------------------
    @property
    def highlighted(self) -> dict | None:
        rows = self.rows
        if self.view == "grid" and not self.at_top:
            tile = self.query_one(TileGrid).focused_tile
            return tile.entry if tile is not None else None
        index = self.query_one("#grid-table", DataTable).cursor_row
        return rows[index] if 0 <= index < len(rows) else None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        self.highlighted_changed()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if isinstance(event.widget, Tile):
            self.highlighted_changed()

    def highlighted_changed(self) -> None:
        setter = getattr(self.screen, "redraw_status", None)
        if callable(setter):
            setter()
        self.update_picture()

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        count = len(self.groups)
        noun = str(self.group_model.get("label") or "group").lower()
        return "ok", f"{count} {noun}{'' if count == 1 else 's'}"

    def status_detail(self) -> str:
        entry = self.highlighted
        if entry is None:
            return ""
        if self.at_top:
            for ext in self.extensions:
                if ext.detail is not None:
                    said = ext.detail(entry)
                    if said:
                        return said
            return ""
        if entry["is_dir"]:
            return f"[b]{escape(entry['name'])}[/]  [{MUTED}]folder[/]"
        return (
            f"[b]{escape(entry['name'])}[/]  [{MUTED}]{format_size(entry['size'])}  "
            f"{type_label(entry)}  {format_date(entry['modified'])}[/]"
        )

    @work(exclusive=True, group="grid-picture")
    async def update_picture(self) -> None:
        panel = self.query_one(Picture)
        entry = self.highlighted
        if self.at_top or entry is None or kind_of(entry) != "image":
            panel.hide()
            return
        where = f"{self.group_label(self.current_group)}/{self.folder + '/' if self.folder else ''}{entry['name']}"
        if panel.shown == where:
            return
        key = (entry["id"], entry["rev"])
        data = self._pictures.get(key)
        if data is None:
            panel.say(f"fetching {entry['name']}…")
            try:
                data = await self.api.record_thumb(self.model_id, entry["id"], size=1024)
            except ApiError as exc:
                if exc.status_code == 415:
                    panel.say(f"{entry['name']}: not a picture the server can draw")
                    return
                try:
                    data = await self.api.record_content(self.model_id, entry["id"])
                except ApiError as exc2:
                    panel.say(f"{entry['name']}: {exc2}")
                    return
            self._pictures[key] = data
        await panel.show(where, entry["name"], data)

    # -- moving about -----------------------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.act_open()

    def on_tile_opened(self, event: Tile.Opened) -> None:
        event.stop()
        self.act_open()

    def act_open(self) -> None:
        entry = self.highlighted
        if entry is None:
            return
        if self.at_top:
            if not self.opens(entry):
                about = str((entry.get("fields") or {}).get(self.group_subtitle) or "")
                self.status(
                    f"{self.group_label(entry)}: {about}"
                    if about
                    else f"{self.group_label(entry)} cannot be opened from here."
                )
                return
            self.open_group(entry["id"])
        elif entry["is_dir"]:
            self.folder = f"{self.folder}/{entry['name']}" if self.folder else entry["name"]
            self.reload()
        elif kind_of(entry) == "image":
            self.update_picture()
        else:
            self.status(
                f"{entry['name']} is a {type_label(entry).lower()} — g gets it onto this machine."
            )

    def act_up(self) -> None:
        if self.at_top:
            return
        if self.folder:
            self.folder = self.folder.rsplit("/", 1)[0] if "/" in self.folder else ""
        else:
            self.group = None
        self.reload()

    def act_toggle_view(self) -> None:
        if self.at_top:
            return
        self.view = "list" if self.view == "grid" else "grid"
        self.draw()

    def act_sort(self) -> None:
        keys = [key for key, _label in SORTS]
        self.sort_key = keys[(keys.index(self.sort_key) + 1) % len(keys)]
        self.descending = DESCENDING_BY_DEFAULT[self.sort_key]
        self.draw()

    def act_reverse(self) -> None:
        self.descending = not self.descending
        self.draw()

    def act_refresh(self) -> None:
        self.reload()

    # -- the extensions' own keys, among the groups ---------------------------------
    def fire(self, name: str) -> None:
        for ext in self.extensions:
            if any(a.id == name for a in ext.actions):
                if self.at_top and ext.run is not None:
                    self._run_extension(ext, name, self.highlighted)
                return
        super().fire(name)

    @work(group="ui")
    async def _run_extension(self, ext: GroupExtension, name: str, record: dict | None) -> None:
        await ext.run(self, name, record)

    def on_key(self, event: events.Key) -> None:
        if not self.at_top:
            return
        for ext in self.extensions:
            for action_id, key in ext.keys.items():
                if event.key == key:
                    event.stop()
                    self.fire(action_id)
                    return

    # -- changing what is there ----------------------------------------------------
    def _where(self) -> dict:
        return {self.group_field: self.group, self.folder_field: self.folder}

    def act_new_record(self) -> None:
        if self.at_top:
            for ext in self.extensions:
                if any(a.id == "new_group" for a in ext.actions):
                    self.fire("new_group")
                    return
            return
        self.new_folder()

    @work(group="ui")
    async def new_folder(self) -> None:
        name = await self.app.push_screen_wait(PromptModal("New folder", placeholder="Its name"))
        if not name or not name.strip():
            return
        try:
            await self.api.create_record(
                self.model_id,
                {**self._where(), self.title_field: name.strip(), self.kind_field: "folder"},
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Made {name.strip()}")
        self.reload()

    def act_put(self) -> None:
        if not self.at_top:
            self.put_file()

    @work(group="ui")
    async def put_file(self) -> None:
        answer = await self.app.push_screen_wait(
            PromptModal(
                "Put a file here",
                placeholder="~/Pictures/cat.jpg",
                detail=f"[dim]A file on this machine, into {escape(self._here())}.[/]",
            )
        )
        if not answer or not answer.strip():
            return
        source = Path(answer.strip()).expanduser()
        if not source.is_file():
            self.status(f"There is no file at {source}.", error=True)
            return
        self.status(f"putting {source.name}…", note=True)
        try:
            made = await self.api.upload_record(
                self.model_id,
                {**self._where(), self.title_field: source.name},
                source.read_bytes(),
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(
            f"Put {(made.get('fields') or {}).get(self.title_field, source.name)} in {self._here()}"
        )
        self.reload()

    def _here(self) -> str:
        return self.group_label(self.current_group) + (f"/{self.folder}" if self.folder else "")

    def act_get(self) -> None:
        entry = self.highlighted
        if self.at_top or entry is None or entry["is_dir"]:
            return
        self.get_file(entry)

    @work(group="ui")
    async def get_file(self, entry: dict) -> None:
        default = Path.home() / "Downloads" / entry["name"]
        answer = await self.app.push_screen_wait(
            PromptModal(
                f"Get {entry['name']}",
                value=str(default),
                detail="[dim]Where on this machine to save it.[/]",
            )
        )
        if not answer or not answer.strip():
            return
        target = Path(answer.strip()).expanduser()
        if target.is_dir():
            target = target / entry["name"]
        if target.exists():
            self.status(f"{target} is there already; pick another name.", error=True)
            return
        try:
            data = await self.api.record_content(self.model_id, entry["id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except (ApiError, OSError) as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Saved {entry['name']} at {target}")

    def act_rename(self) -> None:
        entry = self.highlighted
        if not self.at_top and entry is not None:
            self.change(entry, "rename")

    def act_move(self) -> None:
        entry = self.highlighted
        if not self.at_top and entry is not None:
            self.change(entry, "move")

    @work(group="ui")
    async def change(self, entry: dict, what: str) -> None:
        if what == "rename":
            answer = await self.app.push_screen_wait(PromptModal("Rename", value=entry["name"]))
            if not answer or answer.strip() == entry["name"]:
                return
            fields = {self.title_field: answer.strip()}
        else:
            answer = await self.app.push_screen_wait(
                PromptModal(
                    f"Move {entry['name']}",
                    value=entry["folder"],
                    detail="[dim]To which folder; / is the top.[/]",
                )
            )
            if answer is None or answer.strip("/ ") == entry["folder"]:
                return
            fields = {self.folder_field: answer.strip("/ ")}
        try:
            await self.api.update_record(
                self.model_id, entry["id"], fields, rev=entry["rev"] or None
            )
        except ApiError as exc:
            self.status(
                "That changed somewhere else — here it is as it is now."
                if exc.status_code == 409
                else str(exc),
                error=True,
            )
            self.reload()
            return
        self.status(
            "Renamed" if what == "rename" else f"Moved to {answer.strip('/ ') or 'the top'}"
        )
        self.reload()

    def act_delete_record(self) -> None:
        entry = self.highlighted
        if not self.at_top and entry is not None:
            self.delete_entry(entry)

    @work(group="ui")
    async def delete_entry(self, entry: dict) -> None:
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete {entry['name']}?",
                detail="[dim]Everything in it goes with it. It is not recoverable.[/]"
                if entry["is_dir"]
                else "[dim]It is not recoverable.[/]",
                confirm_label="Delete",
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete_record(self.model_id, entry["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Deleted {entry['name']}")
        self.reload()
