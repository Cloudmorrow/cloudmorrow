"""The record sheet: any record of any datamodel, every field, editable.

Every kit screen gets this for free (docs/QUILLS.md, *Screens*): open a card
or a row and here are the record's fields, each with the widget its kind
calls for, a Save and a Delete. It is drawn from the datamodel alone, so a
Quill installed tomorrow with a kind of data nobody has seen yet opens here
exactly as a task does.

One widget per kind, and adding a kind means adding it here as well as on
the web:

    string email phone url   a one-line input
    int decimal              a one-line input that only takes a number
    date datetime            a one-line input, checked before it is sent
    text json                a text area (json is checked before it is sent)
    markdown                 the notes' own live editor
    bool                     a tick box
    enum                     radio buttons, or a drop-down when there are many
    link                     a drop-down of the linked datamodel's records

A stamped field is the server's to set — a task's "Done" moment follows its
lane — so it is shown and never typed into.

The sheet talks to the server itself, the way the password dialog does, so a
conflict is said here with the sheet still open: a save carries the record's
`rev`, and when somebody else got there first (409) the sheet says so and
shows their version, rather than writing over it or closing on a red line in
the status bar. It dismisses with the saved record, the string "deleted", or
None when nothing changed.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TextArea,
)

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.theme import BAD, MUTED, WARN
from cloudmorrow.tui.widgets.kit import (
    enum_options,
    field_label,
    read_only,
    safe_id,
    title_of,
)

# Kinds that take more than a line, drawn below the short ones so the sheet
# reads as a form and then a body — the way a task was always drawn.
LONG_KINDS = ("markdown", "text", "json")
# More options than this and radio buttons stop fitting on one line.
MAX_RADIOS = 5
# Placeholders that say the format, since the box itself cannot.
PLACEHOLDERS = {
    "date": "YYYY-MM-DD",
    "datetime": "YYYY-MM-DD HH:MM",
    "email": "name@example.org",
    "url": "https://",
    "int": "a whole number",
    "decimal": "a number",
}


async def link_choices(client: Any, models: dict, model: dict) -> dict[str, list[tuple[str, str]]]:
    """For every link field of *model*: the records it may point at, titled.

    Fetched before the sheet opens rather than by it, so the sheet has its
    drop-downs filled the moment it is on screen and never shows a link as
    empty while it waits.
    """
    choices: dict[str, list[tuple[str, str]]] = {}
    for field in model.get("fields", []):
        if field.get("kind") != "link" or not field.get("to"):
            continue
        target = models.get(field["to"]) or {}
        try:
            rows = await client.records(field["to"])
        except ApiError:
            rows = []
        choices[field["name"]] = [(title_of(row, target), str(row["id"])) for row in rows]
    return choices


def _as_local(value: str) -> str:
    """A stored ISO moment as the minute it is here."""
    try:
        moment = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return str(value or "")
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def shown(field: dict, value: Any) -> str:
    """A value as the sheet writes it where it cannot be edited."""
    if value in (None, ""):
        return "—"
    kind = field.get("kind")
    if kind == "datetime":
        return _as_local(str(value))
    if kind == "enum":
        return dict(enum_options(field)).get(str(value), str(value))
    if kind == "bool":
        return "yes" if value else "no"
    if kind == "json":
        return json.dumps(value)
    return str(value)


class RecordSheet(Modal[dict | str | None]):
    """Every field of one record, with Save, Delete and Cancel."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self,
        client: Any,
        models: dict,
        model_id: str,
        *,
        record: dict | None = None,
        preset: dict | None = None,
        only: list[str] | None = None,
        choices: dict[str, list[tuple[str, str]]] | None = None,
        heading: str = "",
    ) -> None:
        super().__init__()
        self.client = client
        self.models = models
        self.model = models[model_id]
        self.model_id = model_id
        self.record = record
        # What a new record starts with: the board it is on, the lane.
        self.preset = dict(preset or {})
        self.choices = choices or {}
        label = self.model.get("label") or model_id
        self.heading = heading or (label if record else f"New {label.lower()}")
        self.fields = self._ordered(only)

    # -- which fields, in which order ------------------------------------------
    def _ordered(self, only: list[str] | None) -> list[dict]:
        """The title first, the short fields, then the long ones.

        A detail screen may name its `fields`; a record sheet shows those,
        in that order, and a board or list shows them all.
        """
        fields = list(self.model.get("fields", []))
        if only:
            by_name = {f["name"]: f for f in fields}
            return [by_name[name] for name in only if name in by_name]
        title = self.model.get("title")
        first = [f for f in fields if f["name"] == title]
        rest = [f for f in fields if f["name"] != title]
        short = [f for f in rest if f.get("kind") not in LONG_KINDS]
        long = [f for f in rest if f.get("kind") in LONG_KINDS]
        return first + short + long

    def _value(self, field: dict) -> Any:
        name = field["name"]
        if self.record is not None:
            return (self.record.get("fields") or {}).get(name)
        if name in self.preset:
            return self.preset[name]
        return field.get("default")

    # -- layout ----------------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="record-sheet"):
            yield Label(self.heading, classes="modal-title", id="sheet-heading")
            with VerticalScroll(id="sheet-fields"):
                for field in self.fields:
                    long = field.get("kind") in LONG_KINDS and not read_only(field)
                    with Horizontal(classes="sheet-row" + (" -long" if long else "")):
                        label = field_label(field)
                        if field.get("required") and not read_only(field):
                            label += " *"
                        yield Static(label, classes="sheet-label")
                        yield self._widget(field)
            yield Static("", id="sheet-complaint", classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                if self.record is not None:
                    yield Button("Delete", variant="error", id="sheet-delete")
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def _widget(self, field: dict):
        """The one widget for this field's kind, holding its value."""
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        name = field["name"]
        wid = f"field-{safe_id(name)}"
        value = self._value(field)
        kind = field.get("kind")
        if read_only(field):
            note = shown(field, value)
            return Static(f"{note}  [{MUTED}]set by the server[/]", id=wid, classes="sheet-fixed")
        if kind == "markdown":
            return LiveMarkdownEditor(str(value or ""), id=wid, classes="sheet-markdown")
        if kind in ("text", "json"):
            if kind == "json" and value is not None:
                text = json.dumps(value, indent=2)
            else:
                text = str(value or "")
            return TextArea(text, id=wid, classes="sheet-text", soft_wrap=True, compact=True)
        if kind == "bool":
            return Checkbox("", value=bool(value), id=wid, compact=True)
        if kind == "enum":
            options = enum_options(field)
            if len(options) <= MAX_RADIOS:
                current = str(value) if value is not None else ""
                return RadioSet(
                    *(
                        RadioButton(label, value=option == current, id=f"{wid}--{safe_id(option)}")
                        for option, label in options
                    ),
                    id=wid,
                    classes="sheet-radios",
                    compact=True,
                )
            return Select(
                [(label, option) for option, label in options],
                value=str(value) if value is not None else Select.NULL,
                allow_blank=not field.get("required"),
                id=wid,
                compact=True,
            )
        if kind == "link":
            options = [(label, key) for label, key in self.choices.get(name, [])]
            current = str(value) if value not in (None, "") else None
            if current is not None and current not in {key for _, key in options}:
                # Pointing at something this account cannot list: keep it,
                # rather than quietly moving the record elsewhere on save.
                options.append((current, current))
            return Select(
                options,
                value=current if current is not None else Select.NULL,
                allow_blank=not field.get("required") or current is None,
                prompt="—",
                id=wid,
                compact=True,
            )
        text = str(value) if value not in (None, "") else ""
        if kind == "datetime" and text:
            text = _as_local(text)
        input_type = {"int": "integer", "decimal": "number"}.get(kind or "", "text")
        return Input(
            text,
            placeholder=PLACEHOLDERS.get(kind or "", ""),
            type=input_type,
            id=wid,
            compact=True,
        )

    def on_mount(self) -> None:
        # Where you start is where you would start typing: the title.
        for field in self.fields:
            if read_only(field):
                continue
            widget = self._field_widget(field)
            if widget is not None and widget.focusable:
                widget.focus()
                if isinstance(widget, Input):
                    widget.cursor_position = len(widget.value)
                break

    def _field_widget(self, field: dict):
        try:
            return self.query_one(f"#field-{safe_id(field['name'])}")
        except Exception:
            return None

    # -- reading it back -------------------------------------------------------
    def _read(self, field: dict) -> Any:
        """What the widget for *field* holds now, as the API wants it.

        Raises ValueError with what is wrong, said the way a person would.
        """
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        widget = self._field_widget(field)
        kind = field.get("kind")
        label = field_label(field)
        if isinstance(widget, LiveMarkdownEditor):
            return widget.text
        if isinstance(widget, TextArea):
            text = widget.text
            if kind == "json":
                if not text.strip():
                    return None
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{label} is not valid JSON: {exc.msg}.") from None
            return text
        if isinstance(widget, Checkbox):
            return widget.value
        if isinstance(widget, RadioSet):
            pressed = widget.pressed_button
            if pressed is None or not pressed.id:
                return None
            index = widget.pressed_index
            options = enum_options(field)
            return options[index][0] if 0 <= index < len(options) else None
        if isinstance(widget, Select):
            return None if widget.is_blank() else widget.value
        if isinstance(widget, Input):
            text = widget.value.strip()
            if not text:
                return "" if kind in ("string", "email", "phone", "url") else None
            if kind == "int":
                try:
                    return int(text)
                except ValueError:
                    raise ValueError(f"{label} is a whole number.") from None
            if kind == "decimal":
                try:
                    float(text)
                except ValueError:
                    raise ValueError(f"{label} is a number.") from None
                return text
            if kind == "date":
                try:
                    return dt.date.fromisoformat(text).isoformat()
                except ValueError:
                    raise ValueError(f"{label} is a date, like 2026-09-26.") from None
            if kind == "datetime":
                try:
                    moment = dt.datetime.fromisoformat(text)
                except ValueError:
                    raise ValueError(
                        f"{label} is a date and a time, like 2026-09-26 14:30."
                    ) from None
                if moment.tzinfo is None:
                    # Typed here, so it is a time here.
                    moment = moment.astimezone()
                return moment.isoformat(timespec="seconds")
            if kind == "email" and "@" not in text:
                raise ValueError(f"{label} is an email address.")
            if kind == "url" and "://" not in text:
                raise ValueError(f"{label} is a web address, starting https://.")
            return text
        return None

    def _collect(self) -> dict | None:
        """The fields to send: every one on a new record, the changed on an old one."""
        before = (self.record or {}).get("fields") or {}
        collected: dict[str, Any] = {}
        for field in self.fields:
            if read_only(field):
                continue
            try:
                value = self._read(field)
            except ValueError as exc:
                self._say(str(exc))
                self._focus(field)
                return None
            if field.get("required") and value in (None, ""):
                self._say(f"{field_label(field)} is needed.")
                self._focus(field)
                return None
            name = field["name"]
            if self.record is not None and _same(field, before.get(name), value):
                continue
            if self.record is None and value in (None, "") and name not in self.preset:
                # Left empty on a new record: the datamodel's default decides.
                continue
            collected[name] = value
        if self.record is None:
            # What the pane decided for a new record (its board) stands even
            # when the sheet does not show that field.
            for name, value in self.preset.items():
                collected.setdefault(name, value)
        return collected

    def _focus(self, field: dict) -> None:
        widget = self._field_widget(field)
        if widget is not None and widget.focusable:
            widget.focus()

    def _say(self, message: str, *, colour: str = BAD) -> None:
        text = f"[{colour}]{message}[/]" if message else ""
        self.query_one("#sheet-complaint", Static).update(text)

    # -- saving ----------------------------------------------------------------
    async def action_save(self) -> None:
        fields = self._collect()
        if fields is None:
            return
        self._say("")
        if self.record is not None and not fields:
            # Nothing changed; closing is the whole of saving it.
            self.dismiss(None)
            return
        try:
            if self.record is None:
                saved = await self.client.create_record(self.model_id, fields)
            else:
                saved = await self.client.update_record(
                    self.model_id, self.record["id"], fields, rev=self.record.get("rev")
                )
        except ApiError as exc:
            if exc.status_code == 409 and self.record is not None:
                await self._reload_theirs()
                return
            self._say(str(exc))
            return
        self.dismiss(saved)

    async def _reload_theirs(self) -> None:
        """Somebody saved this record while it was open here: show theirs."""
        try:
            fresh = await self.client.record(self.model_id, self.record["id"])
        except ApiError as exc:
            self._say(f"It changed elsewhere, and could not be read again: {exc}")
            return
        self.record = fresh
        for field in self.fields:
            old = self._field_widget(field)
            if old is None:
                continue
            # The widget is the last thing in its row, after the label; the
            # old one goes first, since the new one has the same id.
            row = old.parent
            await old.remove()
            await row.mount(self._widget(field))
        self._say(
            "This changed somewhere else while it was open. Theirs is shown now — "
            "make your change again and save.",
            colour=WARN,
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            await self.action_save()
        elif event.button.id == "sheet-delete":
            self.ask_delete()
        else:
            self.dismiss(None)

    def ask_delete(self) -> None:
        if self.record is None:
            return
        name = title_of(self.record, self.model)
        cascades = [
            model.get("label") or model_id
            for model_id, model in self.models.items()
            for f in model.get("fields", [])
            if f.get("kind") == "link" and f.get("to") == self.model_id
            and f.get("on_delete") == "cascade"
        ]
        detail = "[dim]It is not recoverable.[/]"
        if cascades:
            detail = (
                f"[dim]Every {' and '.join(c.lower() for c in cascades)} on it goes too. "
                "It is not recoverable.[/]"
            )
        self.app.push_screen(ConfirmModal(f"Delete {name}?", detail=detail), self._delete_answered)

    async def _delete_answered(self, confirmed: bool | None) -> None:
        if not confirmed or self.record is None:
            return
        try:
            await self.client.delete_record(self.model_id, self.record["id"])
        except ApiError as exc:
            self._say(str(exc))
            return
        self.dismiss("deleted")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter moves to the next field rather than saving half a record."""
        event.stop()
        self.focus_next()

    def on_live_markdown_editor_save_requested(self, event) -> None:
        """ctrl+s inside the markdown saves the record.

        The editor swallows the key and asks for a save instead of letting it
        through, so without this the shortcut works everywhere but the body —
        which is where you are when you have finished typing.
        """
        event.stop()
        self.run_worker(self.action_save(), group="sheet-save")

    def action_cancel(self) -> None:
        self.dismiss(None)

    # The arrows move between fields, as in every dialog here — except in
    # the ones that use them themselves.
    def action_focus_next(self) -> None:
        if self._arrows_are_the_widgets():
            return
        super().action_focus_next()

    def action_focus_previous(self) -> None:
        if self._arrows_are_the_widgets():
            return
        super().action_focus_previous()

    def _arrows_are_the_widgets(self) -> bool:
        from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

        return isinstance(self.focused, LiveMarkdownEditor | TextArea)


def _same(field: dict, before: Any, after: Any) -> bool:
    """Whether a field reads back as what it was, so it is not sent again."""
    if before in (None, "") and after in (None, ""):
        return True
    kind = field.get("kind")
    if kind == "datetime" and before and after:
        try:
            return dt.datetime.fromisoformat(str(before)) == dt.datetime.fromisoformat(str(after))
        except ValueError:
            return False
    if kind == "decimal" and before is not None and after is not None:
        try:
            return float(before) == float(after)
        except (TypeError, ValueError):
            return False
    return before == after
