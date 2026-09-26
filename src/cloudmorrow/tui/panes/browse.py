"""Browse: what is in a server share, seen from the terminal.

The third view on the Files tab. The shares first; open one and it is the
folders and files in it, sorted the way the web app sorts them — name, date,
size or type, folders first — as a list, or as a grid of thumbnails, since
the terminal can draw a picture. The picture the cursor is on is shown
beside the listing, the way a note's picture is shown beside the note.

Only a server share opens. A machine share's files are on that machine and
the server has nothing to show; mount it, and look with whatever you look
at files with.

The server makes the thumbnails small, so a tile is a few kilobytes and not
the photo. The panel asks for a bigger one, which is still not the whole
photo: a terminal has no use for twelve megapixels.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from io import BytesIO

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, ContentSwitcher, DataTable, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.picture import Picture, TerminalImage
from cloudmorrow.tui.widgets.toolbar import Action

# -- what a file is ----------------------------------------------------------------
# The same kinds, by the same extensions, as the web app's files.js: the two
# should agree about what a thing is and where it sorts.
KINDS = ("folder", "image", "video", "audio", "document", "text", "archive", "file")
BY_EXT = {
    "image": (
        "jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "avif", "bmp", "svg", "tif", "tiff",
    ),
    "video": ("mp4", "m4v", "mov", "mkv", "webm", "avi", "wmv"),
    "audio": ("mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "aiff"),
    "document": (
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp",
        "pages", "numbers", "key", "epub",
    ),
    "text": (
        "txt", "md", "json", "csv", "xml", "yaml", "yml", "toml", "log",
        "py", "js", "ts", "html", "css", "sh", "ini", "conf",
    ),
    "archive": ("zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "dmg", "iso"),
}
KIND_OF_EXT = {ext: kind for kind, exts in BY_EXT.items() for ext in exts}
KIND_LABEL = {
    "folder": "Folder", "image": "Picture", "video": "Video", "audio": "Audio",
    "document": "Document", "text": "Text", "archive": "Archive", "file": "File",
}
# What a tile shows until it has a picture, or when it will never have one.
GLYPH = {
    "folder": "▰▰▰", "image": "▣", "video": "▶", "audio": "♪",
    "document": "≡", "text": "≡", "archive": "▤", "file": "▢",
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


# -- the grid ----------------------------------------------------------------------------
class Tile(Vertical, can_focus=True):
    """One thing in the grid: its picture or its glyph, and its name under it."""

    class Opened(Message):
        def __init__(self, tile: Tile) -> None:
            self.tile = tile
            super().__init__()

    def __init__(self, index: int, entry: dict, path: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.index = index
        self.entry = entry
        self.path = path
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


# -- the pane --------------------------------------------------------------------------------
class BrowsePane(Pane):
    """A share's folders and files, as a list or a grid, with the picture beside."""

    TAB_LABEL = "Browse"
    HEAD = False
    BINDINGS = [
        ("backspace", "fire('up')", "Up"),
        ("v", "fire('toggle_view')", "List or thumbnails"),
        ("s", "fire('sort')", "Sort"),
        ("S", "fire('reverse')", "Turn the sort around"),
        ("r", "fire('refresh')", "Refresh"),
    ]
    ACTIONS = (
        Action("open", "Open", "enter", hint="Into the folder, or the picture beside"),
        Action("up", "Up", "bksp", hint="The folder above; the shares at the top"),
        Action("toggle_view", "Thumbnails", "v", hint="Show the folder as pictures, or as a list"),
        Action("sort", "Sort: Name", "s", hint="Name, date, size or type; shift-s turns it around"),
        Action("refresh", "Refresh", "r"),
    )

    DEFAULT_CSS = """
    BrowsePane {
        #browse-crumb { height: 1; padding: 0 3; color: $muted; }
        #browse-row { height: 1fr; }
        #browse-views { height: 1fr; width: 1fr; padding: 1 2; }
        #browse-grid {
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
        #browse-grid:focus-within { border: round $primary; }
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
        #browse-picture {
            width: 40%;
            height: 1fr;
            padding: 1 2;
            background: $surface;
            border-left: solid $line;
        }
        #browse-picture #picture-caption { height: auto; margin-bottom: 1; }
        #browse-picture .picture-image { width: auto; height: auto; }
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # None at the top, where the shares are; then a share and a folder in it.
        self.share: str | None = None
        self.path = ""
        self.shares: list[dict] = []
        self.entries: list[dict] = []
        self.sort_key = "name"
        self.descending = False
        self.view = "list"
        # Pictures already fetched: thumbnails by (share, path, modified), and
        # the bigger ones the panel shows. A share's pictures are its own.
        self._thumbs: dict[tuple[str, str, float], bytes] = {}
        self._pictures: dict[tuple[str, str, float], bytes] = {}

    def content(self) -> ComposeResult:
        yield Static("", id="browse-crumb")
        with Horizontal(id="browse-row"):
            with ContentSwitcher(id="browse-views", initial="browse-table"):
                yield DataTable(id="browse-table", cursor_type="row")
                yield TileGrid(id="browse-grid")
            yield Picture(id="browse-picture")

    def on_mount(self) -> None:
        self.query_one("#browse-table", DataTable).add_columns("NAME", "MODIFIED", "SIZE", "TYPE")

    def on_show(self) -> None:
        self.reload()

    # -- where we are -------------------------------------------------------
    @property
    def at_top(self) -> bool:
        return self.share is None

    def go_to(self, name: str) -> None:
        """Stand at *name*'s top folder; the next reload lists it."""
        if name != self.share:
            self._thumbs.clear()
            self._pictures.clear()
        self.share, self.path = name, ""

    def open_share(self, name: str) -> None:
        """Land in *name*'s top folder — the Fileshares view asks for this."""
        self.go_to(name)
        self.reload()

    def reload(self) -> None:
        self.load()

    @work(exclusive=True, group="browse")
    async def load(self, notice: str = "") -> None:
        """List where we stand. *notice* is said afterwards, in red: why we
        are here rather than where we were."""
        client = self.api
        if client is None:
            return
        self.query_one(Picture).hide()
        try:
            if self.at_top:
                self.shares = await client.shares()
                self.entries = []
            else:
                listing = await client.share_listing(self.share, self.path)
                self.entries = listing["entries"]
        except ApiError as exc:
            if exc.status_code in (404, 409) and not self.at_top:
                # Gone from under us, or a machine share after all: back up.
                self.share, self.path = None, ""
                self.load(str(exc))
                return
            self.status(str(exc), error=True)
            return
        self.draw()
        self.status(notice, error=bool(notice))

    # -- drawing -------------------------------------------------------------
    @property
    def rows(self) -> list[dict]:
        """What is listed, in order: the shares at the top, else the folder."""
        if self.at_top:
            return self.shares
        return sort_entries(self.entries, self.sort_key, self.descending)

    def draw(self) -> None:
        crumb = self.query_one("#browse-crumb", Static)
        if self.at_top:
            crumb.update(f"[{MUTED}]Shares[/]")
        else:
            trail = self.share + (" / " + self.path.replace("/", " / ") if self.path else "")
            crumb.update(f"[b]{trail}[/]")
        self._label("toggle_view", "List" if self.view == "grid" else "Thumbnails")
        self._label("sort", f"Sort: {dict(SORTS)[self.sort_key]} {'↓' if self.descending else '↑'}")
        showing = "browse-grid" if self.view == "grid" and not self.at_top else "browse-table"
        self.query_one("#browse-views", ContentSwitcher).current = showing
        if showing == "browse-grid":
            self.draw_grid()
        else:
            self.draw_table()
        self.highlighted_changed()

    def _label(self, action: str, text: str) -> None:
        button = self.query_one(f"#do-{action}", Button)
        key = next(a.key for a in self.ACTIONS if a.id == action)
        button.label = f"{text}  {key}"

    def draw_table(self) -> None:
        table = self.query_one("#browse-table", DataTable)
        row = table.cursor_row
        table.clear()
        if self.at_top:
            for share in self.shares:
                if share.get("kind") == "machine":
                    where = f"on {share.get('machine', '')}"
                    if not share.get("online"):
                        where += ", offline"
                    table.add_row(
                        Text(share["name"], style=MUTED),
                        Text(f"{where} — mount it to browse it", style=MUTED),
                        "",
                        "",
                    )
                elif share.get("kind") == "drive":
                    about = share.get("description") or "your own files on the server"
                    table.add_row(Text(share["name"], style="bold"), about, "", "My Files")
                else:
                    about = share.get("description") or "on the server"
                    table.add_row(Text(share["name"], style="bold"), about, "", "Share")
        else:
            for entry in self.rows:
                if entry.get("is_dir"):
                    when = format_date(entry.get("modified", 0))
                    table.add_row(Text(entry["name"] + "/", style="bold"), when, "", "Folder")
                else:
                    table.add_row(
                        entry["name"], format_date(entry.get("modified", 0)),
                        format_size(entry.get("size", 0)), type_label(entry),
                    )
        if table.row_count:
            table.move_cursor(row=min(max(row, 0), table.row_count - 1))
        if self.screen.focused is None or self in self.screen.focused.ancestors_with_self:
            table.focus()

    def draw_grid(self) -> None:
        grid = self.query_one(TileGrid)
        grid.remove_children()
        tiles = [
            Tile(index, entry, f"{self.path}/{entry['name']}" if self.path else entry["name"])
            for index, entry in enumerate(self.rows)
        ]
        grid.mount(*tiles)
        grid.styles.grid_size_columns = grid.columns
        if tiles:
            wanted = min(self.query_one("#browse-table", DataTable).cursor_row, len(tiles) - 1)
            tiles[max(wanted, 0)].focus()
        self.fill_thumbs()

    @work(exclusive=True, group="browse-thumbs")
    async def fill_thumbs(self) -> None:
        """Every picture tile gets its picture, a few at a time, in order."""
        client = self.api
        share = self.share
        if client is None or share is None:
            return
        tiles = [tile for tile in self.query_one(TileGrid).query(Tile) if tile.kind == "image"]
        gate = asyncio.Semaphore(4)

        async def one(tile: Tile) -> None:
            key = (share, tile.path, tile.entry.get("modified", 0))
            data = self._thumbs.get(key)
            if data is None:
                async with gate:
                    try:
                        data = await client.share_thumb(share, tile.path, size=256)
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
        index = self.query_one("#browse-table", DataTable).cursor_row
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

    def status_detail(self) -> str:
        entry = self.highlighted
        if entry is None:
            return ""
        if self.at_top:
            return entry.get("url") or ""
        if entry.get("is_dir"):
            return f"[b]{entry['name']}[/]  [{MUTED}]folder[/]"
        return (
            f"[b]{entry['name']}[/]  [{MUTED}]{format_size(entry.get('size', 0))}  "
            f"{type_label(entry)}  {format_date(entry.get('modified', 0))}[/]"
        )

    @work(exclusive=True, group="browse-picture")
    async def update_picture(self) -> None:
        panel = self.query_one(Picture)
        entry = self.highlighted
        if self.at_top or entry is None or kind_of(entry) != "image":
            panel.hide()
            return
        share = self.share
        path = f"{self.path}/{entry['name']}" if self.path else entry["name"]
        if panel.shown == path:
            return
        key = (share, path, entry.get("modified", 0))
        data = self._pictures.get(key)
        if data is None:
            panel.say(f"fetching {entry['name']}…")
            try:
                data = await self.api.share_thumb(share, path, size=1024)
            except ApiError as exc:
                if exc.status_code == 415:
                    panel.say(f"{entry['name']}: not a picture the server can draw")
                    return
                try:
                    data = await self.api.share_file(share, path)
                except ApiError as exc2:
                    panel.say(f"{entry['name']}: {exc2}")
                    return
            self._pictures[key] = data
        await panel.show(path, entry["name"], data)

    # -- actions ---------------------------------------------------------------
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
            if entry.get("kind") == "machine":
                machine = entry.get("machine") or "a machine"
                self.status(f"{entry['name']} is on {machine} — mount it to browse it.")
                return
            self.open_share(entry["name"])
        elif entry.get("is_dir"):
            self.path = f"{self.path}/{entry['name']}" if self.path else entry["name"]
            self.reload()
        elif kind_of(entry) == "image":
            self.update_picture()
        else:
            what = type_label(entry).lower()
            self.status(f"{entry['name']} is a {what} — mount the share to open it.")

    def act_up(self) -> None:
        if self.at_top:
            return
        if self.path:
            self.path = self.path.rsplit("/", 1)[0] if "/" in self.path else ""
        else:
            self.share = None
        self.reload()

    def act_toggle_view(self) -> None:
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
