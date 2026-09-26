"""Quills: reading a manifest, fetching a release, installing it, and what it adds.

A Quill is a folder with a `quill.toml` — a checkout, a release tarball, or a
folder somebody is working in. This module reads the manifest and checks it
against the datamodels there are; lists everything the Quill would add, for
the install sheet; copies it into `<data_dir>/quills/<id>/` with the
foundational datamodels it uses into `<data_dir>/datamodels/`; and keeps the
registry of what is installed, which the record store, the jobs, the routes
and every client read.

The catalog is a `catalog.toml`, read from `quill_catalog` in the config: a
URL, or a local path. A Quill is fetched as the tarball of its pinned ref,
so a server needs no git; a local path is used as it is, which is how one is
developed.

Nothing here runs code from a Quill. Services, webhooks and APIs are read,
checked and listed; running them is the next piece of the core, and the
install sheet says so.

See docs/QUILLS.md for the format.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import shutil
import tarfile
import tempfile
import threading
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.datamodels import (
    Datamodel,
    DatamodelError,
    load_datamodel,
    parse_datamodel,
    parse_duration,
)
from cloudmorrow.server.records import NEVER_FOR_ASSISTANTS

__all__ = [
    "KIT",
    "KIT_READY",
    "Catalog",
    "Manifest",
    "QuillError",
    "QuillRegistry",
    "fetch",
    "load_catalog",
    "parse_manifest",
]

MANIFEST = "quill.toml"
ORIGIN = ".origin.json"

# The screens every surface draws. A Quill has these and nothing else.
KIT = ("list", "board", "detail", "form", "calendar", "thread", "grid", "editor")
# The ones every surface draws *today*. A screen of another kind is refused at
# install, so a Quill never lands with a tab that draws nothing somewhere.
KIT_READY = frozenset({"list", "board", "detail", "form", "calendar", "grid", "editor", "thread"})

# How a thread screen may make a space: in one of the scopes, or `direct`,
# found-or-made between the people picked.
MADE_AS = ("personal", "shared", "public", "direct")

JOB_ACTIONS = frozenset({"expire", "run"})
SEED_KINDS = frozenset({"per-owner", "once"})

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")

# Surfaces a kit screen is drawn on, for the install sheet to say so.
SURFACES = ("phone", "web", "terminal", "command line", "assistant")

FETCH_TIMEOUT = 30
MAX_DOWNLOAD = 50 * 1024 * 1024


class QuillError(ValueError):
    """A Quill that cannot be installed, and why, in words for a person."""


# -- the manifest --------------------------------------------------------------------
@dataclass(slots=True)
class Manifest:
    id: str
    name: str
    version: str
    summary: str
    category: str
    icon: str
    publisher: str
    license: str
    uses: tuple[str, ...]
    extends: dict[str, dict[str, dict]]
    introduces: tuple[Datamodel, ...]
    grants: tuple[dict, ...]
    screens: tuple[dict, ...]
    jobs: tuple[dict, ...]
    datasets: tuple[dict, ...]
    services: tuple[dict, ...]
    webhooks: tuple[dict, ...]
    apis: tuple[dict, ...]
    # What it does, one line each, for the catalog and the install sheet.
    features: tuple[str, ...] = ()
    readme: str = ""
    folder: Path | None = None
    origin: dict = field(default_factory=dict)

    @property
    def models(self) -> frozenset[str]:
        """Every datamodel this Quill may touch: used, introduced, granted."""
        return frozenset(
            (
                *self.uses,
                *(m.id for m in self.introduces),
                *self.extends,
                *(g["model"] for g in self.grants),
            )
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "summary": self.summary,
            "features": list(self.features),
            "category": self.category,
            "icon": self.icon,
            "publisher": self.publisher,
            "license": self.license,
            "uses": list(self.uses),
            "extends": {model: list(fields) for model, fields in self.extends.items()},
            "introduces": [m.id for m in self.introduces],
            "grants": list(self.grants),
            "screens": list(self.screens),
            "jobs": list(self.jobs),
            "datasets": [
                {k: v for k, v in d.items() if k != "records"} | {"count": len(d["records"])}
                for d in self.datasets
            ],
            "services": list(self.services),
            "webhooks": list(self.webhooks),
            "apis": list(self.apis),
            "origin": dict(self.origin),
        }


def _table_list(data: dict, key: str, where: str) -> list[dict]:
    items = data.get(key, [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise QuillError(f"{where}: [[{key}]] must be tables")
    return items


def _ids_unique(items: list[dict], what: str, where: str) -> None:
    seen: set[str] = set()
    for item in items:
        item_id = str(item.get("id", ""))
        if not ID_RE.match(item_id.replace("-", "_")):
            raise QuillError(f"{where}: every {what} needs an id of lowercase letters")
        if item_id in seen:
            raise QuillError(f"{where}: two {what}s called {item_id!r}")
        seen.add(item_id)


def _dataset_records(folder: Path | None, item: dict, where: str) -> list[dict]:
    records = item.get("records")
    source = item.get("file")
    if (records is None) == (source is None):
        raise QuillError(
            f"{where}: dataset {item.get('id')!r} has `records` or a `file`, one of them"
        )
    if records is not None:
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise QuillError(f"{where}: dataset {item.get('id')!r} records are tables")
        return records
    if folder is None:
        raise QuillError(
            f"{where}: dataset {item.get('id')!r} names a file, and there is no folder"
        )
    path = (folder / str(source)).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        raise QuillError(f"{where}: dataset file {source!r} is not in the Quill")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".csv":
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    if path.suffix == ".toml":
        loaded = tomllib.loads(text).get("records", [])
        if not isinstance(loaded, list):
            raise QuillError(f"{where}: {source} has no [[records]]")
        return loaded
    raise QuillError(f"{where}: a dataset file is .csv or .toml")


def parse_manifest(data: dict, folder: Path | None = None) -> Manifest:
    """A manifest, checked on its own. `QuillRegistry.check` checks it against the rest."""
    head = data.get("quill")
    if not isinstance(head, dict):
        raise QuillError("quill.toml has no [quill] table")
    quill_id = str(head.get("id", ""))
    if not ID_RE.match(quill_id):
        raise QuillError(f"quill id {quill_id!r}: lowercase letters, digits and _, 2 to 32 of them")
    where = quill_id
    name = str(head.get("name", "")).strip()
    if not name:
        raise QuillError(f"{where}: [quill] needs a name")
    version = str(head.get("version", ""))
    if not VERSION_RE.match(version):
        raise QuillError(f"{where}: version {version!r} is major.minor.patch")

    uses_table = data.get("uses", {})
    if not isinstance(uses_table, dict):
        raise QuillError(f"{where}: [uses] is a table")
    uses = tuple(str(m) for m in uses_table.get("datamodels", ()))

    extends: dict[str, dict[str, dict]] = {}
    for item in _table_list(data, "extends", where):
        model = str(item.get("model", ""))
        fields = item.get("fields")
        if not model or not isinstance(fields, dict) or not fields:
            raise QuillError(f"{where}: [[extends]] needs a model and [extends.fields]")
        if model in extends:
            raise QuillError(f"{where}: {model} is extended twice; put the fields in one table")
        extends[model] = fields

    introduces: list[Datamodel] = []
    if folder is not None and (folder / "datamodels").is_dir():
        for path in sorted((folder / "datamodels").glob("*.toml")):
            try:
                introduces.append(load_datamodel(path, source=quill_id))
            except DatamodelError as exc:
                raise QuillError(f"{where}: {exc}") from exc

    grants = _table_list(data, "grants", where)
    for grant in grants:
        if not grant.get("model") or grant.get("access") not in ("read", "write"):
            raise QuillError(f"{where}: a grant is a model, access read or write, and why")
        if not str(grant.get("why", "")).strip():
            raise QuillError(f"{where}: the grant on {grant['model']} says why; a person reads it")

    screens = _table_list(data, "screens", where)
    _ids_unique(screens, "screen", where)
    for screen in screens:
        kit = screen.get("kit")
        if kit not in KIT:
            raise QuillError(f"{where}: screen {screen['id']!r} kit is one of {', '.join(KIT)}")
        if kit not in KIT_READY:
            raise QuillError(
                f"{where}: screen {screen['id']!r} is a {kit}, which the kit does not draw on every"
                f" surface yet; today it is {', '.join(sorted(KIT_READY))}"
            )
        if not screen.get("model"):
            raise QuillError(f"{where}: screen {screen['id']!r} names a model")

    jobs = _table_list(data, "jobs", where)
    _ids_unique(jobs, "job", where)
    for job in jobs:
        if job.get("action") not in JOB_ACTIONS:
            raise QuillError(
                f"{where}: job {job['id']!r} action is one of {', '.join(sorted(JOB_ACTIONS))}"
            )
        for key in ("every", "after"):
            if key in job:
                try:
                    parse_duration(str(job[key]))
                except ValueError as exc:
                    raise QuillError(f"{where}: job {job['id']!r} {key}: {exc}") from exc
        if job["action"] == "expire" and not (
            job.get("model") and job.get("field") and job.get("after")
        ):
            raise QuillError(f"{where}: an expire job names a model, a field and after")

    datasets = []
    raw_sets = _table_list(data, "datasets", where)
    _ids_unique(raw_sets, "dataset", where)
    for item in raw_sets:
        if item.get("seed") not in SEED_KINDS:
            raise QuillError(
                f"{where}: dataset {item['id']!r} seed is {', '.join(sorted(SEED_KINDS))}"
            )
        if not item.get("model"):
            raise QuillError(f"{where}: dataset {item['id']!r} names a model")
        datasets.append(
            {
                **{k: v for k, v in item.items() if k not in ("records", "file")},
                "records": _dataset_records(folder, item, where),
            }
        )

    services = _table_list(data, "services", where)
    _ids_unique(services, "service", where)
    for service in services:
        command = service.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(c, str) for c in command)
        ):
            raise QuillError(f"{where}: service {service['id']!r} command is a list of strings")
    webhooks = _table_list(data, "webhooks", where)
    _ids_unique(webhooks, "webhook", where)
    apis = _table_list(data, "apis", where)
    _ids_unique(apis, "api", where)
    service_ids = {s["id"] for s in services}
    for hook in webhooks:
        if not (hook.get("model") or hook.get("forward")):
            raise QuillError(
                f"{where}: webhook {hook['id']!r} makes a record in a model, or forwards to a service"
            )
        if hook.get("forward") and hook["forward"] not in service_ids:
            raise QuillError(
                f"{where}: webhook {hook['id']!r} forwards to a service it does not have"
            )
    for api in apis:
        if api.get("service") not in service_ids:
            raise QuillError(f"{where}: api {api['id']!r} is served by one of its services")

    readme = ""
    if folder is not None and (folder / "README.md").is_file():
        readme = (folder / "README.md").read_text(encoding="utf-8")

    return Manifest(
        id=quill_id,
        name=name,
        version=version,
        summary=str(head.get("summary", "")),
        features=_features(head, where),
        category=str(head.get("category", "")),
        icon=str(head.get("icon", "")) or quill_id,
        publisher=str(head.get("publisher", "")),
        license=str(head.get("license", "")),
        uses=uses,
        extends=extends,
        introduces=tuple(introduces),
        grants=tuple(grants),
        screens=tuple(screens),
        jobs=tuple(jobs),
        datasets=tuple(datasets),
        services=tuple(services),
        webhooks=tuple(webhooks),
        apis=tuple(apis),
        readme=readme,
        folder=folder,
    )


def _features(head: dict, where: str) -> tuple[str, ...]:
    features = head.get("features", [])
    if not isinstance(features, list) or not all(isinstance(f, str) and f.strip() for f in features):
        raise QuillError(f"{where}: features is a list of one-line sentences")
    return tuple(f.strip() for f in features)


def load_manifest(folder: Path) -> Manifest:
    path = folder / MANIFEST
    if not path.is_file():
        raise QuillError(f"there is no {MANIFEST} in {folder.name}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise QuillError(f"{MANIFEST}: {exc}") from exc
    manifest = parse_manifest(data, folder)
    origin = folder / ORIGIN
    if origin.is_file():
        try:
            manifest.origin = json.loads(origin.read_text(encoding="utf-8"))
        except ValueError:
            manifest.origin = {}
    return manifest


# -- fetching --------------------------------------------------------------------------
_GITHUB_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def tarball_url(repo: str, ref: str) -> str:
    """Where a release of *repo* at *ref* is downloaded from, as a tarball."""
    match = _GITHUB_RE.match(repo)
    if match:
        return f"https://codeload.github.com/{match.group(1)}/{match.group(2)}/tar.gz/{urllib.parse.quote(ref)}"
    if repo.endswith((".tar.gz", ".tgz")):
        return repo
    raise QuillError(f"{repo} is not a GitHub repository or a tarball URL")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "cloudmorrow"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
            data = response.read(MAX_DOWNLOAD + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise QuillError(f"could not fetch {url}: {exc}") from exc
    if len(data) > MAX_DOWNLOAD:
        raise QuillError(f"{url} is bigger than a Quill should be")
    return data


def fetch(source: str, ref: str = "", *, base: Path | None = None, into: Path) -> Path:
    """A folder holding *source*: a local path as it is, or a release unpacked into *into*.

    *base* is what a relative local path is relative to: the catalog's own folder.
    """
    if not source.startswith(("https://", "http://")):
        path = Path(source).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        if not path.is_dir():
            raise QuillError(f"{source} is not a folder")
        return path.resolve()
    if not ref:
        raise QuillError(f"{source}: a release is fetched at a pinned ref")
    data = _download(tarball_url(source, ref))
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            archive.extractall(into, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise QuillError(f"{source}@{ref} is not a tarball that unpacks: {exc}") from exc
    tops = [p for p in into.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else into


# -- the catalog -----------------------------------------------------------------------
@dataclass(slots=True)
class Catalog:
    categories: list[dict]
    quills: list[dict]
    datamodels: dict
    # The folder relative paths in it are relative to, when it is local.
    base: Path | None = None

    def entry(self, quill_id: str) -> dict:
        for entry in self.quills:
            if entry.get("id") == quill_id:
                return entry
        raise QuillError(f"{quill_id} is not in the catalog")


def parse_catalog(data: dict, base: Path | None = None) -> Catalog:
    quills = data.get("quills", [])
    for entry in quills:
        if not entry.get("id") or not entry.get("repo"):
            raise QuillError("every Quill in the catalog has an id and a repo")
    return Catalog(
        categories=list(data.get("categories", [])),
        quills=list(quills),
        datamodels=dict(data.get("datamodels", {})),
        base=base,
    )


def load_catalog(location: str) -> Catalog:
    if location.startswith(("https://", "http://")):
        text = _download(location).decode("utf-8")
        base = None
    else:
        path = Path(location).expanduser()
        if path.is_dir():
            path = path / "catalog.toml"
        if not path.is_file():
            raise QuillError(f"no catalog at {location}")
        text = path.read_text(encoding="utf-8")
        base = path.parent
    try:
        return parse_catalog(tomllib.loads(text), base)
    except tomllib.TOMLDecodeError as exc:
        raise QuillError(f"the catalog does not parse: {exc}") from exc


# -- the registry ----------------------------------------------------------------------
class QuillRegistry:
    """What is installed: the Quills, the datamodels, and what each adds.

    Read from disk at boot and after every install; everything else asks it.
    A Quill whose folder no longer checks out is left out and listed in
    `broken`, rather than stopping the server.
    """

    def __init__(self, quills_dir: Path, datamodels_dir: Path, catalog: str = "") -> None:
        self.quills_dir = quills_dir
        self.datamodels_dir = datamodels_dir
        self.catalog_location = catalog
        self._lock = threading.RLock()
        self.quills: dict[str, Manifest] = {}
        self.foundation: dict[str, Datamodel] = {}
        self.datamodels: dict[str, Datamodel] = {}
        self.broken: dict[str, str] = {}
        # What the last plan found to copy in: foundational datamodel -> file.
        self._pending_paths: dict[str, Path] = {}
        self.reload()

    # -- reading what is there -------------------------------------------------------
    def reload(self) -> None:
        with self._lock:
            foundation: dict[str, Datamodel] = {}
            if self.datamodels_dir.is_dir():
                for path in sorted(self.datamodels_dir.glob("*.toml")):
                    try:
                        model = load_datamodel(path)
                    except DatamodelError as exc:
                        self.broken[path.name] = str(exc)
                        continue
                    foundation[model.id] = model
            quills: dict[str, Manifest] = {}
            broken: dict[str, str] = {}
            if self.quills_dir.is_dir():
                for folder in sorted(p for p in self.quills_dir.iterdir() if p.is_dir()):
                    if folder.name.startswith("."):
                        continue
                    try:
                        quills[folder.name] = load_manifest(folder)
                    except QuillError as exc:
                        broken[folder.name] = str(exc)
            models, problems = _assemble(foundation, quills)
            for quill_id, problem in problems.items():
                broken[quill_id] = problem
                quills.pop(quill_id, None)
            if problems:
                models, _ = _assemble(foundation, quills)
            self.foundation = foundation
            self.quills = quills
            self.datamodels = models
            self.broken = broken

    def models(self) -> dict[str, Datamodel]:
        return self.datamodels

    def expiries(self) -> dict[str, tuple[str, dt.timedelta]]:
        """model -> (field, after), from every installed Quill's expire jobs."""
        found: dict[str, tuple[str, dt.timedelta]] = {}
        for manifest in self.quills.values():
            for job in manifest.jobs:
                if job["action"] == "expire":
                    found[job["model"]] = (job["field"], parse_duration(job["after"]))
        return found

    def users_of(self, model_id: str) -> list[str]:
        return sorted(q.id for q in self.quills.values() if model_id in q.models)

    def seeds_for(self, model_id: str) -> list[tuple[Manifest, dict]]:
        return [
            (manifest, dataset)
            for manifest in self.quills.values()
            for dataset in manifest.datasets
            if dataset["model"] == model_id
        ]

    # -- what a Quill would add ------------------------------------------------------
    def plan(self, folder: Path, datamodels_source: Path | None = None) -> dict:
        """Everything installing *folder* would add, checked, for the install sheet."""
        manifest = load_manifest(folder)
        needed = self._needed_foundation(manifest, datamodels_source)
        foundation = {**self.foundation, **needed}
        quills = {
            **{k: v for k, v in self.quills.items() if k != manifest.id},
            manifest.id: manifest,
        }
        models, problems = _assemble(foundation, quills)
        if manifest.id in problems:
            raise QuillError(problems[manifest.id])
        _check_bindings(manifest, models)
        plan = describe(
            manifest,
            models,
            new_foundation=sorted(set(needed) - set(self.foundation)),
            installed=self.quills.get(manifest.id),
        )
        # The datamodels as they would be after installing, for a preview.
        touched = set(manifest.models)
        touched |= {
            f.to for m in touched if m in models for f in models[m].fields if f.kind == "link"
        }
        plan["models"] = {m: models[m].to_dict() for m in sorted(touched) if m in models}
        return plan

    def _needed_foundation(self, manifest: Manifest, source: Path | None) -> dict[str, Datamodel]:
        """The foundational datamodels *manifest* needs that this server lacks, found in *source*."""
        introduced = {m.id for m in manifest.introduces}
        wanted = {
            m
            for m in (*manifest.uses, *manifest.extends, *(g["model"] for g in manifest.grants))
            if m not in introduced and m not in self.foundation
        }
        # Links from what it uses pull in their targets too: a task needs its board.
        found: dict[str, Datamodel] = {}
        available = _scan_datamodels(source) if source is not None else {}
        queue = list(wanted)
        while queue:
            model_id = queue.pop()
            if model_id in found or model_id in self.foundation or model_id in introduced:
                continue
            if "." in model_id and model_id.split(".", 1)[0] in self.quills:
                continue
            if model_id not in available:
                raise QuillError(
                    f"{manifest.id} uses the datamodel {model_id}, which is neither installed nor"
                    " in the datamodels it came with"
                )
            found[model_id] = available[model_id][0]
            queue.extend(f.to for f in found[model_id].fields if f.kind == "link")
        found_paths = {model_id: available[model_id][1] for model_id in found}
        self._pending_paths = found_paths
        return found

    # -- installing --------------------------------------------------------------------
    def install(
        self, folder: Path, datamodels_source: Path | None = None, *, origin: dict | None = None
    ) -> dict:
        """Install the Quill in *folder*, replacing an earlier version of it. Returns the plan."""
        with self._lock:
            plan = self.plan(folder, datamodels_source)
            manifest_id = plan["id"]
            self.datamodels_dir.mkdir(parents=True, exist_ok=True)
            for model_id, path in self._pending_paths.items():
                shutil.copyfile(path, self.datamodels_dir / f"{model_id}.toml")
            self.quills_dir.mkdir(parents=True, exist_ok=True)
            target = self.quills_dir / manifest_id
            staging = self.quills_dir / f".{manifest_id}.new"
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(
                folder, staging, ignore=shutil.ignore_patterns(".git", "__pycache__", ORIGIN)
            )
            (staging / ORIGIN).write_text(
                json.dumps(
                    {
                        **(origin or {}),
                        # To the microsecond: Quills installed together at
                        # boot keep the order they were installed in, which
                        # is the order of their tabs.
                        "installed_at": dt.datetime.now(tz=dt.UTC).isoformat(
                            timespec="microseconds"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
            self.reload()
            if manifest_id in self.broken:
                raise QuillError(self.broken[manifest_id])
            return plan

    def uninstall(self, quill_id: str) -> None:
        """Take a Quill away: its screens and jobs go, its records stay."""
        with self._lock:
            target = self.quills_dir / quill_id
            if not target.is_dir():
                raise QuillError(f"{quill_id} is not installed")
            dependants = [
                q.id
                for q in self.quills.values()
                if q.id != quill_id and any(m.startswith(quill_id + ".") for m in q.models)
            ]
            if dependants:
                raise QuillError(
                    f"{', '.join(dependants)} use what {quill_id} introduced; remove those first"
                )
            shutil.rmtree(target)
            self.reload()

    def install_from_catalog(self, quill_id: str, catalog: Catalog | None = None) -> dict:
        catalog = catalog or load_catalog(self.catalog_location)
        entry = catalog.entry(quill_id)
        with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
            folder = fetch(
                entry["repo"], str(entry.get("ref", "")), base=catalog.base, into=Path(tmp) / "q"
            )
            models = self.datamodels_source(catalog, Path(tmp) / "m")
            return self.install(
                folder,
                models,
                origin={
                    "catalog": True, "repo": entry["repo"], "ref": entry.get("ref", ""),
                    # Where it stands in the catalog, which is where its tabs stand.
                    "position": catalog.quills.index(entry),
                },
            )

    def datamodels_source(self, catalog: Catalog, into: Path) -> Path | None:
        spec = catalog.datamodels
        if not spec.get("repo"):
            return None
        return fetch(str(spec["repo"]), str(spec.get("ref", "")), base=catalog.base, into=into)

    # -- telling -----------------------------------------------------------------------
    def installed(self) -> list[dict]:
        """Every installed Quill, in the order its tabs appear in.

        The catalog's order first — Notes, then Tasks, as they stand there —
        whenever each was installed; then every other Quill, oldest first.
        One installed before the catalog said where (Tasks, on a server from
        before this) goes after those that know.
        """
        def place(m: Manifest) -> tuple:
            position = m.origin.get("position")
            known = isinstance(position, int)
            return (not known, position if known else 0, m.origin.get("installed_at", ""), m.id)

        ordered = sorted(self.quills.values(), key=place)
        return [describe(m, self.datamodels, installed=m) for m in ordered]

    def catalogue_of_models(self) -> list[dict]:
        rows = []
        for model in self.datamodels.values():
            row = model.to_dict()
            row["used_by"] = self.users_of(model.id)
            row["foundation"] = model.source == "foundation"
            rows.append(row)
        return sorted(rows, key=lambda r: (not r["foundation"], r["id"]))


def _scan_datamodels(source: Path) -> dict[str, tuple[Datamodel, Path]]:
    """Every datamodel file under *source*, by id: the datamodels repository."""
    found: dict[str, tuple[Datamodel, Path]] = {}
    for path in sorted(source.rglob("*.toml")):
        if any(part.startswith(".") for part in path.relative_to(source).parts):
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if "datamodel" not in data:
            continue
        try:
            model = parse_datamodel(data, where=path.name)
        except DatamodelError as exc:
            raise QuillError(f"the datamodels have a bad file: {exc}") from exc
        found[model.id] = (model, path)
    return found


def _assemble(
    foundation: dict[str, Datamodel], quills: dict[str, Manifest]
) -> tuple[dict[str, Datamodel], dict[str, str]]:
    """The datamodels there are with these Quills: foundation, introduced, extended.

    Returns them and, per Quill, what stops it fitting — a datamodel it needs
    that is not there, a link that goes nowhere, a scope the store cannot keep.
    """
    models = dict(foundation)
    problems: dict[str, str] = {}
    for manifest in quills.values():
        for model in manifest.introduces:
            if model.id in models:
                problems[manifest.id] = f"{model.id} is introduced twice"
            models[model.id] = model
    for manifest in quills.values():
        for model_id, fields in manifest.extends.items():
            if model_id not in models:
                problems.setdefault(
                    manifest.id, f"{manifest.id} extends {model_id}, which is not installed"
                )
                continue
            try:
                models[model_id] = models[model_id].with_extension(manifest.id, fields)
            except DatamodelError as exc:
                problems.setdefault(manifest.id, str(exc))
    for manifest in quills.values():
        for model_id in manifest.models:
            if model_id not in models:
                problems.setdefault(
                    manifest.id,
                    f"{manifest.id} needs the datamodel {model_id}, which is not installed",
                )
    for model in models.values():
        for f in model.fields:
            if f.kind == "link" and f.to not in models:
                owner = (
                    model.source
                    if model.source != "foundation"
                    else next((q.id for q in quills.values() if model.id in q.models), "")
                )
                if owner:
                    problems.setdefault(
                        owner, f"{model.id}.{f.name} links to {f.to}, which is not installed"
                    )
        if model.in_space:
            target = models.get(model.get_field(model.in_space).to)
            if target is not None and not target.space:
                owner = model.source if model.source != "foundation" else next(
                    (q.id for q in quills.values() if model.id in q.models), "")
                if owner:
                    problems.setdefault(owner, f"{model.id} is in_space {target.id}, which is not a space")
    return models, problems


def _check_bindings(manifest: Manifest, models: dict[str, Datamodel]) -> None:
    """Every screen, job and dataset points at fields that are there, of the right kind."""
    where = manifest.id
    mine = manifest.models

    def model_of(thing: str, model_id: str) -> Datamodel:
        if model_id not in mine:
            raise QuillError(
                f"{where}: {thing} uses {model_id}, which the Quill does not declare in [uses]"
            )
        return models[model_id]

    def need(model: Datamodel, thing: str, name: object, kinds: tuple[str, ...] = ()) -> None:
        if not isinstance(name, str) or name not in model.by_name:
            raise QuillError(f"{where}: {thing} names {name!r}, which {model.id} does not have")
        if kinds and model.by_name[name].kind not in kinds:
            raise QuillError(
                f"{where}: {thing} {name!r} is a {model.by_name[name].kind}; it wants {' or '.join(kinds)}"
            )

    for screen in manifest.screens:
        thing = f"screen {screen['id']!r}"
        model = model_of(thing, screen["model"])
        kit = screen["kit"]
        need(model, thing, screen.get("title", model.title))
        if kit == "board":
            need(model, thing + " lane", screen.get("lane"), ("enum",))
            lane = model.by_name[screen["lane"]]
            if screen.get("done") and screen["done"] not in lane.values:
                raise QuillError(
                    f"{where}: {thing} done lane {screen['done']!r} is not a value of {lane.name}"
                )
            if screen.get("group"):
                need(model, thing + " group", screen["group"], ("link",))
            if screen.get("body"):
                need(model, thing + " body", screen["body"], ("markdown", "text"))
            if not model.ordered or screen["lane"] not in model.ordered_within:
                raise QuillError(
                    f"{where}: {thing} is a board, so {model.id} keeps order within its lanes"
                )
        elif kit == "list":
            if screen.get("tick"):
                need(model, thing + " tick", screen["tick"], ("bool",))
            if screen.get("subtitle"):
                need(model, thing + " subtitle", screen["subtitle"])
            _check_list_groups(where, thing, model, screen, need)
            for name in screen.get("fields", []):
                need(model, thing, name)
        elif kit in ("detail", "form"):
            for name in screen.get("fields", []):
                need(model, thing, name)
        elif kit == "calendar":
            _check_calendar(screen, model, models, thing, need, where)
        elif kit == "editor":
            # A page of Markdown with a title; `path`, when bound, is a string
            # like `folder/sub/title` whose folders are the tree beside it.
            need(model, thing + " body", screen.get("body"), ("markdown",))
            if screen.get("path"):
                need(model, thing + " path", screen["path"], ("string",))
        elif kit == "grid":
            # Files: folders and tiles, in groups (the shares) picked first.
            if not model.backend:
                raise QuillError(
                    f"{where}: {thing} is a grid, which shows files; {model.id} keeps no bytes"
                )
            need(model, thing + " group", screen.get("group"), ("link",))
            need(model, thing + " folder", screen.get("folder"), ("string",))
            need(model, thing + " kind", screen.get("kind"), ("enum",))
            if "folder" not in model.by_name[screen["kind"]].values:
                raise QuillError(f"{where}: {thing} kind {screen['kind']!r} has no value 'folder'")
            for binding, kinds in (("size", ("int",)), ("modified", ("datetime", "date")),
                                   ("mime", ("string",))):
                if screen.get(binding):
                    need(model, f"{thing} {binding}", screen[binding], kinds)
            group_model = models.get(model.by_name[screen["group"]].to)
            if group_model is not None:
                if screen.get("group_subtitle"):
                    need(group_model, thing + " group_subtitle", screen["group_subtitle"])
                if screen.get("group_open"):
                    need(group_model, thing + " group_open", screen["group_open"], ("bool",))
        elif kit == "thread":
            _check_thread(manifest, screen, model, models, need)
    for job in manifest.jobs:
        if job["action"] == "expire":
            model = model_of(f"job {job['id']!r}", job["model"])
            need(model, f"job {job['id']!r}", job["field"], ("datetime", "date"))
            if not model.by_name[job["field"]].indexed:
                raise QuillError(
                    f"{where}: job {job['id']!r} expires on {job['field']}, which must be indexed"
                )
    for dataset in manifest.datasets:
        model = model_of(f"dataset {dataset['id']!r}", dataset["model"])
        for record in dataset["records"]:
            for name in record:
                need(model, f"dataset {dataset['id']!r}", name)


def _check_list_groups(where: str, thing: str, model: Datamodel, screen: dict, need) -> None:
    """A list's `group` and `subgroup`: the two levels it is picked through.

    Each is a field whose values sort the records — a link (the linked
    records are the choices), an enum (its values are) or an indexed string
    (the values the records have are, and a new one is a name typed in).
    """
    for level in ("group", "subgroup"):
        name = screen.get(level)
        if not name:
            continue
        need(model, f"{thing} {level}", name, ("link", "enum", "string"))
        field = model.by_name[name]
        if field.kind != "link" and not field.indexed:
            raise QuillError(f"{where}: {thing} {level} {name!r} must be indexed, to be picked by")
    if screen.get("subgroup") and not screen.get("group"):
        raise QuillError(f"{where}: {thing} has a subgroup, so it needs a group above it")
    if screen.get("subgroup") and screen.get("subgroup") == screen.get("group"):
        raise QuillError(f"{where}: {thing} group and subgroup are two different fields")


def _surfaces(manifest: Manifest) -> list[str]:
    """Where its screens are drawn: everywhere, but to an assistant only what one may reach."""
    if not manifest.screens:
        return []
    if all(screen["model"] in NEVER_FOR_ASSISTANTS for screen in manifest.screens):
        return [s for s in SURFACES if s != "assistant"]
    return list(SURFACES)


def _check_thread(manifest: Manifest, screen: dict, model: Datamodel, models: dict, need) -> None:
    """A thread: things written (`body`) in a space (`space`), and how spaces are made.

    `space` is the link field that puts a record in its space, `about` a field
    of the space shown under its name, and `made_as` the fields a space gets
    for how it is made: `public`, `shared` or `personal` — its scope — or
    `direct`, a shared space found-or-made between the people picked, named
    for whoever else is in it.
    """
    where = manifest.id
    thing = f"screen {screen['id']!r}"
    need(model, thing + " space", screen.get("space"), ("link",))
    if model.in_space != screen["space"]:
        raise QuillError(f"{where}: {thing} space {screen['space']!r} is not what {model.id} is in")
    need(model, thing + " body", screen.get("body"), ("text", "markdown", "string"))
    space_model = models[model.by_name[screen["space"]].to]
    if screen.get("about"):
        need(space_model, thing + " about", screen["about"])
    made_as = screen.get("made_as") or {}
    if not isinstance(made_as, dict):
        raise QuillError(f"{where}: {thing} made_as is a table of how a space is made")
    for how, fields in made_as.items():
        if how not in MADE_AS:
            raise QuillError(f"{where}: {thing} made_as {how!r} is one of {', '.join(MADE_AS)}")
        scope = "shared" if how == "direct" else how
        if scope not in space_model.scopes:
            raise QuillError(f"{where}: {thing} made_as {how}, but a {space_model.id} is never {scope}")
        if not isinstance(fields, dict):
            raise QuillError(f"{where}: {thing} made_as {how} is the fields it sets")
        for name, value in fields.items():
            need(space_model, f"{thing} made_as {how}", name)
            f = space_model.by_name[name]
            if f.kind == "enum" and value not in f.values:
                raise QuillError(f"{where}: {thing} made_as {how}: {value!r} is not a value of {name}")
            if how == "direct" and not f.indexed:
                raise QuillError(
                    f"{where}: {thing} made_as direct marks a space by {name}, which must be indexed"
                )
def _check_calendar(screen: dict, model: Datamodel, models: dict[str, Datamodel],
                    thing: str, need, where: str) -> None:
    """A calendar: two moments, whether it is all day, and the spaces it is drawn from."""
    moments = ("datetime", "date")
    need(model, thing + " starts", screen.get("starts"), moments)
    need(model, thing + " ends", screen.get("ends"), moments)
    for name in ("starts", "ends"):
        if not model.by_name[screen[name]].indexed:
            raise QuillError(
                f"{where}: {thing} {name} {screen[name]!r} must be indexed, to ask for a range of days"
            )
    if screen.get("all_day"):
        need(model, thing + " all_day", screen["all_day"], ("bool",))
    need(model, thing + " space", screen.get("space"), ("link",))
    space = models.get(model.by_name[screen["space"]].to)
    if space is None or not space.space:
        raise QuillError(f"{where}: {thing} space {screen['space']!r} must link to a space")
    if screen.get("colour"):
        need(space, thing + " colour", screen["colour"], ("string", "enum"))
    if screen.get("subtitle"):
        need(model, thing + " subtitle", screen["subtitle"])


def describe(
    manifest: Manifest,
    models: dict[str, Datamodel],
    *,
    new_foundation: list[str] | None = None,
    installed: Manifest | None = None,
) -> dict:
    """What a Quill is and adds, in the shape the install sheet and the catalog draw."""
    introduced = {m.id for m in manifest.introduces}
    data = []
    for model_id in sorted(manifest.models):
        model = models.get(model_id)
        if model_id in introduced:
            how = "introduces"
        elif model_id in manifest.extends:
            how = "extends"
        elif any(g["model"] == model_id for g in manifest.grants):
            how = "asks for"
        else:
            how = "uses"
        row = {
            "id": model_id,
            "label": model.label if model else model_id,
            "how": how,
            "foundation": bool(model and model.source == "foundation"),
            "new": model_id in (new_foundation or []) or model_id in introduced,
        }
        if model_id in manifest.extends:
            row["fields"] = [f"{manifest.id}.{name}" for name in manifest.extends[model_id]]
        grant = next((g for g in manifest.grants if g["model"] == model_id), None)
        if grant:
            row["access"] = grant["access"]
            row["why"] = grant["why"]
        data.append(row)
    body = manifest.to_dict()
    body.update(
        {
            "readme": manifest.readme,
            "data": data,
            "surfaces": _surfaces(manifest),
            "installed_version": installed.version if installed else None,
            # Declared, checked, shown — and not run yet, which the sheet says.
            "not_running_yet": [
                f"{kind[:-1]} {item['id']}"
                for kind, items in (
                    ("services", manifest.services),
                    ("webhooks", manifest.webhooks),
                    ("apis", manifest.apis),
                )
                for item in items
            ]
            + [f"job {j['id']}" for j in manifest.jobs if j["action"] == "run"],
        }
    )
    return body
