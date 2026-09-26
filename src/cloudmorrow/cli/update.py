"""`cloudmorrow update` — this machine's CLI and agent, and the server itself."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

import typer
from rich.markup import escape

import cloudmorrow
from cloudmorrow import __version__
from cloudmorrow.agent import service as agent_service
from cloudmorrow.cli import progress
from cloudmorrow.cli.common import client, console, fail, run
from cloudmorrow.client.api import ApiError, CloudmorrowClient, client_from_credentials
from cloudmorrow.client.config import ClientConfig, StoredCredentials
from cloudmorrow.desktop import extra as desktop_extra
from cloudmorrow.links import link_new_commands
from cloudmorrow.palette import GOOD, MUTED, SECOND, WARN

app = typer.Typer(
    help=(
        "Update this machine's CLI and agent. `update server` updates the "
        "server itself; `update all` does both, in the order that works."
    ),
    invoke_without_command=True,
)


def ssh_target(config: ClientConfig) -> str:
    """Where `update server` should ssh. The API host, unless told otherwise."""
    if config.server_host:
        return config.server_host
    return urlparse(config.api_url).hostname or config.api_url


def dev_checkout() -> Path | None:
    """The git checkout this copy runs from, when it is an editable install."""
    root = Path(cloudmorrow.__file__).resolve().parents[2]
    return root if (root / ".git").is_dir() else None


@app.callback(invoke_without_command=True)
def update_local(
    ctx: typer.Context,
    check: Annotated[
        bool, typer.Option("--check", help="Say what would be installed, and change nothing.")
    ] = False,
    agent: Annotated[
        bool, typer.Option(help="Also restart this machine's agent afterwards.")
    ] = True,
    force: Annotated[
        bool, typer.Option("--force", help="Update even from a development checkout.")
    ] = False,
) -> None:
    """Update the CLI and the agent on this machine, from your server.

    The same thing the install command does, without the copy and paste: the
    server publishes a wheel on every deployment, and this installs it.
    """
    if ctx.invoked_subcommand is not None:
        return
    _update_client(check=check, agent=agent, force=force)


def _update_client(*, check: bool, agent: bool, force: bool) -> None:
    """Install what the server publishes.

    The body of `update`, kept out of the callback so `update all` can run the
    same thing straight after the deploy.
    """
    checkout = dev_checkout()
    if checkout is not None and not force:
        fail(
            f"this is a development checkout at {checkout} — `git pull` there instead.\n"
            "Pass --force to install over it anyway."
        )

    config, api = client()
    progress.header(console, "update", config.api_url)
    prefix = Path(sys.executable).parent.parent

    with progress.Activity(console) as activity:
        activity.step("asking what the server publishes")
        release = run(_fetch_release(api))
    # escape(): a spec carries extras like cloudmorrow[tui,agent], which rich
    # would otherwise read as markup and swallow.
    package = escape(release["package"])

    theirs = str(release.get("version") or "")
    if check:
        console.print(f" [{MUTED}]would install[/] [b]{package}[/]  [{MUTED}]→ {prefix}[/]")
        if not needs_update(__version__, theirs):
            console.print(f" [{GOOD}]✔[/] Up to date  [{MUTED}]v{__version__}[/]\n")
        else:
            console.print(
                f" [{MUTED}]this copy is[/] [b]v{__version__}[/] "
                f"[{MUTED}]and the server publishes[/] [b]v{theirs or '?'}[/]\n"
            )
        return

    # Nothing to do is nothing to do: no reinstall, and no agent restarted
    # onto the code it is already running. --force is for a redeploy of the
    # same tag, where the version says the same and the wheel may not be.
    if not force and not needs_update(__version__, theirs):
        progress.good(console, f"Up to date  [{MUTED}]v{__version__}[/]")
        console.print()
        return

    restarted = None
    with progress.Activity(console) as activity:
        activity.step(f"installing {package}")
        # --force-reinstall because a redeploy of the same tag publishes the
        # same version, and pip would decide the copy installed satisfies it.
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "--upgrade",
             "--force-reinstall", release["package"]],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            fail(f"pip could not install {package}:\n{detail}")
        if desktop_extra.installed():
            # The desktop app was added here, so keep it: whatever a new
            # release needs for it, without reinstalling Qt every time,
            # which is what --force-reinstall on the whole extra would do.
            activity.step("keeping the desktop app")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet",
                 desktop_extra.with_extra(release["package"])],
                capture_output=True,
                text=True,
            )
        if agent:
            activity.step("restarting the agent")
            restarted = agent_service.restart()

    progress.good(console, updated_line(__version__, theirs or installed_version()))
    console.print(f" [{MUTED}]{package}  → {prefix}[/]")
    for linked in link_new_commands(prefix):
        progress.good(console, f"linked [b]{linked}[/]")
    if restarted is not None:
        if restarted.installed:
            progress.good(console, f"agent restarted  [{MUTED}]({restarted.kind})[/]")
        else:
            progress.warn(
                console,
                f"agent not restarted  "
                f"[{MUTED}]{restarted.detail or 'not installed here'}[/]",
            )
    console.print()


def needs_update(current: str, published: str) -> bool:
    """Whether the server's wheel is not the one running here.

    Every deploy is a tagged release, so a version that matches is the same
    code. An unknown published version is taken as new: better an install
    that changes nothing than a machine left behind.
    """
    return not published or published != current


def updated_line(before: str, after: str) -> str:
    """`cloudmorrow updated  v0.9.0 → v0.10.0` — or just the one, when it is the same."""
    if after and after != before:
        return f"cloudmorrow updated  [{MUTED}]v{before} → [/][b]v{after}[/]"
    return f"cloudmorrow reinstalled  [{MUTED}]v{after or before}[/]"


def installed_version() -> str:
    """The version on disk now — after an install, not the one this process started with."""
    try:
        return metadata.version("cloudmorrow")
    except metadata.PackageNotFoundError:
        return ""


async def _fetch_release(api: CloudmorrowClient) -> dict:
    try:
        return await api.client_release()
    finally:
        await api.aclose()


@app.command("server")
def update_server(
    ssh: Annotated[
        bool, typer.Option("--ssh", help="Deploy over ssh instead of the API.")
    ] = False,
    host: Annotated[
        str | None, typer.Option("--host", "-H", help="ssh target. Implies --ssh.")
    ] = None,
    branch: Annotated[str | None, typer.Option(help="Branch to deploy.")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Update even with local changes or nothing new.")
    ] = False,
    restart: Annotated[
        bool, typer.Option(help="Restart the service onto the new code.")
    ] = True,
    wait: Annotated[
        int, typer.Option(help="Seconds to wait for the server to come back.")
    ] = 60,
) -> None:
    """Deploy the server from git: push, then run this. Admin accounts only.

    It asks the API to put its own checkout on whatever the remote branch says,
    reinstall, republish the client wheel, and restart onto the new code — so a
    release is `git push` and this, with no shell on the server.

    What that trusts is worth saying out loud: an admin token can change the
    code the server runs. It is bounded — the server can only go to a commit
    already pushed to its remote, so nothing can be deployed that is not in the
    repo — but if that is more than you want a token to do, set
    `allow_api_update = false` in the server config and use --ssh, which is
    authorised by your ssh access and the sudoers rule instead.
    """
    if host:
        ssh = True
    if ssh:
        _update_over_ssh(host=host, branch=branch, force=force)
        return

    config = ClientConfig.load()
    progress.header(console, "update server", config.api_url)

    with progress.Activity(console) as activity:
        activity.step("checking your account")
        _require_admin(config)
        api = client_from_credentials(config, StoredCredentials.load())
        activity.step(f"deploying {branch or 'the tracked branch'} from git")
        try:
            result = run(_deploy(api, branch=branch, force=force, restart=restart))
        except ApiError as exc:
            if exc.status_code == 404:
                fail(
                    "this server has no /api/server/update — it is running a build from "
                    "before API deploys. Update it once with `cloudmorrow update server --ssh`."
                )
            fail(str(exc))

    lines, waiting = _deploy_lines(result, restart=restart, force=force)
    for line in lines:
        console.print(line)
    if waiting:
        _wait_for(config, expect=result["new_commit"], seconds=wait)
    console.print()


@app.command("all")
def update_all(
    branch: Annotated[str | None, typer.Option(help="Branch to deploy.")] = None,
    ssh: Annotated[
        bool, typer.Option("--ssh", help="Deploy the server over ssh instead of the API.")
    ] = False,
    host: Annotated[
        str | None, typer.Option("--host", "-H", help="ssh target. Implies --ssh.")
    ] = None,
    wait: Annotated[
        int, typer.Option(help="Seconds to wait for the server to come back.")
    ] = 60,
    agent: Annotated[
        bool, typer.Option(help="Also restart this machine's agent afterwards.")
    ] = True,
    force: Annotated[
        bool, typer.Option("--force", help="Deploy and install even with nothing new.")
    ] = False,
) -> None:
    """The whole thing: deploy the server, then follow it on this machine.

    `update server` and then `update`, which is the only order that works: the
    server builds and publishes the client wheel as it deploys, so the wheel
    this machine installs is the one the deploy just made. Either half on its
    own leaves the two ends on different code for a while.

    It stops if the deploy does. Whatever the server did before it failed
    stands, but nothing is installed here on top of a deploy that did not land.
    """
    update_server(ssh=ssh, host=host, branch=branch, force=force, restart=True, wait=wait)
    _update_client(check=False, agent=agent, force=force)


def _name(result: dict, end: str) -> str:
    """What to call one end of a deploy: its release, or its commit.

    A tagged commit is a release and says so. Anything else is not one, and
    saying `0.8.0.dev3` where a version is expected would read as a release
    that is not — so the commit says it instead, plainly.
    """
    version = (result.get(f"{end}_version") or "").strip()
    commit = result[f"{end}_commit"][:8]
    return f"v{version}" if version and ".dev" not in version else commit


def _deploy_lines(result: dict, *, restart: bool, force: bool) -> tuple[list[str], bool]:
    """What to say about a deploy, and whether a restart is worth waiting for.

    Split out from the command because "nothing to pull" and "restarting" are
    not opposites: --force redeploys the commit that is already there and
    restarts onto it, and saying only "already up to date" while the API bounces
    underneath you is a lie by omission.
    """
    subject = escape(result.get("commit_subject") or "")
    lines: list[str] = []
    discarded = int(result.get("discarded") or 0)
    if discarded:
        # The ordinary cause is a force-push, and then this is just bookkeeping.
        # The other cause is a commit made on the server, which is worth seeing.
        lines.append(
            f" [{WARN}]![/] Rewound onto origin/{result['branch']}, discarding "
            f"[b]{discarded}[/] commit{'s' if discarded != 1 else ''} "
            f"the remote does not have"
        )
    if result["changed"]:
        came_from, went_to = _name(result, "old"), _name(result, "new")
        if came_from == went_to:
            # Two different commits the versions cannot tell apart: a rewind
            # onto as many commits as it discarded. Name them by their commits,
            # rather than announce a move from something to itself.
            came_from, went_to = result["old_commit"][:8], result["new_commit"][:8]
        lines.append(
            f" [{GOOD}]✔[/] Updated [b]{came_from}[/] → [b]{went_to}[/]"
            f"  [{MUTED}]{result['changed_files']} files · {result['branch']}[/]"
        )
    else:
        lines.append(
            f" [{GOOD}]✔[/] Already up to date  "
            f"[{MUTED}]{_name(result, 'new')} · {result['branch']}[/]"
        )
    if subject:
        lines.append(f"   [{SECOND}]{subject}[/]")
    # One line for the housekeeping, since neither half is news on its own.
    done = [word for word, did in
            (("reinstalled", result.get("reinstalled")),
             (f"published {escape(result.get('published_wheel') or '')}",
              result.get("published_wheel"))) if did]
    if done:
        lines.append(f"   [{MUTED}]{' · '.join(done)}[/]")

    if result.get("restart_blocked"):
        lines.append(f" [{WARN}]![/] Not restarted: {result['restart_blocked']}")
        lines.append(f"   [{MUTED}]the new code is on disk; the old code is still serving.[/]")
        return lines, False
    if result.get("restarting"):
        return lines, True
    if not restart and (result["changed"] or force):
        lines.append(f"   [{MUTED}]not restarted, as asked[/]")
    return lines, False


def _update_over_ssh(*, host: str | None, branch: str | None, force: bool) -> None:
    """The original path, kept as the way back in when the API is the problem."""
    config = ClientConfig.load()
    target = host or ssh_target(config)
    _require_admin(config)

    command = ["ssh", target, "cloudmorrow-update"]
    if force:
        command.append("--force")
    if branch:
        command += ["--branch", branch]
    progress.header(console, "update server · ssh", target)
    # No spinner here: ssh inherits this terminal so it can ask for a
    # passphrase, and two things drawing on one terminal is one too many.
    console.print(f" [{MUTED}]$ {' '.join(command)}[/]")
    try:
        # stdio is inherited so ssh can ask for a key passphrase, and so the
        # update's own output arrives as it happens.
        completed = subprocess.run(command)
    except OSError as exc:
        fail(f"cannot run ssh: {exc}")
    if completed.returncode != 0:
        # Deliberately not "nothing changed": the update may have pulled,
        # reinstalled and restarted before whatever failed.
        fail(f"ssh exited {completed.returncode} — see its output above.")
    progress.good(console, "Server updated")
    console.print(
        f"   [{MUTED}]the client wheel was republished too — "
        f"`cloudmorrow update` to follow it.[/]\n"
    )


async def _deploy(
    api: CloudmorrowClient, *, branch: str | None, force: bool, restart: bool
) -> dict:
    try:
        return await api.update_server(branch=branch, force=force, restart=restart)
    finally:
        await api.aclose()


def _wait_for(config: ClientConfig, *, expect: str, seconds: int) -> None:
    """Watch the server go away and come back, and say what it came back on.

    The bar fills towards the moment we stop waiting, because that is the only
    thing here with a known size — the service is not answering yet, so it
    cannot tell us how far along it is.
    """

    async def _poll(bar: progress.Waiter) -> str | None:
        deadline = time.monotonic() + seconds
        # A moment first, or the still-draining old process answers and we
        # call the restart done before it has happened.
        await asyncio.sleep(2)
        while time.monotonic() < deadline:
            bar.tick()
            api = client_from_credentials(config, StoredCredentials.load())
            try:
                return (await api.health()).get("commit", "")
            except ApiError:
                await asyncio.sleep(0.5)
            finally:
                await api.aclose()
        return None

    with progress.Waiter(console, "waiting for the server to come back", seconds) as bar:
        commit = run(_poll(bar))

    if commit is None:
        fail(
            f"the server did not answer within {seconds}s. It may still be starting — "
            "check `systemctl status cloudmorrow` on the box."
        )
    if commit and commit != expect:
        progress.warn(
            console,
            f"Back up, but on [b]{commit[:8]}[/], not [b]{expect[:8]}[/]  "
            f"[{MUTED}]— something else deployed at the same time?[/]",
        )
        return
    progress.good(console, f"Back up on [b]{expect[:8]}[/]")
    console.print(
        f"   [{MUTED}]the client wheel was republished too — "
        f"`cloudmorrow update` to follow it.[/]"
    )


def _require_admin(config: ClientConfig) -> None:
    """Refuse early for a non-admin. The server's sudoers is the real gate."""

    async def _me() -> dict | None:
        api = client_from_credentials(config, StoredCredentials.load())
        try:
            return await api.me()
        except ApiError:
            # Signed out, or the server is down — which is exactly when you
            # might want to redeploy it. Let ssh have the final say.
            return None
        finally:
            await api.aclose()

    user = asyncio.run(_me())
    if user is None:
        console.print("[dim]could not check your account; ssh decides.[/]")
        return
    if not user.get("is_admin"):
        fail(
            f"{user['username']} is not an admin.\n"
            "Updating the server is an admin job — and needs ssh access to the box."
        )
