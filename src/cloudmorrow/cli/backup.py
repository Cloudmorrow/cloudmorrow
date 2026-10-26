"""`cloudmorrow backup` — the server's copies in a bucket, and restoring from one.

What Administration, Backups does in the browser, from a computer, for an
administrator. The settings themselves — the bucket and its keys — are set
in the browser, where the secret is typed once and kept sealed; from here
you watch, run one, look at what is in the bucket, and put it back.

    cloudmorrow backup status
    cloudmorrow backup now [--part database --part drives]
    cloudmorrow backup list
    cloudmorrow backup show 20261023T030000Z
    cloudmorrow backup restore 20261023T030000Z --all
    cloudmorrow backup restore 20261023T030000Z --drive bram --share Photos
    cloudmorrow backup restore 20261023T030000Z --path drives/bram/Notes/plan.md
    cloudmorrow backup files 20261023T030000Z drives/bram Notes
    cloudmorrow backup get 20261023T030000Z drives/bram/Notes/plan.md -o plan.md
    cloudmorrow backup delete 20261023T030000Z

Every backup is a complete picture of its day, and every file in it is
there as it was that day: `files` looks, `get` pulls one out, `restore
--path` puts one back where it was.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import client, console, fail, plural, run
from cloudmorrow.console import TITLE

app = typer.Typer(help="Backups: everything on the server into a bucket, and back.", no_args_is_help=True)

StampArg = Annotated[str, typer.Argument(help="The backup, by its stamp: 20261023T030000Z.")]
# The clock asks the server every two seconds while something runs.
POLL = 2.0


def size_of(count: int) -> str:
    size = float(count or 0)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{count} B"


def _said_settings(settings: dict) -> str:
    if not settings.get("configured"):
        return "[yellow]Not set up:[/] say where backups go under Administration, Backups, in the browser."
    where = f"{settings['endpoint']} · bucket [b]{settings['bucket']}[/]"
    if settings.get("prefix"):
        where += f" · folder {settings['prefix']}"
    when = (
        f"every day at {settings['time']}, kept {plural(settings['keep_days'], 'day')}"
        if settings.get("enabled")
        else "[yellow]switched off[/] — only when asked"
    )
    return f"{where}\n{when} · {', '.join(settings.get('parts') or [])}" + (
        " · with the sealing key" if settings.get("seal_key") else ""
    )


def _said_last(label: str, last: dict | None) -> str:
    if not last:
        return f"{label}: none yet"
    verdict = "[green]ok[/]" if last.get("ok") else f"[red]failed[/] — {last.get('error', '')}"
    when = last.get("finished_at") or last.get("started_at") or ""
    size = f", {size_of(last['size'])}" if last.get("size") else ""
    if last.get("added") is not None and last.get("size"):
        size += f", {size_of(last['added'])} new"
    return f"{label}: {last.get('stamp', '')} {verdict} ({when}{size})"


@app.command("status")
def status() -> None:
    """Where backups go, whether one runs, and how the last went."""

    async def _status() -> None:
        _, api = client()
        async with api:
            told = await api.backup_status()
        console.print(_said_settings(told["settings"]))
        if told.get("running"):
            console.print(f"[yellow]{told['running'].capitalize()} running[/]: {told.get('step') or '…'}")
        console.print(_said_last("Last backup", told.get("last")))
        console.print(_said_last("Last restore", told.get("last_restore")))
        store = told.get("store") or {}
        if store.get("objects"):
            console.print(f"The bucket holds {size_of(store.get('bytes', 0))} in {plural(store['objects'], 'object')}")

    run(_status())


async def _watch(api, what: str) -> dict:
    """Print the lines as they come until the run is over; answer the status."""
    seen = 0
    while True:
        told = await api.backup_status()
        for line in told.get("lines", [])[seen:]:
            console.print(f"  {line}")
        seen = len(told.get("lines", []))
        if told.get("running") != what:
            return told
        await asyncio.sleep(POLL)


@app.command("now")
def now(
    parts: Annotated[
        list[str] | None,
        typer.Option(
            "--part", help="A part to back up: database, drives, shares, quills, keys. Every chosen one unless said."
        ),
    ] = None,
    wait: Annotated[bool, typer.Option(help="Watch it until it is done.")] = True,
) -> None:
    """Back up now, to the bucket the settings name."""

    async def _now() -> None:
        _, api = client()
        async with api:
            await api.run_backup(parts)
            console.print(f"[{TITLE}]Backing up…[/]")
            if not wait:
                return
            told = await _watch(api, "backup")
            last = told.get("last") or {}
            if not last.get("ok"):
                fail(f"the backup failed: {last.get('error', 'no word why')}")
            console.print(
                f"[green]Done:[/] {last.get('stamp')} · {size_of(last.get('size', 0))}"
                + (f", {size_of(last['added'])} new" if last.get("added") is not None else "")
            )

    run(_now())


@app.command("list")
def list_backups() -> None:
    """Every finished backup in the bucket, newest first."""

    async def _list() -> None:
        _, api = client()
        async with api:
            found = await api.backups()
        if not found:
            console.print("No backups in the bucket.")
            return
        table = Table(title=plural(len(found), "backup"), header_style=TITLE)
        table.add_column("Stamp")
        table.add_column("Made")
        table.add_column("Size", justify="right")
        table.add_column("New", justify="right")
        table.add_column("Parts")
        table.add_column("Key")
        for b in found:
            what = ", ".join(b.get("parts") or [])
            if b.get("drives"):
                what += f" ({plural(b['drives'], 'drive')}"
                what += f", {plural(b['shares'], 'share')})" if b.get("shares") else ")"
            table.add_row(
                b["stamp"],
                (b.get("made_at") or "")[:16].replace("T", " "),
                size_of(b.get("size", 0)),
                size_of(b.get("added", 0)) if b.get("format", 1) >= 2 else "all",
                what,
                "[green]this server's[/]" if b.get("key_matches") else "[yellow]another[/]",
            )
        console.print(table)

    run(_list())


@app.command("show")
def show(stamp: StampArg) -> None:
    """What one backup holds, part by part."""

    async def _show() -> None:
        _, api = client()
        async with api:
            told = await api.backup(stamp)
        made = f"{told.get('made_at', '')} · {told.get('cloud', '')} v{told.get('version', '')}"
        console.print(f"[{TITLE}]{told['stamp']}[/] · {made}")
        console.print(
            "Sealed with "
            + (
                "[green]this server's key[/]"
                if told.get("key_matches")
                else "[yellow]another key[/] than this server's"
            )
        )
        new = lambda part: f", {size_of(part['added'])} new" if part.get("added") is not None else ""  # noqa: E731
        if told.get("database"):
            console.print(
                f"  database ({told['database']['engine']}): {size_of(told['database']['size'])}{new(told['database'])}"
            )
        for d in told.get("drives") or []:
            console.print(f"  drive {d['name']}: {size_of(d['size'])}, {plural(d.get('files', 0), 'file')}{new(d)}")
        for s in told.get("shares") or []:
            console.print(f"  share {s['name']}: {size_of(s['size'])}, {plural(s.get('files', 0), 'file')}{new(s)}")
        if told.get("quills"):
            console.print(
                f"  quills: {size_of(told['quills']['size'])}, {plural(told['quills'].get('files', 0), 'file')}"
            )
        if told.get("keys"):
            console.print(f"  keys: {', '.join(told['keys'].get('files') or [])}")
        console.print(
            f"{size_of(told.get('size', 0))} in all"
            + (f", {size_of(told['added'])} new" if told.get("added") is not None else "")
            + f", in {told.get('took', 0)} s"
        )
        if told.get("cloudmorrow_backup", 1) < 2:
            console.print("[dim]From before the store: whole drives only, nothing to browse.[/]")

    run(_show())


@app.command("files")
def files(
    stamp: StampArg,
    where: Annotated[str, typer.Argument(help="drives/<name> or shares/<name>.")],
    path: Annotated[str, typer.Argument(help="A folder in it; nothing for its top.")] = "",
) -> None:
    """What a backup holds under one folder of a drive or a share."""

    async def _files() -> None:
        _, api = client()
        async with api:
            told = await api.backup_files(stamp, where, path)
        head = f"{told['where']}/{told['path']}" if told.get("path") else told["where"]
        console.print(f"[{TITLE}]{stamp}[/] · {head}")
        for folder in told.get("folders") or []:
            inside = f"{plural(folder.get('files', 0), 'file')}, {size_of(folder.get('size', 0))}"
            console.print(f"  {folder['name']}/  [dim]{inside}[/]")
        for file in told.get("files") or []:
            when = (file.get("modified") or "")[:16].replace("T", " ")
            console.print(f"  {file['name']}  [dim]{size_of(file.get('size', 0))} · {when}[/]")
        if not told.get("folders") and not told.get("files"):
            console.print("  [dim]empty[/]")

    run(_files())


@app.command("get")
def get(
    stamp: StampArg,
    path: Annotated[str, typer.Argument(help="drives/<name>/<path> or shares/<name>/<path>.")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Where to write it; the file's own name here.")
    ] = None,
) -> None:
    """Pull one file out of a backup, as it was that day, onto this computer."""

    async def _get() -> None:
        _, api = client()
        async with api:
            data = await api.backup_file(stamp, path)
        target = out or Path(path.rstrip("/").rsplit("/", 1)[-1])
        if target.is_dir():
            target = target / path.rstrip("/").rsplit("/", 1)[-1]
        target.write_bytes(data)
        console.print(f"[green]Wrote[/] {target} ({size_of(len(data))})")

    run(_get())


@app.command("restore")
def restore(
    stamp: StampArg,
    everything: Annotated[bool, typer.Option("--all", help="Every part the backup has.")] = False,
    database: Annotated[bool, typer.Option("--database", help="The database.")] = False,
    drives: Annotated[
        list[str] | None, typer.Option("--drive", help="One person's files, by drive name. Repeatable.")
    ] = None,
    all_drives: Annotated[bool, typer.Option("--drives", help="Everybody's files.")] = False,
    shares: Annotated[list[str] | None, typer.Option("--share", help="One share, by name. Repeatable.")] = None,
    all_shares: Annotated[bool, typer.Option("--shares", help="Every share.")] = False,
    paths: Annotated[
        list[str] | None,
        typer.Option("--path", help="One file or folder: drives/<name>/<path> or shares/<name>/<path>. Repeatable."),
    ] = None,
    quills: Annotated[bool, typer.Option("--quills", help="The installed Quills, datamodels and runtimes.")] = False,
    keys: Annotated[bool, typer.Option("--keys", help="The server's keys.")] = False,
    restart: Annotated[
        bool, typer.Option(help="Restart the server afterwards, when what was restored asks for it.")
    ] = True,
    force: Annotated[
        bool, typer.Option("--force", help="Restore the database although it was sealed with another key.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False,
) -> None:
    """Put a backup back, all of it or the parts named, over what the server has now."""

    async def _restore() -> None:
        _, api = client()
        async with api:
            told = await api.backup(stamp)
            choice = {
                "database": everything or database,
                "drives": [d["name"] for d in told.get("drives") or []]
                if everything or all_drives
                else list(drives or []),
                "shares": [s["name"] for s in told.get("shares") or []]
                if everything or all_shares
                else list(shares or []),
                "paths": list(paths or []),
                "quills": (everything or quills) and bool(told.get("quills")),
                "keys": (everything or keys) and bool(told.get("keys")),
                "restart": restart,
                "force": force,
            }
            if everything and not told.get("database"):
                choice["database"] = False
            if not (
                choice["database"]
                or choice["drives"]
                or choice["shares"]
                or choice["paths"]
                or choice["quills"]
                or choice["keys"]
            ):
                fail(
                    "say what to restore: --all, --database, --drive NAME, --drives, "
                    "--share NAME, --shares, --path drives/NAME/PATH, --quills, --keys"
                )
            said = []
            if choice["database"]:
                said.append("the database")
            if choice["drives"]:
                said.append(f"the files of {', '.join(choice['drives'])}")
            if choice["shares"]:
                said.append(f"the shares {', '.join(choice['shares'])}")
            if choice["paths"]:
                said.append(", ".join(choice["paths"]))
            if choice["quills"]:
                said.append("the Quills")
            if choice["keys"]:
                said.append("the keys")
            console.print(f"From {stamp} ({told.get('made_at', '')}): " + "; ".join(said))
            if not yes and not typer.confirm("Restore over what the server has now?", default=False):
                raise typer.Exit(code=1)
            await api.restore_backup(stamp, **choice)
            console.print(f"[{TITLE}]Restoring…[/]")
            result = await _watch(api, "restore")
            last = result.get("last_restore") or {}
            if not last.get("ok"):
                fail(f"the restore failed: {last.get('error', 'no word why')}")
            if last.get("restarting"):
                console.print("[green]Restored.[/] The server is restarting onto it.")
            elif last.get("restart_blocked"):
                console.print(f"[green]Restored.[/] [yellow]Not restarted:[/] {last['restart_blocked']}")
            else:
                console.print("[green]Restored.[/]")

    run(_restore())


@app.command("delete")
def delete(stamp: StampArg, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False) -> None:
    """Take one backup out of the bucket."""
    if not yes and not typer.confirm(f"Delete the backup {stamp} from the bucket?", default=False):
        raise typer.Exit(code=1)

    async def _delete() -> None:
        _, api = client()
        async with api:
            await api.delete_backup(stamp)
        console.print(f"Deleted {stamp}")

    run(_delete())
