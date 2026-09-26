"""Mounting a fileshare on this machine.

A share is a WebDAV URL, and every machine already knows how to mount one of
those — what differs is who does it:

- **macOS** mounts it itself. Finder has spoken WebDAV for twenty years, so
  the mount is one AppleScript line (`mount volume`), lands under
  `/Volumes/<name>`, and needs nothing installed. Finder picks the place, not
  us, so a path given on a Mac is ignored and the real one is reported back.
- **Linux** uses `rclone mount`, which puts a FUSE filesystem in front of the
  share, at a path you choose: `~/Fileshares/<name>` unless you say
  otherwise. rclone is one binary from every distribution's repository; the
  message when it is missing says the command that installs it, and `rclone`
  (the module beside this one) can run it.

Either way the mount signs in as you: the username and the stored access
token, which the server accepts in a password's place. So a mount works
exactly as long as the client that made it is signed in, and no second
password is written anywhere.

What was mounted, and where, is written to `mounts.json` beside the client
config — per machine, since the same share is at a different path on each —
so the TUI can say "mounted at …" and `share unmount` knows what to undo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.client import rclone
from cloudmorrow.client.config import config_dir

FILENAME = "mounts.json"

# How long to give the mount command. rclone waits for the mount to be
# ready before it returns; Finder pops a dialog and hangs on a bad address.
MOUNT_TIMEOUT = 90

MACOS = "darwin"

# Where a share is mounted by default, per platform. Finder decides on a Mac.
LINUX_MOUNT_ROOT = Path.home() / "Fileshares"
MACOS_VOLUMES = Path("/Volumes")


class MountError(RuntimeError):
    """The mount or unmount did not happen; the message says why."""


@dataclass(slots=True, frozen=True)
class Mount:
    """A share this machine mounted, and where."""

    name: str
    path: Path
    url: str
    # What did the mounting: "rclone" on Linux, "finder" on a Mac.
    tool: str

    @property
    def active(self) -> bool:
        """Still there right now — a reboot or a `umount` by hand ends it."""
        return os.path.ismount(self.path)

    def to_dict(self) -> dict:
        return {"path": str(self.path), "url": self.url, "tool": self.tool}


def platform() -> str:
    """`sys.platform`, behind a function so a test can be a Mac for a moment."""
    return sys.platform


# -- the record ----------------------------------------------------------------
def mounts_path() -> Path:
    return config_dir() / FILENAME


def _load() -> dict[str, dict]:
    path = mounts_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mounts = data.get("mounts", {}) if isinstance(data, dict) else {}
    return {str(key): dict(value) for key, value in mounts.items()} if mounts else {}


def _save(mounts: dict[str, dict]) -> Path:
    path = mounts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mounts": mounts}, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _mount(name: str, record: dict) -> Mount:
    return Mount(
        name=name,
        path=Path(record["path"]),
        url=str(record.get("url", "")),
        tool=str(record.get("tool", "")),
    )


def all_mounts() -> dict[str, Mount]:
    """Every share this machine has mounted, whether or not it still is."""
    return {name: _mount(name, record) for name, record in _load().items()}


def lookup(name: str) -> Mount | None:
    record = _load().get(name)
    return _mount(name, record) if record else None


def remember(mount: Mount) -> None:
    mounts = _load()
    mounts[mount.name] = mount.to_dict()
    _save(mounts)


def forget(name: str) -> bool:
    mounts = _load()
    if mounts.pop(name, None) is None:
        return False
    _save(mounts)
    return True


# -- mounting -------------------------------------------------------------------
def default_mountpoint(name: str) -> Path:
    """Where `mount` puts a share when not told: `~/Fileshares/<name>`, or
    `/Volumes/<name>` on a Mac, where Finder puts it whatever we say."""
    if platform() == MACOS:
        return MACOS_VOLUMES / name
    return LINUX_MOUNT_ROOT / name


def mount(name: str, url: str, username: str, secret: str, *, path: Path | None = None) -> Mount:
    """Mount *url* as *username*, and remember where it went."""
    existing = lookup(name)
    if existing is not None and existing.active:
        raise MountError(f"{name} is already mounted at {existing.path}")
    if platform() == MACOS:
        mounted = _mount_finder(name, url, username, secret)
    else:
        mounted = _mount_rclone(name, url, username, secret, path or default_mountpoint(name))
    remember(mounted)
    return mounted


def refusal(share: dict) -> str | None:
    """Why *share*, as the server describes it, cannot be mounted from anywhere now.

    The one check that is about the share rather than this machine, kept
    here so the command line and the desktop app refuse it in the same
    words: a machine share is only there while its machine's agent serves it.
    """
    if share.get("kind") == "machine" and not share.get("online"):
        return (
            f"{share['name']} is on {share.get('machine')}, and its agent is not serving "
            "right now — start the agent there, or wait for its next heartbeat"
        )
    return None


def mount_share(share: dict, username: str, secret: str, *, path: Path | None = None) -> Mount:
    """Mount a share as `/api/shares/<name>` describes it, and remember where it went."""
    why = refusal(share)
    if why:
        raise MountError(why)
    return mount(share["name"], share["url"], username, secret, path=path)


def unmount(name: str) -> Mount:
    """Unmount a share this machine mounted, and forget it."""
    mounted = lookup(name)
    if mounted is None:
        raise MountError(f"{name} is not mounted on this machine")
    if mounted.active:
        _unmount_path(mounted.path)
    forget(name)
    return mounted


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """One place every shell-out goes through, so a test can stand in for it.

    Output is captured unless the caller says where it goes — a daemon that
    inherits a captured pipe holds it open, and `run` would wait on it forever.
    """
    if "stdout" not in kwargs and "stderr" not in kwargs:
        kwargs["capture_output"] = True
    return subprocess.run(command, text=True, timeout=MOUNT_TIMEOUT, **kwargs)


def _failed(what: str, result: subprocess.CompletedProcess, log: Path | None = None) -> MountError:
    text = result.stderr or result.stdout or ""
    if not text and log is not None:
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    detail = text.strip().splitlines()
    return MountError(f"{what}: {detail[-1] if detail else f'exit {result.returncode}'}")


# -- macOS: Finder ------------------------------------------------------------
def _applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mount_finder(name: str, url: str, username: str, secret: str) -> Mount:
    if shutil.which("osascript") is None:
        raise MountError("osascript is not available — this does not look like a Mac")
    # The script goes in on stdin rather than as an argument, so the token
    # never shows in `ps`.
    script = (
        f"mount volume {_applescript_string(url)} "
        f"as user name {_applescript_string(username)} "
        f"with password {_applescript_string(secret)}"
    )
    result = _run(["osascript"], input=script)
    if result.returncode != 0:
        raise _failed(f"could not mount {name}", result)
    return Mount(name=name, path=_finder_mountpoint(url, name), url=url, tool="finder")


def _finder_mountpoint(url: str, name: str) -> Path:
    """Where Finder put it: `mount` lists the URL and the path on one line.

    Usually `/Volumes/<name>`, but `/Volumes/<name>-1` when something else
    already had the name, so the real answer is read back rather than assumed.
    """
    try:
        listing = _run(["mount"]).stdout
    except (OSError, subprocess.SubprocessError):
        listing = ""
    wanted = url.rstrip("/")
    for line in listing.splitlines():
        head, sep, rest = line.partition(" on ")
        if sep and head.strip().rstrip("/") == wanted:
            path = rest.split(" (", 1)[0].strip()
            if path:
                return Path(path)
    return default_mountpoint(name)


# -- Linux: rclone ----------------------------------------------------------------
def _mount_rclone(name: str, url: str, username: str, secret: str, path: Path) -> Mount:
    binary = shutil.which("rclone")
    if binary is None:
        raise MountError(rclone.hint())
    path = Path(path).expanduser()
    if os.path.ismount(path):
        raise MountError(f"something is already mounted at {path}")
    path.mkdir(parents=True, exist_ok=True)
    if any(path.iterdir()):
        raise MountError(f"{path} is not empty — a mount would hide what is in it")
    obscured = _run([binary, "obscure", "-"], input=secret)
    if obscured.returncode != 0:
        raise _failed("rclone could not prepare the credentials", obscured)
    log = mounts_path().parent / f"mount-{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    # The remote is described in the environment rather than on the command
    # line, so the token is not in `ps` either. `:webdav:` is rclone's
    # spelling for "a remote I am not saving".
    env = {
        **os.environ,
        "RCLONE_WEBDAV_URL": url,
        "RCLONE_WEBDAV_VENDOR": "other",
        "RCLONE_WEBDAV_USER": username,
        "RCLONE_WEBDAV_PASS": obscured.stdout.strip(),
    }
    command = [
        binary,
        "mount",
        ":webdav:",
        str(path),
        # Fork, and come back once the mount is up — or say why it is not.
        "--daemon",
        # Writes go through a local cache, which is what lets programs that
        # seek and rewrite (editors, most of them) work on a share. A closed
        # file is on the server a second later rather than rclone's five.
        "--vfs-cache-mode",
        "writes",
        "--vfs-write-back",
        "1s",
        "--dir-cache-time",
        "30s",
        "--volname",
        name,
        "--log-file",
        str(log),
        "--log-level",
        "NOTICE",
    ]
    # Its output goes to the log, not to a pipe: the daemon it leaves behind
    # keeps whatever it inherited, and a pipe held open is a `run` that never
    # returns. What went wrong is read back out of the log instead.
    with log.open("a", encoding="utf-8") as sink:
        result = _run(command, env=env, stdout=sink, stderr=sink)
    if result.returncode != 0:
        raise _failed(f"could not mount {name}", result, log)
    return Mount(name=name, path=path, url=url, tool="rclone")


def _unmount_path(path: Path) -> None:
    if platform() == MACOS:
        candidates = [["diskutil", "unmount", str(path)], ["umount", str(path)]]
    else:
        candidates = [
            ["fusermount3", "-u", str(path)],
            ["fusermount", "-u", str(path)],
            ["umount", str(path)],
        ]
    last: subprocess.CompletedProcess | None = None
    for command in candidates:
        if shutil.which(command[0]) is None:
            continue
        last = _run(command)
        if last.returncode == 0:
            return
    if last is None:
        raise MountError(f"no unmount command found for {path}")
    raise _failed(f"could not unmount {path}", last)
