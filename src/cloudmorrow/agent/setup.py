"""Setting the local agent up as a side effect of signing in.

Having an agent is not something anyone should have to think about, so this
runs on `cloudmorrow login`: enrol this machine under the user who just signed
in, write the agent's config, and start it under their own account. Every
failure here is non-fatal — a machine without an agent is still a perfectly
good notes client.
"""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow import __version__
from cloudmorrow.agent import service
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.config import default_config_path as agent_config_path


@dataclass(slots=True)
class SetupResult:
    enrolled: bool
    started: bool
    agent_name: str = ""
    detail: str = ""


def machine_name() -> str:
    """A stable agent name for this machine, in the shape the server accepts."""
    raw = socket.gethostname().split(".")[0].strip().lower()
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in raw)
    cleaned = cleaned.strip("-_") or "machine"
    return cleaned[:64]


async def ensure_agent(
    api,
    *,
    config_path: Path | None = None,
    install_service: bool = True,
) -> SetupResult:
    """Enrol this machine for the signed-in user and keep the agent running.

    *api* is an authenticated CloudmorrowClient. Safe to call on every login:
    re-enrolling rotates this machine's token rather than failing.
    """
    path = config_path or agent_config_path()
    agent_config = AgentConfig.load(path)
    agent_config.server_url = api.config.api_url
    agent_config.verify_tls = api.config.verify_tls
    agent_config.allow_insecure_http = api.config.allow_insecure_http
    # Keep the name a machine already enrolled under; otherwise derive one.
    if not agent_config.agent_token:
        agent_config.name = machine_name()

    try:
        enrolled = await api.enroll_self(
            name=agent_config.name,
            hostname=socket.gethostname(),
            platform=platform.platform(),
            version=__version__,
            capabilities=agent_config.capabilities,
        )
    except Exception as exc:  # never block a login on this
        return SetupResult(False, False, agent_config.name, str(exc))

    agent_config.agent_token = enrolled["agent_token"]
    agent_config.name = enrolled["name"]
    try:
        agent_config.save(path)
    except OSError as exc:
        return SetupResult(False, False, agent_config.name, f"could not write {path}: {exc}")

    if not install_service:
        return SetupResult(True, False, agent_config.name)

    try:
        result = service.install()
    except Exception as exc:  # a service manager we cannot drive is not fatal
        return SetupResult(True, False, agent_config.name, str(exc))
    return SetupResult(True, result.installed, agent_config.name, result.detail)


def stop_agent(*, config_path: Path | None = None) -> bool:
    """Stop and remove the local agent service. Used by `cloudmorrow logout`."""
    try:
        removed = service.uninstall().installed
    except OSError:
        removed = False
    path = config_path or agent_config_path()
    try:
        if path.exists():
            config = AgentConfig.load(path)
            config.agent_token = ""
            config.save(path)
    except OSError:
        pass
    return removed
