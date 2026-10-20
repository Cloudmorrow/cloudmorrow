"""The kit's `data` in the terminal: the datamodels down the left, the records of one beside them.

The Data tab (server/dataview.py) is what uses it: every datamodel this
person's circles give them, each marked read, composed by the server for
whoever asks. Laid out as the grouped list is (panes/kit_grouped.py): the
datamodels in a list you pick from on the left, and beside it the records
of the one you are on, as a table of its title and what it is sorted by.
Enter, or a click, opens a record in the sheet every record has, which
cannot save here: this pane looks, and writes nothing.

Nothing here knows what any datamodel is: a ledger and a book are rows in
the same list.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.kitdata import field_label, field_of, shown, title_of
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.group_list import GroupList
from cloudmorrow.tui.widgets.kit import settle_widths
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import plural

# How many columns beside the title: where a record is, and what it is sorted by.
COLUMNS = 3


def many(word: str) -> str:
    """A datamodel's label for all of its records: "Deals", "Activities", "Journal entries"."""
    if word.lower().endswith("s"):
        return word
    if word.lower().endswith("y") and word[-2:-1].lower() not in "aeiou":
        return f"{word[:-1]}ies"
    return f"{word}s"


def models_of(quill: dict, screen: dict) -> list[dict]:
    """The datamodels a data screen draws: the Quill's, or the ones the screen names."""
    models = quill.get("models") or {}
    ids = screen.get("models") or sorted(models)
    return [models[i] for i in ids if i in models]


def columns_of(model: dict) -> list[dict]:
    """The fields a row says beside its title: where it is, then what it is indexed by."""
    title = model.get("title")
    chosen: list[dict] = []
    in_space = field_of(model, model.get("in_space"))
    if in_space:
        chosen.append(in_space)
    for f in model.get("fields") or []:
        if len(chosen) >= COLUMNS:
            break
        if f["name"] == title or f in chosen or not f.get("indexed") or f.get("kind") == "json" or f.get("secret"):
            continue
        chosen.append(f)
    return chosen


class DataPane(KitPane):
    """`data`: the datamodels, the records of one, each opened in the sheet to look at."""

    BINDINGS = [
        ("r", "fire('refresh')", "Refresh"),
    ]
    # Nothing here writes: the sheet cannot save, and there is no new or delete.
    WRITING = frozenset({"new_record", "delete_record"})

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        self.choices = models_of(quill, screen)
        first = self.choices[0]["id"] if self.choices else ""
        super().__init__(quill, screen | {"model": first}, **kwargs)
        self.writes = False
        self.refused = set(self.WRITING)
        self.SUMMARY = str(quill.get("summary") or "to look at")
        self.ACTIONS = self.offer([Action("open_record", "Open", "enter"), Action("refresh", "Refresh", "r")])
        self.columns: list[dict] = columns_of(self.model) if self.choices else []

    def content(self) -> ComposeResult:
        with Horizontal(classes="kit-grouped"):
            yield GroupList(id="kit-group-list", classes="kit-group-list", new=False)
            with Vertical(classes="kit-group-side"):
                yield Static("", id="kit-group-name", classes="kit-group-name")
                with Vertical(classes="kit-group-rows"):
                    yield DataTable(id="kit-table", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="kit-group-empty", classes="kit-group-empty")

    def on_mount(self) -> None:
        self.query_one(GroupList).show([(m["id"], m["label"], 0) for m in self.choices], self.model_id or None)
        self._columns()

    def on_show(self) -> None:
        self.reload()
        focused = self.screen.focused
        if focused is None or self not in focused.ancestors:
            self.query_one("#kit-group-list").focus()

    # -- which datamodel ------------------------------------------------------
    def stand(self, model_id: str) -> None:
        """Look at another datamodel: its columns, then its records."""
        if model_id not in self.models:
            return
        self.model_id = model_id
        self.model = self.models[model_id]
        self.columns = columns_of(self.model)
        self.records = []
        self._columns()
        self.reload()

    def _columns(self) -> None:
        table = self.query_one("#kit-table", DataTable)
        table.clear(columns=True)
        title = field_of(self.model, self.model.get("title"))
        table.add_column(field_label(title).upper() if title else "")
        for f in self.columns:
            table.add_column(field_label(f).upper())
        table.add_column("UPDATED")
        self.query_one("#kit-group-name", Static).update(f"[b]{many(self.model.get('label') or self.model_id)}[/]")

    def on_group_list_chosen(self, event: GroupList.Chosen) -> None:
        event.stop()
        if event.value != self.model_id:
            self.stand(event.value)

    # -- loading -----------------------------------------------------------
    @work(exclusive=True, group="kit-list")
    async def reload(self) -> None:
        if self.api is None or not self.model_id:
            return
        self.forget_links()
        try:
            self.records = await self.api.records(self.model_id)
            await self.load_link_titles(list(self.columns))
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.loaded = True
        self.draw()

    def act_refresh(self) -> None:
        self.reload()

    def draw(self) -> None:
        table = self.query_one("#kit-table", DataTable)
        empty = self.query_one("#kit-group-empty", Static)
        table.clear()
        for record in self.records:
            table.add_row(*self._row(record), key=str(record["id"]))
        table.display = bool(self.records)
        empty.display = not self.records
        if self.records:
            table.move_cursor(row=0)
            table.call_after_refresh(settle_widths, table)
        else:
            empty.update(f"[{MUTED}]No {many(self.noun)} you may see.[/]")
        self.status("", note=True)

    def _row(self, record: dict) -> tuple[str, ...]:
        fields = record.get("fields") or {}
        cells = [f"[b]{title_of(record, self.model)}[/]"]
        for f in self.columns:
            cells.append(f"[{MUTED}]{self.say(f, fields.get(f['name']))}[/]")
        stamp = str(record.get("updated_at") or "")
        cells.append(f"[{MUTED}]{shown({'kind': 'datetime'}, stamp) if stamp else ''}[/]")
        return tuple(cells)

    def card_status(self) -> tuple[str, str] | None:
        if not self.choices:
            return "none", "nothing you may see"
        return "ok", plural(len(self.choices), "datamodel")

    def status_detail(self) -> str:
        if not self.loaded:
            return ""
        return f"[{MUTED}]{plural(len(self.records), self.noun)}[/]"

    # -- opening ------------------------------------------------------------------
    @property
    def selected(self) -> dict | None:
        table = self.query_one("#kit-table", DataTable)
        if not self.records or not 0 <= table.cursor_row < len(self.records):
            return None
        return self.records[table.cursor_row]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.act_open_record()

    def act_open_record(self) -> None:
        record = self.selected
        if record is not None:
            self.look_at(record)

    @work(group="ui")
    async def look_at(self, record: dict) -> None:
        # The sheet of a datamodel marked read cannot save: it is looked at.
        await self.open_sheet(record, model_id=self.model_id)
