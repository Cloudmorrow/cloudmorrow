"""`cloudmorrow uninstall`: take Cloudmorrow off this machine.

The reverse of install.sh and `login`, in the reverse order: this machine's
agent is struck off the server, its service stopped and removed, then the
config and the token, the backups it made, the commands on the PATH, and
last of all the venv the command itself is running from. Nothing on the
server is touched beyond this machine's own agent record — the notes, the
secrets and the notes are the server's, and an uninstall is not a
delete.

It says what it is about to remove and asks first, unless told `--yes`.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from platformdirs import user_data_dir

from cloudmorrow.agent import service
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.config import default_config_path as agent_config_path
from cloudmorrow.cli import dev
from cloudmorrow.cli.common import client, console
from cloudmorrow.client.config import APP_NAME, config_dir, credentials_path
from cloudmorrow.desktop import launcher
from cloudmorrow.links import COMMANDS


def data_dir() -> Path:
    """Where install.sh put the venv, and where the agent keeps its backups."""
    return Path(user_data_dir(APP_NAME))


def install_prefix() -> Path | None:
    """The directory install.sh made — the venv's parent — or None.

    None from a development checkout, which is somebody's working copy and
    not ours to delete, and None from anywhere that does not look exactly
    like what install.sh makes: a venv called `venv` inside a directory
    called `cloudmorrow`, with this package in it. This is the one path the
    command deletes wholesale, so it is matched, not guessed — `sys.prefix`
    rather than the interpreter's real location, because in a venv the
    interpreter is a symlink to the system's, and the system's is /usr.
    """
    if dev.checkout():
        return None
    venv = Path(sys.prefix)
    if venv == Path(sys.base_prefix) or venv.name != "venv" or not (venv / "pyvenv.cfg").is_file():
        return None
    prefix = venv.parent
    if prefix.name != APP_NAME or prefix.parent == prefix:
        return None
    if not any(venv.glob("lib*/python*/site-packages/cloudmorrow")):
        return None
    return prefix


def bin_dirs() -> list[Path]:
    """Where the commands were linked: install.sh's two choices, and the PATH."""
    dirs = [Path.home() / ".local" / "bin", Path("/usr/local/bin")]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            dirs.append(Path(entry))
    seen: list[Path] = []
    for directory in dirs:
        if directory not in seen:
            seen.append(directory)
    return seen


@dataclass(slots=True)
class Plan:
    """What an uninstall would remove, gathered before anything is touched."""

    agent_name: str = ""  # struck off the server, when signed in
    service: bool = False  # the user service (launchd or systemd --user)
    system_unit: Path | None = None  # a root-installed unit: needs sudo, only reported
    config: Path | None = None
    backups: Path | None = None
    links: list[Path] = field(default_factory=list)
    launcher: list[Path] = field(default_factory=list)  # the desktop app in the menu
    prefix: Path | None = None  # the venv and whatever else install.sh put beside it
    checkout: Path | None = None  # running from source: the venv is left alone
    elsewhere: str = ""  # installed some other way: where, and left alone

    def lines(self) -> list[str]:
        out = []
        if self.agent_name:
            out.append(f"the agent [b]{self.agent_name}[/] on the server")
        if self.service:
            out.append("the agent service on this machine")
        if self.config:
            out.append(f"{self.config}  [dim](config and token)[/]")
        if self.backups:
            out.append(f"{self.backups}  [dim](backups the agent made)[/]")
        for link in self.links:
            out.append(str(link))
        for path in self.launcher:
            out.append(f"{path}  [dim](the desktop app's launcher)[/]")
        if self.prefix:
            out.append(f"{self.prefix}  [dim](the venv)[/]")
        return out


def plan(*, keep_backups: bool = False) -> Plan:
    found = Plan()
    agent_path = agent_config_path()
    if agent_path.exists() and credentials_path().exists():
        try:
            found.agent_name = AgentConfig.load(agent_path).name
        except (OSError, ValueError):
            found.agent_name = ""
    found.service = service.is_installed()
    system_unit = service.SYSTEM_UNIT_DIR / service.UNIT_NAME
    if system_unit.exists():
        found.system_unit = system_unit

    if config_dir().exists():
        found.config = config_dir()

    prefix = install_prefix()
    found.prefix = prefix if prefix and prefix.exists() else None
    if prefix is None:
        found.checkout = dev.checkout()
        if found.checkout is None:
            found.elsewhere = sys.prefix

    if not keep_backups:
        backups = data_dir() / "backups"
        try:
            if agent_path.exists():
                backups = Path(AgentConfig.load(agent_path).backup_dir)
        except (OSError, ValueError):
            pass
        # Inside the prefix it goes with the prefix; elsewhere it is its own line.
        if backups.exists() and not (found.prefix and backups.is_relative_to(found.prefix)):
            found.backups = backups

    for directory in bin_dirs():
        for name in COMMANDS:
            link = directory / name
            if not link.is_symlink():
                continue
            target = link.resolve()
            if (found.prefix and target.is_relative_to(found.prefix)) or (
                found.checkout and target.is_relative_to(found.checkout)
            ):
                if link not in found.links:
                    found.links.append(link)
    found.launcher = launcher.installed()
    return found


async def forget_on_server(name: str) -> str:
    """Strike this machine's agent off the server. Returns a note, "" when done."""
    try:
        _config, api = client()
    except Exception as exc:  # no stored session, or a config that cannot be read
        return f"not signed in ({exc}); the agent record stays on the server"
    try:
        for agent in await api.agents():
            if agent.get("name") == name:
                await api.delete_agent(agent["id"])
                return ""
        return "no agent by that name on the server"
    except Exception as exc:
        return f"could not reach the server ({exc}); the agent record stays"
    finally:
        await api.aclose()


def remove(found: Plan, *, forget=forget_on_server) -> list[str]:
    """Carry the plan out. Returns the notes worth reading afterwards."""
    import asyncio

    notes: list[str] = []
    if found.agent_name:
        note = asyncio.run(forget(found.agent_name))
        if note:
            notes.append(note)
    if found.service:
        try:
            service.uninstall()
        except OSError as exc:
            notes.append(f"the agent service could not be removed: {exc}")
    if found.system_unit:
        notes.append(
            f"{found.system_unit} was installed as root and is left: "
            f"`sudo systemctl disable --now {service.UNIT_NAME}` and remove the file"
        )
    for path in (found.config, found.backups):
        if path and path.exists():
            shutil.rmtree(path, ignore_errors=True)
    for link in found.links:
        try:
            link.unlink()
        except OSError as exc:
            notes.append(f"{link} could not be removed: {exc}")
    if found.launcher:
        try:
            launcher.remove()
        except OSError as exc:
            notes.append(f"the desktop app's launcher could not be removed: {exc}")
    if found.checkout:
        notes.append(f"running from {found.checkout}, which is left as it is")
    if found.elsewhere:
        notes.append(
            f"this copy was not installed by install.sh ({found.elsewhere}); "
            "remove it the way it was installed — `pipx uninstall cloudmorrow`, or pip"
        )
    # Last, because it is the code running this. On Linux and macOS an open
    # file lives on until it is closed, so the interpreter finishes fine.
    if found.prefix and found.prefix.exists():
        shutil.rmtree(found.prefix, ignore_errors=True)
        if found.prefix.exists():
            notes.append(f"{found.prefix} could not be removed entirely; delete what is left")
    return notes


def uninstall(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask first.")] = False,
    keep_backups: Annotated[
        bool, typer.Option("--keep-backups", help="Leave the backups the agent made.")
    ] = False,
) -> None:
    """Remove Cloudmorrow from this machine: the agent, the config, the command.

    Nothing on the server is deleted except this machine's own agent record.
    """
    found = plan(keep_backups=keep_backups)
    lines = found.lines()
    if not lines:
        console.print("[dim]Nothing of Cloudmorrow's on this machine.[/]")
        return
    console.print("This removes:")
    for line in lines:
        console.print(f"  [red]-[/] {line}")
    if found.checkout:
        console.print(f"  [dim]and leaves {found.checkout}, which this runs from[/]")
    if not yes and not typer.confirm("Go ahead?", default=False):
        raise typer.Exit(code=1)
    notes = remove(found)
    for note in notes:
        console.print(f"[yellow]note:[/] {note}")
    console.print("[green]Cloudmorrow is gone from this machine.[/]")
    # The venv this ran from is gone; leave before anything wants it again.
    sys.stdout.flush()
    sys.stderr.flush()
    if found.prefix:
        os._exit(0)
