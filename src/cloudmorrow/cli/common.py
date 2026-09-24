"""What every `cloudmorrow` command needs: a client, a scope, and a way to fail.

Commands are `cloudmorrow RESOURCE ACTION`, and they share one shape: sign
in, do one thing, print what happened. Data goes to stdout so it can be
piped; everything else goes to stderr so it does not end up in the pipe.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Awaitable
from pathlib import Path
from typing import Annotated, Any, NoReturn, TypeVar

import typer

from cloudmorrow.client.api import ApiError, CloudmorrowClient, client_from_credentials
from cloudmorrow.client.config import ClientConfig, StoredCredentials
from cloudmorrow.console import console as make_console
from cloudmorrow.dotenv import DEFAULT_ENVIRONMENT, DEFAULT_VAULT

T = TypeVar("T")

# Status and tables: stderr, so `cloudmorrow secret get KEY > file` gets the value
# and nothing else. Anything a script would want is written to stdout by hand.
#
# highlight=False: rich otherwise colours numbers, paths and quoted words on
# its own initiative, which lands on top of the styling here and makes a dim
# aside come out as three colours. Everything on this console is coloured
# because something chose to colour it.
console = make_console(stderr=True, highlight=False)
# For the rare table that is the answer rather than a comment on it.
out = make_console()

STDIO = "-"

VaultOption = Annotated[
    str | None,
    typer.Option(
        "--vault",
        "-v",
        help=f"Which vault: {DEFAULT_VAULT} unless the config says otherwise.",
        show_default=False,
    ),
]

EnvOption = Annotated[
    str | None,
    typer.Option(
        "--environment",
        "-e",
        help=f"Environment: {DEFAULT_ENVIRONMENT}, development, staging, production…",
        show_default=False,
    ),
]


def fail(message: str) -> NoReturn:
    console.print(f"[red]{message}[/]")
    raise typer.Exit(code=1)


def run(coro: Awaitable[T]) -> T:
    """Run one command's coroutine, turning an API error into a clean exit."""
    try:
        return asyncio.run(coro)
    except ApiError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None


def client() -> tuple[ClientConfig, CloudmorrowClient]:
    """A client for the signed-in user, in the vault the config names."""
    config = ClientConfig.load()
    return config, client_from_credentials(config, StoredCredentials.load())


def in_vault(override: str | None) -> tuple[ClientConfig, CloudmorrowClient, str]:
    """A client pointed at the vault this command is about, and its name."""
    config, api = client()
    vault = vault_for(config, override)
    api.vault = vault
    return config, api, vault


def vault_for(config: ClientConfig, requested: str | None) -> str:
    return (requested or config.vault or DEFAULT_VAULT).strip().lower()


def environment_for(config: ClientConfig, requested: str | None) -> str:
    return (requested or config.environment or DEFAULT_ENVIRONMENT).strip().lower()


def where(vault: str, environment: str | None = None) -> str:
    """How a place is written in a message: `home · production`."""
    return f"{vault} · {environment}" if environment else vault


def read_input(path: Path) -> str:
    """Read a file, or stdin when the path is `-`."""
    if str(path) == STDIO:
        return sys.stdin.read()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")


def guard_overwrite(path: Path, force: bool) -> None:
    if path.exists() and not force:
        fail(f"{path} already exists — pass --force to overwrite it")


def write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read, private from the moment it exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(text)
    # A file that already existed keeps its old mode through O_CREAT.
    os.chmod(path, 0o600)


def would_commit(path: Path) -> bool:
    """Whether writing here puts secrets somewhere git is willing to commit."""

    def git(*args: str) -> int:
        try:
            return subprocess.run(
                ["git", *args], cwd=str(path.parent), capture_output=True, timeout=15
            ).returncode
        except (OSError, subprocess.SubprocessError):
            return 1

    if git("rev-parse", "--is-inside-work-tree") != 0:
        return False
    return git("check-ignore", "-q", path.name) != 0


def warn_if_tracked(path: Path) -> None:
    """Say something if a file of secrets just landed somewhere git would commit."""
    if would_commit(path):
        console.print(
            f"[yellow]![/] [dim]{path.name} is not in .gitignore — and this is a git repo.[/]"
        )


def edit_text(initial: str = "", *, suffix: str = ".md") -> str:
    """Open $EDITOR on some text and hand back what was saved."""
    editor = os.environ.get("CLOUDMORROW_EDITOR") or os.environ.get("EDITOR") or "vi"
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=suffix, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(initial)
        temporary = Path(handle.name)
    try:
        completed = subprocess.run([*editor.split(), str(temporary)])
        if completed.returncode != 0:
            fail(f"{editor} exited with {completed.returncode} — nothing was saved")
        return temporary.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot run {editor}: {exc}")
    finally:
        temporary.unlink(missing_ok=True)


def stdin_is_a_terminal() -> bool:
    try:
        return sys.stdin.isatty()
    except ValueError:  # stdin was closed
        return False


def emit(text: str) -> None:
    """Write an answer to stdout, exactly as it is."""
    sys.stdout.write(text)


def plural(count: int, noun: str, suffix: str = "s") -> str:
    return f"{count} {noun}{'' if count == 1 else suffix}"


def shorten(value: Any, width: int = 48) -> str:
    text = str(value)
    return text if len(text) <= width else text[: width - 1] + "…"
