"""A project on this machine: its folder, its git repository and its .env files.

A `list` screen that binds `vault` (docs/QUILLS.md) is a list of projects:
each record names the vault its secrets are kept in, and perhaps its git
repository (`repo`) and which file each environment was read from
(`env_files`). The command line (`cm <quill> init`, `update`, `clone`,
`secrets`) and the terminal app both do the work here, so the two can never
disagree about which file is which environment.

The files and the environments:

- `.env.<name>` is the environment `<name>`: `.env.prod` is `prod`.
- `.env` is `local`, unless there is a `.env.local` beside it; then it is
  `default`.
- `.env.example`, `.sample`, `.template`, `.dist` and `.defaults` are left
  alone: they are meant to be committed. So is any file git tracks.

Writing them back, the vault is what is true, but a file is never made to
forget a key it has and the vault does not: that file is left as it is and
said, until it is imported or the write is forced. Each is written private
(mode 600).

Where each project is on this machine is remembered in the client's config
directory (checkouts.json), by server and vault, so `update` finds it from
anywhere.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow import dotenv
from cloudmorrow.locations import config_dir
from cloudmorrow.privatefile import write_private

# The shape the server holds a vault and an environment to.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
# What a file meant for committing ends in.
EXAMPLES = frozenset({"example", "examples", "sample", "template", "dist", "defaults", "schema"})


class CheckoutError(RuntimeError):
    """Something about a folder or its repository, said plainly."""


# -- the files ---------------------------------------------------------------------


def environment_of(name: str, beside: set[str] | frozenset[str] = frozenset()) -> str | None:
    """Which environment a file of this name is, or None when it is not one of ours."""
    if name == ".env":
        return "default" if ".env.local" in beside else dotenv.DEFAULT_ENVIRONMENT
    if not name.startswith(".env."):
        return None
    rest = name[len(".env.") :].lower()
    if not rest or set(rest.split(".")) & EXAMPLES or not NAME_RE.match(rest):
        return None
    return rest


def file_for(environment: str, remembered: dict[str, str]) -> str:
    """The file an environment is written to: the one it was read from, else `.env` or `.env.<it>`."""
    if remembered.get(environment):
        return remembered[environment]
    return ".env" if environment == dotenv.DEFAULT_ENVIRONMENT else f".env.{environment}"


def env_files(folder: Path) -> dict[str, str]:
    """The .env files in *folder* that are secrets, by environment: {"prod": ".env.prod"}."""
    names = {p.name for p in folder.iterdir() if p.is_file() and (p.name == ".env" or p.name.startswith(".env."))}
    tracked = _tracked(folder, names)
    found: dict[str, str] = {}
    for name in sorted(names - tracked):
        environment = environment_of(name, names)
        if environment:
            found[environment] = name
    return found


def _tracked(folder: Path, names: set[str]) -> set[str]:
    """Which of *names* git already commits: those are not secrets to us."""
    if not names or not (folder / ".git").exists():
        return set()
    try:
        answer = subprocess.run(
            ["git", "ls-files", "--", *sorted(names)], cwd=folder, capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return set(answer.stdout.split()) if answer.returncode == 0 else set()


def read_file(path: Path) -> dict[str, str]:
    try:
        return dotenv.parse(path.read_text(encoding="utf-8"))
    except dotenv.DotenvError as exc:
        raise CheckoutError(f"{path.name}: {exc}") from exc


@dataclass
class Written:
    """What writing one environment to its file did."""

    environment: str
    file: str
    state: str  # written, unchanged, kept
    changed: list[str] = field(default_factory=list)
    only_here: list[str] = field(default_factory=list)


def write_file(path: Path, environment: str, entries: dict[str, str], *, header: str, force: bool = False) -> Written:
    """Write an environment to its file, unless the file knows keys the vault does not."""
    before = read_file(path) if path.exists() else None
    if before == entries:
        return Written(environment, path.name, "unchanged")
    only_here = sorted(set(before or {}) - set(entries))
    if only_here and not force:
        return Written(environment, path.name, "kept", only_here=only_here)
    changed = sorted(k for k in entries if (before or {}).get(k) != entries[k])
    write_private(path, dotenv.dump(entries, header=header))
    return Written(environment, path.name, "written", changed=changed, only_here=only_here)


# -- names -------------------------------------------------------------------------


def vault_name(text: str) -> str:
    """A vault for a project called *text*: `My App` → `my-app`."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", text.strip().lower()).strip("-._")
    return slug[:32].rstrip("-._") or "project"


# -- git ---------------------------------------------------------------------------


def _git(folder: Path, *args: str, timeout: float = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise CheckoutError("git is not on this machine") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckoutError(f"git {args[0]} took too long") from exc


def remote(folder: Path) -> str:
    """Where the checkout in *folder* came from (origin), or "" when it is no checkout."""
    if not (folder / ".git").exists():
        return ""
    answer = _git(folder, "remote", "get-url", "origin", timeout=15)
    return answer.stdout.strip() if answer.returncode == 0 else ""


def same_repo(a: str, b: str) -> bool:
    """Whether two ways of writing a repository are the same one: ssh or https, .git or not."""

    def bare(url: str) -> str:
        url = url.strip().lower().removesuffix("/").removesuffix(".git")
        url = re.sub(r"^[a-z+]+://", "", url)
        url = re.sub(r"^[^@/]+@", "", url)
        return url.replace(":", "/", 1) if "/" in url and ":" in url.split("/", 1)[0] else url

    return bool(a.strip() and b.strip()) and bare(a) == bare(b)


async def clone(url: str, folder: Path) -> None:
    if folder.exists() and any(folder.iterdir()):
        raise CheckoutError(f"{folder} is there already, and not empty")
    folder.parent.mkdir(parents=True, exist_ok=True)
    answer = await asyncio.to_thread(_git, folder.parent, "clone", "--quiet", url, str(folder))
    if answer.returncode != 0:
        raise CheckoutError(f"git clone: {answer.stderr.strip() or 'failed'}")


async def pull(folder: Path) -> str:
    """`git pull --ff-only`; what git said, in one line."""
    answer = await asyncio.to_thread(_git, folder, "pull", "--ff-only", "--quiet")
    if answer.returncode != 0:
        raise CheckoutError(f"git pull: {answer.stderr.strip() or 'failed'}")
    head = await asyncio.to_thread(_git, folder, "log", "-1", "--format=%h %s", timeout=15)
    return head.stdout.strip()


# -- where each project is, on this machine ------------------------------------------


def _places_path() -> Path:
    return config_dir() / "checkouts.json"


def _places() -> dict[str, str]:
    try:
        return dict(json.loads(_places_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def remembered(server: str, vault: str) -> Path | None:
    place = _places().get(f"{server}|{vault}")
    return Path(place) if place and Path(place).is_dir() else None


def remember(server: str, vault: str, folder: Path) -> None:
    places = _places()
    places[f"{server}|{vault}"] = str(folder.resolve())
    write_private(_places_path(), json.dumps(places, indent=2, sort_keys=True) + "\n")


# -- the projects ------------------------------------------------------------------


@dataclass
class Projects:
    """A screen of projects: which fields are the vault, the repository and the files."""

    model: str
    title: str
    vault: str
    repo: str = ""
    files: str = ""

    @classmethod
    def of(cls, screen: dict, models: dict) -> Projects | None:
        """The projects a screen is, or None when it binds no `vault`."""
        if not screen.get("vault") or screen.get("kit") != "list":
            return None
        model = models.get(screen["model"]) or {}
        return cls(
            model=screen["model"],
            title=screen.get("title") or model.get("title") or "name",
            vault=screen["vault"],
            repo=screen.get("repo") or "",
            files=screen.get("env_files") or "",
        )

    def name(self, record: dict) -> str:
        return str(record["fields"].get(self.title) or record["id"])

    def vault_of(self, record: dict) -> str:
        return str(record["fields"].get(self.vault) or "") or vault_name(self.name(record))

    def repo_of(self, record: dict) -> str:
        return str(record["fields"].get(self.repo) or "") if self.repo else ""

    def files_of(self, record: dict) -> dict[str, str]:
        value = record["fields"].get(self.files) if self.files else None
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

    def here(self, records: list[dict], folder: Path, server: str) -> dict | None:
        """The project *folder* is a checkout of: by its origin, where it was put, or its name."""
        folder = folder.resolve()
        origin = remote(folder)
        if origin and self.repo:
            found = [r for r in records if same_repo(self.repo_of(r), origin)]
            if len(found) == 1:
                return found[0]
        for record in records:
            if remembered(server, self.vault_of(record)) == folder:
                return record
        slug = vault_name(folder.name)
        found = [r for r in records if self.vault_of(r) == slug]
        return found[0] if len(found) == 1 else None


@dataclass
class Imported:
    environment: str
    file: str
    result: dict


async def import_file(api, vault: str, environment: str, path: Path, *, prune: bool = False) -> Imported:
    """One .env file into one environment of a vault."""
    entries = read_file(path)
    result = await api.import_secrets(entries, environment, prune=prune, filename=path.name, vault=vault)
    return Imported(environment, path.name, result)


async def export_file(api, vault: str, environment: str, path: Path, *, force: bool = False) -> Written:
    """One environment of a vault into one .env file."""
    entries = await api.export_secrets(environment, vault=vault)
    header = f"{vault} · {environment}\nWritten by cloudmorrow. Keep it out of version control."
    return write_file(path, environment, entries, header=header, force=force)


async def init(api, projects: Projects, folder: Path, *, name: str = "") -> tuple[dict, bool, list[Imported]]:
    """Make *folder* a project (or find the one it is) and read its .env files into the vault.

    The project, whether it was made just now, and what each file did.
    """
    folder = folder.resolve()
    server = api.config.api_url
    if not folder.is_dir():
        raise CheckoutError(f"{folder} is not a folder")
    found = env_files(folder)
    records = await api.records(projects.model)
    record = projects.here(records, folder, server)
    made = record is None
    if made:
        fields: dict = {projects.title: name or folder.name, projects.vault: vault_name(name or folder.name)}
        origin = remote(folder)
        if projects.repo and origin:
            fields[projects.repo] = origin
        if projects.files:
            fields[projects.files] = found
        record = await api.create_record(projects.model, fields)
    elif projects.files and found:
        # Remembered as it is here now, beside what other machines read.
        files = {**projects.files_of(record), **found}
        if files != projects.files_of(record):
            record = await api.update_record(projects.model, record["id"], {projects.files: files}, rev=record["rev"])
    vault = projects.vault_of(record)
    done = [await import_file(api, vault, environment, folder / file) for environment, file in found.items()]
    remember(server, vault, folder)
    return record, made, done


async def write_all(api, projects: Projects, record: dict, folder: Path, *, force: bool = False) -> list[Written]:
    """Every environment of the project's vault, into its file in *folder*."""
    vault = projects.vault_of(record)
    files = projects.files_of(record)
    environments = [e["environment"] for e in await api.secret_environments(vault=vault)]
    written = [
        await export_file(api, vault, environment, folder / file_for(environment, files), force=force)
        for environment in environments
    ]
    remember(api.config.api_url, vault, folder)
    return written
