"""`cloudmorrow secret` — your keys and passwords, encrypted, in vaults.

A secret lives in a vault and an environment. Both have a default, so the
common case is bare:

    cloudmorrow secret list
    cloudmorrow secret get OPENAI_API_KEY
    cloudmorrow secret set OPENAI_API_KEY

`-v home` picks a vault, `-e production` an environment, and
`cloudmorrow config set vault home` makes one the default.

Values are never passed as arguments — an argument is visible in `ps` and lands
in your shell history. `set` prompts without echo, or reads stdin when it is
handed something.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow import dotenv
from cloudmorrow.cli.common import (
    STDIO,
    EnvOption,
    VaultOption,
    client,
    console,
    emit,
    environment_for,
    fail,
    guard_overwrite,
    in_vault,
    out,
    plural,
    read_input,
    run,
    stdin_is_a_terminal,
    vault_for,
    warn_if_tracked,
    where,
    write_private,
)
from cloudmorrow.console import TITLE

app = typer.Typer(
    help="Secrets: encrypted keys and passwords, in vaults.",
    no_args_is_help=True,
)


def print_import(result: dict) -> None:
    """The same summary whether something was imported or only rehearsed."""
    rows = (
        ("added", "green", result["added"]),
        ("updated", "cyan", result["updated"]),
        ("removed", "red", result["removed"]),
        ("unchanged", "dim", result["unchanged"]),
        ("kept", "yellow", result["skipped"]),
    )
    for name, colour, keys in rows:
        if keys:
            console.print(
                f"    [{colour}]{name:<9}[/] {len(keys):>3}  [dim]{', '.join(keys)}[/]"
            )
    if not any(keys for _, _, keys in rows):
        console.print("    [dim]nothing to do[/]")


def _mask(secret: dict) -> str:
    return "•" * min(secret.get("length", 0), 12) or "[dim]empty[/]"


async def _hint_other_environments(api, chosen: str, vault: str) -> None:
    """When an environment is empty, say which ones are not."""
    others = [
        environment
        for environment in await api.secret_environments()
        if environment["environment"] != chosen
    ]
    if not others:
        return
    listed = ", ".join(
        f"{environment['environment']} ({environment['secrets']})" for environment in others
    )
    console.print(f"[dim]Other environments in {vault}: {listed}[/]")


@app.command("list")
def list_secrets(
    vault: VaultOption = None,
    environment: EnvOption = None,
    every: Annotated[
        bool, typer.Option("--all", "-a", help="Every environment, not just one.")
    ] = False,
    reveal: Annotated[
        bool, typer.Option("--reveal", help="Print the values. They go to your terminal.")
    ] = False,
    plain: Annotated[
        bool, typer.Option("--plain", help="One key per line, for scripts.")
    ] = False,
) -> None:
    """List the keys in an environment. Values stay hidden unless you ask."""

    async def _list() -> None:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        try:
            secrets = await api.secrets(None if every else chosen, reveal=reveal)
            if not secrets:
                if plain:
                    return
                console.print(
                    f"[dim]No secrets in {where(chosen_vault, None if every else chosen)}.[/]"
                )
                if not every:
                    await _hint_other_environments(api, chosen, chosen_vault)
                return
        finally:
            await api.aclose()
        if plain:
            emit("".join(f"{secret['key']}\n" for secret in secrets))
            return
        title = f"secrets · {where(chosen_vault, None if every else chosen)}"
        table = Table(title=title, title_style=TITLE)
        if every:
            table.add_column("environment")
        table.add_column("key")
        table.add_column("value", overflow="fold")
        table.add_column("len", justify="right", style="dim")
        table.add_column("updated", style="dim")
        for secret in secrets:
            row = [secret["environment"]] if every else []
            row += [
                secret["key"],
                secret["value"] if reveal else _mask(secret),
                str(secret["length"]),
                secret["updated_at"].replace("T", " ")[:16],
            ]
            table.add_row(*row)
        out.print(table)

    run(_list())


@app.command("get")
def get(
    key: Annotated[str, typer.Argument(help="The variable name.")],
    vault: VaultOption = None,
    environment: EnvOption = None,
) -> None:
    """Print one value, and nothing else — for `$(cloudmorrow secret get KEY)`."""

    async def _get() -> None:
        config, api, _ = in_vault(vault)
        chosen = environment_for(config, environment)
        try:
            secret = await api.read_secret(key, chosen)
        finally:
            await api.aclose()
        # Raw stdout, with a newline a shell will strip: `$( )` eats it, and a
        # redirect to a file gets the tidy trailing newline a file should have.
        emit((secret["value"] or "") + "\n")

    run(_get())


@app.command("set")
def set_secret(
    key: Annotated[str, typer.Argument(help="The variable name.")],
    vault: VaultOption = None,
    environment: EnvOption = None,
) -> None:
    """Store one secret, read from a prompt or from stdin.

    The value is never an argument: it would show up in `ps` and in your shell
    history. Typed at a terminal it is prompted for without echo; piped or
    redirected in, it is taken exactly as given, minus one trailing newline.
    """
    if stdin_is_a_terminal():
        value = getpass.getpass(f"Value for {key}: ")
    else:
        value = sys.stdin.read()
        # `printf '%s\n' "$V" |` and `< file` both add the newline back.
        value = value[:-1] if value.endswith("\n") else value

    async def _set() -> None:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        try:
            secret = await api.write_secret(key, value, chosen)
        finally:
            await api.aclose()
        console.print(
            f"[green]Set[/] {secret['key']} [dim]in {where(chosen_vault, chosen)} "
            f"({plural(secret['length'], 'byte')})[/]"
        )

    run(_set())


@app.command("remove")
def remove(
    keys: Annotated[list[str], typer.Argument(help="One or more variable names.")],
    vault: VaultOption = None,
    environment: EnvOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Delete secrets from an environment."""

    async def _remove() -> None:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        place = where(chosen_vault, chosen)
        if not yes:
            typer.confirm(f"Delete {', '.join(keys)} from {place}?", abort=True)
        try:
            for key in keys:
                await api.delete_secret(key, chosen)
                console.print(f"[green]Deleted[/] {key} [dim]from {place}[/]")
        finally:
            await api.aclose()

    run(_remove())


@app.command("import")
def import_secrets(
    file: Annotated[
        Path, typer.Option("--file", "-f", help="The .env file to read, or '-' for stdin.")
    ],
    vault: VaultOption = None,
    environment: EnvOption = None,
    prune: Annotated[
        bool, typer.Option("--prune", help="Delete keys the file does not mention.")
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite/--no-overwrite", help="Replace values that already exist."),
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would change, and write nothing.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Import one .env file into an environment."""
    try:
        entries = dotenv.parse(read_input(file))
    except dotenv.DotenvError as exc:
        fail(f"{file}: {exc}")
    if not entries:
        fail(f"{file} holds no assignments")
    if prune and not (yes or dry_run):
        typer.confirm(f"--prune deletes every key not in {file}. Continue?", abort=True)

    async def _import() -> None:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        try:
            result = await api.import_secrets(
                entries, chosen, prune=prune, overwrite=overwrite, dry_run=dry_run
            )
        finally:
            await api.aclose()
        console.print(
            f"[dim]{'would import' if dry_run else 'imported'} "
            f"{plural(len(entries), 'key')} from {file} into[/] "
            f"[b]{where(chosen_vault, chosen)}[/]"
        )
        print_import(result)

    run(_import())


@app.command("export")
def export(
    file: Annotated[
        Path, typer.Option("--file", "-f", help="File to write, or '-' for stdout.")
    ] = Path(STDIO),
    vault: VaultOption = None,
    environment: EnvOption = None,
    fmt: Annotated[str, typer.Option("--format", help="env, shell or json.")] = "env",
    force: Annotated[bool, typer.Option("--force", help="Overwrite the file.")] = False,
) -> None:
    """Write an environment out as a .env file."""
    if fmt not in {"env", "shell", "json"}:
        fail(f"unknown format: {fmt} (env, shell or json)")
    if str(file) != STDIO:
        guard_overwrite(file, force)

    async def _export() -> None:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        place = where(chosen_vault, chosen)
        try:
            entries = await api.export_secrets(chosen)
        finally:
            await api.aclose()
        if not entries:
            fail(f"no secrets in {place}")
        if fmt == "json":
            rendered = json.dumps(entries, indent=2) + "\n"
        elif fmt == "shell":
            rendered = "".join(
                f"export {key}={dotenv.quote(value)}\n" for key, value in entries.items()
            )
        else:
            rendered = dotenv.dump(
                entries,
                header=f"{place}\nWritten by cloudmorrow. Keep it out of version control.",
            )
        if str(file) == STDIO:
            emit(rendered)
            return
        write_private(file, rendered)
        console.print(
            f"[green]Wrote[/] {plural(len(entries), 'secret')} to {file} "
            f"[dim]from {place}, mode 600[/]"
        )
        warn_if_tracked(file)

    run(_export())


@app.command("vaults")
def vaults() -> None:
    """List your vaults: the ones that hold something."""

    async def _vaults() -> None:
        config, api = client()
        try:
            found = await api.secret_vaults()
        finally:
            await api.aclose()
        if not found:
            console.print("[dim]No secrets yet. `cloudmorrow secret set KEY` makes the first.[/]")
            return
        current = vault_for(config, None)
        table = Table(title="vaults", title_style=TITLE)
        table.add_column("", width=1)
        table.add_column("vault")
        table.add_column("secrets", justify="right")
        table.add_column("environments", justify="right")
        table.add_column("updated", style="dim")
        for vault in found:
            table.add_row(
                "▸" if vault["vault"] == current else "",
                vault["vault"],
                str(vault["secrets"]),
                str(vault["environments"]),
                vault["updated_at"].replace("T", " ")[:16],
            )
        out.print(table)

    run(_vaults())


@app.command("environments")
def environments(vault: VaultOption = None) -> None:
    """List the environments that hold something, in a vault."""

    async def _environments() -> None:
        config, api, chosen_vault = in_vault(vault)
        try:
            found = await api.secret_environments()
        finally:
            await api.aclose()
        if not found:
            console.print(f"[dim]No secrets yet in {chosen_vault}.[/]")
            return
        current = environment_for(config, None)
        table = Table(title=f"environments · {chosen_vault}", title_style=TITLE)
        table.add_column("", width=1)
        table.add_column("environment")
        table.add_column("secrets", justify="right")
        table.add_column("updated", style="dim")
        for environment in found:
            table.add_row(
                "▸" if environment["environment"] == current else "",
                environment["environment"],
                str(environment["secrets"]),
                environment["updated_at"].replace("T", " ")[:16],
            )
        out.print(table)

    run(_environments())


@app.command("purge")
def purge(
    vault: VaultOption = None,
    environment: EnvOption = None,
    whole_vault: Annotated[
        bool, typer.Option("--vault-and-all", help="The whole vault, every environment of it.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Delete every secret in one environment, or in a whole vault."""

    async def _purge() -> None:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        place = chosen_vault if whole_vault else where(chosen_vault, chosen)
        if not yes:
            typer.confirm(f"Delete every secret in {place}?", abort=True)
        try:
            if whole_vault:
                result = await api.delete_vault(chosen_vault)
            else:
                result = await api.delete_environment(chosen)
        finally:
            await api.aclose()
        console.print(
            f"[green]Deleted[/] {plural(result['removed'], 'secret')} [dim]from {place}[/]"
        )

    run(_purge())


@app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_with(
    ctx: typer.Context, vault: VaultOption = None, environment: EnvOption = None
) -> None:
    """Run a command with an environment's secrets in its environment.

    `cloudmorrow secret run -e production -- npm start`. Nothing is written to
    disk: the values only ever exist in the child process.
    """
    command = list(ctx.args)
    if not command:
        fail("nothing to run — try `cloudmorrow secret run -e production -- npm start`")

    async def _load() -> dict[str, str]:
        config, api, chosen_vault = in_vault(vault)
        chosen = environment_for(config, environment)
        place = where(chosen_vault, chosen)
        try:
            entries = await api.export_secrets(chosen)
        finally:
            await api.aclose()
        if entries:
            console.print(f"[dim]{plural(len(entries), 'secret')} from {place} → {command[0]}[/]")
        else:
            console.print(f"[yellow]![/] [dim]no secrets in {place} — running anyway[/]")
        return entries

    entries = run(_load())
    try:
        completed = subprocess.run(command, env={**os.environ, **entries})
    except OSError as exc:
        fail(f"cannot run {command[0]}: {exc}")
    raise typer.Exit(code=completed.returncode)


# Short forms for the two that get typed most.
app.command("rm", hidden=True)(remove)
app.command("envs", hidden=True)(environments)
