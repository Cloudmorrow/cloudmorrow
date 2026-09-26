"""`cloudmorrow-server` — run the API and manage users from the server shell."""

from __future__ import annotations

import base64
import getpass
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow import __version__
from cloudmorrow.console import TITLE
from cloudmorrow.console import console as make_console
from cloudmorrow.logo import banner
from cloudmorrow.server.cli_quill import app as quill_app
from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.db import (
    TYPE_HUMAN,
    InvalidUsernameError,
    UnknownUserError,
    UserExistsError,
    UserStore,
)
from cloudmorrow.server.maintenance import delete_orphans, find_orphans
from cloudmorrow.server.sealed import Sealer, key_for, rotate, use_key
from cloudmorrow.server.security import hash_password
from cloudmorrow.server.update import UpdateError, build_wheel, describe, find_source_dir
from cloudmorrow.server.update import update as do_update

app = typer.Typer(help="Cloudmorrow API server.", no_args_is_help=True)

# How long a shutdown waits for connections in flight before it stops waiting.
SHUTDOWN_GRACE_SECONDS = 10
user_app = typer.Typer(help="Manage Cloudmorrow users.", no_args_is_help=True)
app.add_typer(user_app, name="user")
app.add_typer(quill_app, name="quill")

console = make_console()

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Path to server.toml (default: search standard paths)."),
]


def _load(config_path: Path | None) -> ServerConfig:
    config = load_config(config_path)
    config.ensure_dirs()
    # Whatever this command touches is sealed under the service's key, not
    # one made up beside the database.
    use_key(config.db_path, config.secrets_key_path)
    return config


def _store(config: ServerConfig) -> UserStore:
    return UserStore(config.db_path)


def _plural(count: int, one: str, many: str = "") -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _prompt_password(username: str) -> str:
    password = getpass.getpass(f"Password for {username}: ")
    confirm = getpass.getpass("Repeat password: ")
    if password != confirm:
        console.print("[red]Passwords do not match.[/]")
        raise typer.Exit(code=1)
    return password


@app.command()
def serve(
    config_path: ConfigOption = None,
    host: Annotated[str | None, typer.Option(help="Bind address (overrides config).")] = None,
    port: Annotated[int | None, typer.Option(help="Bind port (overrides config).")] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes (dev only).")] = False,
) -> None:
    """Run the API server."""
    import uvicorn

    config = _load(config_path)
    config.ensure_secret_key()
    console.print(banner(subtitle="api server"))
    console.print(
        f"  notes dir : [cyan]{config.notes_dir}[/]\n"
        f"  data dir  : [cyan]{config.data_dir}[/]\n"
        f"  per-user  : [cyan]{config.per_user_dirs}[/]\n"
        f"  public url: [cyan]{config.public_url or 'derived from each request'}[/]\n"
        f"  config    : [cyan]{config.config_path or 'defaults + environment'}[/]\n"
    )
    if _store(config).count() == 0:
        console.print("[yellow]No users yet — create one with `cloudmorrow-server user create`.[/]\n")

    # timeout_graceful_shutdown: an API deploy restarts the server by stopping
    # it, and without this uvicorn would wait for every keep-alive connection to
    # close first — one idle TUI could hold the restart open indefinitely.
    if reload:
        uvicorn.run(
            "cloudmorrow.server.asgi:app",
            host=host or config.host,
            port=port or config.port,
            reload=True,
            timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
        )
    else:
        from cloudmorrow.server.app import create_app

        uvicorn.run(
            create_app(config),
            host=host or config.host,
            port=port or config.port,
            timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
        )


@app.command()
def config(config_path: ConfigOption = None) -> None:
    """Show the effective configuration."""
    cfg = _load(config_path)
    table = Table(title="cloudmorrow server config", title_style=TITLE)
    table.add_column("key", style="dim")
    table.add_column("value")
    for key in ("config_path", "name", "notes_dir", "data_dir", "per_user_dirs", "host",
                "port", "token_ttl_hours", "cors_origins", "public_url", "package_spec",
                "allow_api_update", "service_name"):
        table.add_row(key, str(getattr(cfg, key)))
    table.add_row("db_path", str(cfg.db_path))
    table.add_row("secret_key", "set" if cfg.secret_key else "generated on first run")
    console.print(table)


@app.command("init")
def init_cmd(config_path: ConfigOption = None) -> None:
    """Create directories, the database and the signing key."""
    cfg = _load(config_path)
    cfg.ensure_secret_key()
    _store(cfg)
    console.print(f"[green]Ready.[/] notes: {cfg.notes_dir}  data: {cfg.data_dir}")


@user_app.command("create")
def user_create(
    username: str,
    config_path: ConfigOption = None,
    display_name: Annotated[str, typer.Option(help="Human-readable name.")] = "",
    admin: Annotated[bool, typer.Option(help="Grant admin rights.")] = False,
    user_type: Annotated[
        str, typer.Option("--type", help="human, agent or systems_user.")
    ] = TYPE_HUMAN,
    password: Annotated[
        str | None, typer.Option(help="Password (prompted when omitted).")
    ] = None,
    password_stdin: Annotated[
        bool,
        typer.Option(
            "--password-stdin",
            help="Read the password from stdin, for a script: it never shows in `ps`.",
        ),
    ] = False,
) -> None:
    """Create a user. The first one on a server is its administrator."""
    cfg = _load(config_path)
    store = _store(cfg)
    if password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            console.print("[red]--password-stdin was given, but nothing came in on stdin.[/]")
            raise typer.Exit(code=1)
    password = password or _prompt_password(username)
    try:
        user = store.create(
            username,
            hash_password(password),
            display_name=display_name,
            is_admin=admin or store.count() == 0,
            user_type=user_type,
        )
    except UserExistsError:
        console.print(f"[red]User {username!r} already exists.[/]")
        raise typer.Exit(code=1) from None
    except (InvalidUsernameError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None
    notes = cfg.notes_root(user.username)
    notes.mkdir(parents=True, exist_ok=True)
    console.print(
        f"[green]Created[/] {user.username} ({user.role}, {user.user_type}) — notes: {notes}"
    )


@user_app.command("list")
def user_list(
    config_path: ConfigOption = None,
    count: Annotated[
        bool, typer.Option("--count", help="Print how many there are, and nothing else.")
    ] = False,
) -> None:
    """List users."""
    store = _store(_load(config_path))
    if count:
        # For a script deciding whether this server has anybody on it yet —
        # the installer, asking whether to make the first account.
        print(store.count())
        return
    table = Table(title="cloudmorrow users", title_style=TITLE)
    for column in ("username", "display name", "role", "type", "active", "system uid",
                   "created"):
        table.add_column(column)
    for user in store.list():
        table.add_row(
            user.username,
            user.display_name,
            user.role,
            user.user_type,
            "yes" if user.is_active else "no",
            "" if user.system_uid is None else str(user.system_uid),
            user.created_at,
        )
    console.print(table)


@user_app.command("passwd")
def user_passwd(
    username: str,
    config_path: ConfigOption = None,
    password: Annotated[str | None, typer.Option(help="New password.")] = None,
) -> None:
    """Set a user's password."""
    store = _store(_load(config_path))
    password = password or _prompt_password(username)
    try:
        store.update(username, password_hash=hash_password(password))
    except UnknownUserError:
        console.print(f"[red]No such user: {username}[/]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]Password updated for {username}.[/]")


@user_app.command("delete")
def user_delete(
    username: str,
    config_path: ConfigOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Delete a user (their notes directory is left untouched)."""
    store = _store(_load(config_path))
    if not yes:
        typer.confirm(f"Delete user {username}?", abort=True)
    try:
        store.delete(username)
    except UnknownUserError:
        console.print(f"[red]No such user: {username}[/]")
        raise typer.Exit(code=1) from None
    console.print(f"[green]Deleted {username}.[/] Their notes directory was left in place.")


@app.command("agent-install")
def agent_install(
    config_path: ConfigOption = None,
    name: Annotated[
        str | None, typer.Option(help="What to call this machine (default: its hostname).")
    ] = None,
    owner: Annotated[
        str | None, typer.Option(help="Whose agent it is (default: the first admin).")
    ] = None,
    url: Annotated[
        str | None, typer.Option(help="How the agent reaches the API (default: this server).")
    ] = None,
    agent_config: Annotated[
        Path, typer.Option("--agent-config", help="Where to write the agent's config.")
    ] = Path("/etc/cloudmorrow/agent.toml"),
    run_as: Annotated[
        str | None, typer.Option(help="The system user to run it as. Omit to skip the service.")
    ] = None,
    service: Annotated[bool, typer.Option(help="Install and start a systemd unit.")] = True,
) -> None:
    """Give the server itself an agent.

    Every other machine enrols by signing in, and nobody signs in on the
    server — so it enrols itself here, straight against its own database, and
    runs as the service account rather than as anybody.

    Run it again to rotate the token and rewrite the unit; nothing is
    duplicated.
    """
    import os
    import socket

    from cloudmorrow.server.agents import AgentStore, InvalidAgentNameError

    try:
        from cloudmorrow.agent import service as agent_service
        from cloudmorrow.agent.config import AgentConfig
    except ImportError as exc:
        # The server runs an agent of its own, so its venv needs what an agent
        # needs. A deployment from before that was true has only [server].
        console.print(
            f"[red]The agent's dependencies are not installed here[/] ({exc.name}).\n"
            "[dim]The server's venv needs both extras now that it runs an agent:[/]\n"
            "  pip install --editable '/path/to/checkout[server,agent]'\n"
            "[dim]`cloudmorrow update server --force` does that for you.[/]"
        )
        raise typer.Exit(code=1) from None

    cfg = _load(config_path)
    store = _store(cfg)
    if owner:
        try:
            account = store.require(owner)
        except UnknownUserError:
            console.print(f"[red]No such user: {owner}[/]")
            raise typer.Exit(code=1) from None
    else:
        admins = [user for user in store.list() if user.is_admin and user.is_active]
        if not admins:
            console.print(
                "[yellow]No admin account yet.[/] Create one with "
                "`cloudmorrow-server user create <name> --admin`, then run this again."
            )
            raise typer.Exit(code=1)
        account = admins[0]

    machine = name or socket.gethostname().split(".")[0].lower()
    reach = (url or cfg.public_url or f"http://{cfg.host}:{cfg.port}").rstrip("/")
    try:
        agent, token = AgentStore(cfg.db_path).enroll_for_user(
            account.username,
            name=machine,
            hostname=socket.gethostname(),
            platform=platform.platform(),
            version=__version__,
        )
    except InvalidAgentNameError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None

    agent_cfg = AgentConfig.load(agent_config)
    agent_cfg.server_url = reach
    agent_cfg.agent_token = token
    agent_cfg.name = agent.name
    # It is the server's agent, so what it may back up is the server's data —
    # not whatever home directory happened to run this command.
    agent_cfg.backup_roots = [str(cfg.data_dir), str(cfg.notes_dir)]
    agent_cfg.backup_dir = str(cfg.data_dir / "backups")
    written = agent_cfg.save(agent_config)
    if run_as and os.geteuid() == 0:
        shutil.chown(written, user=run_as)
    console.print(
        f"[green]Enrolled[/] [b]{agent.name}[/] as {account.username}'s agent "
        f"(agent {agent.id})\n[dim]config written to {written}, pointing at {reach}[/]"
    )

    if not service:
        console.print(f"[dim]no service asked for; run `{agent_service.agent_executable()} run`[/]")
        return
    if not run_as:
        console.print(
            "[yellow]No --run-as given[/], so no service was installed. "
            f"Run [b]{agent_service.agent_executable()} run[/] yourself, or pass "
            "--run-as with the user the server runs as."
        )
        return
    result = agent_service.install_system(run_as=run_as, config_path=written)
    if result.installed:
        console.print(f"[green]Started[/] {result.path} [dim](as {run_as})[/]")
    else:
        console.print(f"[yellow]Wrote {result.path}, but could not start it:[/] {result.detail}")


@app.command()
def update(
    source: Annotated[
        Path | None, typer.Option(help="The git checkout (default: where this is installed from).")
    ] = None,
    config_path: ConfigOption = None,
    branch: Annotated[str | None, typer.Option(help="Branch to follow (default: current).")] = None,
    service: Annotated[str, typer.Option(help="systemd unit to restart.")] = "cloudmorrow",
    restart: Annotated[bool, typer.Option(help="Restart the service after updating.")] = True,
    reinstall: Annotated[bool, typer.Option(help="Reinstall in case dependencies moved.")] = True,
    force: Annotated[
        bool, typer.Option(help="Update even with local changes or nothing new.")
    ] = False,
    exit_status: Annotated[
        bool,
        typer.Option(
            help="Exit 3 when there was nothing to pull, so a caller can skip restarting."
        ),
    ] = False,
) -> None:
    """Pull the latest code from git and restart the server."""
    try:
        result = do_update(
            source=source,
            branch=branch,
            service=service,
            restart=restart,
            reinstall=reinstall,
            force=force,
        )
    except UpdateError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from None

    console.print(f"[dim]{result.source}  on  {result.branch}[/]")
    if result.rewound:
        # Not a warning: it is the normal shape of a force-push or a rollback.
        # It is said out loud because the one other thing it can mean — somebody
        # committed on the server — should never pass unnoticed.
        console.print(
            f"[yellow]Rewound[/] onto origin/{result.branch}, discarding "
            f"{result.discarded} commit{'s' if result.discarded != 1 else ''} "
            f"the remote does not have."
        )
    where = f"v{result.new_version}" if result.new_version else result.new_commit[:8]
    if not result.changed:
        console.print(
            f"[green]Already up to date.[/] [b]{where}[/]  "
            + describe(result.source, result.new_commit)
        )
        if not force:
            # Exit 3 lets cloudmorrow-update skip a pointless service restart.
            raise typer.Exit(code=3 if exit_status else 0)
    else:
        came_from = f"v{result.old_version}" if result.old_version else result.old_commit[:8]
        went_to = where
        if came_from == went_to:
            # Two commits the versions cannot tell apart — a rewind onto as
            # many commits as it discarded. Their commits can tell them apart.
            came_from, went_to = result.old_commit[:8], result.new_commit[:8]
        console.print(
            f"[green]Updated[/] {came_from} → [b]{went_to}[/]"
            f"  [dim]({result.changed_files} files)[/]\n"
            f"  {describe(result.source, result.new_commit)}"
        )
    if result.reinstalled:
        console.print("[dim]reinstalled the package[/]")
    if result.changed or force:
        try:
            published = build_wheel(result.source, load_config(config_path).dist_dir)
            console.print(f"[dim]published {published.name} for clients[/]")
        except (UpdateError, OSError) as exc:
            console.print(f"[yellow]could not publish a client wheel:[/] {exc}")
    if result.restarted:
        console.print(f"[green]Restarted[/] {service}")
    elif result.changed and not restart:
        # --no-restart is what cloudmorrow-update passes before restarting the
        # service itself, so this is a note, not a warning.
        console.print("[dim]not restarted, as asked[/]")


@app.command()
def prune(
    config_path: ConfigOption = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Actually delete it. Without this, it only looks.")
    ] = False,
) -> None:
    """Find what an older layout left behind, and optionally delete it.

    The empty per-project note directories from when notes were kept inside
    projects. Notes themselves are never deleted: the layout migration moves
    them into the owner's tree first.
    """
    config = _load(config_path)
    orphans = find_orphans(config)
    if orphans.empty:
        typer.echo("Nothing orphaned.")
        return
    for directory in orphans.directories:
        typer.echo(f"  dir      {directory}")
    summary = _plural(len(orphans.directories), "leftover directory", "leftover directories")
    if not yes:
        typer.echo(f"\n{summary}. Nothing deleted — pass --yes to delete it.")
        return
    delete_orphans(config, orphans)
    typer.echo(f"\nDeleted {summary}.")


@app.command()
def publish(
    wheel: Annotated[
        Path | None,
        typer.Argument(help="A built .whl. Omit to build one from this server's checkout."),
    ] = None,
    config_path: ConfigOption = None,
    source: Annotated[Path | None, typer.Option(help="The git checkout to build from.")] = None,
) -> None:
    """Serve the client from this server, so machines need no route to PyPI.

    With no argument it builds a wheel from the deployed checkout, which is
    what `cloudmorrow-server update` does after every pull.
    """
    cfg = _load(config_path)
    if wheel is None:
        try:
            target = build_wheel(find_source_dir(source), cfg.dist_dir)
        except UpdateError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from None
    else:
        if wheel.suffix != ".whl" or not wheel.is_file():
            console.print(f"[red]Not a wheel: {wheel}[/]")
            raise typer.Exit(code=1)
        cfg.dist_dir.mkdir(parents=True, exist_ok=True)
        target = cfg.dist_dir / wheel.name
        shutil.copy2(wheel, target)
    console.print(
        f"[green]Published[/] {target.name}\n"
        f"[dim]install.sh now installs it from {cfg.public_url or '<public_url>'}"
        f"/dist/{target.name}[/]"
    )


@app.command("rotate-key")
def rotate_key(
    config_path: ConfigOption = None,
    yes: Annotated[bool, typer.Option("--yes", help="Do it without asking.")] = False,
) -> None:
    """Seal everything again under a fresh key. Stop the service first.

    Every sealed row and every note is opened with the key in place and
    sealed with a new one, which then replaces it; the old key is kept
    beside it as `<key>.old` until you delete it. Nothing may write to the
    database or the notes while this runs, so `systemctl stop cloudmorrow`
    before and `start` after.
    """
    console = make_console()
    config = _load(config_path)
    key_path = config.secrets_key_path
    if not yes:
        console.print(
            f"This reseals the database and every note under a new key at {key_path}."
        )
        console.print("The service must be stopped. Continue? [y/N] ", end="")
        if input().strip().lower() not in {"y", "yes"}:
            raise typer.Exit(code=1)
    old = Sealer(key_for(config.db_path))
    new = Sealer(os.urandom(32))
    roots = [config.notes_root(user.username) for user in _store(config).list()]
    counts = rotate(config.db_path, roots, old, new)
    backup = key_path.with_name(key_path.name + ".old")
    os.replace(key_path, backup)
    handle = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(base64.urlsafe_b64encode(new.master).decode("ascii") + "\n")
    console.print(
        f"Resealed {_plural(counts['rows'], 'row')} and {_plural(counts['files'], 'file')}."
        f" The old key is at {backup}; delete it once you have started the service and"
        " seen it open things."
    )


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"cloudmorrow-server {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
