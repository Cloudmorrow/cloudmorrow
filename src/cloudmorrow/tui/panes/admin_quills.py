"""Administration → Quills: the catalog, and what this server has from it.

Every Quill in the catalog, shelved by category, with the version installed
here if there is one. Installing is two steps on purpose (docs/QUILLS.md,
rule 3): what a Quill adds is visible before it is added, so Install opens
the install sheet — the data it uses, extends or introduces, the screens, the
jobs, the grants it asks for and why — and nothing happens without a yes.

A Quill with code of its own says on the sheet what it runs, as whom, and
what it may reach; once installed, Running (`r`) shows what that code is
doing — see `admin_quill_services`.

Removing one takes its tabs and its jobs away, from every client. It never
takes a record: the data is the person's, and it is there again the day the
Quill (or another that uses the same datamodels) is installed.

Both change what the workspace behind this panel should show, so each asks
it to fetch the Quills again: the tab comes or goes without a restart.
"""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Label, Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.admin_quill_services import QuillServicesModal
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.theme import ACCENT, FAINT, GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action

# How the install sheet words each way a Quill can touch a datamodel.
HOW = {
    "uses": "uses",
    "extends": "adds fields to",
    "introduces": "introduces",
    "asks for": "asks to reach",
}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def sheet_text(plan: dict) -> str:
    """The install sheet as markup: what the Quill is, then everything it adds.

    Kept apart from the dialog so it reads top to bottom as the sheet does,
    and so a test can read it without a screen.
    """
    lines: list[str] = []
    name = plan.get("name") or plan.get("id", "?")
    head = f"[b]{name}[/] [{MUTED}]{plan.get('version', '')}[/]"
    if plan.get("publisher"):
        head += f"  [{MUTED}]by {plan['publisher']}[/]"
    if plan.get("license"):
        head += f"  [{MUTED}]· {plan['license']}[/]"
    lines.append(head)
    if plan.get("summary"):
        lines.append(str(plan["summary"]))
    installed = plan.get("installed_version")
    if installed:
        lines.append(f"[{WARN}]{installed} is installed; this replaces it.[/]")

    data = plan.get("data") or []
    if data:
        lines += ["", f"[b {ACCENT}]Data[/]"]
        for row in data:
            how = HOW.get(row.get("how", ""), row.get("how", ""))
            line = f"  {how} [b]{row.get('label') or row['id']}[/] [{MUTED}]({row['id']})[/]"
            marks = []
            if row.get("foundation"):
                marks.append("foundational")
            if row.get("new"):
                marks.append(f"[{GOOD}]new on this server[/]")
            if row.get("access"):
                marks.append(f"{row['access']} access")
            if marks:
                line += f"  [{MUTED}]{' · '.join(marks)}[/]"
            lines.append(line)
            if row.get("fields"):
                lines.append(f"    [{MUTED}]fields:[/] {', '.join(row['fields'])}")
            if row.get("why"):
                lines.append(f"    [{MUTED}]why:[/] {row['why']}")

    screens = plan.get("screens") or []
    if screens:
        lines += ["", f"[b {ACCENT}]Screens[/]  [{MUTED}]a tab each, on every surface[/]"]
        for screen in screens:
            lines.append(
                f"  [b]{screen.get('label') or screen['id']}[/] "
                f"[{MUTED}]{screen.get('kit', '')} of {screen.get('model', '')}[/]"
            )
        surfaces = plan.get("surfaces") or []
        if surfaces:
            lines.append(f"  [{MUTED}]on: {', '.join(surfaces)}[/]")

    jobs = plan.get("jobs") or []
    if jobs:
        lines += ["", f"[b {ACCENT}]Jobs[/]"]
        for job in jobs:
            if job.get("action") == "expire":
                what = (
                    f"deletes {job.get('model')} records {job.get('after')} after "
                    f"{job.get('field')}"
                )
            else:
                what = f"{job.get('action')}"
            every = f", every {job['every']}" if job.get("every") else ""
            lines.append(f"  [b]{job['id']}[/] [{MUTED}]{what}{every}[/]")

    datasets = plan.get("datasets") or []
    if datasets:
        lines += ["", f"[b {ACCENT}]Starts you with[/]"]
        for dataset in datasets:
            count = dataset.get("count")
            amount = _plural(int(count), "record") if count is not None else "records"
            per = " for each person" if dataset.get("seed") == "per-owner" else ""
            what = f"{amount} of {dataset.get('model')}{per}"
            lines.append(f"  [b]{dataset['id']}[/] [{MUTED}]{what}[/]")

    lines += code_lines(plan)
    return "\n".join(lines)


def code_lines(plan: dict) -> list[str]:
    """What the Quill runs on this server, as whom, and what it may reach there.

    Said plainly because it is the one part of a Quill that is not drawn by
    the kit: a program, started by the server, acting for an account.
    """
    commands = plan.get("runs_code") or []
    hooks = plan.get("webhooks") or []
    apis = plan.get("apis") or []
    if not (commands or hooks or apis):
        return []
    quill = plan.get("id", "?")
    lines = ["", f"[b {ACCENT}]Its own code[/]"]
    if commands:
        lines.append(f"  Runs code on this server: [b]{escape('; '.join(commands))}[/]")
    for hook in hooks:
        lines.append(
            f"  [{MUTED}]webhook[/] {hook.get('id', '?')}  "
            f"[{MUTED}]POST /hooks/{quill}/{hook.get('path') or hook.get('id')}[/]"
        )
    for api in apis:
        lines.append(f"  [{MUTED}]api[/] {api.get('id', '?')}  [{MUTED}]/api/q/{quill}/…[/]")
    who = plan.get("runs_as") or "you, the administrator who installs it"
    reach = ", ".join(plan.get("reach") or []) or "nothing"
    lines.append(f"  [{WARN}]Runs as {escape(who)}, and can read and write only: {reach}.[/]")
    return lines


class QuillSheet(Modal[bool]):
    """The install sheet: everything a Quill adds, and Install or Cancel."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, plan: dict) -> None:
        super().__init__()
        self.plan = plan

    def compose(self) -> ComposeResult:
        installed = self.plan.get("installed_version")
        verb = "Reinstall" if installed == self.plan.get("version") else (
            "Update" if installed else "Install"
        )
        with Vertical(classes="modal modal-wide", id="quill-sheet"):
            yield Label(f"{verb} {self.plan.get('name') or self.plan.get('id')}?",
                        classes="modal-title")
            with VerticalScroll(id="quill-sheet-body"):
                yield Static(sheet_text(self.plan), id="quill-sheet-text")
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(verb, variant="primary", id="install")

    def on_mount(self) -> None:
        self.query_one("#install", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "install")

    def action_cancel(self) -> None:
        self.dismiss(False)


class QuillsView(Pane):
    """The catalog by category, what is installed, install and remove."""

    TAB_LABEL = "Quills"
    SUMMARY = "software for this server, from the Quill Catalog"
    BINDINGS = [
        ("i", "fire('install')", "Install"),
        ("d", "fire('remove')", "Remove"),
        ("r", "fire('running')", "Running"),
    ]
    ACTIONS = (
        Action("install", "Install…", "i", variant="primary",
               hint="See what it adds, then install it"),
        Action("running", "Running…", "r",
               hint="What its code is doing: services, logs, webhook addresses"),
        Action("remove", "Remove", "d", variant="error",
               hint="Its tabs and jobs go; its records stay"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # One entry per table row: a catalog entry, or None for a category heading.
        self._rows: list[dict | None] = []

    def content(self) -> ComposeResult:
        yield Static(
            f"[{FAINT}]Each is drawn here, on the web and on the phone from the same kit. "
            f"Removing one keeps every record.[/]",
            id="admin-quills-note",
        )
        yield DataTable(id="admin-quill-table", cursor_type="row", zebra_stripes=False)

    def on_mount(self) -> None:
        self.query_one("#admin-quill-table", DataTable).add_columns(
            "QUILL", "INSTALLED", "PUBLISHER", "WHAT IT IS"
        )

    def on_show(self) -> None:
        self.reload()

    @property
    def selected(self) -> dict | None:
        table = self.query_one("#admin-quill-table", DataTable)
        if not 0 <= table.cursor_row < len(self._rows):
            return None
        return self._rows[table.cursor_row]

    @work(exclusive=True, group="admin-quills")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            catalog = await client.quill_catalog()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        categories = catalog.get("categories") or []
        quills = catalog.get("quills") or []
        order = [c["id"] for c in categories]
        labels = {c["id"]: c.get("label") or c["id"] for c in categories}
        # Shelved as the catalog orders its categories; anything on a shelf
        # the catalog does not list goes at the end rather than nowhere.
        shelves = order + sorted({q.get("category") or "other" for q in quills} - set(order))
        table = self.query_one("#admin-quill-table", DataTable)
        row = table.cursor_row
        table.clear()
        self._rows = []
        for shelf in shelves:
            here = [q for q in quills if (q.get("category") or "other") == shelf]
            if not here:
                continue
            shelf_name = str(labels.get(shelf, shelf)).upper()
            table.add_row(f"[b {MUTED}]{shelf_name}[/]", "", "", "")
            self._rows.append(None)
            for quill in sorted(here, key=lambda q: str(q.get("name") or q["id"]).lower()):
                table.add_row(*self._row(quill), key=f"quill-{quill['id']}")
                self._rows.append(quill)
        if self._rows:
            table.move_cursor(row=self._nearest(max(row, 0)))
        installed = sum(1 for q in quills if q.get("installed_version"))
        self.status(
            f"{_plural(len(quills), 'Quill')} in the catalog, {installed} installed", note=True
        )

    def _nearest(self, row: int) -> int:
        """The row to stand on: *row*, or the first Quill below a heading."""
        row = min(row, len(self._rows) - 1)
        for index in range(row, len(self._rows)):
            if self._rows[index] is not None:
                return index
        return row

    @staticmethod
    def _row(quill: dict) -> tuple[str, ...]:
        version = quill.get("installed_version")
        return (
            f"  [b]{quill.get('name') or quill['id']}[/]",
            f"[{GOOD}]{version}[/]" if version else f"[{MUTED}]—[/]",
            f"[{MUTED}]{quill.get('publisher') or ''}[/]",
            str(quill.get("summary") or ""),
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """A heading is not something to stand on; step off it."""
        event.stop()
        if 0 <= event.cursor_row < len(self._rows) and self._rows[event.cursor_row] is None:
            nearest = self._nearest(event.cursor_row)
            if nearest != event.cursor_row and self._rows[nearest] is not None:
                event.data_table.move_cursor(row=nearest)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.act_install()

    # -- installing --------------------------------------------------------
    def act_install(self) -> None:
        quill = self.selected
        if quill is None:
            self.status("Pick a Quill first.", error=True)
            return
        self.install(quill)

    @work(group="ui")
    async def install(self, quill: dict) -> None:
        self.status(f"Asking the catalog about {quill.get('name') or quill['id']}…", note=True)
        try:
            plan = await self.api.plan_quill(id=quill["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status("", note=True)
        if not await self.app.push_screen_wait(QuillSheet(plan)):
            return
        self.status(f"Installing {plan.get('name') or quill['id']}…", note=True)
        try:
            done = await self.api.install_quill(id=quill["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Installed {done.get('name') or quill['id']} {done.get('version', '')}.")
        self._workspace_follows()
        self.reload()

    # -- what its code is doing --------------------------------------------
    def act_running(self) -> None:
        quill = self.selected
        if quill is None or not quill.get("installed_version"):
            self.status("That Quill is not installed.", error=True)
            return
        self.running(quill)

    @work(group="ui")
    async def running(self, quill: dict) -> None:
        try:
            rows = await self.api.quill_services()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        row = next((r for r in rows if r["id"] == quill["id"]), None)
        if row is None:
            self.status(f"{quill.get('name') or quill['id']} runs no code of its own.", note=True)
            return
        await self.app.push_screen_wait(QuillServicesModal(row))

    def act_remove(self) -> None:
        quill = self.selected
        if quill is None or not quill.get("installed_version"):
            self.status("That Quill is not installed.", error=True)
            return
        self.remove(quill)

    @work(group="ui")
    async def remove(self, quill: dict) -> None:
        name = quill.get("name") or quill["id"]
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Remove {name}?",
                detail=(
                    "[dim]Its tabs and its jobs go, for everybody on this server. Its "
                    "records stay: install it again and they are all there.[/]"
                ),
                confirm_label="Remove",
            )
        )
        if not confirmed:
            return
        try:
            await self.api.uninstall_quill(quill["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Removed {name}. Its records are kept.")
        self._workspace_follows()
        self.reload()

    def _workspace_follows(self) -> None:
        """The tabs behind this panel: fetched again, so they match."""
        again = getattr(self.screen, "ask_the_server", None)
        if callable(again):
            again()
