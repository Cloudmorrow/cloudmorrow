"""Server configuration: TOML file + environment overrides."""

from __future__ import annotations

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATHS = (
    Path("/etc/cloudmorrow/server.toml"),
    Path.home() / ".config" / "cloudmorrow" / "server.toml",
)

ENV_PREFIX = "CLOUDMORROW_"

DEFAULT_QUILL_CATALOG = (
    "https://raw.githubusercontent.com/Cloudmorrow/quill-catalog/main/catalog.toml"
)


@dataclass(slots=True)
class ServerConfig:
    """Everything the server needs to boot."""

    # What this cloud is called: the name on the sign-in screen, the install
    # page, the phone's home screen and `/api/health`. "Cloudmorrow" until
    # somebody names it, which the installer asks them to.
    name: str = "Cloudmorrow"
    # Where notes live. This is the directory you hand the server.
    notes_dir: Path = Path("/var/lib/cloudmorrow/notes")
    # Where the user database and generated secret key live.
    data_dir: Path = Path("/var/lib/cloudmorrow")
    # One notes subdirectory per user (notes_dir/<username>), or one shared tree.
    per_user_dirs: bool = True
    # The Shares folder: every server share is a folder in it, whoever made
    # it. Empty puts it in the Cloudmorrow directory: `<notes_dir>/Shares`.
    shares_dir: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8787
    # Signing key for access tokens. Generated into data_dir/secret.key when empty.
    secret_key: str = ""
    # The file holding the key everything is sealed with at rest: secrets,
    # chat, calendar, tasks, notes, pictures. Unset, it is data_dir/secrets.key.
    # A fresh install puts it in /etc/cloudmorrow, away from the data, so a
    # copy of the data directory on its own opens nothing.
    key_file: Path | None = None
    # Refuse requests that did not come over TLS (426), and send HSTS on the
    # ones that did. Unset, it follows public_url: on for https, off for
    # http or none. A call from this machine with no proxy header is always
    # let through; it crosses no wire.
    require_tls: bool | None = None
    token_ttl_hours: int = 24 * 30
    # Origins allowed to call the API from a browser. The TUI does not need this.
    cors_origins: list[str] = field(default_factory=list)
    # Hosts allowed to talk to the API at all, as addresses or CIDR ranges.
    # Empty means anyone who can reach the port. Set it to your reverse proxy
    # when the machine also serves other things and you would rather not run a
    # host firewall.
    allowed_client_ips: list[str] = field(default_factory=list)
    # The URL clients reach this server on. Needed for the install page, because
    # behind a reverse proxy the server only sees the proxy's request.
    public_url: str = ""
    # What the install script pip-installs. A wheel published into data_dir/dist
    # takes precedence, so a server with no route to PyPI still works.
    package_spec: str = "cloudmorrow[tui,agent]"
    # Who a push service should complain to about this server: a mailto:
    # or an https: URL, as VAPID asks for. Empty derives one from
    # public_url, which is the truest answer the server has on its own.
    push_subject: str = ""
    # Whether an admin may deploy from git over the API (`cloudmorrow update
    # server`). It can only move to a commit already on the configured
    # remote, but it is still "an admin token can change the running code" —
    # set it false to require ssh, and the endpoint answers 403.
    allow_api_update: bool = True
    # The unit the API update stops so systemd starts it again on new code.
    service_name: str = "cloudmorrow"
    # Where the weather on the app's front page is for: a place name
    # ("Copenhagen", "Aarhus, Denmark") or "latitude,longitude". Empty and
    # the page says nothing about the weather; nothing else minds.
    weather_place: str = ""
    # Where the Quill Catalog is read from: a URL to its catalog.toml, or a
    # local path to one (or to a checkout of the catalog repository).
    quill_catalog: str = DEFAULT_QUILL_CATALOG
    config_path: Path | None = None

    @property
    def tls_required(self) -> bool:
        if self.require_tls is not None:
            return self.require_tls
        return self.public_url.lower().startswith("https://")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cloudmorrow.db"

    @property
    def secrets_key_path(self) -> Path:
        """The key everything is sealed with. Back it up with the data, and apart from it."""
        return self.key_file or self.data_dir / "secrets.key"

    @property
    def vapid_key_path(self) -> Path:
        """The key web pushes are signed with. Lose it and every phone
        subscribed under it has to be asked again — nothing else breaks."""
        return self.data_dir / "vapid.key"

    @property
    def quills_dir(self) -> Path:
        """Installed Quills, one folder each, as their release shipped them."""
        return self.data_dir / "quills"

    @property
    def datamodels_dir(self) -> Path:
        """The foundational datamodels this server has records of, or may."""
        return self.data_dir / "datamodels"

    @property
    def dist_dir(self) -> Path:
        """Where `cloudmorrow-server publish` puts wheels for the install script."""
        return self.data_dir / "dist"

    def published_wheel(self) -> Path | None:
        """The newest published wheel, if there is one."""
        if not self.dist_dir.is_dir():
            return None
        wheels = sorted(self.dist_dir.glob("*.whl"), key=lambda p: p.stat().st_mtime)
        return wheels[-1] if wheels else None

    def resolve_package_spec(self, base_url: str) -> str:
        wheel = self.published_wheel()
        if wheel is not None:
            # PEP 508 direct reference: extras on a bare URL are not valid.
            return f"cloudmorrow[tui,agent] @ {base_url.rstrip('/')}/dist/{wheel.name}"
        return self.package_spec

    def shares_root(self, username: str = "") -> Path:
        """The Shares folder on the server — one, whoever *username* is.

        Shares are an admin's to make and are for everyone's machines, so
        they sit together in the Cloudmorrow directory rather than under the
        account that happened to make them.
        """
        if self.shares_dir is not None:
            return self.shares_dir
        return self.notes_dir / "Shares"

    def user_base(self, username: str) -> Path:
        """The directory holding everything that belongs to *username*."""
        return self.notes_dir / username if self.per_user_dirs else self.notes_dir

    def notes_root(self, username: str) -> Path:
        """Where a user's notes live: `<base>/notes`, and nowhere else.

        Notes belong to the person, not to a project. The extra `notes` level
        leaves room for other per-user data beside them later.
        """
        return self.user_base(username) / "notes"

    def files_root(self, username: str) -> Path:
        """Where a user's own files live: `<base>/files`, beside their notes.

        The drive every account has on the server, served as `my-files`.
        With one shared tree (`per_user_dirs` off) it is one drive for
        everyone, the same as the notes then are.
        """
        return self.user_base(username) / "files"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def ensure_secret_key(self) -> str:
        """Return the signing key, generating and persisting one on first boot."""
        if self.secret_key:
            return self.secret_key
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            self.secret_key = key_file.read_text(encoding="utf-8").strip()
            return self.secret_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secret_key = secrets.token_urlsafe(48)
        key_file.write_text(self.secret_key + "\n", encoding="utf-8")
        key_file.chmod(0o600)
        return self.secret_key


def _config_file() -> Path | None:
    override = os.environ.get(f"{ENV_PREFIX}SERVER_CONFIG")
    if override:
        path = Path(override).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"config file not found: {path}")
        return path
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    return None


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(path: Path | None = None) -> ServerConfig:
    """Load config from TOML (if present), then apply CLOUDMORROW_* env overrides."""
    config = ServerConfig()
    source = path or _config_file()
    if source is not None:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
        section = data.get("server", data)
        for key in (
            "name",
            "notes_dir",
            "data_dir",
            "per_user_dirs",
            "shares_dir",
            "host",
            "port",
            "secret_key",
            "key_file",
            "require_tls",
            "token_ttl_hours",
            "cors_origins",
            "allowed_client_ips",
            "public_url",
            "package_spec",
            "push_subject",
            "allow_api_update",
            "service_name",
            "weather_place",
            "quill_catalog",
        ):
            if key in section:
                value = section[key]
                if key in {"notes_dir", "data_dir", "shares_dir", "key_file"}:
                    value = Path(str(value)).expanduser()
                setattr(config, key, value)
        config.config_path = source

    env_map = {
        "NAME": ("name", str),
        "NOTES_DIR": ("notes_dir", lambda v: Path(v).expanduser()),
        "DATA_DIR": ("data_dir", lambda v: Path(v).expanduser()),
        "PER_USER_DIRS": ("per_user_dirs", _env_bool),
        "SHARES_DIR": ("shares_dir", lambda v: Path(v).expanduser()),
        "HOST": ("host", str),
        "PORT": ("port", int),
        "SECRET_KEY": ("secret_key", str),
        "KEY_FILE": ("key_file", lambda v: Path(v).expanduser()),
        "REQUIRE_TLS": ("require_tls", _env_bool),
        "TOKEN_TTL_HOURS": ("token_ttl_hours", int),
        "CORS_ORIGINS": ("cors_origins", lambda v: [o.strip() for o in v.split(",") if o.strip()]),
        "ALLOWED_CLIENT_IPS": (
            "allowed_client_ips",
            lambda v: [o.strip() for o in v.split(",") if o.strip()],
        ),
        "PUBLIC_URL": ("public_url", str),
        "PACKAGE_SPEC": ("package_spec", str),
        "PUSH_SUBJECT": ("push_subject", str),
        "ALLOW_API_UPDATE": ("allow_api_update", _env_bool),
        "SERVICE_NAME": ("service_name", str),
        "WEATHER_PLACE": ("weather_place", str),
        "QUILL_CATALOG": ("quill_catalog", str),
    }
    for env_suffix, (attr, caster) in env_map.items():
        raw = os.environ.get(ENV_PREFIX + env_suffix)
        if raw is not None:
            setattr(config, attr, caster(raw))

    config.name = config.name.strip() or "Cloudmorrow"
    config.notes_dir = Path(config.notes_dir).expanduser()
    config.data_dir = Path(config.data_dir).expanduser()
    if config.shares_dir is not None:
        config.shares_dir = Path(config.shares_dir).expanduser()
    if config.key_file is not None:
        config.key_file = Path(config.key_file).expanduser()
    return config
