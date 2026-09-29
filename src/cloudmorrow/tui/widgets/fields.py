"""A field, drawn and read back: the one widget for each kind, and rows of them.

The record sheet, an action's form and a view's editable `field` all draw a
field the same way, so a kind looks and behaves the same wherever it is:

    string email phone url   a one-line input
    int decimal              a one-line input that only takes a number
    date datetime            a one-line input, checked before it is sent
    text json                a text area (json is checked before it is sent)
    markdown                 the notes' own live editor
    bool                     a tick box
    enum                     radio buttons, or a drop-down when there are many
    link                     a drop-down of the linked datamodel's records

`FieldRows` is the form around them: a row per field, its label and then
its widget, a star on the ones that must be filled in, and `value`, which
reads one back as the API wants it or says what is wrong with it.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import (
    Checkbox,
    Input,
    RadioButton,
    RadioSet,
    Select,
    Static,
    TextArea,
)

from cloudmorrow.tui.dates import as_local
from cloudmorrow.tui.kitdata import enum_options, field_label
from cloudmorrow.tui.widgets.kit import safe_id

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


def field_widget(
    field: dict, value: Any, wid: str, *, choices: list[tuple[str, str]] | None = None
):
    """The one widget that edits a field of *field*'s kind, holding *value*.

    The sheet's, and the same for an action's form (tui/quill_actions.py)
    and a view's editable `field`, so a kind is drawn one way everywhere.
    *choices* are a link field's (title, id) pairs.
    """
    from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

    kind = field.get("kind")
    if field.get("secret"):
        return Input(
            str(value) if value not in (None, "") else "",
            placeholder="hidden · ctrl+r shows it",
            password=True,
            id=wid,
            classes="sheet-secret",
            compact=True,
        )
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
        options = [(label, key) for label, key in choices or []]
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
        text = as_local(text)
    input_type = {"int": "integer", "decimal": "number"}.get(kind or "", "text")
    return Input(
        text,
        placeholder=PLACEHOLDERS.get(kind or "", ""),
        type=input_type,
        id=wid,
        compact=True,
    )


def read_field(widget: Any, field: dict) -> Any:
    """What *widget*, drawn by `field_widget` for *field*, holds now, as the API wants it.

    Raises ValueError with what is wrong, said the way a person would.
    """
    from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor

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
    if isinstance(widget, Input) and field.get("secret"):
        # Exactly as typed: a password's spaces are part of it.
        return widget.value
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
                if len(text) == 10:
                    # A date alone is a whole day, and stays one.
                    return dt.date.fromisoformat(text).isoformat()
                moment = dt.datetime.fromisoformat(text)
            except ValueError:
                raise ValueError(
                    f"{label} is a date and a time, like 2026-09-26 14:30."
                ) from None
            if moment.tzinfo is None:
                # Typed here with no zone: the time on the wall, as typed.
                return moment.isoformat(timespec="minutes")
            return moment.isoformat(timespec="seconds")
        if kind == "email" and "@" not in text:
            raise ValueError(f"{label} is an email address.")
        if kind == "url" and "://" not in text:
            raise ValueError(f"{label} is a web address, starting https://.")
        return text
    return None


class FormProblem(ValueError):
    """What is wrong with a form as filled in, and the widget it is wrong in."""

    def __init__(self, message: str, widget: Widget | None) -> None:
        super().__init__(message)
        self.widget = widget


class FieldRows(Vertical):
    """Fields, a row each: the label, then the widget the field's kind calls for.

    *widget_for* draws a field's widget, with the id `wid` gives it; without
    it, the field's default in its kind's widget. *asks* says whether a
    field is typed into here — only those get a star when they must be
    filled in, and a long body's room.
    """

    DEFAULT_CSS = """
    FieldRows {
        height: auto;
    }
    """

    def __init__(
        self,
        fields: list[dict],
        *,
        prefix: str = "field",
        widget_for: Callable[[dict], Widget] | None = None,
        asks: Callable[[dict], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.fields = list(fields)
        self.prefix = prefix
        self._widget_for = widget_for
        self._asks = asks

    def wid(self, field: dict) -> str:
        return f"{self.prefix}-{safe_id(field['name'])}"

    def asks(self, field: dict) -> bool:
        return self._asks(field) if self._asks is not None else True

    def widget(self, field: dict) -> Widget:
        """The widget for *field*, holding what it holds."""
        if self._widget_for is not None:
            return self._widget_for(field)
        return field_widget(field, field.get("default"), self.wid(field))

    def compose(self) -> ComposeResult:
        for field in self.fields:
            asked = self.asks(field)
            long = asked and field.get("kind") in LONG_KINDS and not field.get("secret")
            label = field_label(field) + (" *" if asked and field.get("required") else "")
            with Horizontal(classes="sheet-row" + (" -long" if long else "")):
                yield Static(label, classes="sheet-label")
                yield self.widget(field)

    def find(self, field: dict) -> Widget | None:
        try:
            return self.query_one(f"#{self.wid(field)}")
        except Exception:
            return None

    def first(self) -> Widget | None:
        """The first widget there is to type into."""
        for field in self.fields:
            widget = self.find(field)
            if widget is not None and widget.focusable:
                return widget
        return None

    def value(self, field: dict) -> Any:
        """What *field* holds now, as the API wants it; FormProblem when it is wrong or missing."""
        widget = self.find(field)
        try:
            value = read_field(widget, field)
        except ValueError as exc:
            raise FormProblem(str(exc), widget) from None
        if field.get("required") and value in (None, ""):
            raise FormProblem(f"{field_label(field)} is needed.", widget)
        return value
