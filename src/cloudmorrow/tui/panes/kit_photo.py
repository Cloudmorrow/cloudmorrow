"""The kit's `photo` in the terminal: a photo editor, by the numbers.

It opens on the edits, newest first, with New, which asks which photo of
the drive to start from. An edit opens the editor (docs/PHOTO.md, *The
editor*): the picture in the middle, the words laid on it listed on the
right, and the edit's size, turn and crop said in the header.

The picture is the Quill's pictures API's `picture` of the edit — the
export as it would be — drawn by textual-image: the real picture where the
terminal speaks Kitty or Sixel, half-cells elsewhere. Without a pictures
API the viewer says in words what the edit does, and the edit's size is
asked for the first time it is needed.

Everything is a key (the spec's): r turns right, R left, m mirrors, c crops
from four typed numbers, C keeps the whole picture, s sets the export's
size, t lays words on the picture, enter on them changes the words, k moves
them (x y, typed), x takes them off, e exports, o opens the export, and
tab goes between the picture and the texts.

The sums are cloudmorrow.quill.photo's and the writes client/photo.py's,
which the command line uses too: a crop here and `cm <quill> crop` are the
same write.
"""

from __future__ import annotations

from io import BytesIO

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ContentSwitcher, DataTable, Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.client.photo import Photo
from cloudmorrow.quill import photo as ph
from cloudmorrow.tui.kitdata import title_of
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.quill_actions import run_action
from cloudmorrow.tui.screens.modals import Modal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, LENS, MUTED
from cloudmorrow.tui.widgets.picture import TerminalImage
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import escape, plural

# How often the header asks after an export that is queued or rendering.
POLL_SECONDS = 2.0
# How a status is toned in the header.
STATUS_TONE = {"queued": LENS, "rendering": LENS, "done": GOOD, "failed": BAD}

# Which actions each of the two places has: the edits, and the editor.
IN_LIST = frozenset({"new_record", "open", "delete_record", "refresh"})
IN_EDITOR = frozenset(
    {
        "back",
        "turn_right",
        "turn_left",
        "mirror",
        "crop",
        "reset_crop",
        "size",
        "text",
        "move_text",
        "delete_record",
        "export",
        "open_output",
        "refresh",
    }
)


def viewer_words(fields: dict, texts: list[dict]) -> str:
    """What the edit does, said, for a terminal with no picture to show."""
    lines = []
    source = ph.source_size(fields)
    lines.append(f"[b]{source[0]} × {source[1]}[/] as taken" if source else f"[{MUTED}]size not known yet[/]")
    turn = ph.rotation_of(fields)
    if turn:
        lines.append(f"turned {turn}° clockwise")
    if ph.mirrored(fields):
        lines.append("mirrored")
    crop = ph.crop_of(fields)
    if crop != ph.WHOLE:
        lines.append(f"cropped to {ph.box_said(crop)}")
    out = ph.size_said(fields)
    if out:
        lines.append(f"comes out [b]{out}[/]")
    for text in texts:
        lines.append(f"[{ACCENT}]“{escape(str((text.get('fields') or {}).get('text') or ''))}”[/]")
    return "\n".join(lines)


class PickPhotoModal(Modal[dict | None]):
    """Which photo of the drive a new edit starts from. Dismisses with the file record, or None."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, photos: list[dict], *, within: str = "") -> None:
        super().__init__()
        self.photos = photos
        self.within = within.strip("/")

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="ph-pick"):
            yield Label("Which photo?", classes="modal-title")
            yield DataTable(id="ph-pick-photos", cursor_type="row", show_header=False)
            yield Static(
                f"[{MUTED}]Enter starts an edit of it; the photos are the ones in {self.within or 'the drive'}.[/]",
                classes="modal-detail",
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        table = self.query_one("#ph-pick-photos", DataTable)
        table.add_columns("photo")
        for photo in self.photos:
            f = photo.get("fields") or {}
            folder = str(f.get("folder") or "").strip("/").removeprefix(self.within).strip("/")
            name = Text()
            if folder:
                name.append(f"{folder}/", style=MUTED)
            name.append(str(f.get("name") or ""))
            table.add_row(name, key=photo["id"])
        if not self.photos:
            table.add_row(Text("No photos here yet.", style=MUTED))
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if 0 <= event.cursor_row < len(self.photos):
            self.dismiss(self.photos[event.cursor_row])

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)


class PhotoPane(KitPane):
    """The edits; then one of them, worked on."""

    BINDINGS = [
        *KitPane.BINDINGS,
        Binding("n", "fire('new_record')", "New", show=False),
        Binding("r", "fire('turn_right')", "Turn right", show=False),
        Binding("R", "fire('turn_left')", "Turn left", show=False),
        Binding("escape,backspace", "fire('back')", "Edits", show=False),
        Binding("m", "fire('mirror')", "Mirror", show=False),
        Binding("c", "fire('crop')", "Crop", show=False),
        Binding("C", "fire('reset_crop')", "Whole picture", show=False),
        Binding("s", "fire('size')", "Size", show=False),
        Binding("t", "fire('text')", "Text", show=False),
        Binding("k", "fire('move_text')", "Move text", show=False),
        Binding("x", "fire('delete_record')", "Delete", show=False),
        Binding("e", "fire('export')", "Export", show=False),
        Binding("o", "fire('open_output')", "Open the export", show=False),
        Binding("f5", "fire('refresh')", "Refresh", show=False),
        Binding("tab", "cycle(1)", "Next panel", show=False),
        Binding("shift+tab", "cycle(-1)", "Last panel", show=False),
    ]
    WRITING = KitPane.WRITING | {"turn_right", "turn_left", "mirror", "crop", "reset_crop", "size", "text", "move_text"}

    DEFAULT_CSS = """
    PhotoPane {
        #ph-views { height: 1fr; }
        #ph-list, #ph-editor { height: 1fr; }
        #ph-edits { height: 1fr; margin: 1 2 0 2; }
        #ph-head { height: 1; padding: 0 2; }
        #ph-top { height: 1fr; }
        #ph-viewer { width: 1fr; padding: 0 1; }
        #ph-viewer-caption { height: 1; }
        #ph-picture { width: auto; height: auto; }
        #ph-viewer-words { height: 1fr; }
        #ph-texts-col { width: 40; padding: 0 1; border-left: solid $line; }
        #ph-texts { height: 1fr; }
        .ph-title { height: 1; color: $muted; }
    }
    """

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.photo = Photo(None, quill, screen)
        self.edits: list[dict] = []
        # The edit open in the editor, and the words on it.
        self.edit: dict | None = None
        self.texts: list[dict] = []
        # What a Quill's `go` asked for: `edit` opens that one's editor.
        self.params: dict = {}
        # One picture on its way at a time; a change meanwhile asks again once it lands.
        self._fetching = False
        self._again = False
        actions = [
            Action("new_record", "New", "n", variant="primary"),
            Action("open", "Open", "enter"),
            Action("back", "Edits", "esc"),
            Action("turn_right", "Turn", "r", hint="A quarter turn clockwise; shift-r the other way"),
            Action("mirror", "Mirror", "m"),
            Action("crop", "Crop", "c", hint="The part kept, as x y w h in percent; shift-c keeps all of it"),
            Action("size", "Size", "s", hint="The export's size: 1920x1080, a width, or a percent"),
            Action("text", "Text", "t", hint="Words on the picture; enter changes them, k moves them"),
        ]
        if self.photo.export is not None:
            actions.append(Action("export", str(self.photo.export.get("label") or "Export"), "e"))
        actions += [
            Action("delete_record", "Delete", "del"),
            Action("refresh", "Refresh", "f5"),
        ]
        self.ACTIONS = self.offer(actions)

    # -- where we are ----------------------------------------------------------------
    @property
    def editing(self) -> bool:
        return self.edit is not None

    @property
    def edit_fields(self) -> dict:
        return (self.edit or {}).get("fields") or {}

    @property
    def text(self) -> dict | None:
        """The text the texts' cursor is on."""
        row = self.query_one("#ph-texts", DataTable).cursor_row
        return self.texts[row] if 0 <= row < len(self.texts) else None

    def fire(self, name: str) -> None:
        # Each place has its own actions; the other's keys do nothing here.
        if name not in (IN_EDITOR if self.editing else IN_LIST):
            return
        super().fire(name)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "fire" and parameters:
            name = str(parameters[0])
            if name not in (IN_EDITOR if self.editing else IN_LIST):
                return False
        return super().check_action(action, parameters)

    # -- layout -----------------------------------------------------------------------
    def content(self) -> ComposeResult:
        with ContentSwitcher(id="ph-views", initial="ph-list"):
            with Vertical(id="ph-list"):
                yield DataTable(id="ph-edits", cursor_type="row", zebra_stripes=True)
            with Vertical(id="ph-editor"):
                yield Static("", id="ph-head")
                with Horizontal(id="ph-top"):
                    with Vertical(id="ph-viewer"):
                        yield Static("", id="ph-viewer-caption")
                        if TerminalImage is not None and self.photo.pictures:
                            yield TerminalImage(id="ph-picture")
                        yield Static("", id="ph-viewer-words")
                    with Vertical(id="ph-texts-col"):
                        yield Static("Text on the picture", classes="ph-title")
                        yield DataTable(id="ph-texts", cursor_type="row", show_header=False)

    def on_mount(self) -> None:
        self.query_one("#ph-edits", DataTable).add_columns("NAME", "SIZE", "STATUS", "MADE")
        self.query_one("#ph-texts", DataTable).add_columns("words", "where")
        self._poll = self.set_interval(POLL_SECONDS, self._poll_status, pause=True)

    def card_status(self) -> tuple[str, str] | None:
        if not self.loaded:
            return None
        busy = [e for e in self.edits if (e.get("fields") or {}).get("status") in ("queued", "rendering")]
        if busy:
            return "news", f"{len(busy)} exporting"
        return "ok", plural(len(self.edits), self.noun)

    def status_detail(self) -> str:
        if self.editing:
            return f"[{MUTED}]{plural(len(self.texts), 'text')}[/]"
        return f"[{MUTED}]{plural(len(self.edits), self.noun)}[/]"

    def reload(self) -> None:
        self.photo.api = self.api
        if self.api is None:
            return
        wanted = str(self.params.pop("edit", "") or "")
        if wanted and wanted != (self.edit or {}).get("id"):
            # go("editor", edit=…): straight into its editor; the editor reads the rest.
            self.open_edit({"id": wanted, "fields": {}})
            return
        if self.editing:
            self.load_editor()
        else:
            self.load_edits()

    @work(exclusive=True, group="photo")
    async def load_edits(self, keep: str = "") -> None:
        try:
            self.edits = await self.photo.edits()
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.loaded = True
        self.draw_edits(keep)
        self.status("" if self.edits else f"No {plural(2, self.noun)} yet — New starts one from a photo.", note=True)

    def draw_edits(self, keep: str = "") -> None:
        self._show("ph-list")
        table = self.query_one("#ph-edits", DataTable)
        row = table.cursor_row
        table.clear()
        for record in self.edits:
            f = record.get("fields") or {}
            status = str(f.get("status") or "")
            table.add_row(
                Text(title_of(record, self.model), style="bold"),
                Text(ph.size_said(f), style=MUTED),
                Text(status, style=STATUS_TONE.get(status, MUTED)),
                Text(str(record.get("created_at") or "")[:16].replace("T", " "), style=MUTED),
                key=record["id"],
            )
        if keep:
            row = next((i for i, r in enumerate(self.edits) if r["id"] == keep), row)
        if self.edits:
            table.move_cursor(row=min(max(row, 0), len(self.edits) - 1))
        table.focus()

    @work(exclusive=True, group="photo")
    async def load_editor(self) -> None:
        if not await self._fetch_editor():
            return
        self.draw_editor()

    async def _fetch_editor(self) -> bool:
        """The edit and its texts again. False when it failed."""
        assert self.edit is not None
        try:
            self.edit = await self.api.record(self.photo.edit_model, self.edit["id"])
            self.texts = await self.photo.texts(self.edit["id"])
        except ApiError as exc:
            if exc.status_code == 404:
                # Gone from under us: back to the list.
                self.edit = None
                self.load_edits()
                self.status(str(exc), error=True)
                return False
            await self.went_wrong(exc)
            return False
        return True

    # -- drawing the editor ----------------------------------------------------------------
    def _show(self, view: str) -> None:
        self.query_one("#ph-views", ContentSwitcher).current = view
        for button in self.query(".toolbar Button"):
            action = (button.id or "")[len("do-") :]
            button.display = action in (IN_EDITOR if view == "ph-editor" else IN_LIST)
        self.refresh_bindings()

    def draw_editor(self) -> None:
        self._show("ph-editor")
        self.draw_head()
        self.draw_texts()
        self.draw_now()

    def draw_head(self) -> None:
        f = self.edit_fields
        parts = [f"[b {ACCENT}]{escape(title_of(self.edit, self.model))}[/]"]
        out = ph.size_said(f)
        parts.append(f"[{MUTED}]{out}[/]" if out else f"[{MUTED}]size not known yet[/]")
        turn = ph.rotation_of(f)
        if turn:
            parts.append(f"[{MUTED}]turned {turn}°[/]")
        if ph.mirrored(f):
            parts.append(f"[{MUTED}]mirrored[/]")
        crop = ph.crop_of(f)
        if crop != ph.WHOLE:
            parts.append(f"[{MUTED}]crop {ph.box_said(crop)}[/]")
        status = str(f.get("status") or "")
        if status:
            said = f"[{STATUS_TONE.get(status, MUTED)}]{escape(status)}[/]"
            if f.get("message"):
                said += f" [{MUTED}]{escape(str(f['message']))}[/]"
            parts.append(said)
        if f.get("output"):
            parts.append(f"[{GOOD}]exported[/] [{MUTED}]o opens it[/]")
        self.query_one("#ph-head", Static).update("   ".join(parts))

    def draw_texts(self) -> None:
        table = self.query_one("#ph-texts", DataTable)
        row = table.cursor_row
        table.clear()
        for text in self.texts:
            t = ph.text_of(text.get("fields") or {})
            where = f"{t['x']:g} {t['y']:g} · {t['size']:g}% · {t['colour']}"
            table.add_row(escape(t["text"].replace("\n", " / ")), Text(where, style=MUTED), key=text["id"])
        if self.texts:
            table.move_cursor(row=min(max(row, 0), len(self.texts) - 1))
        else:
            table.add_row(Text("None yet: t lays words on the picture.", style=MUTED), "")

    def draw_now(self) -> None:
        """The caption, and the picture or the words."""
        f = self.edit_fields
        self.query_one("#ph-viewer-caption", Static).update(
            f"[{MUTED}]as it will be:[/] [b]{ph.size_said(f) or '?'}[/]"
        )
        words = self.query_one("#ph-viewer-words", Static)
        if self.photo.pictures and TerminalImage is not None:
            words.display = False
            self.want_picture()
        else:
            words.display = True
            words.update(viewer_words(f, self.texts))

    # -- the picture -------------------------------------------------------------------------
    def want_picture(self) -> None:
        """The edit as it would export: now, or as soon as the one on its way lands."""
        if self.edit is None or not self.photo.pictures:
            return
        if self._fetching:
            self._again = True
            return
        self._fetching = True
        self.fetch_picture()

    @work(group="photo-picture")
    async def fetch_picture(self) -> None:
        try:
            while self.edit is not None:
                self._again = False
                viewer = self.query_one("#ph-viewer")
                width = max(160, min(1280, (viewer.content_size.width or 60) * 10))
                try:
                    data = await self.photo.picture(self.edit["id"], width)
                except ApiError as exc:
                    words = self.query_one("#ph-viewer-words", Static)
                    words.update(f"[{MUTED}]no picture: {escape(str(exc))}[/]")
                    words.display = True
                    return
                self.show_picture(data)
                if not self._again:
                    return
        finally:
            self._fetching = False

    def show_picture(self, data: bytes) -> None:
        try:
            from PIL import Image as PILImage

            opened = PILImage.open(BytesIO(data))
            opened.load()
        except Exception as exc:  # not a picture after all
            words = self.query_one("#ph-viewer-words", Static)
            words.update(f"[{MUTED}]cannot draw the picture: {escape(str(exc))}[/]")
            words.display = True
            return
        self.query_one("#ph-picture").image = opened

    # -- moving about ----------------------------------------------------------------------------
    def action_cycle(self, step: int) -> None:
        """Tab: in the editor the texts are the one thing to be on; elsewhere, the next widget."""
        if not self.editing:
            self.app.action_focus_next() if step > 0 else self.app.action_focus_previous()
            return
        self.query_one("#ph-texts", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if event.data_table.id == "ph-edits":
            self.act_open()
        elif event.data_table.id == "ph-texts":
            text = self.text
            if text is not None:
                self.change_text(text)

    # -- the edits ----------------------------------------------------------------------------------
    def act_open(self) -> None:
        table = self.query_one("#ph-edits", DataTable)
        if not self.edits or not 0 <= table.cursor_row < len(self.edits):
            return
        self.open_edit(self.edits[table.cursor_row])

    def open_edit(self, edit: dict) -> None:
        self.edit = edit
        self.texts = []
        self._show("ph-editor")
        self.load_editor()
        self.call_after_refresh(lambda: self.query_one("#ph-texts", DataTable).focus())

    def act_back(self) -> None:
        self._poll.pause()
        keep = (self.edit or {}).get("id", "")
        self.edit = None
        self.load_edits(keep)

    def act_refresh(self) -> None:
        self.reload()

    def act_new_record(self) -> None:
        self.new_edit()

    @work(group="ui")
    async def new_edit(self) -> None:
        try:
            photos = await self.photo.material()
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        picked = await self.app.push_screen_wait(
            PickPhotoModal(photos, within=str(self.photo.media.get("within") or ""))
        )
        if not picked:
            return
        try:
            made = await self.photo.new_edit(picked)
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.status(f"{title_of(made, self.model)} is started.")
        self.open_edit(made)

    def act_delete_record(self) -> None:
        if not self.editing:
            table = self.query_one("#ph-edits", DataTable)
            if 0 <= table.cursor_row < len(self.edits):
                self.delete_edit(self.edits[table.cursor_row])
            return
        text = self.text
        if text is not None:
            self.remove_text(text)

    @work(group="ui")
    async def delete_edit(self, edit: dict) -> None:
        if await self.confirm_delete(edit):
            self.status(f"Deleted {title_of(edit, self.model)}.")
            self.load_edits()

    # -- editing ---------------------------------------------------------------------------------------
    async def edited(self, said: str) -> None:
        """After a write: everything read again and drawn, *said* in the log."""
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

    def _need_edit(self) -> dict | None:
        if self.edit is None:
            return None
        if not self.writes:
            self.status("You may only look at this.", error=True)
            return None
        return self.edit

    def act_turn_right(self) -> None:
        if (edit := self._need_edit()) is not None:
            self.turn(edit, 90)

    def act_turn_left(self) -> None:
        if (edit := self._need_edit()) is not None:
            self.turn(edit, -90)

    @work(group="ui")
    async def turn(self, edit: dict, by: int) -> None:
        if await self._try(self.photo.rotate(edit, by)):
            await self.edited(f"Turned {'right' if by > 0 else 'left'}: {ph.rotation_of(self.edit_fields)}°.")

    def act_mirror(self) -> None:
        if (edit := self._need_edit()) is not None:
            self.flip(edit)

    @work(group="ui")
    async def flip(self, edit: dict) -> None:
        if await self._try(self.photo.mirror(edit)):
            await self.edited("Mirrored." if ph.mirrored(self.edit_fields) else "As taken again.")

    # -- the crop ----------------------------------------------------------------------------------------
    def act_crop(self) -> None:
        if self._need_edit() is not None:
            self.crop()

    def act_reset_crop(self) -> None:
        if self._need_edit() is not None:
            self.set_crop(None)

    @work(group="ui")
    async def crop(self) -> None:
        asked = await self.app.push_screen_wait(
            PromptModal(
                "Crop",
                value=ph.box_said(ph.crop_of(self.edit_fields)),
                detail=f"[{MUTED}]The part kept: x y w h, in percent of the turned picture; `all` keeps everything.[/]",
            )
        )
        if not asked:
            return
        if asked.strip().lower() in ("all", "reset", "whole"):
            self.set_crop(None)
            return
        try:
            box = ph.box_from(asked)
        except ValueError as exc:
            self.status(str(exc), error=True)
            return
        self.set_crop(box)

    @work(group="ui")
    async def set_crop(self, box: dict | None) -> None:
        if await self._try(self.photo.crop(self.edit, box)):
            await self.edited("The whole picture." if box is None else f"Cropped to {ph.box_said(box)}.")

    # -- the size ---------------------------------------------------------------------------------------
    def act_size(self) -> None:
        if self._need_edit() is not None:
            self.ask_size()

    @work(group="ui")
    async def ask_size(self) -> None:
        f = self.edit_fields
        asked = await self.app.push_screen_wait(
            PromptModal(
                "Size",
                value=ph.size_said(f).replace(" × ", "x"),
                detail=f"[{MUTED}]Width x height, a width (the shape kept), a percent, or `as is`.[/]",
            )
        )
        if asked is None:
            return
        try:
            size = ph.size_from(asked, ph.cropped_size(f))
        except ValueError as exc:
            self.status(str(exc), error=True)
            return
        if await self._try(self.photo.resize(self.edit, size)):
            await self.edited(f"Comes out {ph.size_said(self.edit_fields) or 'as it is'}.")

    # -- texts -------------------------------------------------------------------------------------------
    def act_text(self) -> None:
        if self._need_edit() is None:
            return
        if not self.photo.text_model:
            self.status("This editor has no texts.", error=True)
            return
        self.add_text()

    @work(group="ui")
    async def add_text(self) -> None:
        words = await self.app.push_screen_wait(
            PromptModal("Words on the picture", detail=f"[{MUTED}]They start in the top left corner; k moves them.[/]")
        )
        if not words or not words.strip():
            return
        if await self._try(self.photo.add_text(self.edit, words.strip())):
            await self.edited(f"“{words.strip()}” is on the picture: k moves it, enter changes it.")
            table = self.query_one("#ph-texts", DataTable)
            table.move_cursor(row=table.row_count - 1)

    @work(group="ui")
    async def change_text(self, text: dict) -> None:
        """Enter on a text: its sheet, to change the words, the size and the colour."""
        result = await self.open_sheet(text, model_id=self.photo.text_model, only=["text", "size", "colour", "x", "y"])
        if result is not None:
            await self.edited("Changed." if result != "deleted" else "Taken off.")

    def act_move_text(self) -> None:
        if self._need_edit() is None:
            return
        text = self.text
        if text is None:
            self.status("No text to move: t lays words on the picture.", error=True)
            return
        self.move_text(text)

    @work(group="ui")
    async def move_text(self, text: dict) -> None:
        t = ph.text_of(text.get("fields") or {})
        asked = await self.app.push_screen_wait(
            PromptModal(
                "Where",
                value=f"{t['x']:g} {t['y']:g}",
                detail=f"[{MUTED}]x y: the top left corner, in percent of the picture; a third number is the size.[/]",
            )
        )
        if not asked:
            return
        parts = asked.replace(",", " ").split()
        try:
            numbers = [float(p) for p in parts]
            if len(numbers) not in (2, 3):
                raise ValueError
        except ValueError:
            self.status("Give two numbers, x y, or three with the size.", error=True)
            return
        fields = {"x": min(max(numbers[0], 0.0), 100.0), "y": min(max(numbers[1], 0.0), 100.0)}
        if len(numbers) == 3:
            fields["size"] = min(max(numbers[2], 0.5), 100.0)
        if await self._try(self.photo.set_text(text, fields)):
            await self.edited(f"Moved to {fields['x']:g} {fields['y']:g}.")

    @work(group="ui")
    async def remove_text(self, text: dict) -> None:
        if await self._try(self.photo.remove_text(text)):
            await self.edited("Taken off the picture.")

    # -- the export -------------------------------------------------------------------------------------
    def act_export(self) -> None:
        if self.photo.export is None:
            self.status("This editor has no export.", error=True)
            return
        self.export()

    @work(group="ui")
    async def export(self) -> None:
        ran = await run_action(self.app, self.quill, self.photo.export, record=self.edit)
        if ran:
            await self.edited("Exporting.")
            self._poll.resume()

    async def _poll_status(self) -> None:
        """While an export is queued or rendering, the header follows it."""
        if self.edit is None:
            self._poll.pause()
            return
        try:
            self.edit = await self.api.record(self.photo.edit_model, self.edit["id"])
        except ApiError:
            return
        self.draw_head()
        if self.edit_fields.get("status") not in ("queued", "rendering"):
            self._poll.pause()

    def act_open_output(self) -> None:
        output = self.edit_fields.get("output")
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


__all__ = ["PhotoPane", "PickPhotoModal", "viewer_words"]
