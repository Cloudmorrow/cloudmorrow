"""A view's tree as widgets: one for every primitive, and the `Drawer` that makes them.

panes/kit_view.py asks the server for a view (docs/QUILLCODE.md, *Views and
primitives*) and hands the tree here; `Drawer` turns each node into its
widget, one method each (`RENDERERS`), with an id from where the node is in
the tree so a redraw finds its place again. The vocabulary, its tones and
gaps, and what each node holds are cloudmorrow.quill.ui's, the SDK's own, so
the terminal draws exactly what a view may say.

Nothing here talks to the server. What a node wants done — an action run, a
record opened, a field saved, a card moved, a month turned — it says as a
message, and the pane does it.
"""

from __future__ import annotations

import datetime as dt
from io import BytesIO
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Input,
    Markdown,
    RadioSet,
    Rule,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from cloudmorrow.quill.text import value_text
from cloudmorrow.quill.ui import GAPS, TONES, children
from cloudmorrow.tui.dates import month_start, shift_month, span, weeks_of
from cloudmorrow.tui.kitdata import (
    can_write,
    enum_options,
    field_label,
    field_of,
    find_action,
    read_only,
    shown,
)
from cloudmorrow.tui.quill_actions import ActionFields
from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import ACCENT, BAD, MUTED, TEXT, variant_for
from cloudmorrow.tui.widgets.fields import FormProblem, field_widget, read_field
from cloudmorrow.tui.widgets.kit import (
    Lane,
    RecordCard,
    lane_under,
    neighbour_lane,
    safe_id,
    settle_widths,
)

if TYPE_CHECKING:
    from cloudmorrow.tui.panes.kit_view import ViewPane

# Every primitive, and the method of `Drawer` that draws it. A primitive
# the SDK grows is drawn here too, or the test that walks this says so.
RENDERERS: dict[str, str] = {
    "stack": "draw_stack",
    "row": "draw_row",
    "columns": "draw_columns",
    "tabs": "draw_tabs",
    "text": "draw_text",
    "markdown": "draw_markdown",
    "image": "draw_image",
    "badge": "draw_badge",
    "stat": "draw_stat",
    "empty": "draw_empty",
    "divider": "draw_divider",
    "field": "draw_field",
    "form": "draw_form",
    "button": "draw_button",
    "menu": "draw_menu",
    "table": "draw_table",
    "cards": "draw_cards",
    "lanes": "draw_lanes",
    "month": "draw_month",
}


def _text(value: object) -> Text:
    """Whatever a Quill says is text, never markup."""
    return Text(str(value if value is not None else ""))


def _tone(value: object) -> str:
    return str(value) if value in TONES else "neutral"


def _cell(model: dict | None, name: str, fields: dict) -> str:
    """A field of a record as a table cell or a card line says it.

    By its datamodel's field, as the record sheet says it; a name the
    datamodel does not have, as the plain-text view does.
    """
    field = field_of(model or {}, name)
    if field:
        return shown(field, fields.get(name))
    return value_text({"fields": fields}, name) or "—"


# -- what the pieces tell the pane ------------------------------------------------------------
class ViewAct(Message):
    """Something pressed: a button's node — an action, a record to open, a screen."""

    def __init__(self, node: dict) -> None:
        self.node = node
        super().__init__()


class ViewOpen(Message):
    """A record to open in its sheet: a row, a card."""

    def __init__(self, record: dict) -> None:
        self.record = record
        super().__init__()


# -- the pieces --------------------------------------------------------------------------------
class ViewButton(Button):
    """A `button` (or an `empty`'s): runs an action, opens a record, or goes to a screen."""

    def __init__(self, node: dict, **kwargs: Any) -> None:
        super().__init__(
            str(node.get("label") or ""),
            variant=variant_for(node.get("tone")),
            compact=True,
            **kwargs,
        )
        self.node = node
        self.add_class("view-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(ViewAct(self.node))


class MenuModal(Modal[int | None]):
    """A `menu`'s buttons, one under another: the one pressed, by its place."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, label: str, items: list[dict]) -> None:
        super().__init__()
        self.label = label
        self.items = items

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal", id="view-menu"):
            yield Static(_text(self.label), classes="modal-title")
            for index, item in enumerate(self.items):
                yield Button(
                    _text(item.get("label") or ""),
                    variant=variant_for(item.get("tone")),
                    id=f"menu-item-{index}",
                    compact=True,
                    classes="view-menu-item",
                )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.focus_next()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id.startswith("menu-item-"):
            self.dismiss(int(button_id[len("menu-item-") :]))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ViewMenu(Button):
    """A `menu`: a button that opens its items."""

    def __init__(self, node: dict, **kwargs: Any) -> None:
        super().__init__(f"{node.get('label') or ''} ▾", compact=True, **kwargs)
        self.node = node
        self.add_class("view-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        items = [item for item in self.node.get("items") or [] if item.get("ui") == "button"]
        self.app.push_screen(
            MenuModal(str(self.node.get("label") or ""), items), lambda index: self._chosen(items, index)
        )

    def _chosen(self, items: list[dict], index: int | None) -> None:
        if index is not None and 0 <= index < len(items):
            self.post_message(ViewAct(items[index]))


class ViewTabs(Vertical):
    """`tabs`: a tab each, and the one you were on stays on after a redraw."""

    def __init__(self, tabs: list[tuple[str, Widget]], *, initial: str = "", **kwargs: Any):
        super().__init__(**kwargs)
        self.tabs = tabs
        self.initial = initial
        self.add_class("view-tabs")

    def compose(self) -> ComposeResult:
        ids = [f"{self.id}-tab-{index}" for index in range(len(self.tabs))]
        initial = self.initial if self.initial in ids else (ids[0] if ids else "")
        with TabbedContent(initial=initial):
            for tab_id, (label, child) in zip(ids, self.tabs, strict=True):
                with TabPane(label, id=tab_id):
                    yield child


class ViewImage(Vertical):
    """`image`: a record's picture, drawn as the note editor draws one; an address, said."""

    def __init__(self, node: dict, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node = node
        self.add_class("view-image")

    def compose(self) -> ComposeResult:
        alt = str(self.node.get("alt") or "")
        if self.node.get("src"):
            said = Text(alt or "A picture", style=f"bold {TEXT}")
            said.append(f"\n{self.node['src']}", style=MUTED)
            yield Static(said, classes="view-image-caption")
        else:
            yield Static(Text(alt, style=MUTED), classes="view-image-caption")

    def on_mount(self) -> None:
        if self.node.get("model") and self.node.get("id"):
            self.fetch()

    @work(exclusive=True)
    async def fetch(self) -> None:
        from cloudmorrow.tui.widgets.picture import TerminalImage

        api = getattr(self.app, "client", None)
        if api is None or TerminalImage is None:
            return
        try:
            data = await api.record_content(str(self.node["model"]), str(self.node["id"]))
            from PIL import Image as PILImage

            opened = PILImage.open(BytesIO(data))
            opened.load()
        except Exception:  # not there, not theirs, or not a picture: the alt text stays
            return
        await self.mount(TerminalImage(opened, classes="view-picture"))


class FieldNode(Horizontal):
    """`field`: its label, and its value — or its kind's widget, saved as you leave it."""

    class Save(Message):
        def __init__(self, node: FieldNode, value: Any) -> None:
            self.node = node
            self.value = value
            super().__init__()

    def __init__(self, node: dict, model: dict | None, choices: list | None, **kwargs: Any):
        super().__init__(**kwargs)
        self.node = node
        self.record: dict = node["record"]
        self.name_ = str(node["name"])
        self.field = field_of(model or {}, self.name_) or {"name": self.name_, "kind": "string"}
        self.choices = choices
        self.editable = bool(node.get("edit")) and can_write(model) and not read_only(self.field)
        self.saved = (self.record.get("fields") or {}).get(self.name_)
        self.add_class("view-field")

    @property
    def wid(self) -> str:
        return f"{self.id}-input"

    def compose(self) -> ComposeResult:
        label = self.node.get("label") or field_label(self.field)
        yield Static(_text(label), classes="sheet-label")
        if self.editable:
            yield field_widget(self.field, self.saved, self.wid, choices=self.choices)
        else:
            yield Static(_text(shown(self.field, self.saved)), classes="view-field-value")

    def _widget(self) -> Widget | None:
        try:
            return self.query_one(f"#{self.wid}")
        except Exception:
            return None

    def _changed(self) -> None:
        if not self.editable:
            return
        try:
            value = read_field(self._widget(), self.field)
        except ValueError as exc:
            self.app.say(str(exc), error=True)
            return
        if value == self.saved or (value in (None, "") and self.saved in (None, "")):
            return
        self.post_message(self.Save(self, value))

    # Typed things save when you leave them; chosen things at once.
    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._changed()

    def on_descendant_blur(self, _event: events.DescendantBlur) -> None:
        self._changed()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        self._changed()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        event.stop()
        self._changed()

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        self._changed()


class FormNode(Vertical):
    """`form`: an action's fields in place, filled with its values, and its button."""

    class Submitted(Message):
        def __init__(self, form: FormNode) -> None:
            self.form = form
            super().__init__()

    def __init__(self, node: dict, action: dict, choices: dict, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node = node
        self.action = action
        self.choices = choices
        self.add_class("view-form")

    def compose(self) -> ComposeResult:
        yield ActionFields(
            self.action.get("fields") or [],
            values=self.node.get("values") or {},
            choices=self.choices,
            prefix=f"{self.id}-f",
        )
        yield Static("", classes="view-form-complaint")
        with Horizontal(classes="view-form-buttons"):
            yield Button(
                str(self.node.get("submit") or self.action.get("label") or "Run"),
                variant=variant_for(self.action.get("tone") or "primary"),
                compact=True,
                id=f"{self.id}-submit",
                classes="view-button",
            )

    def collect(self) -> dict | None:
        try:
            values = self.query_one(ActionFields).collect()
        except FormProblem as problem:
            self.say(str(problem))
            if problem.widget is not None and problem.widget.focusable:
                problem.widget.focus()
            return None
        self.say("")
        return {**(self.node.get("values") or {}), **values}

    def say(self, message: str) -> None:
        self.query_one(".view-form-complaint", Static).update(Text(message, style=BAD) if message else "")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.Submitted(self))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.screen.focus_next()


class TableNode(Vertical):
    """`table`: a row per record, and the row's actions under it."""

    def __init__(self, node: dict, models: dict, actions: list[dict], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node = node
        self.records: list[dict] = list(node.get("records") or [])
        self.models = models
        self.actions = actions
        self.cursor = 0
        self.add_class("view-table")

    @property
    def table(self) -> DataTable:
        return self.query_one(DataTable)

    def compose(self) -> ComposeResult:
        if not self.records:
            yield Static(_text(self.node.get("empty") or "Nothing here."), classes="view-muted")
            return
        yield DataTable(id=f"{self.id}-rows", cursor_type="row", zebra_stripes=True)
        if self.actions:
            with Horizontal(classes="view-row-actions"):
                for action in self.actions:
                    button = Button(
                        str(action.get("label") or action["id"]),
                        variant=variant_for(action.get("tone")),
                        compact=True,
                        id=f"{self.id}-act-{safe_id(action['id'])}",
                        classes="view-button",
                    )
                    button.tooltip = "On the row you are on"
                    yield button

    def on_mount(self) -> None:
        if not self.records:
            return
        table = self.table
        columns = self.node.get("columns") or []
        first = self.models.get(self.records[0].get("model", "")) or {}
        for column in columns:
            label = column.get("label")
            if not label:
                field = field_of(first, column["field"])
                label = field_label(field) if field else column["field"]
            table.add_column(str(label).upper())
        for record in self.records:
            model = self.models.get(record.get("model", ""))
            fields = record.get("fields") or {}
            table.add_row(*(_text(_cell(model, c["field"], fields)) for c in columns))
        table.move_cursor(row=min(self.cursor, len(self.records) - 1))
        table.call_after_refresh(settle_widths, table)

    @property
    def selected(self) -> dict | None:
        if not self.records:
            return None
        row = self.table.cursor_row
        return self.records[row] if 0 <= row < len(self.records) else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        record = self.selected
        if record is not None and self.node.get("open", True):
            self.post_message(ViewOpen(record))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        record = self.selected
        prefix = f"{self.id}-act-"
        button_id = event.button.id or ""
        action = next((a for a in self.actions if button_id == f"{prefix}{safe_id(a['id'])}"), None)
        if record is not None and action is not None:
            self.post_message(ViewAct({"ui": "button", "action": action["id"], "record": record}))


class ViewCard(Static, can_focus=True):
    """One of `cards`: its title, subtitle, body and badge. Enter or a click opens it."""

    BINDINGS = [("enter", "open", "Open")]

    def __init__(self, record: dict, node: dict, model: dict | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.record = record
        self.node = node
        self.model = model
        self.add_class("view-card")
        self.update(self.render_card())

    def render_card(self) -> Text:
        fields = self.record.get("fields") or {}
        text = Text()
        title = fields.get(self.node["title"])
        text.append(str(title) if title not in (None, "") else "(untitled)", style=f"bold {TEXT}")
        if self.node.get("badge"):
            badge = fields.get(self.node["badge"])
            if badge not in (None, ""):
                text.append(f"  {_cell(self.model, self.node['badge'], fields)}", style=ACCENT)
        for key, style in (("subtitle", MUTED), ("body", TEXT)):
            name = self.node.get(key)
            if name and fields.get(name) not in (None, ""):
                text.append(f"\n{_cell(self.model, name, fields)}", style=style)
        return text

    def on_click(self) -> None:
        self.action_open()

    def action_open(self) -> None:
        if self.node.get("open", True):
            self.post_message(ViewOpen(self.record))


class LanesNode(Horizontal):
    """`lanes`: the board's lanes and cards, moved through the record API."""

    class Moved(Message):
        def __init__(self, record: dict, field: str, lane: str, index: int | None) -> None:
            self.record = record
            self.field = field
            self.lane = lane
            self.index = index
            super().__init__()

    def __init__(self, node: dict, model_id: str, model: dict | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node = node
        self.records: list[dict] = list(node.get("records") or [])
        self.model_id = model_id
        self.field = str(node["field"])
        if node.get("lanes"):
            self.lanes = [(str(lane["value"]), str(lane["label"])) for lane in node["lanes"]]
        else:
            self.lanes = enum_options(field_of(model or {}, self.field) or {})
        self.values = [value for value, _ in self.lanes]
        self.movable = can_write(model)
        self.add_class("view-lanes")

    def compose(self) -> ComposeResult:
        if not self.lanes:
            yield Static(Text(f"No lanes: {self.field} has no values.", style=MUTED))
            return
        for value, label in self.lanes:
            yield Lane(value, label, id=f"lane-{safe_id(value)}", classes="lane")

    async def on_mount(self) -> None:
        for value in self.values:
            await self.query_one(f"#lane-{safe_id(value)}", Lane).show(
                [r for r in self.records if self._lane_of(r) == value],
                title=str(self.node["title"]),
                body=self.node.get("body"),
                movable=self.movable,
            )

    def _lane_of(self, record: dict) -> str:
        value = (record.get("fields") or {}).get(self.field)
        return value if value in self.values else (self.values or [""])[0]

    def on_record_card_opened(self, event: RecordCard.Opened) -> None:
        event.stop()
        self.post_message(ViewOpen(event.record))

    def on_record_card_shifted(self, event: RecordCard.Shifted) -> None:
        event.stop()
        current = self._lane_of(event.record)
        lane = neighbour_lane(self.values, current, event.delta)
        if self.movable and lane != current:
            self.post_message(self.Moved(event.record, self.field, lane, None))

    def on_record_card_ticked(self, event: RecordCard.Ticked) -> None:
        event.stop()  # a view's lanes have no done lane to tick into

    def on_record_card_dragging(self, event: RecordCard.Dragging) -> None:
        event.stop()
        target = lane_under(self.screen, event.x, event.y)
        for lane in self.query(Lane):
            lane.set_class(lane is target, "-drop-target")

    def on_record_card_dropped(self, event: RecordCard.Dropped) -> None:
        event.stop()
        for lane in self.query(Lane):
            lane.remove_class("-drop-target")
        target = lane_under(self.screen, event.x, event.y)
        if not self.movable or target is None or target not in self.query(Lane):
            return
        self.post_message(self.Moved(event.record, self.field, target.value, target.index_at(event.y)))


class MonthNode(Vertical):
    """`month`: a month of days with a dot for each record, and the month's list under it."""

    BINDINGS = [
        Binding("left_square_bracket", "month(-1)", "Month back"),
        Binding("right_square_bracket", "month(1)", "Month on"),
    ]

    class Turned(Message):
        def __init__(self, month: MonthNode) -> None:
            self.month = month
            super().__init__()

    def __init__(self, node: dict, models: dict, shown_month: dt.date, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node = node
        self.models = models
        self.shown = shown_month
        self.add_class("view-month")

    @staticmethod
    def first_shown(node: dict) -> dt.date:
        try:
            return dt.date.fromisoformat(f"{node.get('start')}-01")
        except ValueError:
            return month_start(dt.date.today())

    def _days(self, record: dict) -> list[dt.date]:
        fields = record.get("fields") or {}
        try:
            first = dt.date.fromisoformat(str(fields.get(self.node["date"]) or "")[:10])
        except ValueError:
            return []
        last = first
        if self.node.get("ends"):
            try:
                last = dt.date.fromisoformat(str(fields.get(self.node["ends"]))[:10])
            except ValueError:
                pass
        # Somebody else's code chose the end: a year of dots is plenty.
        return span(first, last, most=366)

    def in_month(self) -> list[tuple[dt.date, dict]]:
        """The records on a day of the month shown, by their first day in it."""
        out = []
        for record in self.node.get("records") or []:
            days = [d for d in self._days(record) if month_start(d) == self.shown]
            if days:
                out.append((days[0], record))
        return sorted(out, key=lambda pair: pair[0])

    def compose(self) -> ComposeResult:
        with Horizontal(classes="view-month-head"):
            yield Button("‹", id=f"{self.id}-back", compact=True, classes="view-button")
            yield Static("", classes="view-month-title")
            yield Button("›", id=f"{self.id}-on", compact=True, classes="view-button")
        yield DataTable(id=f"{self.id}-grid", cursor_type="none", show_cursor=False, classes="view-month-grid")
        yield DataTable(id=f"{self.id}-list", cursor_type="row", show_header=False, classes="view-month-list")

    def on_mount(self) -> None:
        grid = self.query_one(f"#{self.id}-grid", DataTable)
        for weekday in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            grid.add_column(weekday, width=6)
        self.query_one(f"#{self.id}-list", DataTable).add_column("record")
        self.draw()

    def draw(self) -> None:
        showing = self.in_month()
        on_day: dict[dt.date, int] = {}
        for record in self.node.get("records") or []:
            for day in self._days(record):
                on_day[day] = on_day.get(day, 0) + 1
        title = Text(self.shown.strftime("%B %Y"), style=f"bold {ACCENT}")
        title.append("   [ ] months", style=MUTED)
        self.query_one(".view-month-title", Static).update(title)
        grid = self.query_one(f"#{self.id}-grid", DataTable)
        grid.clear()
        today = dt.date.today()
        for week in weeks_of(self.shown):
            cells = []
            for day in week:
                cell = Text(
                    f"{day.day:>2}",
                    style=(f"bold {ACCENT}" if day == today else MUTED if day.month != self.shown.month else TEXT),
                )
                count = on_day.get(day, 0) if day.month == self.shown.month else 0
                if count:
                    cell.append(" " + "●" * min(count, 3), style=ACCENT)
                cells.append(cell)
            grid.add_row(*cells)
        listing = self.query_one(f"#{self.id}-list", DataTable)
        listing.clear()
        if not showing:
            listing.add_row(Text("Nothing this month.", style=MUTED))
            return
        for day, record in showing:
            model = self.models.get(record.get("model", ""))
            line = Text(day.strftime("%a %d  "), style=MUTED)
            line.append(_cell(model, self.node["title"], record.get("fields") or {}), style=TEXT)
            listing.add_row(line)

    def action_month(self, step: int) -> None:
        self.shown = month_start(shift_month(self.shown, step))
        self.draw()
        self.post_message(self.Turned(self))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_month(-1 if event.button.id == f"{self.id}-back" else 1)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        showing = self.in_month()
        row = event.cursor_row
        if 0 <= row < len(showing):
            self.post_message(ViewOpen(showing[row][1]))


# -- the tree, as widgets --------------------------------------------------------------------
class Drawer:
    """Turns a view's tree into widgets, for one pane. Each node's widget has an
    id from where it is in the tree, so a redraw can find its place again."""

    def __init__(self, pane: ViewPane) -> None:
        self.pane = pane

    @property
    def models(self) -> dict:
        return self.pane.all_models

    def draw(self, node: dict, path: str) -> Widget:
        kind = node.get("ui") if isinstance(node, dict) else None
        method = RENDERERS.get(str(kind))
        if method is None:
            return Static(Text(f"({kind!r} is not drawn in the terminal yet)", style=MUTED), id=path)
        return getattr(self, method)(node, path)

    def _children(self, node: dict, key: str, path: str) -> list[Widget]:
        return [self.draw(child, f"{path}-{i}") for i, child in enumerate(node.get(key) or [])]

    # layout
    def draw_stack(self, node: dict, path: str) -> Widget:
        gap = node.get("gap") if node.get("gap") in GAPS else "normal"
        return Vertical(*self._children(node, "children", path), id=path, classes=f"view-stack -gap-{gap}")

    def draw_row(self, node: dict, path: str) -> Widget:
        return Horizontal(*self._children(node, "children", path), id=path, classes="view-row")

    def draw_columns(self, node: dict, path: str) -> Widget:
        columns = [Vertical(child, classes="view-column") for child in self._children(node, "children", path)]
        return Horizontal(*columns, id=path, classes="view-columns")

    def draw_tabs(self, node: dict, path: str) -> Widget:
        tabs = [
            (str(tab.get("label") or ""), self.draw(tab.get("child") or {}, f"{path}-{i}"))
            for i, tab in enumerate(node.get("tabs") or [])
        ]
        return ViewTabs(tabs, initial=self.pane.kept.get(path, ""), id=path)

    # content
    def draw_text(self, node: dict, path: str) -> Widget:
        style = node.get("style") or "body"
        return Static(_text(node.get("text")), id=path, classes=f"view-text -{style}")

    def draw_markdown(self, node: dict, path: str) -> Widget:
        return Markdown(str(node.get("text") or ""), id=path, classes="view-markdown")

    def draw_image(self, node: dict, path: str) -> Widget:
        return ViewImage(node, id=path)

    def draw_badge(self, node: dict, path: str) -> Widget:
        return Static(_text(f" {node.get('text')} "), id=path, classes=f"view-badge -tone-{_tone(node.get('tone'))}")

    def draw_stat(self, node: dict, path: str) -> Widget:
        text = Text(str(node.get("label") or ""), style=MUTED)
        text.append(f"\n{node.get('value')}", style="bold")
        if node.get("hint"):
            text.append(f"\n{node['hint']}", style=MUTED)
        return Static(text, id=path, classes=f"view-stat -tone-{_tone(node.get('tone'))}")

    def draw_empty(self, node: dict, path: str) -> Widget:
        parts: list[Widget] = [Static(_text(node.get("text")), classes="view-muted")]
        if node.get("action"):
            action = find_action(self.pane.quill, str(node["action"])) or {}
            label = node.get("label") or action.get("label") or node["action"]
            parts.append(
                ViewButton(
                    {"ui": "button", "label": label, "action": node["action"], "tone": "primary"},
                    id=f"{path}-do",
                )
            )
        return Vertical(*parts, id=path, classes="view-empty")

    def draw_divider(self, node: dict, path: str) -> Widget:
        return Rule(id=path, classes="view-divider")

    # records and what can be done to them
    def draw_field(self, node: dict, path: str) -> Widget:
        model = self.models.get(node["record"].get("model", ""))
        return FieldNode(node, model, self.pane.choices.get(path), id=path)

    def draw_form(self, node: dict, path: str) -> Widget:
        action = find_action(self.pane.quill, str(node.get("action") or ""))
        if action is None:
            return Static(Text(f"No action {node.get('action')!r} here.", style=MUTED), id=path)
        return FormNode(node, action, self.pane.choices.get(path) or {}, id=path)

    def draw_button(self, node: dict, path: str) -> Widget:
        return ViewButton(node, id=path)

    def draw_menu(self, node: dict, path: str) -> Widget:
        return ViewMenu(node, id=path)

    def draw_table(self, node: dict, path: str) -> Widget:
        actions = [
            a for a in (find_action(self.pane.quill, str(i)) for i in node.get("actions") or []) if a is not None
        ]
        table = TableNode(node, self.models, actions, id=path)
        table.cursor = int(self.pane.kept.get(path) or 0)
        return table

    def draw_cards(self, node: dict, path: str) -> Widget:
        records = node.get("records") or []
        if not records:
            return Static(_text(node.get("empty") or "Nothing here."), id=path, classes="view-muted")
        return Vertical(
            *(
                ViewCard(
                    record, node, self.models.get(record.get("model", "")), id=f"{path}-card-{safe_id(record['id'])}"
                )
                for record in records
            ),
            id=path,
            classes="view-cards",
        )

    def draw_lanes(self, node: dict, path: str) -> Widget:
        records = node.get("records") or []
        model_id = node.get("model") or (records[0]["model"] if records else self.pane.model_id)
        return LanesNode(node, model_id, self.models.get(model_id), id=path)

    def draw_month(self, node: dict, path: str) -> Widget:
        shown_month = self.pane.kept.get(path) or MonthNode.first_shown(node)
        return MonthNode(node, self.models, shown_month, id=path)


def walk(node: dict, path: str = "v"):
    """Every (node, path) in a tree, the way `Drawer` names them."""
    if not isinstance(node, dict):
        return
    yield node, path
    for index, child in enumerate(children(node)):
        yield from walk(child, f"{path}-{index}")
