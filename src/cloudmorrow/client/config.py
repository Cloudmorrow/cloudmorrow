"""Client configuration and the stored access token."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from cloudmorrow.locations import config_dir
from cloudmorrow.privatefile import write_private

DEFAULT_API_URL = "https://cm.hl.bramlabs.io"


def config_path() -> Path:
    return config_dir() / "config.toml"


def credentials_path() -> Path:
    return config_dir() / "credentials.json"


@dataclass(slots=True)
class ClientConfig:
    api_url: str = DEFAULT_API_URL
    # Autosave delay after the last keystroke, in seconds.
    autosave_seconds: float = 1.5
    # Set false only for a server on a private network with a self-signed certificate.
    verify_tls: bool = True
    # A plain http:// api_url is refused unless it is this machine — or this
    # is true, which says the box is meant to be reached in the clear.
    allow_insecure_http: bool = False
    # Which vault and environment secrets commands work in unless -v or -e
    # says otherwise. `default` is the vault everyone has.
    vault: str = "default"
    environment: str = "local"
    # ssh target for `cloudmorrow update server`. Empty derives it from api_url.
    server_host: str = ""
    # The cloud's address on the home network ("192.168.1.20:443"), found by
    # `cm login` when the cloud announces itself there. While it answers,
    # requests go to it directly, still checked against api_url's real name
    # (client/localroute.py); away from home, api_url is used as it is.
    local_address: str = ""
    # Join a linked cloud's mesh after signing in (client/autojoin.py).
    # False keeps this computer off it, and is what declining Tailscale sets.
    mesh: bool = True

    @classmethod
    def load(cls) -> ClientConfig:
        config = cls()
        path = config_path()
        if path.exists():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            section = data.get("client", data)
            for key in (
                "api_url",
                "autosave_seconds",
                "verify_tls",
                "allow_insecure_http",
                "vault",
                "environment",
                "server_host",
                "local_address",
                "mesh",
            ):
                if key in section:
                    setattr(config, key, section[key])
            # A config from when the vault was a project: the fallback project
            # is the natural vault to land in, since its secrets are there.
            if "vault" not in section and section.get("project"):
                config.vault = str(section["project"])
        config.vault = config.vault.strip().lower() or "default"
        if env_url := os.environ.get("CLOUDMORROW_API_URL"):
            config.api_url = env_url
        config.api_url = config.api_url.rstrip("/")
        return config

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "client": {
                "api_url": self.api_url,
                "autosave_seconds": self.autosave_seconds,
                "verify_tls": self.verify_tls,
                "allow_insecure_http": self.allow_insecure_http,
                "vault": self.vault,
                "environment": self.environment,
                "server_host": self.server_host,
                "local_address": self.local_address,
                "mesh": self.mesh,
            }
        }
        path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        return path


@dataclass(slots=True)
class StoredCredentials:
    api_url: str
    username: str
    access_token: str
    expires_at: str = ""

    @classmethod
    def load(cls) -> StoredCredentials | None:
        path = credentials_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                **{k: data[k] for k in ("api_url", "username", "access_token") if k in data},
                expires_at=data.get("expires_at", ""),
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def save(self) -> Path:
        path = credentials_path()
        write_private(
            path,
            json.dumps(
                {
                    "api_url": self.api_url,
                    "username": self.username,
                    "access_token": self.access_token,
                    "expires_at": self.expires_at,
                },
                indent=2,
            ),
        )
        return path


def clear_credentials() -> bool:
    path = credentials_path()
    if path.exists():
        path.unlink()
        return True
    return False
