"""Administration → Quills: what this server runs, people's own, and the catalog.

Three tabs, with the chosen Quill's details beside them:

- **Server Quills.** Every Quill installed here, each with a state — on,
  off, or for one with code of its own, running, restarting or stopped —
  and where it stands against the catalog: a newer release out, up to date,
  or no telling. Space ticks one; Update selected (`u`) and Update all (`U`)
  install each again from the catalog, for the same people, and say how
  each went. On/off (`o`) is the server's switch, for everybody: off takes
  its tabs out of every client and closes its API. There is no separate
  list of features: what this server offers is its Quills.
- **User Quills.** What the server allows people to add for themselves,
  what they have asked for — approve for everyone, for the one who asked,
  or decline — and whose is whose: promote one for everyone, or switch it
  off. The policy itself is `cm quill policy`.
- **Catalog.** Every Quill there is, shelved by category, with the version
  installed here if there is one.

Installing is two steps on purpose (docs/QUILLS.md, rule 3): what a Quill
adds is visible before it is added, so Install (`i`) opens the install sheet
— the data it uses, extends or introduces, the screens, the jobs, the grants
it asks for and why — and nothing happens without a yes. On an installed
one the same sheet says Update or Reinstall, which is the same install
again.

A Quill with code of its own says on the sheet what it runs, as whom, and
what it may reach; once installed, Running (`r`) shows what that code is
doing — see `admin_quill_services`.

A Quill that brings data new to this server asks on its sheet which circles
get it (docs/CIRCLES.md): a tick each, and after the install every ticked
circle may write it. A circle with `* = write` has it already, and says so.

Removing one (`d`) takes its tabs and its jobs away, from every client. It
never takes a record: the data is the person's, and it is there again the
day the Quill (or another that uses the same datamodels) is installed.

All of it changes what the workspace behind this panel should show, so each
asks it to fetch the Quills again: the tab comes or goes without a restart.
"""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, ContentSwitcher, DataTable, Label, Static, Tab, Tabs

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.admin_quill_services import QuillServicesModal
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, Modal
from cloudmorrow.tui.theme import ACCENT, BAD, FAINT, GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.words import megabytes, plural

# How the install sheet words each way a Quill can touch a datamodel.
HOW = {
    "uses": "uses",
    "extends": "adds fields to",
    "introduces": "introduces",
    "asks for": "asks to reach",
}


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
    return "\n".join(lines + sections_text(plan))


def sections_text(plan: dict) -> list[str]:
    """Everything a Quill adds, a section each: the sheet's body, and the details
    beside the list once it is installed."""
    lines: list[str] = []
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
                what = f"deletes {job.get('model')} records {job.get('after')} after {job.get('field')}"
            else:
                what = f"{job.get('action')}"
            every = f", every {job['every']}" if job.get("every") else ""
            lines.append(f"  [b]{job['id']}[/] [{MUTED}]{what}{every}[/]")

    datasets = plan.get("datasets") or []
    if datasets:
        lines += ["", f"[b {ACCENT}]Starts you with[/]"]
        for dataset in datasets:
            count = dataset.get("count")
            amount = plural(int(count), "record") if count is not None else "records"
            per = " for each person" if dataset.get("seed") == "per-owner" else ""
            what = f"{amount} of {dataset.get('model')}{per}"
            lines.append(f"  [b]{dataset['id']}[/] [{MUTED}]{what}[/]")

    lines += runtime_lines(plan)
    lines += machine_runtime_lines(plan)
    lines += code_lines(plan)
    return lines


def runtime_lines(plan: dict) -> list[str]:
    """The programs the Quill needs, which the server fetches for it: said with their size."""
    runtimes = plan.get("runtimes") or []
    if not runtimes:
        return []
    lines = ["", f"[b {ACCENT}]Adds to this server[/]"]
    for runtime in runtimes:
        name = escape(str(runtime.get("label") or runtime.get("id", "?")))
        if runtime.get("version"):
            name += f" {escape(str(runtime['version']))}"
        facts = [
            escape(str(runtime.get("summary") or "")),
            megabytes(int(runtime.get("size") or 0)) if runtime.get("size") else "",
            escape(str(runtime.get("license") or "")),
        ]
        if runtime.get("installed"):
            facts.append(f"[{GOOD}]here already[/]")
        elif runtime.get("available"):
            facts.append("downloaded, checked against the catalog's checksum")
        if runtime.get("problem"):
            facts.append(f"[{WARN}]{escape(str(runtime['problem']))}[/]")
        lines.append(f"  [b]{name}[/]")
        lines.append(f"    [{MUTED}]{' · '.join(f for f in facts if f)}[/]")
    lines.append(f"  [{MUTED}]Kept by the server for its Quills; nothing is installed on the system itself.[/]")
    return lines


def machine_runtime_lines(plan: dict) -> list[str]:
    """What its machine handlers bring to a computer they are switched on on."""
    runtimes = plan.get("machine_runtimes") or []
    if not runtimes:
        return []
    lines = ["", f"[b {ACCENT}]Adds to a machine that runs it[/]"]
    for runtime in runtimes:
        name = escape(str(runtime.get("label") or runtime.get("id", "?")))
        if runtime.get("version"):
            name += f" {escape(str(runtime['version']))}"
        facts = [
            escape(str(runtime.get("summary") or "")),
            f"up to {megabytes(int(runtime['size']))}" if runtime.get("size") else "",
            escape(str(runtime.get("license") or "")),
        ]
        if runtime.get("problem"):
            facts.append(f"[{WARN}]{escape(str(runtime['problem']))}[/]")
        lines.append(f"  [b]{name}[/]")
        lines.append(f"    [{MUTED}]{' · '.join(f for f in facts if f)}[/]")
    lines.append(f"  [{MUTED}]Fetched by the agent on a computer where somebody switches the handler on; not here.[/]")
    return lines


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


def new_data(plan: dict) -> list[dict]:
    """The data a fresh install brings that no circle names yet."""
    if plan.get("installed_version"):
        return []
    return [row for row in plan.get("data") or [] if row.get("new")]


def has_everything(circle: dict) -> bool:
    return (circle.get("rules") or {}).get("*") == "write"


class QuillSheet(Modal[bool]):
    """The install sheet: everything a Quill adds, and Install or Cancel.

    With *circles*, and data new to this server, a tick per circle for who
    gets it; the ticked circles' ids are in `chosen` once it is answered.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, plan: dict, *, circles: list[dict] | None = None) -> None:
        super().__init__()
        self.plan = plan
        self.fresh = new_data(plan)
        self.circles = (circles or []) if self.fresh else []
        self.chosen: list[str] = []

    def compose(self) -> ComposeResult:
        installed = self.plan.get("installed_version")
        verb = "Reinstall" if installed == self.plan.get("version") else ("Update" if installed else "Install")
        with Vertical(classes="modal modal-wide", id="quill-sheet"):
            yield Label(f"{verb} {self.plan.get('name') or self.plan.get('id')}?", classes="modal-title")
            with VerticalScroll(id="quill-sheet-body"):
                yield Static(sheet_text(self.plan), id="quill-sheet-text")
                if self.circles:
                    what = ", ".join(row.get("label") or row["id"] for row in self.fresh)
                    everyone = [c["name"] for c in self.circles if has_everything(c)]
                    lead = (
                        f"everyone in {', '.join(everyone)} can read and write {what} the moment it is installed"
                        if everyone
                        else f"no circle has everything, so nobody reaches {what} until a circle is ticked"
                    )
                    yield Static(
                        f"\n[b {ACCENT}]Who gets it[/]  [{MUTED}]{escape(lead)}; tick the other circles "
                        f"that should too — the rest do not see it until a circle is given it[/]",
                        id="sheet-circles-note",
                    )
                    with Vertical(id="sheet-circles"):
                        for index, circle in enumerate(self.circles):
                            everything = has_everything(circle)
                            label = circle["name"] + ("  (has everything: gets it anyway)" if everything else "")
                            yield Checkbox(
                                label,
                                value=everything,
                                disabled=everything,
                                id=f"sheet-circle-{index}",
                            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(verb, variant="primary", id="install")

    def on_mount(self) -> None:
        self.query_one("#install", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "install":
            self.chosen = [
                circle["id"]
                for index, circle in enumerate(self.circles)
                if not has_everything(circle) and self.query_one(f"#sheet-circle-{index}", Checkbox).value
            ]
        self.dismiss(event.button.id == "install")

    def action_cancel(self) -> None:
        self.dismiss(False)


class RemoveSheet(Modal[list[str] | None]):
    """Removing a Quill: what it brought, a tick each to keep it. Answers the
    ids to drop — unticked — or None for not removing after all."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str, brought: list[dict]) -> None:
        super().__init__()
        self.quill_name = name
        self.brought = brought

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="remove-sheet"):
            yield Label(f"Remove {self.quill_name}?", classes="modal-title")
            yield Static(
                f"[{MUTED}]Its tabs and jobs go, for everybody. What it brought stays, ticked: a "
                "datamodel's records are there again the day it comes back, and a field stays on "
                "the records, read-only. Untick what should go with it — records and all, for good."
                + (
                    " A program only this Quill needed is unticked: it goes too, unless you tick it.[/]"
                    if any(row.get("kind") == "runtime" for row in self.brought)
                    else "[/]"
                ),
                classes="modal-detail",
            )
            with Vertical(id="remove-brought"):
                for index, row in enumerate(self.brought):
                    if row.get("kind") == "runtime":
                        # A program it fetched that nothing else needs: unticked,
                        # it goes with the Quill, because nothing runs on it.
                        size = row.get("size_said") or megabytes(int(row.get("size") or 0))
                        label = f"{row.get('label') or row['id']}  (a program it added, {size}, nothing else needs it)"
                        yield Checkbox(label, value=False, id=f"remove-keep-{index}")
                        continue
                    what = "a datamodel it introduced" if row.get("kind") == "datamodel" else "a field it added"
                    count = int(row.get("records") or 0)
                    label = f"{row.get('label') or row['id']}  ({what}, {count} record{'' if count == 1 else 's'})"
                    yield Checkbox(label, value=True, id=f"remove-keep-{index}")
            with Horizontal(classes="modal-buttons"):
                yield Button("Keep it", id="cancel")
                yield Button("Remove", variant="error", id="remove")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id != "remove":
            self.dismiss(None)
            return
        drop = [
            row["id"]
            for index, row in enumerate(self.brought)
            if not self.query_one(f"#remove-keep-{index}", Checkbox).value
        ]
        self.dismiss(drop)

    def action_cancel(self) -> None:
        self.dismiss(None)


# -- what a Quill is doing, and where it stands ------------------------------------------
STATE_TONES = {"on": GOOD, "running": GOOD, "off": FAINT, "restarting": WARN, "stopped": BAD, "broken": BAD}


def state_of(quill: dict, running: list[dict]) -> str:
    """One word for an installed Quill: off, or on and — with code of its own —
    running, restarting or stopped."""
    if quill.get("enabled") is False:
        return "off"
    code = next((r for r in running if r.get("id") == quill["id"]), None)
    live = [s for s in (code or {}).get("services") or [] if not s.get("scheduled")]
    if not live:
        return "on"
    if any(s.get("state") == "stopped" for s in live):
        return "stopped"
    if any(s.get("state") == "restarting" for s in live):
        return "restarting"
    return "running"


def standing_of(quill: dict, entry: dict | None) -> tuple[bool | None, str]:
    """Where an installed Quill stands against the catalog (routes/quills.py): True
    with a newer release named there, False when up to date, None when there is no
    telling — the entry names no release, or the Quill came from a source of its
    own — and the words for it."""
    origin = quill.get("origin") or {}
    if entry is None:
        if origin.get("dev"):
            return None, "from a folder, with cm quill dev"
        return None, f"from {origin['repo']}" if origin.get("repo") else "not in the catalog"
    if entry.get("update_available") is True:
        return True, f"newer in the catalog: {entry.get('ref', '')}"
    if entry.get("update_available") is False:
        return False, "up to date"
    return None, "from the catalog"


def audience_said(quill: dict) -> str:
    audience = quill.get("audience") or {}
    circles = list(audience.get("circles") or [])
    people = list(audience.get("people") or [])
    if not circles and not people:
        return "for everyone"
    return "for " + ", ".join(circles + people)


def detail_text(quill: dict, *, entry: dict | None, state: str, feature: dict | None) -> str:
    """An installed Quill, beside the list: what it is, how it is, where it stands,
    and everything it adds."""
    lines: list[str] = []
    name = escape(str(quill.get("name") or quill.get("id", "?")))
    head = f"[b]{name}[/] [{MUTED}]{escape(str(quill.get('version', '')))}[/]"
    if quill.get("publisher"):
        head += f"  [{MUTED}]by {escape(str(quill['publisher']))}[/]"
    if quill.get("license"):
        head += f"  [{MUTED}]· {escape(str(quill['license']))}[/]"
    lines.append(head)
    if quill.get("summary"):
        lines.append(escape(str(quill["summary"])))
    lines.append("")
    tone = STATE_TONES.get(state, MUTED)
    turned = ""
    if feature and feature.get("changed_by"):
        way = "on" if feature.get("enabled") else "off"
        turned = f"  [{MUTED}]switched {way} by {escape(str(feature['changed_by']))}[/]"
    lines.append(f"[{tone}]{state}[/]  [{MUTED}]{escape(audience_said(quill))}[/]{turned}")
    newer, said = standing_of(quill, entry)
    tone = GOOD if newer else MUTED
    lines.append(f"[{tone}]{escape(said)}[/]" + (f"  [{MUTED}]i updates it[/]" if newer else ""))
    origin = quill.get("origin") or {}
    if origin.get("installed_by"):
        lines.append(f"[{MUTED}]installed by {escape(str(origin['installed_by']))}[/]")
    lines += sections_text(quill)
    return "\n".join(lines)


def entry_text(entry: dict) -> str:
    """A catalog entry that is not installed, beside the list."""
    name = escape(str(entry.get("name") or entry.get("id", "?")))
    head = f"[b]{name}[/]"
    if entry.get("ref"):
        head += f" [{MUTED}]{escape(str(entry['ref']))}[/]"
    if entry.get("publisher"):
        head += f"  [{MUTED}]by {escape(str(entry['publisher']))}[/]"
    lines = [head]
    if entry.get("summary"):
        lines.append(escape(str(entry["summary"])))
    lines += ["", f"[{MUTED}]Not installed. [b]i[/] shows everything it adds, then installs it.[/]"]
    return "\n".join(lines)


# -- User Quills: what the server allows, what was asked for, whose is whose ------------------
def own_widgets(everything: dict) -> list:
    """The User Quills tab's widgets: the policy, the requests with a button each,
    and people's own Quills with theirs. The buttons' ids say what they do.
    Built outright rather than composed, since they are mounted on a reload."""
    policy = everything.get("policy") or {}
    requests = everything.get("requests") or []
    personal = everything.get("personal") or []
    out: list = [
        Static(
            f"[{MUTED}]What this server allows (docs/SHARING.md) — "
            f"people's own: [b]{policy.get('personal_quills', 'on')}[/]"
            f" · code: [b]{policy.get('personal_quill_code', 'on')}[/] · sharing: "
            f"[b]{policy.get('personal_quill_sharing', 'on')}[/]  — `cm quill policy` changes it. "
            f"A Quill somebody adds for themselves is on their shelf alone, over their own data, run as them.[/]",
            id="own-policy",
        )
    ]
    if requests:
        out.append(
            Static(
                f"\n[b {ACCENT}]Asked for[/]  [{MUTED}]for everyone, for the one who asked, or declined[/]",
                classes="own-head",
            )
        )
    for request in requests:
        what = (
            f"{request['quill']} to be promoted"
            if request["kind"] == "promote"
            else request["quill"] or request["source"]
        )
        note = f"  [{MUTED}]{escape(request['note'])}[/]" if request.get("note") else ""
        out.append(
            Static(f"  [b]{escape(request['username'])}[/] asks for [b]{escape(what)}[/]{note}", classes="own-line")
        )
        buttons = [Button("For everyone", variant="primary", id=f"approve-{request['id']}")]
        if request["kind"] != "promote":
            buttons.append(Button(f"For {request['username']}", id=f"asker-{request['id']}"))
        buttons.append(Button("Decline", variant="error", id=f"decline-{request['id']}"))
        out.append(Horizontal(*buttons, classes="own-buttons"))
    out.append(Static(f"\n[b {ACCENT}]Whose[/]", classes="own-head"))
    for index, quill in enumerate(personal):
        shared = [s["username"] for s in quill.get("shared_with", []) if s["state"] == "accepted"]
        with_ = f", shared with {', '.join(shared)}" if shared else ""
        if quill.get("owner_left"):
            others = [h for h in quill.get("holders", []) if h != quill["owner"]]
            with_ = f" — off their shelf; stands with {', '.join(others) or 'nobody'}"
        code = " · runs code, as each of them" if quill.get("code") else ""
        gone = (
            f"  [{WARN}]its owner's account is gone: promote it, or remove it[/]"
            if quill.get("owner_active") is False
            else ""
        )
        on = quill.get("enabled", True)
        off = "" if on else f"  [{WARN}]switched off[/]"
        out.append(
            Static(
                f"  [b]{escape(quill['name'])}[/] [{MUTED}]{quill['version']}[/]  "
                f"[{MUTED}]{escape(quill['owner'])}'s{escape(with_)}{code}[/]{off}{gone}",
                classes="own-line",
            )
        )
        out.append(
            Horizontal(
                Button("Promote for everyone", id=f"promote-{index}"),
                Button("Switch off" if on else "Switch on", id=f"pswitch-{index}"),
                classes="own-buttons",
            )
        )
    if not personal:
        out.append(Static(f"  [{FAINT}]Nobody has added a Quill of their own yet.[/]", classes="own-line"))
    return out


TABS = (("server", "Server Quills"), ("own", "User Quills"), ("catalog", "Catalog"))


class QuillsView(Pane):
    """What this server runs, people's own, and the catalog; the chosen one's details beside."""

    TAB_LABEL = "Quills"
    SUMMARY = "what this server runs, people's own, and the catalog"
    BINDINGS = [
        ("i", "fire('install')", "Install"),
        ("space", "fire('tick')", "Tick"),
        ("u", "fire('update_picked')", "Update selected"),
        ("U", "fire('update_all')", "Update all"),
        ("o", "fire('switch')", "On/off"),
        ("r", "fire('running')", "Running"),
        ("d", "fire('remove')", "Remove"),
    ]
    ACTIONS = (
        Action(
            "install", "Install…", "i", variant="primary", hint="See what it adds, then install, update or reinstall it"
        ),
        Action(
            "update_picked",
            "Update selected",
            "u",
            hint="Install the ticked Quills again from the catalog (space ticks)",
        ),
        Action("update_all", "Update all", "U", hint="Every Quill the catalog may have a newer release of"),
        Action(
            "switch", "On/off", "o", hint="For everybody: off takes its tabs out of every client and closes its API"
        ),
        Action("running", "Running…", "r", hint="What its code is doing: services, logs, webhook addresses"),
        Action("remove", "Remove", "d", variant="error", hint="Its tabs and jobs go; its records stay"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The catalog's rows: an entry, or None for a category heading.
        self._rows: list[dict | None] = []
        self._entries: dict[str, dict] = {}
        # The server's Quills in tab order, what their code is doing, the
        # server's switches, and everything people's own.
        self._server: list[dict] = []
        self._running: list[dict] = []
        self._features: dict[str, dict] = {}
        self._everything: dict = {}
        # Ticked for an update in one go: kept across redraws, not across tabs.
        self._picked: set[str] = set()
        self._tab = "server"

    def content(self) -> ComposeResult:
        yield Tabs(*(Tab(label, id=f"tab-{key}") for key, label in TABS), id="admin-quill-tabs")
        with Horizontal(id="admin-quill-split"):
            with ContentSwitcher(id="admin-quill-pages", initial="quill-page-server"):
                with Vertical(id="quill-page-server"):
                    yield Static(
                        f"[{FAINT}]Every Quill on this server. Space ticks one; u updates the ticked, U every one "
                        f"the catalog has a newer release of — each installed again, for the same people.[/]",
                        id="admin-server-note",
                    )
                    yield DataTable(id="admin-server-table", cursor_type="row", zebra_stripes=False)
                yield VerticalScroll(id="quill-page-own")
                with Vertical(id="quill-page-catalog"):
                    yield Static(
                        f"[{FAINT}]Each is drawn here, on the web and on the phone from the same kit. "
                        f"Removing one keeps every record.[/]",
                        id="admin-quills-note",
                    )
                    yield DataTable(id="admin-quill-table", cursor_type="row", zebra_stripes=False)
            with VerticalScroll(id="admin-quill-detail"):
                yield Static(f"[{FAINT}]Nothing chosen.[/]", id="admin-quill-detail-text")

    def on_mount(self) -> None:
        self.query_one("#admin-server-table", DataTable).add_columns("", "QUILL", "VERSION", "STATE", "CATALOG")
        self.query_one("#admin-quill-table", DataTable).add_columns("QUILL", "INSTALLED", "PUBLISHER", "WHAT IT IS")

    def on_show(self) -> None:
        self.reload()

    # -- the tabs ----------------------------------------------------------------
    @property
    def tab(self) -> str:
        return self._tab

    def show_tab(self, key: str) -> None:
        """Bring one of the three to the front, by key: server, own, catalog."""
        tabs = self.query_one("#admin-quill-tabs", Tabs)
        if tabs.active != f"tab-{key}":
            tabs.active = f"tab-{key}"
        else:
            self._tab_showing(key)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        event.stop()
        self._tab_showing((event.tab.id or "tab-server")[len("tab-") :])

    def _tab_showing(self, key: str) -> None:
        self._tab = key
        self.query_one("#admin-quill-pages", ContentSwitcher).current = f"quill-page-{key}"
        self.query_one("#admin-quill-detail").display = key != "own"
        self._say_detail()

    @property
    def table(self) -> DataTable | None:
        """The table on the tab showing, if that tab is one."""
        if self._tab == "server":
            return self.query_one("#admin-server-table", DataTable)
        if self._tab == "catalog":
            return self.query_one("#admin-quill-table", DataTable)
        return None

    @property
    def selected(self) -> dict | None:
        """The Quill under the cursor: a server Quill, or a catalog entry."""
        table = self.table
        if table is None:
            return None
        if self._tab == "server":
            return self._server[table.cursor_row] if 0 <= table.cursor_row < len(self._server) else None
        if not 0 <= table.cursor_row < len(self._rows):
            return None
        return self._rows[table.cursor_row]

    def _installed(self, quill_id: str) -> dict | None:
        return next((q for q in self._server if q["id"] == quill_id), None)

    # -- loading ------------------------------------------------------------------
    @work(exclusive=True, group="admin-quills")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        problem = ""
        try:
            catalog = await client.quill_catalog()
        except ApiError as exc:
            catalog, problem = {"categories": [], "quills": []}, str(exc)
        try:
            self._everything = await client.all_quills()
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        try:
            self._running = await client.quill_services()
        except ApiError:
            self._running = []
        try:
            self._features = {row["key"]: row for row in await client.features()}
        except ApiError:
            self._features = {}
        self._entries = {entry["id"]: entry for entry in catalog.get("quills") or []}
        self._server = list(self._everything.get("server") or [])
        self._picked &= {q["id"] for q in self._server if q["id"] in self._entries}
        self._draw_server()
        self._draw_catalog(catalog)
        await self._draw_own()
        if problem:
            self.status(f"The catalog could not be read: {problem}", error=True)
        else:
            newer = sum(1 for q in self._server if standing_of(q, self._entries.get(q["id"]))[0])
            said = f"{plural(len(self._server), 'Quill')} installed"
            self.status(said + (f", {newer} with a newer release out" if newer else ""), note=True)
        self._say_detail()

    def _draw_server(self) -> None:
        table = self.query_one("#admin-server-table", DataTable)
        row = table.cursor_row
        table.clear()
        for quill in self._server:
            table.add_row(*self._server_row(quill), key=f"server-{quill['id']}")
        for key, why in (self._everything.get("broken") or {}).items():
            table.add_row("", f"  [b]{escape(str(key))}[/]", "", f"[{BAD}]broken[/]", f"[{MUTED}]{escape(str(why))}[/]")
        if self._server:
            table.move_cursor(row=min(max(row, 0), len(self._server) - 1))

    def _server_row(self, quill: dict) -> tuple[str, ...]:
        state = state_of(quill, self._running)
        newer, said = standing_of(quill, self._entries.get(quill["id"]))
        return (
            f"[{ACCENT}]✓[/]" if quill["id"] in self._picked else " ",
            f"  [b]{escape(str(quill.get('name') or quill['id']))}[/]",
            f"[{MUTED}]{escape(str(quill.get('version', '')))}[/]",
            f"[{STATE_TONES.get(state, MUTED)}]{state}[/]",
            f"[{GOOD if newer else MUTED}]{escape(said)}[/]",
        )

    def _draw_catalog(self, catalog: dict) -> None:
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
        if quill.get("update_available"):
            installed = f"[{GOOD}]{version}[/] [{ACCENT}]↑ {escape(str(quill.get('ref', '')))}[/]"
        else:
            installed = f"[{GOOD}]{version}[/]" if version else f"[{MUTED}]—[/]"
        return (
            f"  [b]{quill.get('name') or quill['id']}[/]",
            installed,
            f"[{MUTED}]{quill.get('publisher') or ''}[/]",
            str(quill.get("summary") or ""),
        )

    async def _draw_own(self) -> None:
        page = self.query_one("#quill-page-own", VerticalScroll)
        await page.remove_children()
        await page.mount_all(own_widgets(self._everything))

    # -- the details beside the list ----------------------------------------------
    def _say_detail(self) -> None:
        text = self.query_one("#admin-quill-detail-text", Static)
        chosen = self.selected
        if chosen is None:
            text.update(f"[{FAINT}]Nothing chosen.[/]")
            return
        installed = self._installed(chosen["id"])
        if installed is None:
            text.update(entry_text(chosen))
            return
        text.update(
            detail_text(
                installed,
                entry=self._entries.get(chosen["id"]),
                state=state_of(installed, self._running),
                feature=self._features.get(chosen["id"]),
            )
        )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """A heading is not something to stand on; step off it. Whatever is stood
        on is what the details beside say."""
        event.stop()
        if event.data_table.id == "admin-quill-table" and 0 <= event.cursor_row < len(self._rows):
            if self._rows[event.cursor_row] is None:
                nearest = self._nearest(event.cursor_row)
                if nearest != event.cursor_row and self._rows[nearest] is not None:
                    event.data_table.move_cursor(row=nearest)
                    return
        self._say_detail()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.act_install()

    # -- ticking, and updating in one go -----------------------------------------------
    def act_tick(self) -> None:
        if self._tab != "server":
            return
        quill = self.selected
        if quill is None:
            return
        if quill["id"] not in self._entries:
            self.status(
                f"{quill.get('name') or quill['id']} is not in the catalog, so it cannot be updated from it.",
                error=True,
            )
            return
        if quill["id"] in self._picked:
            self._picked.discard(quill["id"])
        else:
            self._picked.add(quill["id"])
        self._draw_server()
        self.status(f"{plural(len(self._picked), 'Quill')} ticked for an update", note=True)

    def act_update_picked(self) -> None:
        if not self._picked:
            self.status("Nothing is ticked: space ticks a server Quill.", error=True)
            return
        self.update_many([q for q in self._server if q["id"] in self._picked])

    def act_update_all(self) -> None:
        wanted = [
            q
            for q in self._server
            if q["id"] in self._entries and standing_of(q, self._entries[q["id"]])[0] is not False
        ]
        if not wanted:
            self.status("Everything is up to date.", note=True)
            return
        self.update_many(wanted)

    @work(group="ui")
    async def update_many(self, quills: list[dict]) -> None:
        """Each installed again from the catalog, one after the other, for the same
        people, with a word on how each went."""
        names = [str(q.get("name") or q["id"]) for q in quills]
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Update {plural(len(quills), 'Quill')}?",
                detail=(
                    f"[b]{escape(', '.join(names))}[/]\n"
                    "[dim]Each is installed again from the catalog. Its tabs stay for the same "
                    "people; nothing anybody wrote is touched.[/]"
                ),
                confirm_label="Update",
            )
        )
        if not confirmed:
            return
        went: list[str] = []
        for quill in quills:
            name = str(quill.get("name") or quill["id"])
            self.status(f"Updating {name}…", note=True)
            try:
                done = await self.api.install_quill(id=quill["id"], audience=quill.get("audience"))
            except ApiError as exc:
                self.status(f"{name}: {exc}", error=True)
                went.append(f"{name} failed")
                continue
            if done.get("version") == quill.get("version"):
                went.append(f"{name} {quill.get('version', '')} installed again")
            else:
                went.append(f"{name} {quill.get('version', '')} → {done.get('version', '')}")
        self._picked.clear()
        self.status("; ".join(went) + ".")
        self._workspace_follows()
        self.reload()

    # -- the server's switch -------------------------------------------------------------
    def act_switch(self) -> None:
        quill = self.selected
        if quill is None or self._installed(quill["id"]) is None:
            self.status("That Quill is not installed.", error=True)
            return
        self.switch(self._installed(quill["id"]))

    @work(group="ui")
    async def switch(self, quill: dict) -> None:
        enabled = not (quill.get("enabled", True))
        try:
            feature = await self.api.set_feature(quill["id"], enabled)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        label = feature.get("label") or quill.get("name") or quill["id"]
        self.status(f"{label} is " + ("on." if feature.get("enabled") else "off — its tab is gone everywhere."))
        self._workspace_follows()
        self.reload()

    # -- installing, updating, reinstalling ---------------------------------------------
    def act_install(self) -> None:
        quill = self.selected
        if quill is None:
            self.status("Pick a Quill first.", error=True)
            return
        if quill["id"] not in self._entries:
            installed = self._installed(quill["id"])
            said = standing_of(installed or quill, None)[1]
            self.status(
                f"{quill.get('name') or quill['id']} is not in the catalog ({said}); install it again from there.",
                error=True,
            )
            return
        self.install(self._entries[quill["id"]], audience=(self._installed(quill["id"]) or {}).get("audience"))

    @work(group="ui")
    async def install(self, quill: dict, *, audience: dict | None = None) -> None:
        self.status(f"Asking the catalog about {quill.get('name') or quill['id']}…", note=True)
        try:
            plan = await self.api.plan_quill(id=quill["id"])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status("", note=True)
        circles: list[dict] = []
        if new_data(plan):
            try:
                circles = await self.api.circles()
            except ApiError:
                circles = []
        sheet = QuillSheet(plan, circles=circles)
        if not await self.app.push_screen_wait(sheet):
            return
        self.status(f"Installing {plan.get('name') or quill['id']}…", note=True)
        try:
            if audience is None:
                done = await self.api.install_quill(id=quill["id"])
            else:
                done = await self.api.install_quill(id=quill["id"], audience=audience)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        given = []
        try:
            for circle in sheet.chosen:
                for row in sheet.fresh:
                    await self.api.set_circle_rule(circle, row["id"], "write")
                given.append(circle)
        except ApiError as exc:
            self.status(f"Installed, but the circles were not all given it: {exc}", error=True)
            self._workspace_follows()
            self.reload()
            return
        self.status(
            f"Installed {done.get('name') or quill['id']} {done.get('version', '')}."
            + (f" Given to: {', '.join(given)}." if given else "")
        )
        self._workspace_follows()
        self.reload()

    # -- what its code is doing --------------------------------------
    def act_running(self) -> None:
        quill = self.selected
        if quill is None or self._installed(quill["id"]) is None:
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
        if quill is None or self._installed(quill["id"]) is None:
            self.status("That Quill is not installed.", error=True)
            return
        self.remove(quill)

    @work(group="ui")
    async def remove(self, quill: dict) -> None:
        name = quill.get("name") or quill["id"]
        try:
            brought = await self.api.quill_brought(quill["id"])
        except ApiError:
            brought = []
        drop: list[str] = []
        if brought:
            answer = await self.app.push_screen_wait(RemoveSheet(name, brought))
            if answer is None:
                return
            drop = answer
        else:
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
            gone = await self.api.uninstall_quill(quill["id"], drop=drop)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        dropped = sum(int(n) for n in ((gone or {}).get("dropped") or {}).values())
        programs = (gone or {}).get("runtimes") or []
        said = f"{dropped} records went with it." if dropped else "Its records are kept."
        if programs:
            said += f" {', '.join(programs)} went too."
        self.status(f"Removed {name}. {said}")
        self._workspace_follows()
        self.reload()

    # -- people's own Quills, and what they asked for ----------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        kind, _, rest = (event.button.id or "").partition("-")
        if kind not in ("approve", "asker", "decline", "promote", "pswitch"):
            return
        event.stop()
        self.answer(kind, rest)

    @work(group="ui")
    async def answer(self, kind: str, rest: str) -> None:
        everything = self._everything
        try:
            if kind == "approve":
                done = await self.api.approve_quill_request(int(rest))
                self.status(f"Installed {done.get('installed', '')} for everyone.")
            elif kind == "asker":
                who = next(r["username"] for r in everything["requests"] if r["id"] == int(rest))
                done = await self.api.approve_quill_request(int(rest), people=[who])
                self.status(f"Installed {done.get('installed', '')} for {who}.")
            elif kind == "decline":
                await self.api.decline_quill_request(int(rest))
                self.status("Declined.")
            elif kind == "pswitch":
                quill = (everything.get("personal") or [])[int(rest)]
                enabled = not quill.get("enabled", True)
                await self.api.set_feature(f"~{quill['owner']}.{quill['id']}", enabled)
                self.status(f"{quill['name']} is " + ("on again." if enabled else "off, for everybody who has it."))
            elif kind == "promote":
                quill = (everything.get("personal") or [])[int(rest)]
                owner, quill_id = quill["owner"], quill["id"]
                confirmed = await self.app.push_screen_wait(
                    ConfirmModal(
                        f"Promote {owner}'s {quill_id}?",
                        detail=(
                            "[dim]It becomes the server's, for everyone. Every record of its own datamodels — "
                            f"{owner}'s and those of the people it was shared with — moves with it.[/]"
                        ),
                        confirm_label="Promote",
                    )
                )
                if not confirmed:
                    return
                plan = await self.api.promote_quill(owner, quill_id)
                moved = sum(int(n) for n in (plan.get("moved") or {}).values())
                self.status(f"Promoted {plan.get('name') or quill_id}; {plural(moved, 'record')} moved.")
        except ApiError as exc:
            self.status(str(exc), error=True)
        self._workspace_follows()
        self.reload()

    def _workspace_follows(self) -> None:
        """The tabs behind this panel: fetched again, so they match."""
        again = getattr(self.screen, "ask_the_server", None)
        if callable(again):
            again()
