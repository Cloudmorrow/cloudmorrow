"""`cloudmorrow quill` — make a Quill, check it, try it, and add Quills from the catalog.

The loop for building one, which is the same loop an assistant runs:

    cm quill new plants            # a folder to start from, with a CLAUDE.md
    cm quill check                 # the manifest against the datamodels, and a preview
    cm quill dev                   # on your own server, on every device, now

And for running a server:

    cm quill catalog               # what there is, by category
    cm quill add fleet             # what it adds, a yes, and it is installed
    cm quill list                  # what is installed
    cm quill remove fleet          # its screens go; its records stay
    cm quill services              # what Quills' code is doing, as whom
    cm quill logs fleet [service]  # the last lines of a service's log

`check` needs no server: it reads the foundational datamodels from the
catalog (or `--datamodels`, a folder) and checks the Quill against them the
way a server would at install.
"""

from __future__ import annotations

import io
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from cloudmorrow.cli.common import client, console, fail, out, run
from cloudmorrow.console import TITLE
from cloudmorrow.quill_reference import quill_reference

app = typer.Typer(
    help="Quills: make one, check it, try it; add them from the catalog.", no_args_is_help=True
)

TEMPLATE = Path(__file__).resolve().parent.parent / "quill_template"
# Stored without their dots, so the package keeps them; restored on copy.
DOTTED = {"gitignore": ".gitignore", "github": ".github", "gitkeep": ".gitkeep"}

FolderArgument = Annotated[Path, typer.Argument(help="The Quill's folder.")]


# -- new ---------------------------------------------------------------------------
@app.command("new")
def new(
    quill_id: Annotated[str, typer.Argument(help="Its id: lowercase letters, digits and _.")],
    name: Annotated[str, typer.Option("--name", help="What people call it.")] = "",
    summary: Annotated[str, typer.Option("--summary", help="One line on what it is for.")] = "",
    into: Annotated[
        Path | None, typer.Option("--dir", help="Where to make it. ./quill-<id>.")
    ] = None,
) -> None:
    """Start a Quill: a folder with a manifest, a datamodel, a CLAUDE.md and a check."""
    if not re.match(r"^[a-z][a-z0-9_]{1,31}$", quill_id):
        fail("an id is 2 to 32 lowercase letters, digits and _, starting with a letter")
    target = into or Path(f"quill-{quill_id}")
    if target.exists() and any(target.iterdir()):
        fail(f"{target} is not empty")
    values = {
        "id": quill_id,
        "name": name or quill_id.replace("_", " ").capitalize(),
        "summary": summary or f"What {quill_id.replace('_', ' ')} is for, in one line.",
    }
    for source in sorted(TEMPLATE.rglob("*")):
        if source.is_dir() or source.name == "CLAUDE.md.head" or "__pycache__" in source.parts:
            continue
        parts = [DOTTED.get(part, part) for part in source.relative_to(TEMPLATE).parts]
        dest = target.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        dest.write_text(text, encoding="utf-8")
    (target / "CLAUDE.md").write_text(
        (TEMPLATE / "CLAUDE.md.head").read_text(encoding="utf-8") + quill_reference(),
        encoding="utf-8",
    )
    console.print(f"[green]Made[/] {target}/ — next: [b]cd {target} && cm quill check[/]")


@app.command("reference")
def reference() -> None:
    """Print the reference for writing a Quill: the manifest, the kit, the datamodels."""
    out.print(quill_reference(), markup=False, highlight=False)


# -- check -------------------------------------------------------------------------
def _datamodels_folder(given: Path | None, tmp: Path) -> Path | None:
    from cloudmorrow.server.config import DEFAULT_QUILL_CATALOG
    from cloudmorrow.server.quills import QuillError, fetch, load_catalog

    if given is not None:
        if not given.is_dir():
            fail(f"{given} is not a folder")
        return given
    try:
        catalog = load_catalog(DEFAULT_QUILL_CATALOG)
        if not catalog.datamodels.get("repo"):
            return None
        return fetch(
            str(catalog.datamodels["repo"]), str(catalog.datamodels.get("ref", "")), into=tmp
        )
    except QuillError as exc:
        fail(
            f"could not read the foundational datamodels ({exc}); point --datamodels at a checkout of them"
        )


def preview(plan: dict) -> str:
    """What each screen will draw, in text: enough to see a binding is the one you meant."""
    lines: list[str] = []
    for screen in plan["screens"]:
        model = plan["models"].get(screen["model"], {})
        fields = {f["name"]: f for f in model.get("fields", [])}
        title = screen.get("title") or model.get("title", "")
        lines.append(
            f"── {screen['label'] or screen['id']} ({screen['kit']} of {screen['model']}) ──"
        )
        if screen["kit"] == "board":
            lane = fields.get(screen["lane"], {})
            labels = lane.get("labels") or lane.get("values") or []
            if screen.get("group"):
                target = fields[screen["group"]]["to"]
                lines.append(f"  [ {target} ▾ ] [ {target} ] [ + New {target} ]")
            width = 18
            lines.append("  " + " ".join(f"{label:<{width}}" for label in labels))
            card = f"◯ <{title}>"[:width]
            lines.append("  " + " ".join(f"{card:<{width}}" for _ in labels))
            if screen.get("body"):
                lines.append(f"  cards show progress of `- [ ]` lines in {screen['body']}")
            if screen.get("done"):
                lines.append(f"  the circle moves a card to {screen['done']}, and back")
        elif screen["kit"] == "grid":
            target = fields.get(screen.get("group", ""), {}).get("to", "group")
            about = f"   <{screen['group_subtitle']}>" if screen.get("group_subtitle") else ""
            lines.append(f"  first the {target}s: <{target}>{about}")
            lines.append(f"  then its folders (<{screen.get('folder')}>), and the rest as a list or tiles:")
            lines.append(f"  ▰ <{title}>/   ▣ <{title}>   ▣ <{title}>")
            lines.append("  put in, get, new folder, rename, move, delete; a picture shown")
            lines.append("")
            continue
        elif screen["kit"] == "list":
            for level in ("group", "subgroup"):
                if screen.get(level):
                    name = screen[level]
                    lines.append(f"  [ <{name}> ] [ <{name}> ] [ + New {name} ]")
            tick = "◯ " if screen.get("tick") else ""
            sub = ""
            if screen.get("subtitle"):
                hidden = fields.get(screen["subtitle"], {}).get("secret")
                sub = "   •••••••• (revealed on asking)" if hidden else f"   <{screen['subtitle']}>"
            for _ in range(2):
                lines.append(f"  {tick}<{title}>{sub}")
        elif screen["kit"] == "calendar":
            space = fields.get(screen.get("space", ""), {}).get("to", "space")
            lines.append(f"  [ every {space} you can see ]   < month >   Mo Tu We Th Fr Sa Su")
            lines.append(f"  a dot per {screen['model']} on each day from {screen['starts']} to {screen['ends']}")
            whole = f", whole days when {screen['all_day']}" if screen.get("all_day") else ""
            lines.append(f"  the day: <{screen['starts']}>  <{title}>  <{space}>{whole}")
        elif screen["kit"] == "editor":
            tree = f"▾ <folders of {screen['path']}>" if screen.get("path") else f"· <{title}>"
            lines.append(f"  {tree:<28}│ # <{title}>")
            page = f"· <{title}>"
            lines.append(f"    {page:<26}│ <{screen.get('body')}, in Markdown>")
            lines.append("  pictures go in when the datamodel keeps attachments")
            lines.append("  opening one: the page, beside the tree")
            lines.append("")
            continue
        elif screen["kit"] == "thread":
            space = fields.get(screen.get("space", ""), {}).get("to", "space")
            about = f" — <{screen['about']}>" if screen.get("about") else ""
            lines.append(f"  # <{space}> (unread)   │ # <{space}>{about}")
            lines.append(f"  # <{space}>            │ <who>  <when>")
            lines.append(f"                        │   <{screen.get('body', title)}>")
            lines.append(f"                        │ [ write in <{space}>… ]")
            made = ", ".join(screen.get("made_as") or {}) or "shared"
            lines.append(f"  a new {space} is made as: {made}")
        else:
            shown = screen.get("fields") or list(fields)
            lines.append("  " + ", ".join(shown))
        editable = [name for name, f in fields.items() if not f.get("stamp")]
        if screen.get("fields"):
            editable = [name for name in screen["fields"] if name in fields]
        lines.append(f"  opening one: a sheet with {', '.join(editable)}")
        lines.append("")
    return "\n".join(lines)


def _plan_offline(folder: Path, datamodels: Path | None) -> dict:
    """The install sheet, from a registry of nothing: what a fresh server would say."""
    from cloudmorrow.server.quills import QuillError, QuillRegistry

    with tempfile.TemporaryDirectory(prefix="quill-check-") as tmp:
        registry = QuillRegistry(Path(tmp) / "quills", Path(tmp) / "datamodels")
        try:
            return registry.plan(folder, datamodels)
        except QuillError as exc:
            fail(f"✗ {exc}")


def print_plan(plan: dict) -> None:
    head = f"[b]{escape(plan['name'])}[/] {plan['version']} — {escape(plan['summary'] or '')}"
    if plan.get("installed_version"):
        head += f" [dim](installed: {plan['installed_version']})[/]"
    console.print(head)
    table = Table(title="what it adds", title_style=TITLE, show_header=True)
    table.add_column("")
    table.add_column("what")
    table.add_column("", style="dim")
    for row in plan["data"]:
        what = f"{row['how']} {row['id']}"
        if row.get("fields"):
            what += f" ({', '.join(row['fields'])})"
        note = "new here" if row["new"] else ""
        if row.get("why"):
            note = f"{row['access']}: {row['why']}"
        table.add_row("datamodel", escape(what), escape(note))
    for screen in plan["screens"]:
        table.add_row(
            "screen",
            escape(f"{screen['label'] or screen['id']} ({screen['kit']})"),
            "on " + ", ".join(plan["surfaces"]),
        )
    for job in plan["jobs"]:
        table.add_row("job", escape(job["id"]), escape(f"{job['action']} {job.get('model', '')}"))
    for dataset in plan["datasets"]:
        table.add_row(
            "dataset",
            escape(dataset["id"]),
            f"{dataset['count']} {dataset['model']} ({dataset['seed']})",
        )
    for service in plan["services"]:
        always = ", kept running" if service.get("always") else ""
        table.add_row(
            "service", escape(service["id"]), escape(" ".join(service["command"]) + always)
        )
    for hook in plan["webhooks"]:
        what = f"→ {hook['model']}" if hook.get("model") else f"→ {hook.get('forward')}"
        table.add_row("webhook", escape(hook["id"]), escape(f"POST /hooks/{plan['id']}/{hook['path']} {what}"))
    for api in plan["apis"]:
        table.add_row("api", escape(api["id"]), escape(f"/api/q/{plan['id']}/… → {api['service']}"))
    console.print(table)
    if plan.get("runs_code") or plan["webhooks"]:
        who = plan.get("runs_as") or "the administrator who installs it"
        reach = ", ".join(plan.get("reach") or []) or "nothing"
        if plan.get("runs_code"):
            console.print(f"[yellow]Runs code on this server:[/] {escape('; '.join(plan['runs_code']))}")
        console.print(f"[yellow]It runs as {escape(who)}, and can read and write only:[/] {escape(reach)}")


@app.command("check")
def check(
    folder: FolderArgument = Path("."),
    datamodels: Annotated[
        Path | None, typer.Option("--datamodels", help="A checkout of the foundational datamodels.")
    ] = None,
) -> None:
    """Check a Quill as a server would, and preview its screens. Needs no server."""
    folder = folder.resolve()
    with tempfile.TemporaryDirectory(prefix="quill-models-") as tmp:
        plan = _plan_offline(folder, _datamodels_folder(datamodels, Path(tmp)))
    print_plan(plan)
    out.print(preview(plan), markup=False, highlight=False)
    console.print("[green]✓ it checks out[/] — next: [b]cm quill dev[/] to try it on your server")


# -- on a server -------------------------------------------------------------------
def _tarball(folder: Path) -> bytes:
    buffer = io.BytesIO()
    skip = {".git", "__pycache__", ".venv", "node_modules"}
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(
            folder,
            arcname=folder.name,
            filter=lambda info: None if skip & set(Path(info.name).parts) else info,
        )
    return buffer.getvalue()


@app.command("dev")
def dev(folder: FolderArgument = Path(".")) -> None:
    """Install this folder on your server as a development Quill. Run again after a change."""
    folder = folder.resolve()
    if not (folder / "quill.toml").is_file():
        fail(f"there is no quill.toml in {folder}")

    async def _dev() -> None:
        _, api = client()
        try:
            plan = await api.upload_quill(_tarball(folder))
        finally:
            await api.aclose()
        console.print(
            f"[green]Installed[/] {plan['name']} {plan['version']} — it is in `cm`, the web app and on the phone now"
        )

    run(_dev())


@app.command("list")
def list_installed() -> None:
    """The Quills on your server."""

    async def _list() -> None:
        _, api = client()
        try:
            quills = await api.quills()
        finally:
            await api.aclose()
        if not quills:
            console.print("[dim]No Quills installed. `cm quill catalog` has some.[/]")
            return
        table = Table(title="quills", title_style=TITLE)
        for column in ("id", "name", "version", "from", "on"):
            table.add_column(column)
        for quill in quills:
            origin = quill.get("origin", {})
            source = (
                "dev"
                if origin.get("dev")
                else ("catalog" if origin.get("catalog") else origin.get("repo", ""))
            )
            table.add_row(
                quill["id"],
                escape(quill["name"]),
                quill["version"],
                escape(source),
                "yes" if quill.get("enabled", True) else "[dim]off[/]",
            )
        out.print(table)

    run(_list())


@app.command("services")
def services() -> None:
    """What every Quill's code is doing on your server: its services, jobs and webhooks (admin)."""

    async def _services() -> None:
        _, api = client()
        try:
            rows = await api.quill_services()
        finally:
            await api.aclose()
        if not rows:
            console.print("[dim]No Quill here runs code of its own.[/]")
            return
        table = Table(title="quill services", title_style=TITLE)
        for column in ("quill", "what", "state", "since", "last exit", "as"):
            table.add_column(column)
        colour = {"running": "green", "restarting": "yellow", "stopped": "dim"}
        for row in rows:
            who = row.get("runs_as") or "[red]nobody[/]"
            for service in row["services"]:
                state = "by its job" if service.get("scheduled") else service["state"]
                exit_ = "" if service.get("last_exit") is None else str(service["last_exit"])
                table.add_row(
                    row["id"], escape(f"service {service['id']}"),
                    f"[{colour.get(state, 'dim')}]{state}[/]", service.get("since", ""),
                    exit_, who,
                )
            for job in row["jobs"]:
                exit_ = "" if job.get("last_exit") is None else str(job["last_exit"])
                table.add_row(
                    row["id"], escape(f"job {job['id']} (every {job['every']})"),
                    "[green]running[/]" if job.get("running") else "",
                    job.get("last_started") or "never yet", exit_, who,
                )
        out.print(table)
        # Whole, outside the table, so they can be copied: what a sender is given.
        for row in rows:
            for hook in row["webhooks"]:
                out.print(
                    f"webhook {row['id']}/{hook['id']}: {hook['url']}?token={hook['secret']}",
                    markup=False, highlight=False, soft_wrap=True,
                )

    run(_services())


@app.command("logs")
def logs(
    quill_id: Annotated[str, typer.Argument(help="The Quill's id.")],
    service: Annotated[str, typer.Argument(help="One of its services; all of them if left out.")] = "",
    lines: Annotated[int, typer.Option("--lines", "-n", help="How many of the last lines.")] = 100,
) -> None:
    """The last lines of a Quill's service logs (admin)."""

    async def _logs() -> None:
        _, api = client()
        try:
            found = await api.quill_logs(quill_id, service, lines)
        finally:
            await api.aclose()
        for name, text in found.items():
            if len(found) > 1:
                console.print(f"[b]── {escape(name)} ──[/]")
            out.print("\n".join(text) or "(nothing yet)", markup=False, highlight=False)

    run(_logs())


@app.command("catalog")
def catalog() -> None:
    """What the Quill Catalog has, by category, with what you have installed."""

    async def _catalog() -> None:
        _, api = client()
        try:
            found = await api.quill_catalog()
        finally:
            await api.aclose()
        labels = {c["id"]: c["label"] for c in found["categories"]}
        table = Table(title="the quill catalog", title_style=TITLE)
        for column in ("category", "id", "name", "summary", "installed"):
            table.add_column(column)
        for entry in sorted(found["quills"], key=lambda e: (e.get("category", ""), e["id"])):
            table.add_row(
                labels.get(entry.get("category", ""), entry.get("category", "")),
                entry["id"],
                escape(entry.get("name", "")),
                escape(entry.get("summary", "")),
                entry.get("installed_version") or "",
            )
        out.print(table)

    run(_catalog())


@app.command("add")
def add(
    quill_id: Annotated[str, typer.Argument(help="The Quill's id in the catalog.")] = "",
    source: Annotated[
        str, typer.Option("--source", help="Instead: a repository or a folder on the server.")
    ] = "",
    ref: Annotated[str, typer.Option("--ref", help="The release of --source, e.g. v1.0.0.")] = "",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False,
) -> None:
    """Install a Quill: shows what it adds, and asks first."""
    if bool(quill_id) == bool(source):
        fail("name a Quill from the catalog, or give --source")

    async def _add() -> None:
        _, api = client()
        try:
            plan = await api.plan_quill(id=quill_id, source=source, ref=ref)
            print_plan(plan)
            if not yes and not typer.confirm("Install it?", default=True):
                console.print("[dim]Nothing installed.[/]")
                return
            await api.install_quill(id=quill_id, source=source, ref=ref)
        finally:
            await api.aclose()
        console.print(f"[green]Installed[/] {plan['name']} {plan['version']}")

    run(_add())


@app.command("remove")
def remove(
    quill_id: Annotated[str, typer.Argument(help="The Quill's id.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False,
) -> None:
    """Remove a Quill. Its screens and jobs go; the records stay, because they are yours."""
    if not yes and not typer.confirm(f"Remove {quill_id}? Its records are kept.", default=False):
        return

    async def _remove() -> None:
        _, api = client()
        try:
            await api.uninstall_quill(quill_id)
        finally:
            await api.aclose()
        console.print(f"[green]Removed[/] {quill_id}")

    run(_remove())
