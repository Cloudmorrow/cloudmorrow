"""The registry of what is installed: the Quills, the datamodels, and what each adds.

Read from disk at boot and after every install; the record store, the jobs,
the routes and every client ask it. Installing copies a Quill into
`<data_dir>/quills/<id>/`, with the foundational datamodels it uses into
`<data_dir>/datamodels/`.

Quills of somebody's own (docs/SHARING.md) are kept apart, under
`<data_dir>/quills-personal/<owner>/<id>/`, and read with their datamodels
under the owner's name, so the one record store knows every shape there is
and nobody's Budget meets anybody else's. Who sees which of them is the
shelf's business (quills/shelf.py); here they are what is installed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import tempfile
import threading
import tomllib
from collections.abc import Iterable, Iterator
from pathlib import Path

from cloudmorrow.server.datamodels import (
    OWNER_PREFIX,
    Datamodel,
    DatamodelError,
    load_datamodel,
    parse_datamodel,
    parse_duration,
)
from cloudmorrow.server.quills.catalog import Catalog, fetch, load_catalog
from cloudmorrow.server.quills.checks import _assemble, _check_bindings, describe
from cloudmorrow.server.quills.manifest import ORIGIN, Manifest, QuillError, load_manifest

PERSONAL_DIR = "quills-personal"


def check_personal(manifest: Manifest) -> None:
    """What a Quill of somebody's own may not do, said before it is installed.

    It changes nothing other people see and runs nothing outside the sandbox:
    no fields on datamodels everybody shares, no datamodel that is a space or
    sits in one, no scope but personal, no service. Everything else a Quill
    may do, it may (docs/SHARING.md, *The rules*).
    """
    where = manifest.id
    if manifest.extends:
        raise QuillError(
            f"{where}: a Quill of your own adds no fields to {', '.join(sorted(manifest.extends))}; a field on a"
            " datamodel is seen by everybody who sees the record. Introduce a datamodel of your own with a link"
            " to it instead"
        )
    if manifest.services:
        raise QuillError(
            f"{where}: a Quill of your own runs no [[services]]: a service runs outside the sandbox, as the"
            " server itself. Its Python runs in the sandbox, as you"
        )
    for model in manifest.introduces:
        plain = manifest.plain(model.id)
        if model.space or model.in_space:
            raise QuillError(f"{where}: {plain} is a space, or in one; a Quill of your own keeps to personal records")
        if set(model.scopes) - {"personal"}:
            raise QuillError(f"{where}: {plain} is {', '.join(model.scopes)}; a Quill of your own is personal only")
    for model_id in (*manifest.uses, *(g["model"] for g in manifest.grants)):
        if model_id.startswith(OWNER_PREFIX) and not model_id.startswith(f"{OWNER_PREFIX}{manifest.owner}."):
            raise QuillError(f"{where}: {model_id} is somebody else's own datamodel, which a Quill does not use")


# -- the registry ----------------------------------------------------------------------
class QuillRegistry:
    """What is installed: the Quills, the datamodels, and what each adds.

    Read from disk at boot and after every install; everything else asks it.
    A Quill whose folder no longer checks out is left out and listed in
    `broken`, rather than stopping the server.
    """

    def __init__(
        self, quills_dir: Path, datamodels_dir: Path, catalog: str = "", personal_dir: Path | None = None
    ) -> None:
        self.quills_dir = quills_dir
        self.datamodels_dir = datamodels_dir
        self.personal_dir = personal_dir or quills_dir.parent / PERSONAL_DIR
        self.catalog_location = catalog
        self._lock = threading.RLock()
        # The server's Quills, by id.
        self.quills: dict[str, Manifest] = {}
        # Everybody's own Quills: owner -> id -> manifest.
        self.personal: dict[str, dict[str, Manifest]] = {}
        self.foundation: dict[str, Datamodel] = {}
        self.datamodels: dict[str, Datamodel] = {}
        self.broken: dict[str, str] = {}
        # What the last plan found to copy in: foundational datamodel -> file.
        self._pending_paths: dict[str, Path] = {}
        # Told after every reload: what runs a Quill's code starts and stops
        # its services by what is installed now, whoever installed it.
        self.listeners: list = []
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
            personal: dict[str, dict[str, Manifest]] = {}
            if self.personal_dir.is_dir():
                for home in sorted(p for p in self.personal_dir.iterdir() if p.is_dir()):
                    if home.name.startswith("."):
                        continue
                    for folder in sorted(p for p in home.iterdir() if p.is_dir()):
                        if folder.name.startswith("."):
                            continue
                        try:
                            manifest = load_manifest(folder, owner=home.name)
                            check_personal(manifest)
                        except QuillError as exc:
                            broken[f"{OWNER_PREFIX}{home.name}.{folder.name}"] = str(exc)
                            continue
                        personal.setdefault(home.name, {})[folder.name] = manifest
            everything = {m.key: m for m in (*quills.values(), *_each(personal))}
            models, problems = _assemble(foundation, everything)
            for key, problem in problems.items():
                broken[key] = problem
                dropped = everything.pop(key, None)
                if dropped is not None:
                    if dropped.owner:
                        personal.get(dropped.owner, {}).pop(dropped.id, None)
                    else:
                        quills.pop(dropped.id, None)
            if problems:
                models, _ = _assemble(foundation, everything)
            self.foundation = foundation
            self.quills = quills
            self.personal = {owner: mine for owner, mine in personal.items() if mine}
            self.datamodels = models
            self.broken = broken
        for listener in list(getattr(self, "listeners", ())):
            try:
                listener()
            except Exception:  # a listener's trouble is not the install's
                logging.getLogger("cloudmorrow.quills").exception("a registry listener failed")

    def models(self) -> dict[str, Datamodel]:
        return self.datamodels

    def all(self) -> Iterator[Manifest]:
        """Every installed Quill, the server's and everybody's own."""
        yield from self.quills.values()
        yield from _each(self.personal)

    def by_key(self, key: str) -> Manifest | None:
        """A Quill by its key: an id, or `~owner.id` for somebody's own."""
        if key.startswith(OWNER_PREFIX):
            owner, _, quill_id = key[len(OWNER_PREFIX) :].partition(".")
            return self.personal.get(owner, {}).get(quill_id)
        return self.quills.get(key)

    def expiries(self) -> dict[str, tuple[str, dt.timedelta]]:
        """model -> (field, after), from every installed Quill's expire jobs."""
        found: dict[str, tuple[str, dt.timedelta]] = {}
        for manifest in self.all():
            for job in manifest.jobs:
                if job["action"] == "expire":
                    found[job["model"]] = (job["field"], parse_duration(job["after"]))
        return found

    def users_of(self, model_id: str) -> list[str]:
        """The keys of every Quill that touches *model_id*."""
        return sorted(q.key for q in self.all() if model_id in q.models)

    def seeds_for(self, model_id: str) -> list[tuple[Manifest, dict]]:
        return [
            (manifest, dataset)
            for manifest in self.all()
            for dataset in manifest.datasets
            if dataset["model"] == model_id
        ]

    # -- what a Quill would add ------------------------------------------------------
    def plan(self, folder: Path, datamodels_source: Path | None = None, *, owner: str = "") -> dict:
        """Everything installing *folder* would add, checked, for the install sheet.

        With *owner*, as that person's own Quill: read under their name, held to
        what such a Quill may do, and refused an id that is taken on their shelf.
        """
        manifest = load_manifest(folder, owner=owner)
        if owner:
            check_personal(manifest)
            if manifest.id in self.quills:
                raise QuillError(f"{manifest.id} is a Quill of this server's; a Quill of your own needs another id")
        elif any(model.startswith(OWNER_PREFIX) for model in manifest.models):
            raise QuillError(f"{manifest.id} uses somebody's own datamodel, which a Quill of the server's does not")
        needed = self._needed_foundation(manifest, datamodels_source)
        foundation = {**self.foundation, **needed}
        everything = {m.key: m for m in self.all() if m.key != manifest.key}
        everything[manifest.key] = manifest
        models, problems = _assemble(foundation, everything)
        if manifest.key in problems:
            raise QuillError(problems[manifest.key])
        _check_bindings(manifest, models)
        installed = self.by_key(manifest.key)
        plan = describe(
            manifest,
            models,
            new_foundation=sorted(set(needed) - set(self.foundation)),
            installed=installed,
        )
        # The datamodels as they would be after installing, for a preview.
        touched = set(manifest.models)
        touched |= {f.to for m in touched if m in models for f in models[m].fields if f.kind == "link"}
        plan["models"] = {m: models[m].to_dict() for m in sorted(touched) if m in models}
        if not owner:
            # Somebody's own Quill of the same id, introducing the same
            # datamodels: installing this for the server can take their
            # records with it (docs/SHARING.md, *Published*).
            plan["adopt"] = [
                {"owner": mine.owner, "version": mine.version, "records": sorted(mine.renamed)}
                for mine in _each(self.personal)
                if mine.id == manifest.id and set(mine.renamed) <= {m.id for m in manifest.introduces}
            ]
        return plan

    def _needed_foundation(self, manifest: Manifest, source: Path | None) -> dict[str, Datamodel]:
        """The foundational datamodels *manifest* needs that this server lacks, found in *source*."""
        introduced = {m.id for m in manifest.introduces}
        available = _scan_datamodels(source) if source is not None else {}

        def lacking(model_id: str) -> bool:
            # Not here, or here in an older version than the one it came with:
            # a datamodel grows (a contact kept in a book), and never loses a field.
            here = self.foundation.get(model_id)
            return here is None or (model_id in available and available[model_id][0].version > here.version)

        wanted = {
            m
            for m in (*manifest.uses, *manifest.extends, *(g["model"] for g in manifest.grants))
            if m not in introduced and not m.startswith(OWNER_PREFIX) and lacking(m)
        }
        # Links from what it uses pull in their targets too: a task needs its board.
        found: dict[str, Datamodel] = {}
        queue = list(wanted)
        while queue:
            model_id = queue.pop()
            if model_id in found or not lacking(model_id) or model_id in introduced:
                continue
            if model_id.startswith(OWNER_PREFIX):
                continue
            if "." in model_id and self.by_key(model_id.split(".", 1)[0]) is not None:
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
    def folder_of(self, quill_id: str, owner: str = "") -> Path:
        return (self.personal_dir / owner / quill_id) if owner else (self.quills_dir / quill_id)

    def install(
        self,
        folder: Path,
        datamodels_source: Path | None = None,
        *,
        origin: dict | None = None,
        owner: str = "",
    ) -> dict:
        """Install the Quill in *folder*, replacing an earlier version of it. Returns the plan.

        With *owner*, as that person's own Quill, under `quills-personal/<owner>/`.
        """
        with self._lock:
            plan = self.plan(folder, datamodels_source, owner=owner)
            manifest_id = plan["id"]
            self.datamodels_dir.mkdir(parents=True, exist_ok=True)
            for model_id, path in self._pending_paths.items():
                shutil.copyfile(path, self.datamodels_dir / f"{model_id}.toml")
            target = self.folder_of(manifest_id, owner)
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.with_name(f".{manifest_id}.new")
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(folder, staging, ignore=shutil.ignore_patterns(".git", "__pycache__", ORIGIN))
            (staging / ORIGIN).write_text(
                json.dumps(
                    {
                        **(origin or {}),
                        **({"owner": owner} if owner else {}),
                        # To the microsecond: Quills installed together at
                        # boot keep the order they were installed in, which
                        # is the order of their tabs.
                        "installed_at": dt.datetime.now(tz=dt.UTC).isoformat(timespec="microseconds"),
                    }
                ),
                encoding="utf-8",
            )
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
            self.reload()
            key = f"{OWNER_PREFIX}{owner}.{manifest_id}" if owner else manifest_id
            if key in self.broken:
                raise QuillError(self.broken[key])
            return plan

    def uninstall(self, quill_id: str, owner: str = "") -> None:
        """Take a Quill away: its screens and jobs go, its records stay."""
        with self._lock:
            target = self.folder_of(quill_id, owner)
            if not target.is_dir():
                raise QuillError(f"{quill_id} is not installed")
            key = f"{OWNER_PREFIX}{owner}.{quill_id}" if owner else quill_id
            prefix = key + "."
            dependants = [q.key for q in self.all() if q.key != key and any(m.startswith(prefix) for m in q.models)]
            if dependants:
                raise QuillError(f"{', '.join(dependants)} use what {quill_id} introduced; remove those first")
            shutil.rmtree(target)
            if owner and target.parent.is_dir() and not any(target.parent.iterdir()):
                target.parent.rmdir()
            self.reload()

    def set_origin(self, manifest: Manifest, **changes) -> Manifest:
        """Change what an installed Quill's `.origin.json` says — its audience, who maintains it."""
        with self._lock:
            folder = manifest.folder or self.folder_of(manifest.id, manifest.owner)
            origin = {**manifest.origin, **changes}
            (folder / ORIGIN).write_text(json.dumps(origin), encoding="utf-8")
            self.reload()
            found = self.by_key(manifest.key)
            if found is None:
                raise QuillError(self.broken.get(manifest.key, f"{manifest.id} did not load again"))
            return found

    def install_from_catalog(self, quill_id: str, catalog: Catalog | None = None, *, owner: str = "") -> dict:
        catalog = catalog or load_catalog(self.catalog_location)
        entry = catalog.entry(quill_id)
        with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
            folder = fetch(entry["repo"], str(entry.get("ref", "")), base=catalog.base, into=Path(tmp) / "q")
            models = self.datamodels_source(catalog, Path(tmp) / "m")
            return self.install(
                folder,
                models,
                origin={
                    "catalog": True,
                    "repo": entry["repo"],
                    "ref": entry.get("ref", ""),
                    # Where it stands in the catalog, which is where its tabs stand.
                    "position": catalog.quills.index(entry),
                },
                owner=owner,
            )

    def datamodels_source(self, catalog: Catalog, into: Path) -> Path | None:
        spec = catalog.datamodels
        if not spec.get("repo"):
            return None
        return fetch(str(spec["repo"]), str(spec.get("ref", "")), base=catalog.base, into=into)

    # -- telling -----------------------------------------------------------------------
    def ordered(self, manifests: Iterable[Manifest]) -> list[Manifest]:
        """*manifests* in the order their tabs appear in.

        The catalog's order first — Notes, then Tasks, as they stand there —
        whenever each was installed; then every other Quill, oldest first.
        One installed before the catalog said where (Tasks, on a server from
        before this) goes after those that know.
        """

        def place(m: Manifest) -> tuple:
            position = m.origin.get("position")
            known = isinstance(position, int)
            return (not known, position if known else 0, m.origin.get("installed_at", ""), m.id)

        return sorted(manifests, key=place)

    def describe(self, manifest: Manifest) -> dict:
        return describe(manifest, self.datamodels, installed=manifest)

    def installed(self) -> list[dict]:
        """Every one of the server's Quills, in the order its tabs appear in."""
        return [self.describe(m) for m in self.ordered(self.quills.values())]

    def catalogue_of_models(self) -> list[dict]:
        rows = []
        for model in self.datamodels.values():
            row = model.to_dict()
            row["used_by"] = self.users_of(model.id)
            row["foundation"] = model.source == "foundation"
            row["owner"] = owner_of(model.id)
            rows.append(row)
        return sorted(rows, key=lambda r: (not r["foundation"], r["id"]))


def owner_of(model_id: str) -> str:
    """Whose own datamodel this is — `~alice.budget.envelope` is alice's — or "" for everybody's."""
    return model_id[len(OWNER_PREFIX) :].partition(".")[0] if model_id.startswith(OWNER_PREFIX) else ""


def _each(personal: dict[str, dict[str, Manifest]]) -> Iterator[Manifest]:
    for mine in personal.values():
        yield from mine.values()


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
