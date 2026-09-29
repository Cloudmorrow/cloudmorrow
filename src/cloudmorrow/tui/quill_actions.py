"""A Quill's actions in the terminal: pressing one, its form, and what it asks for next.

An action is declared in the Quill's manifest and runs its code on the
server (docs/QUILLCODE.md, *Actions, on every surface*). The terminal draws
it in three places, and all three press it here:

- on the record sheet of every record of the datamodel it is `on`, whichever
  Quill declared it (screens/record_sheet.py);
- in a view, wherever a `button`, `form`, `empty` or `table` names it
  (panes/kit_view.py);
- and, for the actions that are not on a record, in the actions palette on
  ctrl+e, from anywhere in the workspace (`QuillCommands`).

Pressing one asks first when the manifest says `confirm`, then draws its
form — the fields the manifest declares, each with the widget its kind has
on the record sheet — unless it has none, or the button already said every
one of them. What comes back is a list of effects, and `apply_effects` is
the one place they are carried out, for every surface in here:

    toast     a line in the log along the bottom, as everything the app says is
    open      the record's sheet
    go        another screen of the Quill, with its parameters
    confirm   a question; on yes, the action `then`, with `args`, on the same record
    error     said under the form, which stays open; a notice when there is none
    redraw    nothing here: whoever pressed it draws again anyway

The server's own words are used wherever it refuses (`{kind, message}`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

from textual.app import ComposeResult
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.tui.kitdata import (
    SESSION_EXPIRED,
    all_models,
    failure,
    find_action,
    installed,
    link_choices,
    loose_actions,
    title_of,
)
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.screens.record_sheet import RecordSheet
from cloudmorrow.tui.theme import BAD, variant_for
from cloudmorrow.tui.widgets.fields import FieldRows, FormProblem, field_widget
from cloudmorrow.tui.words import escape


# -- talking to the server ------------------------------------------------------
async def fetch_view(api: Any, quill_id: str, screen_id: str, params: dict | None = None) -> dict:
    """A view's tree, drawn for whoever is signed in: `{"quill", "screen", "tree"}`."""
    clean = {k: str(v) for k, v in (params or {}).items() if v not in (None, "")}
    record = clean.pop("record", "")
    return await api.quill_view(quill_id, screen_id, record=record, **clean)


async def press(
    api: Any, quill_id: str, action_id: str, *, record: str = "", fields: dict | None = None
) -> list[dict]:
    """Run an action on the server, as whoever is signed in. Its effects.

    A refusal is the client's ApiError, in the Quill's own words.
    """
    return list(await api.quill_action(quill_id, action_id, record=record, fields=fields) or [])


# -- an action's form -------------------------------------------------------------
class ActionFields(FieldRows):
    """An action's fields, a row each, with the record sheet's widget for each kind."""

    def __init__(
        self,
        fields: list[dict],
        *,
        values: dict | None = None,
        choices: dict[str, list[tuple[str, str]]] | None = None,
        prefix: str = "action",
        **kwargs: Any,
    ) -> None:
        super().__init__(fields, prefix=prefix, **kwargs)
        self.values = dict(values or {})
        self.choices = choices or {}
        self.add_class("action-fields")

    def widget(self, field: dict) -> Widget:
        name = field["name"]
        value = self.values.get(name, field.get("default"))
        return field_widget(field, value, self.wid(field), choices=self.choices.get(name))

    def collect(self) -> dict:
        """The fields as the action wants them; FormProblem when one is wrong or missing."""
        out: dict = {}
        for field in self.fields:
            value = self.value(field)
            if value in (None, ""):
                continue  # left empty: the handler's default decides
            out[field["name"]] = value
        return out


class ActionModal(Modal[list | None]):
    """An action's form as a dialog: its fields, and a button that runs it.

    It presses the action itself, so an `error` it answers with is said here
    with the form still open and still filled in. It dismisses with the
    effects to carry out, or None when nothing ran.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Run"),
    ]

    def __init__(
        self,
        api: Any,
        quill: dict,
        action: dict,
        *,
        record: dict | None = None,
        values: dict | None = None,
        choices: dict[str, list[tuple[str, str]]] | None = None,
    ) -> None:
        super().__init__()
        self.api = api
        self.quill = quill
        self.action = action
        self.record = record
        self.values = dict(values or {})
        self.choices = choices or {}

    def compose(self) -> ComposeResult:
        heading = str(self.action.get("label") or self.action.get("id"))
        if self.record is not None:
            models = self.quill.get("models") or {}
            heading += f" · {title_of(self.record, models.get(self.record.get('model', '')))}"
        with Vertical(classes="modal modal-wide", id="action-form"):
            yield Label(heading, classes="modal-title")
            if self.action.get("description"):
                yield Static(str(self.action["description"]), classes="modal-detail", markup=False)
            with VerticalScroll(id="action-fields"):
                yield ActionFields(
                    self.action.get("fields") or [],
                    values=self.values,
                    choices=self.choices,
                    id="action-form-fields",
                )
            yield Static("", id="action-complaint", classes="modal-detail")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    str(self.action.get("label") or "Run"),
                    variant=variant_for(self.action.get("tone") or "primary"),
                    id="action-submit",
                )

    def on_mount(self) -> None:
        first = self.query_one(ActionFields).first()
        if first is not None:
            first.focus()

    def say(self, message: str) -> None:
        self.query_one("#action-complaint", Static).update(
            f"[{BAD}]{escape(message)}[/]" if message else ""
        )

    async def action_submit(self) -> None:
        try:
            fields = {**self.values, **self.query_one(ActionFields).collect()}
        except FormProblem as problem:
            self.say(str(problem))
            if problem.widget is not None and problem.widget.focusable:
                problem.widget.focus()
            return
        self.say("")
        try:
            effects = await press(
                self.api,
                str(self.quill["id"]),
                str(self.action["id"]),
                record=str((self.record or {}).get("id") or ""),
                fields=fields,
            )
        except AuthError:
            self.dismiss(None)
            await self.app.sign_out(message=SESSION_EXPIRED)
            return
        except ApiError as exc:
            self.say(str(exc))
            return
        said = failure(effects)
        if said is not None:
            self.say(said)
            return
        self.dismiss(effects)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "action-submit":
            await self.action_submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter moves to the next field, as on the record sheet."""
        event.stop()
        self.focus_next()

    def action_cancel(self) -> None:
        self.dismiss(None)


# -- pressing one, and what comes of it -------------------------------------------------
async def run_action(
    app: Any,
    quill: dict,
    action: dict,
    *,
    record: dict | None = None,
    values: dict | None = None,
    ask: bool = True,
    leave: Callable[[], None] | None = None,
) -> bool:
    """Press *action*, on *record* when it is on one: ask, fill in, run, carry out.

    *values* fill its form (a button's `args`); when they say every field it
    has, there is no form to fill. *leave* is called before the workspace
    goes to another screen, so a dialog this was pressed in gets out of the
    way. Called from a worker: it waits on the dialogs. True when it ran.
    """
    api = app.client
    values = dict(values or {})
    if ask and action.get("confirm"):
        yes = await app.push_screen_wait(
            ConfirmModal(str(action["confirm"]), confirm_label=str(action.get("label") or "Yes"))
        )
        if not yes:
            return False
    fields = action.get("fields") or []
    if any(field["name"] not in values for field in fields):
        choices = await link_choices(api, all_models(app, quill), {"fields": fields})
        effects = await app.push_screen_wait(
            ActionModal(api, quill, action, record=record, values=values, choices=choices)
        )
        if effects is None:
            return False
    else:
        try:
            effects = await press(
                api, str(quill["id"]), str(action["id"]),
                record=str((record or {}).get("id") or ""), fields=values,
            )
        except AuthError:
            await app.sign_out(message=SESSION_EXPIRED)
            return False
        except ApiError as exc:
            app.say(f"{action.get('label') or ''}: {exc}", error=True)
            return False
    await apply_effects(app, quill, effects, record=record, leave=leave)
    return True


async def apply_effects(
    app: Any,
    quill: dict,
    effects: list[dict],
    *,
    record: dict | None = None,
    leave: Callable[[], None] | None = None,
) -> None:
    """Carry out what an action (or a confirm's `then`) answered, in order."""
    for effect in effects:
        kind = effect.get("effect")
        if kind == "toast":
            app.say(str(effect.get("text") or ""))
        elif kind == "error":
            app.say(str(effect.get("text") or ""), error=True)
        elif kind == "open":
            model_id, record_id = str(effect.get("model") or ""), str(effect.get("id") or "")
            await open_record(app, quill, model_id, record_id)
        elif kind == "go":
            if leave is not None:
                leave()
            screen_id = str(effect.get("screen") or "")
            go_to(app, str(quill["id"]), screen_id, effect.get("params") or {})
        elif kind == "confirm":
            then = find_action(quill, str(effect.get("then") or ""))
            if then is None:
                app.say(f"{quill.get('name')} has no action {effect.get('then')!r}.", error=True)
                continue
            yes = await app.push_screen_wait(
                ConfirmModal(str(effect.get("text") or ""),
                             confirm_label=str(then.get("label") or "Yes"))
            )
            if yes:
                await run_action(app, quill, then, record=record, values=effect.get("args") or {},
                                 ask=False, leave=leave)
        # `redraw` is what every caller does after an action anyway.


async def open_record(app: Any, quill: dict, model_id: str, record_id: str) -> dict | str | None:
    """The record sheet, for one record of any datamodel this person has. Waits on it."""
    api = app.client
    models = all_models(app, quill)
    if model_id not in models or not record_id:
        app.say(f"There is no {model_id or 'record'} here to open.", error=True)
        return None
    try:
        record = await api.record(model_id, record_id)
    except AuthError:
        await app.sign_out(message=SESSION_EXPIRED)
        return None
    except ApiError as exc:
        app.say(str(exc), error=True)
        return None
    choices = await link_choices(api, models, models[model_id])
    return await app.push_screen_wait(
        RecordSheet(api, models, model_id, record=record, choices=choices, run_action=run_action)
    )


def go_to(app: Any, quill_id: str, screen_id: str, params: dict) -> None:
    """To another screen of the Quill: the workspace knows where its pane is."""
    for screen in reversed(app.screen_stack):
        going = getattr(screen, "go_to", None)
        if callable(going):
            going(quill_id, screen_id, params)
            return


# -- the palette -----------------------------------------------------------------------
class QuillCommands(Provider):
    """ctrl+e: every action not on a record, from every Quill, found by typing."""

    def _commands(self) -> Iterator[tuple[str, str, dict, dict]]:
        for quill, action in loose_actions(installed(self.app)):
            name = f"{quill.get('name') or quill['id']}: {action.get('label') or action['id']}"
            yield name, str(action.get("description") or ""), quill, action

    async def discover(self) -> Hits:
        for name, help_text, quill, action in self._commands():
            yield DiscoveryHit(name, partial(self._run, quill, action), help=help_text or None)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, quill, action in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), partial(self._run, quill, action),
                          text=name, help=help_text or None)

    def _run(self, quill: dict, action: dict) -> None:
        runner = getattr(self.screen, "run_quill_action", None)
        if callable(runner):
            runner(quill, action)
