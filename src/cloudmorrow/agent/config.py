"""Agent configuration.

The agent runs unattended, so everything it is allowed to do is declared here
rather than decided at job time. A job asking for something this file does not
permit is refused by the agent, not by the server.
"""

from __future__ import annotations

import os
import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w
from platformdirs import user_data_dir

DEFAULT_PATHS = (
    Path("/etc/cloudmorrow/agent.toml"),
    Path.home() / ".config" / "cloudmorrow" / "agent.toml",
)


def default_config_path() -> Path:
    override = os.environ.get("CLOUDMORROW_AGENT_CONFIG")
    if override:
        return Path(override).expanduser()
    for candidate in DEFAULT_PATHS:
        if candidate.exists():
            return candidate
    # Root installs are system-wide; everything else stays in the user's config.
    if os.geteuid() == 0:
        return DEFAULT_PATHS[0]
    return DEFAULT_PATHS[1]


def default_backup_dir() -> Path:
    return Path(user_data_dir("cloudmorrow")) / "backups"


@dataclass(slots=True)
class AgentConfig:
    server_url: str = ""
    agent_token: str = ""
    name: str = field(default_factory=socket.gethostname)
    poll_seconds: int = 30
    verify_tls: bool = True
    # A plain http:// server_url is refused unless it is this machine, or this
    # says the box is meant to be reached in the clear.
    allow_insecure_http: bool = False

    # Running arbitrary commands is off until this machine opts in.
    allow_shell: bool = False
    shell_timeout_seconds: int = 300

    # Config syncing writes into this machine's ~/.config, so this is its
    # veto. It is on by default because the opt-in is the tick in the TUI —
    # nothing is synced until a bundle is switched on for this machine there —
    # and this is how a machine says "never, whatever the server thinks".
    allow_config_sync: bool = True

    # Backups may only read below these roots, and only write into backup_dir.
    allow_backup: bool = True
    backup_roots: list[str] = field(default_factory=lambda: [str(Path.home())])
    backup_dir: str = field(default_factory=lambda: str(default_backup_dir()))
    backup_retention: int = 7

    # Machine shares: directories on this machine, served over WebDAV to
    # the owner's other machines while the agent runs. The server says which
    # directories, on the heartbeat; this is the machine's veto, and where
    # it listens. `share_host` is the address the other machines reach this
    # one on; left empty, the agent works it out from its route to the server.
    allow_shares: bool = True
    share_port: int = 8788
    share_host: str = ""

    path: Path | None = None

    @property
    def capabilities(self) -> list[str]:
        """What this machine can be asked to do, and what it is.

        `omarchy` is not a job type — it is how a machine says it has a
        Hyprland config worth syncing, so the settings screen knows which
        machines to offer the tick box on.
        """
        caps = ["ping", "sysinfo"]
        if self.allow_backup:
            caps.append("backup")
        if self.allow_shell:
            caps.append("shell")
        if self.allow_config_sync and self.is_omarchy():
            caps.append("omarchy")
        if self.allow_shares:
            caps.append("shares")
        return caps

    @staticmethod
    def is_omarchy() -> bool:
        """Whether this is a Hyprland box. Imported late: it reads the disk."""
        from cloudmorrow.agent.omarchy import is_omarchy

        return is_omarchy()

    @classmethod
    def load(cls, path: Path | None = None) -> AgentConfig:
        config = cls()
        source = path or default_config_path()
        if source.exists():
            data = tomllib.loads(source.read_text(encoding="utf-8"))
            section = data.get("agent", data)
            for key in (
                "server_url",
                "agent_token",
                "name",
                "poll_seconds",
                "verify_tls",
                "allow_insecure_http",
                "allow_shell",
                "shell_timeout_seconds",
                "allow_config_sync",
                "allow_backup",
                "backup_roots",
                "backup_dir",
                "backup_retention",
                "allow_shares",
                "share_port",
                "share_host",
            ):
                if key in section:
                    setattr(config, key, section[key])
            config.path = source
        else:
            config.path = source
        if env_url := os.environ.get("CLOUDMORROW_SERVER_URL"):
            config.server_url = env_url
        if env_token := os.environ.get("CLOUDMORROW_AGENT_TOKEN"):
            config.agent_token = env_token
        config.server_url = config.server_url.rstrip("/")
        return config

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path or default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "agent": {
                "server_url": self.server_url,
                "agent_token": self.agent_token,
                "name": self.name,
                "poll_seconds": self.poll_seconds,
                "verify_tls": self.verify_tls,
                "allow_insecure_http": self.allow_insecure_http,
                "allow_shell": self.allow_shell,
                "shell_timeout_seconds": self.shell_timeout_seconds,
                "allow_config_sync": self.allow_config_sync,
                "allow_backup": self.allow_backup,
                "backup_roots": self.backup_roots,
                "backup_dir": self.backup_dir,
                "backup_retention": self.backup_retention,
                "allow_shares": self.allow_shares,
                "share_port": self.share_port,
                "share_host": self.share_host,
            }
        }
        target.write_text(tomli_w.dumps(payload), encoding="utf-8")
        # The file holds the agent token.
        target.chmod(0o600)
        self.path = target
        return target
