"""`cloudmorrow-server quill` — the quills on this server, from its own shell.

    cloudmorrow-server quill standard          # what a new cloud is offered
    cloudmorrow-server quill choose --ask      # the installer's question
    cloudmorrow-server quill choose --only notes,tasks
    cloudmorrow-server quill list
    cloudmorrow-server quill add fleet
    cloudmorrow-server quill remove fleet

Run as the service user, with the service stopped or before it first
starts: a running server reads what is installed when it boots and when it
installs something itself, so a quill added from here behind its back
appears at its next restart. `cm quill add` goes through the running server
and needs no restart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.console import TITLE
from cloudmorrow.console import console as make_console
from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.quills import QuillError, QuillRegistry
from cloudmorrow.server.sealed import use_key
from cloudmorrow.server.standard import choices, choose, chosen_already

app = typer.Typer(help="Quills on this server.", no_args_is_help=True)
console = make_console()

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to server.toml (default: search standard paths)."),
]


def _config(path: Path | None) -> ServerConfig:
    config = load_config(path)
    config.ensure_dirs()
    use_key(config.db_path, config.secrets_key_path)
    return config


def _registry(config: ServerConfig) -> QuillRegistry:
    return QuillRegistry(config.quills_dir, config.datamodels_dir, config.quill_catalog)


@app.command("standard")
def standard(config_path: ConfigOption = None) -> None:
    """The standard quills a new cloud is offered."""
    options, _, problem = choices(_config(config_path))
    table = Table(title="standard quills", title_style=TITLE)
    for column in ("id", "name", "what it is", ""):
        table.add_column(column)
    for option in options:
        table.add_row(option.id, option.name, option.summary, "built in" if option.kind == "built-in" else "")
    console.print(table)
    if problem:
        console.print(f"[yellow]The catalog could not be read, so only the built-in ones are here: {problem}[/]")


def _ask(options: list) -> set[str]:
    """The question, on the terminal: every one of them, unless you say otherwise."""
    tty = open("/dev/tty", "r+", encoding="utf-8")  # noqa: SIM115 - held for the question
    try:
        tty.write("\n  Which standard quills should your cloud have? All of them, unless you say.\n\n")
        width = max(len(o.name) for o in options)
        for number, option in enumerate(options, 1):
            tty.write(f"    {number}  {option.name:<{width}}  {option.summary}\n")
        while True:
            tty.write("\n\033[1mNumbers to leave out, or Enter for all\033[0m: ")
            tty.flush()
            answer = tty.readline().replace(",", " ").split()
            try:
                out = {int(a) for a in answer}
            except ValueError:
                tty.write("Numbers only, like: 3 5\n")
                continue
            if any(n < 1 or n > len(options) for n in out):
                tty.write(f"Between 1 and {len(options)}, please.\n")
                continue
            return {o.id for n, o in enumerate(options, 1) if n not in out}
    finally:
        tty.close()


@app.command("choose")
def choose_cmd(
    only: Annotated[str, typer.Option("--only", help="Comma-separated ids to have; `all` for every one.")] = "",
    ask: Annotated[bool, typer.Option("--ask", help="Ask on the terminal.")] = False,
    once: Annotated[bool, typer.Option("--once", help="Do nothing if a choice was made before.")] = False,
    config_path: ConfigOption = None,
) -> None:
    """Choose the standard quills: install the ones from the catalog, switch off built-ins left out."""
    config = _config(config_path)
    if once and chosen_already(config):
        console.print("[dim]The standard quills were chosen before; nothing to do.[/]")
        return
    options, _, problem = choices(config)
    if problem:
        console.print(f"[yellow]The Quill Catalog could not be read ({problem}); only built-in quills are offered.[/]")
    if only:
        wanted = {o.id for o in options} if only.strip() == "all" else {w.strip() for w in only.split(",") if w.strip()}
    elif ask:
        wanted = _ask(options)
    else:
        wanted = {o.id for o in options}
    try:
        done = choose(config, wanted)
    except QuillError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    names = {o.id: o.name for o in options}
    if done["installed"]:
        console.print("installed: " + ", ".join(names[i] for i in done["installed"]))
    if done["off"]:
        console.print("switched off: " + ", ".join(names[i] for i in done["off"]) + " [dim](on again from Administration)[/]")
    kept = [names[o.id] for o in options if o.id in wanted]
    console.print("[green]Your cloud has:[/] " + (", ".join(kept) or "none of them"))


@app.command("list")
def list_cmd(config_path: ConfigOption = None) -> None:
    """The quills installed here."""
    registry = _registry(_config(config_path))
    table = Table(title="quills", title_style=TITLE)
    for column in ("id", "name", "version"):
        table.add_column(column)
    for quill in sorted(registry.quills.values(), key=lambda q: q.id):
        table.add_row(quill.id, quill.name, quill.version)
    console.print(table)
    for quill_id, problem in registry.broken.items():
        console.print(f"[red]{quill_id}: {problem}[/]")


@app.command("add")
def add(quill_id: Annotated[str, typer.Argument(help="Its id in the Quill Catalog.")], config_path: ConfigOption = None) -> None:
    """Install a quill from the catalog. Restart the service afterwards if it is running."""
    try:
        plan = _registry(_config(config_path)).install_from_catalog(quill_id)
    except QuillError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]Installed[/] {plan['name']} {plan['version']}")


@app.command("remove")
def remove(quill_id: Annotated[str, typer.Argument(help="The quill's id.")], config_path: ConfigOption = None) -> None:
    """Remove a quill. Its records stay."""
    try:
        _registry(_config(config_path)).uninstall(quill_id)
    except QuillError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]Removed[/] {quill_id}; its records are kept")
