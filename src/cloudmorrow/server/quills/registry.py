"""The registry of what is installed: the Quills, the datamodels, and what each adds.

Read from disk at boot and after every install; the record store, the jobs,
the routes and every client ask it. Installing copies a Quill into
`<data_dir>/quills/<id>/`, with the foundational datamodels it uses into
`<data_dir>/datamodels/`.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import tempfile
import threading
import tomllib
from pathlib import Path

from cloudmorrow.server.datamodels import (
    Datamodel,
    DatamodelError,
    load_datamodel,
    parse_datamodel,
    parse_duration,
)
from cloudmorrow.server.quills.catalog import Catalog, fetch, load_catalog
from cloudmorrow.server.quills.checks import _assemble, _check_bindings, describe
from cloudmorrow.server.quills.manifest import ORIGIN, Manifest, QuillError, load_manifest


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
        for listener in list(getattr(self, "listeners", ())):
            try:
                listener()
            except Exception:  # a listener's trouble is not the install's
                logging.getLogger("cloudmorrow.quills").exception("a registry listener failed")

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
        available = _scan_datamodels(source) if source is not None else {}

        def lacking(model_id: str) -> bool:
            # Not here, or here in an older version than the one it came with:
            # a datamodel grows (a contact kept in a book), and never loses a field.
            here = self.foundation.get(model_id)
            return here is None or (
                model_id in available and available[model_id][0].version > here.version
            )

        wanted = {
            m
            for m in (*manifest.uses, *manifest.extends, *(g["model"] for g in manifest.grants))
            if m not in introduced and lacking(m)
        }
        # Links from what it uses pull in their targets too: a task needs its board.
        found: dict[str, Datamodel] = {}
        queue = list(wanted)
        while queue:
            model_id = queue.pop()
            if model_id in found or not lacking(model_id) or model_id in introduced:
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
