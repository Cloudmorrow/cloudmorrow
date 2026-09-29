"""A Quill's own screen: the view its code returned, drawn as widgets.

A screen with `view = "…"` in its manifest (`kit: "view"` to a client) is not
one of the kit's: the Quill's code draws it, as a tree of primitives
(docs/QUILLCODE.md, *Views and primitives*; the vocabulary and its checks are
cloudmorrow.quill.ui). The pane asks the server for the tree —
`GET /api/quills/{quill}/views/{screen}` with its parameters — and draws
every node with widgets/view_nodes.py, one method each (`RENDERERS`), the
way the web app and the phone draw the same tree their own way:

    stack row columns tabs    one under another; side by side; columns; tabs
    text markdown image       words, in a style; Markdown; a record's picture,
                              or what an https picture is of (a terminal
                              fetches no pictures from elsewhere)
    badge stat empty divider  a tag in a tone; a number with its label; what
                              a list says when there is nothing in it; a rule
    field                     one field of a record, written out, or with its
                              kind's widget when `edit` — saved when you
                              leave it, or at once for a tick, a choice
    form                      an action's form, in place; its button runs it
    button menu               run an action, open a record, go to a screen
    table                     a row per record: enter opens it, and the row's
                              actions are buttons under it, on the row you are on
    cards                     a card per record: enter or a click opens it
    lanes                     the board's lanes and cards: `[` `]` or a drag
                              moves one, through the record API
    month                     a month of the records by a date field, and the
                              month's list under it: `[` `]` for the months

Everything that can be pressed is a widget tab reaches, and enter presses
it. What pressing does is tui/quill_actions.py's — the action's confirm, its
form, its effects — and the view is drawn again afterwards, keeping where
you were: the focus, the scroll, the tab, the month.

When the view cannot be drawn (its code failed, or refused), the pane says
why, in the Quill's own words, where the view would be.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, TabbedContent

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.tui.kitdata import (
    all_models,
    failure,
    field_label,
    field_of,
    find_action,
    link_choices,
)
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.quill_actions import (
    apply_effects,
    fetch_view,
    go_to,
    open_record,
    press,
    run_action,
)
from cloudmorrow.tui.theme import BAD, MUTED
from cloudmorrow.tui.widgets.view_nodes import (
    Drawer,
    FieldNode,
    FormNode,
    LanesNode,
    MonthNode,
    TableNode,
    ViewAct,
    ViewOpen,
    ViewTabs,
    walk,
)


# -- the pane ----------------------------------------------------------------------------------
class ViewPane(KitPane):
    """A screen a Quill's code draws: its tree, asked for again after everything done in it."""

    def __init__(self, quill: dict, screen: dict, **kwargs: Any) -> None:
        # A view need not be about one datamodel; KitPane expects one.
        super().__init__(quill, {**screen, "model": screen.get("model") or ""}, **kwargs)
        self.screen_id = str(screen["id"])
        # What the view is asked with: `record` (and `model`) when it is
        # opened on one, and whatever a `go` handed it.
        self.params: dict = {}
        self.view_tree: dict | None = None
        self.failed = ""
        # Where you were, by node: the tab, the table's row, the month.
        self.kept: dict[str, Any] = {}
        # The link choices each field and form needs, fetched before drawing.
        self.choices: dict[str, Any] = {}
        # The kit's own new and delete are not a view's: its buttons say what it does.
        self.refused = set(KitPane.WRITING)
        self.ACTIONS = ()

    @property
    def all_models(self) -> dict:
        return all_models(self.app, self.quill)

    def content(self) -> ComposeResult:
        yield VerticalScroll(id="view-body", classes="view-body")

    def card_status(self) -> tuple[str, str] | None:
        return None

    # -- asking for it, and drawing it ------------------------------------------------------
    @work(exclusive=True, group="kit-view")
    async def reload(self) -> None:
        if self.api is None:
            return
        try:
            answer = await fetch_view(self.api, str(self.quill["id"]), self.screen_id, self.params)
        except AuthError as exc:
            await self.went_wrong(exc)
            return
        except ApiError as exc:
            self.failed, self.view_tree = str(exc) or "it failed", None
            await self.draw()
            self.status(f"{self.TAB_LABEL} could not be drawn: {self.failed}", error=True)
            return
        self.failed, self.view_tree = "", answer.get("tree")
        self.loaded = True
        await self._fetch_choices()
        await self.draw()
        self.status("")

    async def _fetch_choices(self) -> None:
        """For every link a field or form in the tree can point at: what it may point at."""
        self.choices = {}
        models = self.all_models
        # Each datamodel a link points at is read once for the whole tree.
        read: dict[str, list[dict]] = {}
        for node, path in walk(self.view_tree or {}):
            if node.get("ui") == "field" and node.get("edit"):
                model = models.get((node.get("record") or {}).get("model", "")) or {}
                field = field_of(model, str(node.get("name") or ""))
                if field and field.get("kind") == "link":
                    found = await link_choices(self.api, models, {"fields": [field]}, cache=read)
                    self.choices[path] = found.get(field["name"], [])
            elif node.get("ui") == "form":
                action = find_action(self.quill, str(node.get("action") or ""))
                if action and any(f.get("kind") == "link" for f in action.get("fields") or []):
                    self.choices[path] = await link_choices(self.api, models, {"fields": action["fields"]}, cache=read)

    async def draw(self) -> None:
        """The tree as widgets, keeping the focus and the scroll where they were."""
        body = self.query_one("#view-body", VerticalScroll)
        focused = self.screen.focused
        keep = focused.id if focused is not None and self in focused.ancestors else None
        self._remember()
        scrolled = body.scroll_y
        await body.remove_children()
        if self.failed:
            said = Text("This screen could not be drawn.\n", style=f"bold {BAD}")
            said.append(self.failed, style=MUTED)
            await body.mount(Static(said, id="view-failed", classes="view-failed"))
            return
        if self.view_tree is None:
            return
        await body.mount(Drawer(self).draw(self.view_tree, "v"))
        body.call_after_refresh(body.scroll_to, y=scrolled, animate=False)
        if keep:
            found = self.query(f"#{keep}")
            if found:
                found.first().focus()

    def _remember(self) -> None:
        """Before a redraw: which tab, which row."""
        for tabs in self.query(ViewTabs):
            try:
                self.kept[str(tabs.id)] = tabs.query_one(TabbedContent).active
            except Exception:
                pass
        for table in self.query(TableNode):
            if table.records:
                self.kept[str(table.id)] = table.table.cursor_row

    # -- what the pieces ask for --------------------------------------------------------------
    def on_view_act(self, event: ViewAct) -> None:
        event.stop()
        self.act_on(event.node)

    def on_view_open(self, event: ViewOpen) -> None:
        event.stop()
        self.open_record(event.record)

    def on_month_node_turned(self, event: MonthNode.Turned) -> None:
        event.stop()
        self.kept[str(event.month.id)] = event.month.shown

    @work(group="ui")
    async def act_on(self, node: dict) -> None:
        """A button: run its action, open its record, or go to its screen."""
        if node.get("action"):
            action = find_action(self.quill, str(node["action"]))
            if action is None:
                self.status(f"{node['action']} is not something you can do here.", error=True)
                return
            record = node.get("record")
            if record is None and action.get("on") and self.params.get("record"):
                # A view opened on a record: its buttons are about that one.
                record = {"id": self.params["record"], "model": action["on"]}
            if await run_action(self.app, self.quill, action, record=record, values=node.get("args") or {}):
                self.reload()
        elif node.get("open"):
            await self._open(node["open"])
        elif node.get("go"):
            go_to(self.app, str(self.quill["id"]), str(node["go"]), node.get("params") or {})

    @work(group="ui")
    async def open_record(self, record: dict) -> None:
        await self._open(record)

    async def _open(self, record: dict) -> None:
        result = await open_record(self.app, self.quill, str(record.get("model") or ""), str(record.get("id") or ""))
        if result is not None:
            self.reload()

    def on_form_node_submitted(self, event: FormNode.Submitted) -> None:
        event.stop()
        self.submit(event.form)

    @work(group="ui")
    async def submit(self, form: FormNode) -> None:
        """A form in the view: run its action; an `error` stays under the form."""
        fields = form.collect()
        if fields is None:
            return
        record = form.node.get("record") or None
        try:
            effects = await press(
                self.api,
                str(self.quill["id"]),
                str(form.action["id"]),
                record=str((record or {}).get("id") or ""),
                fields=fields,
            )
        except AuthError as exc:
            await self.went_wrong(exc)
            return
        except ApiError as exc:
            form.say(str(exc))
            return
        said = failure(effects)
        if said is not None:
            form.say(said)
            return
        await apply_effects(self.app, self.quill, effects, record=record)
        self.reload()

    def on_field_node_save(self, event: FieldNode.Save) -> None:
        event.stop()
        self.save_field(event.node, event.value)

    @work(group="ui")
    async def save_field(self, node: FieldNode, value: Any) -> None:
        record = node.record
        try:
            saved = await self.api.update_record(
                str(record["model"]), str(record["id"]), {node.name_: value}, rev=record.get("rev")
            )
        except ApiError as exc:
            if await self.went_wrong(exc, stale=True) != "auth":
                self.reload()
            return
        # The next save carries the new revision; the rest of the view is as it was.
        record["rev"] = saved.get("rev", record.get("rev"))
        node.saved = value
        self.status(f"Saved {field_label(node.field).lower()}.")

    def on_lanes_node_moved(self, event: LanesNode.Moved) -> None:
        event.stop()
        self.move(event.record, event.field, event.lane, event.index)

    @work(group="ui")
    async def move(self, record: dict, field: str, lane: str, index: int | None) -> None:
        try:
            await self.api.move_record(str(record["model"]), str(record["id"]), {field: lane}, index)
        except ApiError as exc:
            if await self.went_wrong(exc) == "auth":
                return
        # Either way the lanes are drawn as the server has them now.
        self.reload()
