"""Where Cloudmorrow keeps things on a person's machine.

Two places, both the platform's own: a config directory, for the client's
config and token and the agent's config, and a data directory, for what
install.sh put there and what the agent keeps — backups, sync state, the
Quills it runs. On Linux that is ~/.config/cloudmorrow and
~/.local/share/cloudmorrow; on a Mac both are under
~/Library/Application Support.

The server's directories are its own business, and are not here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "cloudmorrow"

# Where the agent's config was before it followed the platform: on Linux the
# same place still, on a Mac somewhere an older install may have left one.
LEGACY_AGENT_CONFIG = Path.home() / ".config" / APP_NAME / "agent.toml"


def config_dir() -> Path:
    """The client's config and token: CLOUDMORROW_CONFIG_DIR, else the platform's."""
    override = os.environ.get("CLOUDMORROW_CONFIG_DIR")
    return Path(override).expanduser() if override else Path(user_config_dir(APP_NAME))


def agent_config_path() -> Path:
    """The agent's config for this user, when nothing more particular says where.

    The platform's config directory, as the client's — though never moved by
    CLOUDMORROW_CONFIG_DIR, since the agent has CLOUDMORROW_AGENT_CONFIG — and
    on Linux ~/.config/cloudmorrow whatever XDG_CONFIG_HOME says, which is
    where it has always been and where a service started without the
    session's environment still looks.
    """
    if sys.platform == "darwin" or os.name == "nt":
        return Path(user_config_dir(APP_NAME)) / "agent.toml"
    return LEGACY_AGENT_CONFIG


def data_dir() -> Path:
    """Where install.sh put the venv, and where the agent keeps what it keeps."""
    return Path(user_data_dir(APP_NAME))


def xdg_config_home() -> Path:
    """`~/.config`, or wherever XDG says it is: the root other programs' config lives in."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")).expanduser()
