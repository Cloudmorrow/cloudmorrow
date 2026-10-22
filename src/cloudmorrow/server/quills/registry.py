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
from cloudmorrow.server.quills.runtimes import RUNTIMES_DIR, RuntimeStore

PERSONAL_DIR = "quills-personal"
# The catalog's categories, as this server last read them, beside the Quills:
# the labels and the order the clients shelve the installed Quills under.
CATEGORIES = "quill-categories.json"


def check_personal(manifest: Manifest) -> None:
    """What a Quill of somebody's own may not do, said before it is installed.

    It changes nothing other people see and runs nothing outside the sandbox:
    no fields on datamodels everybody shares, no datamodel that is a space or
    sits in one, no scope but personal, no service, no runtime. Everything else a Quill
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
    if manifest.runtimes:
        raise QuillError(
            f"{where}: a Quill of your own brings no runtimes: a program is fetched onto the server for everybody,"
            " which is an administrator's to say yes to"
        )
    for model in manifest.introduces:
        plain = manifest.plain(model.id)
        if model.space or model.in_space:
            raise QuillError(f"{where}: {plain} is a space, or in one; a Quill of your own keeps to personal records")
        # The files say personal; the server keeps the Quill's own data as the
        # Quill's, public within it (manifest.personalise), so both pass.
        if set(model.scopes) - {"personal", "public"}:
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
        self,
        quills_dir: Path,
        datamodels_dir: Path,
        catalog: str = "",
        personal_dir: Path | None = None,
        runtimes: RuntimeStore | None = None,
    ) -> None:
        self.quills_dir = quills_dir
        self.datamodels_dir = datamodels_dir
        self.personal_dir = personal_dir or quills_dir.parent / PERSONAL_DIR
        self.catalog_location = catalog
        # The programs Quills' services need, fetched for them (quills/runtimes.py).
        self.runtimes = runtimes or RuntimeStore(quills_dir.parent / RUNTIMES_DIR)
        self.categories_path = quills_dir.parent / CATEGORIES
        # The catalog's categories (id, label, description), in its order,
        # from the last time the catalog was read: see `remember_categories`.
        self.categories: list[dict] = _read_categories(self.categories_path)
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
        # The Quills being installed right now, so two that require each other end.
        self._installing: set[str] = set()
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
            # The core's own — approval, flow, flow_run — are on every server,
            # whatever is installed, in the version this server ships.
            for model in core_datamodels():
                here = foundation.get(model.id)
                if here is None or here.version < model.version:
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
    def plan(
        self, folder: Path, datamodels_source: Path | None = None, *, owner: str = "", catalog: Catalog | None = None
    ) -> dict:
        """Everything installing *folder* would add, checked, for the install sheet.

        With *owner*, as that person's own Quill: read under their name, held to
        what such a Quill may do, and refused an id that is taken on their shelf.
        *catalog* is where the runtimes it requires are described; without one,
        this server's own is read when it needs to be.
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
        # The programs it needs on this server, and whether they are here.
        catalog_runtimes = self._runtimes_of(catalog, manifest)
        plan["runtimes"] = self.runtimes.describe(manifest.runtimes, catalog_runtimes)
        # The other Quills it installs with it, and whether they are here.
        plan["quills"] = self._required(manifest, owner, self._catalog(catalog, manifest))
        # What its machine handlers would add to a machine they are switched on on.
        plan["machine_runtimes"] = self.runtimes.describe_for_machines(manifest.machine_runtimes, catalog_runtimes)
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

    def _catalog(self, catalog: Catalog | None, manifest: Manifest) -> Catalog | None:
        """*catalog*, or this server's, read only when *manifest* needs one; None when it cannot be."""
        if catalog is not None or not self.catalog_location:
            return catalog
        if not manifest.runtimes and not manifest.machine_runtimes and not self._missing_quills(manifest):
            return catalog
        try:
            return load_catalog(self.catalog_location)
        except QuillError:
            return None

    def _here(self, quill_id: str, owner: str = "") -> Manifest | None:
        """The Quill of that id somebody sees: the server's, or else their own."""
        return self.quills.get(quill_id) or (self.personal.get(owner, {}).get(quill_id) if owner else None)

    def _missing_quills(self, manifest: Manifest) -> list[str]:
        return [q for q in manifest.quills if self._here(q, manifest.owner) is None]

    def _required(self, manifest: Manifest, owner: str, catalog: Catalog | None) -> list[dict]:
        """The Quills *manifest* requires, for the install sheet: here already,
        or to be installed with it from the catalog. One the catalog lacks
        is refused; without a catalog to ask, each is said and left out."""
        rows = []
        for quill_id in manifest.quills:
            here = self._here(quill_id, owner)
            if here is not None:
                rows.append({"id": quill_id, "name": here.name, "version": here.version, "installed": True})
                continue
            row = {"id": quill_id, "name": quill_id, "version": "", "installed": False}
            if catalog is None:
                row["problem"] = "the catalog could not be read, so it is not installed with it"
            else:
                try:
                    entry = catalog.entry(quill_id)
                except QuillError:
                    raise QuillError(
                        f"{manifest.id} requires the {quill_id} Quill, which is neither installed nor in the catalog"
                    ) from None
                row["name"] = str(entry.get("name") or quill_id)
                row["version"] = str(entry.get("ref", "")).removeprefix("v")
                row["summary"] = str(entry.get("summary", ""))
            rows.append(row)
        return rows

    def _runtimes_of(self, catalog: Catalog | None, manifest: Manifest) -> dict | None:
        found = self._catalog(catalog, manifest)
        return None if found is None else found.runtimes

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
        catalog: Catalog | None = None,
    ) -> dict:
        """Install the Quill in *folder*, replacing an earlier version of it. Returns the plan.

        With *owner*, as that person's own Quill, under `quills-personal/<owner>/`.
        The runtimes it requires are fetched first, from where *catalog* (or
        this server's) says: a download that fails installs nothing. The
        Quills it requires that are not here are installed before it, from
        the same catalog; without one it is installed all the same.
        """
        with self._lock:
            catalog = self._catalog(catalog, load_manifest(folder, owner=owner))
            if catalog is not None:
                self.remember_categories(catalog)
            plan = self.plan(folder, datamodels_source, owner=owner, catalog=catalog)
            # Checked, it is good to go: first the Quills it works with.
            brought, skipped = [], []
            for row in plan["quills"]:
                if row["installed"]:
                    continue
                if catalog is None or row["id"] in self._installing:
                    skipped.append(row["id"])
                    continue
                self._installing.add(plan["id"])
                try:
                    self.install_from_catalog(row["id"], catalog, owner=owner)
                finally:
                    self._installing.discard(plan["id"])
                brought.append(row["id"])
            if brought:
                # Planned again: they may have brought datamodels it finds here now.
                plan = self.plan(folder, datamodels_source, owner=owner, catalog=catalog)
            plan["quills_installed"] = brought
            if skipped:
                plan["quills_skipped"] = skipped
            manifest_id = plan["id"]
            wanted = list(plan.get("requires", {}).get("runtimes", []))
            if wanted and catalog is not None:
                fetched = self.runtimes.ensure(wanted, catalog.runtimes, base=catalog.base)
                plan["runtimes"] = self.runtimes.describe(wanted, catalog.runtimes)
                plan["runtimes_fetched"] = fetched
            elif wanted:
                # No catalog to fetch from: a test harness, an offline check, a
                # server whose catalog is unreachable. The Quill is installed
                # all the same; its services wait and say what for, and an
                # install with the catalog reachable fetches it (services.py).
                plan["runtimes_fetched"] = []
                plan["runtimes_skipped"] = wanted
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
            self.check_unneeded(quill_id, owner)
            shutil.rmtree(target)
            if owner and target.parent.is_dir() and not any(target.parent.iterdir()):
                target.parent.rmdir()
            self.reload()

    def needed_by(self, quill_id: str, owner: str = "") -> list[Manifest]:
        """The installed Quills that require *quill_id* and would be left without
        it: for the server's, every one not holding its own; for somebody's own,
        theirs, when the server has none."""
        if owner:
            if quill_id in self.quills:
                return []
            return [q for q in self.personal.get(owner, {}).values() if quill_id in q.quills]
        return [
            q
            for q in self.all()
            if quill_id in q.quills
            and q.id != quill_id
            and (not q.owner or quill_id not in self.personal.get(q.owner, {}))
        ]

    def check_unneeded(self, quill_id: str, owner: str = "") -> None:
        """Refuse to take away a Quill another installed one requires."""
        needing = sorted({q.name for q in self.needed_by(quill_id, owner)})
        if needing:
            one = len(needing) == 1
            raise QuillError(
                f"{', '.join(needing)} {'needs' if one else 'need'} {quill_id}; remove {'it' if one else 'them'} first"
            )

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
                catalog=catalog,
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

    # -- the categories ----------------------------------------------------------------
    def remember_categories(self, catalog: Catalog) -> None:
        """Keep the catalog's categories, for shelving the installed Quills by.

        Called whenever the catalog is read — an install, a look at the
        catalog page — so a server tells its clients the catalog's labels
        and order without reaching for it every time they ask, or at all
        once the network is gone.
        """
        found = [
            {"id": str(c.get("id", "")), "label": str(c.get("label", "")), "description": str(c.get("description", ""))}
            for c in catalog.categories
            if c.get("id")
        ]
        if found == self.categories:
            return
        with self._lock:
            self.categories = found
            try:
                self.categories_path.parent.mkdir(parents=True, exist_ok=True)
                self.categories_path.write_text(json.dumps(found, indent=1), encoding="utf-8")
            except OSError:
                pass  # remembered for this run; written next time

    def shelf(self, category: str) -> tuple[str, int]:
        """Where a Quill of *category* is shelved: the label to show, and the rank
        of that shelf among the others — the catalog's order for the categories
        it names, then the rest by their own label, Other last."""
        for rank, found in enumerate(self.categories):
            if found["id"] == category:
                return found["label"] or _titled(category), rank
        return _titled(category), len(self.categories) + (1 if not category else 0)

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
        """An installed Quill as a client is told it, its runtimes as they are on this server."""
        told = describe(manifest, self.datamodels, installed=manifest)
        told["runtimes"] = self.runtimes.describe_installed(manifest.runtimes)
        # Where its tabs stand in a client's rail: the catalog's label for
        # its category, and the order of the shelves.
        told["category_label"], told["category_rank"] = self.shelf(manifest.category)
        return told

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


def _titled(category: str) -> str:
    """A label for a category the catalog does not name: `garden` reads Garden,
    `home_office` Home office, and none at all is Other — as the catalog pages
    shelve what has no category."""
    words = category.replace("_", " ").replace("-", " ").split()
    return " ".join(words).capitalize() if words else "Other"


def _read_categories(path: Path) -> list[dict]:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(found, list):
        return []
    return [c for c in found if isinstance(c, dict) and c.get("id")]


CORE_DATAMODELS = Path(__file__).resolve().parent.parent / "core_datamodels"


def core_datamodels() -> list[Datamodel]:
    """The datamodels the core itself needs, shipped with it (docs/FLOWS.md)."""
    return [load_datamodel(path) for path in sorted(CORE_DATAMODELS.glob("*.toml"))]


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
