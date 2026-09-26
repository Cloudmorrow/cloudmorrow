"""Keeping the agent running, without anyone having to think about it.

The agent runs as the logged-in user — their launchd agent on macOS, their
systemd user unit on Linux — so it works on their files with their permissions
and needs no root anywhere.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LABEL = "io.bramlabs.cloudmorrow-agent"
UNIT_NAME = "cloudmorrow-agent.service"
# The server's own agent is the one exception to "runs as the logged-in user":
# nobody logs in on the server, so it runs as the service account instead, from
# a system unit rather than a user one.
SYSTEM_UNIT_DIR = Path("/etc/systemd/system")


@dataclass(slots=True)
class ServiceResult:
    installed: bool
    kind: str
    detail: str = ""
    path: Path | None = None


def agent_executable() -> str:
    """The cloudmorrow-agent next to whatever python is running us."""
    candidate = Path(sys.executable).parent / "cloudmorrow-agent"
    if candidate.exists():
        return str(candidate)
    return shutil.which("cloudmorrow-agent") or "cloudmorrow-agent"


def user_bus_env(environ: dict[str, str] | None = None, uid: int | None = None) -> dict[str, str]:
    """The environment `systemctl --user` needs, filled in where the shell left it out.

    A user's systemd is reached over their session bus, and a shell that
    came in over ssh, or from a cron job, or from an update the TUI ran, may
    carry neither `XDG_RUNTIME_DIR` nor `DBUS_SESSION_BUS_ADDRESS` — and
    then systemctl says only "Failed to connect to bus". The bus is at a
    known place, so it is pointed at.
    """
    env = dict(os.environ if environ is None else environ)
    if uid is None:
        uid = os.getuid()
    runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}")
    env.setdefault("XDG_RUNTIME_DIR", str(runtime))
    if "DBUS_SESSION_BUS_ADDRESS" not in env and (runtime / "bus").exists():
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime / 'bus'}"
    return env


NO_BUS = (
    "no user session bus to reach systemd on — there is no login session for this "
    "account right now. `loginctl enable-linger` keeps one running without a login; "
    "or sign in on the machine and run the update again"
)


def _explain(stderr: str) -> str:
    """systemd's message, or a better one where its own says too little."""
    text = (stderr or "").strip()
    if "Failed to connect to bus" in text:
        return NO_BUS
    return text


def _run(args: list[str]) -> subprocess.CompletedProcess:
    env = user_bus_env() if args[:2] == ["systemctl", "--user"] else None
    return subprocess.run(args, capture_output=True, text=True, check=False, env=env)


# -- macOS -------------------------------------------------------------------
def _launchd_plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _launchd_plist(executable: str, log: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>{LABEL}</string>
	<key>ProgramArguments</key>
	<array>
		<string>{executable}</string>
		<string>run</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>{log}</string>
	<key>StandardErrorPath</key>
	<string>{log}</string>
</dict>
</plist>
"""


def _install_launchd(home: Path, executable: str, runner) -> ServiceResult:
    path = _launchd_plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    log = home / "Library" / "Logs" / "cloudmorrow-agent.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_launchd_plist(executable, log), encoding="utf-8")

    target = f"gui/{os.getuid()}"
    # Replace any previous copy, then load. bootout on a service that is not
    # loaded is an error we do not care about.
    runner(["launchctl", "bootout", f"{target}/{LABEL}"])
    result = runner(["launchctl", "bootstrap", target, str(path)])
    if result.returncode != 0:
        # Older macOS, or a session without a bootstrap domain.
        result = runner(["launchctl", "load", "-w", str(path)])
    if result.returncode != 0:
        return ServiceResult(False, "launchd", (result.stderr or "").strip(), path)
    return ServiceResult(True, "launchd", path=path)


def _restart_launchd(home: Path, runner) -> ServiceResult:
    path = _launchd_plist_path(home)
    if not path.exists():
        return ServiceResult(False, "launchd", "no agent service on this machine", path)
    target = f"gui/{os.getuid()}"
    result = runner(["launchctl", "kickstart", "-k", f"{target}/{LABEL}"])
    if result.returncode != 0:
        # Older macOS has no kickstart: take it out and put it back instead.
        runner(["launchctl", "bootout", f"{target}/{LABEL}"])
        result = runner(["launchctl", "bootstrap", target, str(path)])
    if result.returncode != 0:
        return ServiceResult(False, "launchd", (result.stderr or "").strip(), path)
    return ServiceResult(True, "launchd", path=path)


def _uninstall_launchd(home: Path, runner) -> ServiceResult:
    path = _launchd_plist_path(home)
    runner(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
    if path.exists():
        runner(["launchctl", "unload", "-w", str(path)])
        path.unlink()
    return ServiceResult(True, "launchd", path=path)


# -- Linux -------------------------------------------------------------------
def _systemd_unit_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / UNIT_NAME


def _systemd_unit(executable: str) -> str:
    return f"""[Unit]
Description=Cloudmorrow local agent
After=network-online.target

[Service]
Type=simple
ExecStart={executable} run
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""


def _install_systemd(home: Path, executable: str, runner) -> ServiceResult:
    path = _systemd_unit_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_systemd_unit(executable), encoding="utf-8")
    # A user unit runs only while the user has a session, unless they linger:
    # this is an agent, so they linger. Asking for one's own account needs no
    # root on a usual box; where it is refused, the agent still runs while
    # signed in, and the message on a later restart says what to do.
    runner(["loginctl", "enable-linger"])
    runner(["systemctl", "--user", "daemon-reload"])
    runner(["systemctl", "--user", "enable", UNIT_NAME])
    # restart, not `enable --now`: --now leaves an already-running unit alone,
    # so after an upgrade the old code would keep running. restart starts a
    # stopped unit too, so it covers both.
    result = runner(["systemctl", "--user", "restart", UNIT_NAME])
    if result.returncode != 0:
        return ServiceResult(False, "systemd", _explain(result.stderr), path)
    return ServiceResult(True, "systemd", path=path)


def _restart_systemd(home: Path, runner) -> ServiceResult:
    path = _systemd_unit_path(home)
    if not path.exists():
        return ServiceResult(False, "systemd", "no agent service on this machine", path)
    result = runner(["systemctl", "--user", "restart", UNIT_NAME])
    if result.returncode != 0:
        return ServiceResult(False, "systemd", _explain(result.stderr), path)
    return ServiceResult(True, "systemd", path=path)


def _uninstall_systemd(home: Path, runner) -> ServiceResult:
    path = _systemd_unit_path(home)
    runner(["systemctl", "--user", "disable", "--now", UNIT_NAME])
    if path.exists():
        path.unlink()
    runner(["systemctl", "--user", "daemon-reload"])
    return ServiceResult(True, "systemd", path=path)


# -- Linux, as a service account ---------------------------------------------
def _system_unit(executable: str, run_as: str, config_path: Path | None) -> str:
    environment = (
        f"Environment=CLOUDMORROW_AGENT_CONFIG={config_path}\n" if config_path else ""
    )
    return f"""[Unit]
Description=Cloudmorrow agent (server)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={run_as}
{environment}ExecStart={executable} run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def install_system(
    *,
    run_as: str,
    executable: str | None = None,
    config_path: Path | None = None,
    unit_dir: Path | None = None,
    runner=_run,
) -> ServiceResult:
    """Install the agent as a system service running as *run_as*.

    This is what puts an agent on the server itself. It needs root, and it is
    the only place Cloudmorrow installs anything outside a user's own home.
    """
    directory = unit_dir or SYSTEM_UNIT_DIR
    executable = executable or agent_executable()
    path = directory / UNIT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_system_unit(executable, run_as, config_path), encoding="utf-8")
    except OSError as exc:
        return ServiceResult(False, "systemd-system", str(exc), path)
    if not shutil.which("systemctl") or not Path("/run/systemd/system").exists():
        # The unit is on disk and correct; there is just nothing here to
        # start it. Saying so is more use than pretending it worked.
        return ServiceResult(
            False, "systemd-system", "systemd is not running here; start the agent yourself", path
        )
    runner(["systemctl", "daemon-reload"])
    runner(["systemctl", "enable", UNIT_NAME])
    result = runner(["systemctl", "restart", UNIT_NAME])
    if result.returncode != 0:
        return ServiceResult(False, "systemd-system", (result.stderr or "").strip(), path)
    return ServiceResult(True, "systemd-system", path=path)


def uninstall_system(*, unit_dir: Path | None = None, runner=_run) -> ServiceResult:
    path = (unit_dir or SYSTEM_UNIT_DIR) / UNIT_NAME
    if shutil.which("systemctl"):
        runner(["systemctl", "disable", "--now", UNIT_NAME])
    if path.exists():
        path.unlink()
        if shutil.which("systemctl"):
            runner(["systemctl", "daemon-reload"])
    return ServiceResult(True, "systemd-system", path=path)


# -- dispatch ----------------------------------------------------------------
def detect_kind(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Darwin":
        return "launchd"
    if system == "Linux" and shutil.which("systemctl"):
        return "systemd"
    return "none"


def install(
    *,
    home: Path | None = None,
    executable: str | None = None,
    runner=_run,
    kind: str | None = None,
) -> ServiceResult:
    """Install and start the agent for the current user."""
    home = home or Path.home()
    executable = executable or agent_executable()
    kind = kind or detect_kind()
    if kind == "launchd":
        return _install_launchd(home, executable, runner)
    if kind == "systemd":
        return _install_systemd(home, executable, runner)
    return ServiceResult(
        False,
        "none",
        f"no supported service manager; run `{executable} run` yourself to keep it going",
    )


def restart(*, home: Path | None = None, runner=_run, kind: str | None = None) -> ServiceResult:
    """Restart the agent so it picks up code installed underneath it."""
    home = home or Path.home()
    kind = kind or detect_kind()
    if kind == "launchd":
        return _restart_launchd(home, runner)
    if kind == "systemd":
        return _restart_systemd(home, runner)
    return ServiceResult(False, "none", "no supported service manager")


def uninstall(*, home: Path | None = None, runner=_run, kind: str | None = None) -> ServiceResult:
    home = home or Path.home()
    kind = kind or detect_kind()
    if kind == "launchd":
        return _uninstall_launchd(home, runner)
    if kind == "systemd":
        return _uninstall_systemd(home, runner)
    return ServiceResult(False, "none")


def is_active(*, runner=_run, kind: str | None = None) -> bool | None:
    """Whether the agent service is running right now; None where it cannot be asked.

    For the desktop app's "This computer", which would rather say "not
    known" than guess on a machine with no service manager we drive.
    """
    kind = kind or detect_kind()
    try:
        if kind == "systemd":
            result = runner(["systemctl", "--user", "is-active", "--quiet", UNIT_NAME])
            return result.returncode == 0
        if kind == "launchd":
            return runner(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"]).returncode == 0
    except OSError:
        return None
    return None


def is_installed(*, home: Path | None = None, kind: str | None = None) -> bool:
    home = home or Path.home()
    kind = kind or detect_kind()
    if kind == "launchd":
        return _launchd_plist_path(home).exists()
    if kind == "systemd":
        return _systemd_unit_path(home).exists()
    return False
