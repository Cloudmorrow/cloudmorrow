"""Updating a deployed server from its git checkout.

The server is installed as an editable checkout, so an update is: match the
repo to its remote, reinstall in case dependencies moved, restart the service.
Everything here is deliberately explicit about what it is about to do, because
it runs unattended — over ssh, or from the API.

The checkout is a mirror of origin, not a working copy: nobody commits in it,
so it is reset onto the remote branch rather than merged onto it. Merging would
be the careful thing to do in a place where a local commit is precious, and
there are none here by design — what merging actually buys is a deploy that
wedges the first time the branch is force-pushed or rolled back, because both
of those look exactly like a local commit to git. Uncommitted *edits* are worth
protecting, and they are, separately, below.

Two ways to restart, because there are two identities doing the asking. Over
ssh it is you, and you have a sudoers rule for `systemctl restart`. From the
API it is the service itself, which deliberately has no privilege at all —
so it stops, and systemd starts it again. That is what `Restart=always` in the
unit is for, and why this refuses to stop when the unit would not bring it
back.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cloudmorrow

# A branch to deploy, not an option for git to read and not a path to escape.
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")

_COMMIT: str | None = None


class UpdateError(RuntimeError):
    """The update could not be completed, and this is why."""


@dataclass(slots=True)
class UpdateResult:
    source: Path
    branch: str
    old_commit: str
    new_commit: str
    changed_files: int
    reinstalled: bool
    restarted: bool
    # The release either end of the deploy, from the tags. "" when the checkout
    # has no tag behind it, and then the commit is the only name there is.
    old_version: str = ""
    new_version: str = ""
    # Commits the checkout had that the remote does not, thrown away to get
    # here. Nought on every ordinary deploy; anything else is worth saying.
    discarded: int = 0

    @property
    def changed(self) -> bool:
        return self.old_commit != self.new_commit

    @property
    def rewound(self) -> bool:
        """Whether this deploy moved somewhere the old commit does not lead."""
        return self.discarded > 0


def _run(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as exc:
        raise UpdateError(f"{args[0]} is not installed") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise UpdateError(f"{' '.join(args)} failed:\n{detail}") from exc
    return completed.stdout.strip()


def find_source_dir(explicit: Path | None = None) -> Path:
    """Locate the git checkout this server was installed from."""
    if explicit is not None:
        candidate = Path(explicit).expanduser().resolve()
    elif env := os.environ.get("CLOUDMORROW_SOURCE_DIR"):
        candidate = Path(env).expanduser().resolve()
    else:
        # src layout: <repo>/src/cloudmorrow/__init__.py
        candidate = Path(cloudmorrow.__file__).resolve().parents[2]
    if not (candidate / ".git").exists():
        raise UpdateError(
            f"{candidate} is not a git checkout.\n"
            "Updating from git needs an editable install "
            "(`pip install -e '.[server,agent]'`), which is what "
            "deploy/install-server.sh sets up. "
            "Pass --source to point at the checkout, or set CLOUDMORROW_SOURCE_DIR."
        )
    return candidate


def current_commit(source: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=source)


def current_branch(source: Path) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=source)


def describe(source: Path, commit: str) -> str:
    return _run(["git", "log", "-1", "--pretty=%h %s", commit], cwd=source)


def version_at(source: Path, commit: str) -> str:
    """What to call the release *commit* is part of.

    `0.23.0` only where the tag is: the commits after a release belong to it
    but are not it, and calling them by its name is how a deploy ends up
    announcing itself as 0.23.0 → 0.23.0. Past the tag the distance comes
    along — `0.23.0+3` is three commits after v0.23.0 — which is both true and
    different at each end of the deploy.

    "" when no tag is reachable — a checkout fetched without tags, or history
    from before there were any. The caller falls back to the commit, which is
    what identified a deploy before versions did and still always works.
    """
    try:
        described = _run(
            ["git", "describe", "--tags", "--long", "--match", "v*", commit],
            cwd=source,
        )
    except UpdateError:
        return ""
    # --long always ends in -<commits since the tag>-g<abbreviated commit>, so
    # the tag is whatever comes before those two, dashes in it and all.
    tag, distance, _abbrev = described.rsplit("-", 2)
    return tag.removeprefix("v") + (f"+{distance}" if distance != "0" else "")


def working_tree_is_dirty(source: Path) -> bool:
    return bool(_run(["git", "status", "--porcelain"], cwd=source))


def commits_not_on(source: Path, ref: str) -> int:
    """How many commits HEAD has that *ref* does not.

    Nought whenever the deploy is the ordinary fast-forward. Anything else means
    the checkout is about to lose something: usually a commit it pulled before
    the branch was force-pushed, which is no loss at all, and just possibly one
    somebody made on the server, which is worth hearing about.
    """
    counted = _run(["git", "rev-list", "--count", f"{ref}..HEAD"], cwd=source)
    return int(counted or 0)


def service_is_active(service: str) -> bool:
    if shutil.which("systemctl") is None:
        return False
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", service], capture_output=True
    )
    return result.returncode == 0


def restart_service(service: str) -> None:
    if shutil.which("systemctl") is None:
        raise UpdateError("systemctl is not available; restart the server yourself")
    _run(["systemctl", "restart", service])


def deployed_commit() -> str:
    """The commit this process is running, or "" when it is not from a checkout.

    Cached: it cannot change without the process restarting, which is the whole
    point of it — `/api/health` reporting it is how a deploy is confirmed from
    the other end.
    """
    global _COMMIT
    if _COMMIT is None:
        try:
            _COMMIT = current_commit(find_source_dir())
        except UpdateError:
            _COMMIT = ""
    return _COMMIT


def validate_branch(branch: str) -> str:
    """A branch name, or an UpdateError. Never something git reads as a flag."""
    name = branch.strip()
    if not BRANCH.match(name) or ".." in name:
        raise UpdateError(f"not a branch name: {branch!r}")
    return name


def unit_property(service: str, name: str) -> str:
    """One property of a systemd unit. Reading these needs no privilege."""
    if shutil.which("systemctl") is None:
        return ""
    result = subprocess.run(
        ["systemctl", "show", service, "--property", name, "--value"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def self_restart_blocker(service: str = "cloudmorrow") -> str:
    """Why this process must not stop itself to update, or "" when it may.

    The API update has no way to *start* anything — it can only exit and trust
    systemd. If systemd would not bring it back, exiting takes the server down
    until someone walks over to it, so this is checked before anything stops.
    """
    if not os.environ.get("INVOCATION_ID"):
        return "this server was not started by systemd, so nothing would restart it"
    restart = unit_property(service, "Restart")
    if restart != "always":
        return (
            f"{service}.service has Restart={restart or 'unset'}, so systemd would "
            "not start it again — set Restart=always in the unit "
            "(deploy/install-server.sh writes it) and `systemctl daemon-reload`"
        )
    return ""


def self_restart(hard_exit_after: float = 30.0) -> None:
    """Stop this process, and let systemd start the new code.

    SIGTERM rather than a hard exit: uvicorn takes it as a graceful shutdown,
    so the response that asked for this has already gone out and any other
    request in flight gets to finish.

    The watchdog behind it is the whole reason this is safe to do at all. A
    shutdown that wedges would leave the service neither serving nor restarting
    — the one outcome that needs a walk to the machine — so if the process is
    still here well after the graceful window, it leaves the hard way instead.
    Exit 0 and systemd starts it again just the same.
    """

    def _watchdog() -> None:
        time.sleep(hard_exit_after)
        os._exit(0)

    threading.Thread(target=_watchdog, daemon=True, name="restart-watchdog").start()
    os.kill(os.getpid(), signal.SIGTERM)


def build_wheel(source: Path, dist_dir: Path, *, keep: int = 3) -> Path:
    """Build a wheel from the checkout so /install.sh can hand out this code.

    The server is the only place a client can get Cloudmorrow from — it is not on
    PyPI and the repo is private — so every deployment publishes itself.
    """
    dist_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as staging:
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--quiet",
                "--no-deps",
                "--wheel-dir",
                staging,
                str(source),
            ]
        )
        built = sorted(Path(staging).glob("*.whl"))
        if not built:
            raise UpdateError("pip produced no wheel")
        wheel = built[-1]
        target = dist_dir / wheel.name
        shutil.copy2(wheel, target)
    # os.utime so the newest build always wins published_wheel(), even when the
    # version number has not changed.
    os.utime(target, None)
    for old in sorted(dist_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime)[:-keep]:
        old.unlink(missing_ok=True)
    return target


def update(
    *,
    source: Path | None = None,
    branch: str | None = None,
    service: str = "cloudmorrow",
    restart: bool = True,
    reinstall: bool = True,
    force: bool = False,
) -> UpdateResult:
    """Match the checkout to its remote branch, reinstall, restart the service."""
    checkout = find_source_dir(source)
    if working_tree_is_dirty(checkout) and not force:
        raise UpdateError(
            f"{checkout} has uncommitted changes.\n"
            "Commit or stash them on the server, or pass --force to update anyway."
        )
    on_branch = branch or current_branch(checkout)
    if on_branch == "HEAD":
        raise UpdateError("the checkout is on a detached HEAD; check out a branch first")

    old_commit = current_commit(checkout)
    # --tags: the version is read off them, so a checkout without them would
    # deploy fine and then be unable to say what it had just deployed.
    _run(["git", "fetch", "--quiet", "--tags", "origin", on_branch], cwd=checkout)
    # Counted before the reset, while the old commit is still on a branch.
    discarded = commits_not_on(checkout, f"origin/{on_branch}")
    # reset, not merge: the checkout is a mirror of the remote branch, so it
    # goes wherever that branch went — forward, or back, or onto a history that
    # was rewritten underneath it. No merge commit is possible either way.
    _run(["git", "reset", "--hard", "--quiet", f"origin/{on_branch}"], cwd=checkout)
    new_commit = current_commit(checkout)
    # Read after the reset: the old commit may no longer be on any branch, but
    # both are still objects here, and describe only needs the object.
    old_version = version_at(checkout, old_commit)
    new_version = version_at(checkout, new_commit)

    changed_files = 0
    if new_commit != old_commit:
        diff = _run(["git", "diff", "--name-only", old_commit, new_commit], cwd=checkout)
        changed_files = len(diff.splitlines())

    did_reinstall = False
    if reinstall and (new_commit != old_commit or force):
        # sys.executable is the venv the server runs from, so the reinstall
        # lands in the right place no matter who invoked the update.
        _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--editable",
                # Both extras: the server runs an agent of its own, and that
                # needs the agent's dependencies, not just the API's.
                f"{checkout}[server,agent]",
            ]
        )
        did_reinstall = True

    did_restart = False
    if restart and (new_commit != old_commit or force):
        restart_service(service)
        did_restart = True

    return UpdateResult(
        source=checkout,
        branch=on_branch,
        old_commit=old_commit,
        new_commit=new_commit,
        changed_files=changed_files,
        reinstalled=did_reinstall,
        restarted=did_restart,
        old_version=old_version,
        new_version=new_version,
        discarded=discarded,
    )
