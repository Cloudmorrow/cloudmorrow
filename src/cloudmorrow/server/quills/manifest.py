"""A Quill's manifest: reading `quill.toml`, and checking it on its own.

What is checked here needs nothing but the manifest and the Quill's folder:
the shape of every table, ids, versions, screens of the kit, jobs, webhooks
and the code half. Whether it fits the datamodels there are is `checks`.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from cloudmorrow.server.datamodels import (
    OWNER_PREFIX,
    Datamodel,
    DatamodelError,
    load_datamodel,
    parse_duration,
    renamed,
)
from cloudmorrow.server.quills.codespec import CodeSpecError, check_handlers, parse_code
from cloudmorrow.server.quills.hooks import PathError, parse_path

MANIFEST = "quill.toml"
ORIGIN = ".origin.json"

# The screens every surface draws. A Quill has these and nothing else.
KIT = ("list", "board", "detail", "form", "calendar", "thread", "grid", "editor", "view")
# The ones every surface draws *today*. A screen of another kind is refused at
# install, so a Quill never lands with a tab that draws nothing somewhere.
KIT_READY = frozenset({"list", "board", "detail", "form", "calendar", "grid", "editor", "thread", "view"})

# How a thread screen may make a space: in one of the scopes, or `direct`,
# found-or-made between the people picked.
MADE_AS = ("personal", "shared", "public", "direct")

JOB_ACTIONS = frozenset({"expire", "run", "call"})
SEED_KINDS = frozenset({"per-owner", "once", "per-space"})

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
# A webhook's path under /hooks/<quill>/, and an API's prefix under /api/q/<quill>/.
HOOK_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
API_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")

# Surfaces a kit screen is drawn on, for the install sheet to say so.
SURFACES = ("phone", "web", "terminal", "command line", "assistant")


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
    # Its Python, when it has some (codespec.py, docs/QUILLCODE.md).
    code: str = ""
    sdk: str = ""
    actions: tuple[dict, ...] = ()
    hooks: tuple[dict, ...] = ()
    fetch: tuple[dict, ...] = ()
    secrets: tuple[dict, ...] = ()
    machine: tuple[dict, ...] = ()
    readme: str = ""
    folder: Path | None = None
    origin: dict = field(default_factory=dict)
    # A Quill of somebody's own (docs/SHARING.md): whose, and what its
    # introduced datamodels are called here — `budget.envelope` in the
    # folder, `~alice.budget.envelope` on this server — so two people's
    # Budgets never meet in the record store. Empty for a server Quill.
    owner: str = ""
    renamed: dict[str, str] = field(default_factory=dict)

    @property
    def personal(self) -> bool:
        return bool(self.owner)

    @property
    def key(self) -> str:
        """What this installation is called where one name must do for every
        Quill on the server: the id for a server Quill, `~owner.id` for a
        personal one. The feature switch, the logs and the sandbox go by it."""
        return f"{OWNER_PREFIX}{self.owner}.{self.id}" if self.owner else self.id

    def resolve(self, model: str) -> str:
        """A datamodel as the Quill's own files and code name it, as this server knows it."""
        return self.renamed.get(model, model)

    def plain(self, model: str) -> str:
        """The other way: a datamodel as this server knows it, as the Quill's code names it."""
        return self._plain.get(model, model)

    @property
    def _plain(self) -> dict[str, str]:
        return {v: k for k, v in self.renamed.items()}

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
                {k: v for k, v in d.items() if k != "records"} | {"count": len(d["records"])} for d in self.datasets
            ],
            "services": list(self.services),
            "webhooks": list(self.webhooks),
            "apis": list(self.apis),
            "code": self.code,
            "sdk": self.sdk,
            "actions": list(self.actions),
            "hooks": list(self.hooks),
            "fetch": list(self.fetch),
            "secrets": list(self.secrets),
            "machine": list(self.machine),
            "origin": dict(self.origin),
            "owner": self.owner,
            "key": self.key,
            "personal": self.personal,
            "renamed": dict(self.renamed),
        }


def _renamed_in(items, names: dict[str, str], *keys: str) -> tuple[dict, ...]:
    out = []
    for item in items:
        item = dict(item)
        for key in keys:
            if isinstance(item.get(key), str) and item[key] in names:
                item[key] = names[item[key]]
        if "fields" in item and isinstance(item["fields"], list):  # an action's form: its links
            item["fields"] = [
                {**f, "to": names[f["to"]]} if isinstance(f, dict) and f.get("to") in names else f
                for f in item["fields"]
            ]
        out.append(item)
    return tuple(out)


def personalise(manifest: Manifest, owner: str) -> Manifest:
    """*manifest* as *owner*'s own Quill: every datamodel it introduces, and every
    place the manifest names one, under their name (`~owner.<quill>.<name>`).

    The folder on disk is left as it was written, so the same files publish
    as they are; the renaming is how the server reads them, and `resolve`
    and `plain` carry its code's names across (docs/SHARING.md).
    """
    names = {m.id: f"{OWNER_PREFIX}{owner}.{m.id}" for m in manifest.introduces}
    rename = lambda model: names.get(model, model)  # noqa: E731
    return replace(
        manifest,
        owner=owner,
        renamed=names,
        uses=tuple(rename(m) for m in manifest.uses),
        extends={rename(m): f for m, f in manifest.extends.items()},
        introduces=tuple(renamed(m, names) for m in manifest.introduces),
        grants=_renamed_in(manifest.grants, names, "model"),
        screens=_renamed_in(manifest.screens, names, "model"),
        jobs=_renamed_in(manifest.jobs, names, "model"),
        datasets=_renamed_in(manifest.datasets, names, "model"),
        webhooks=_renamed_in(manifest.webhooks, names, "model"),
        actions=_renamed_in(manifest.actions, names, "on"),
        hooks=_renamed_in(manifest.hooks, names, "on"),
    )


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
        raise QuillError(f"{where}: dataset {item.get('id')!r} has `records` or a `file`, one of them")
    if records is not None:
        if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
            raise QuillError(f"{where}: dataset {item.get('id')!r} records are tables")
        return records
    if folder is None:
        raise QuillError(f"{where}: dataset {item.get('id')!r} names a file, and there is no folder")
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
    jobs = _table_list(data, "jobs", where)
    webhooks = _table_list(data, "webhooks", where)
    apis = _table_list(data, "apis", where)
    try:
        code = parse_code(data, folder, where, screens=screens, jobs=jobs, webhooks=webhooks, apis=apis)
        if folder is not None:
            check_handlers(folder, code, where)
    except CodeSpecError as exc:
        raise QuillError(str(exc)) from exc
    for screen in screens:
        kit = screen.get("kit")
        if kit not in KIT:
            raise QuillError(f"{where}: screen {screen['id']!r} kit is one of {', '.join(KIT)}")
        if kit not in KIT_READY:
            raise QuillError(
                f"{where}: screen {screen['id']!r} is a {kit}, which the kit does not draw on every"
                f" surface yet; today it is {', '.join(sorted(KIT_READY))}"
            )
        if kit == "view":
            if not str(screen.get("label", "")).strip():
                raise QuillError(f"{where}: screen {screen['id']!r} is a view, so it says its label")
            continue
        if not screen.get("model"):
            raise QuillError(f"{where}: screen {screen['id']!r} names a model")

    _ids_unique(jobs, "job", where)
    for job in jobs:
        if job.get("action") not in JOB_ACTIONS:
            raise QuillError(f"{where}: job {job['id']!r} action is one of {', '.join(sorted(JOB_ACTIONS))}")
        for key in ("every", "after"):
            if key in job:
                try:
                    parse_duration(str(job[key]))
                except ValueError as exc:
                    raise QuillError(f"{where}: job {job['id']!r} {key}: {exc}") from exc
        if job["action"] == "expire" and not (job.get("model") and job.get("field") and job.get("after")):
            raise QuillError(f"{where}: an expire job names a model, a field and after")

    datasets = []
    raw_sets = _table_list(data, "datasets", where)
    _ids_unique(raw_sets, "dataset", where)
    for item in raw_sets:
        if item.get("seed") not in SEED_KINDS:
            raise QuillError(f"{where}: dataset {item['id']!r} seed is {', '.join(sorted(SEED_KINDS))}")
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
        if not isinstance(command, list) or not command or not all(isinstance(c, str) and c for c in command):
            raise QuillError(f"{where}: service {service['id']!r} command is a list of strings")
        if not isinstance(service.get("always", False), bool):
            raise QuillError(f"{where}: service {service['id']!r} always is true or false")
    _ids_unique(webhooks, "webhook", where)
    _ids_unique(apis, "api", where)
    service_ids = {s["id"] for s in services}
    for job in jobs:
        if job["action"] == "run":
            if job.get("service") not in service_ids:
                raise QuillError(f'{where}: job {job["id"]!r} runs one of its services: service = "<id>"')
            if not job.get("every"):
                raise QuillError(f'{where}: job {job["id"]!r} runs every so often: every = "1h"')
    paths: set[str] = set()
    for hook in webhooks:
        _check_webhook(hook, service_ids, paths, where)
    for api in apis:
        if bool(api.get("handler")) == bool(api.get("service")):
            raise QuillError(f"{where}: api {api['id']!r} is answered by a handler or one of its services, one of them")
        if api.get("service") and api["service"] not in service_ids:
            raise QuillError(f"{where}: api {api['id']!r} is served by one of its services")
        prefix = api.get("prefix", "")
        if prefix and not (isinstance(prefix, str) and API_PREFIX_RE.match(prefix)):
            raise QuillError(f"{where}: api {api['id']!r} prefix is a path like v1/public")

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
        code=code.code,
        sdk=code.sdk,
        actions=code.actions,
        hooks=code.hooks,
        fetch=code.fetch,
        secrets=code.secrets,
        machine=code.machine,
        readme=readme,
        folder=folder,
    )


def _check_webhook(hook: dict, service_ids: set[str], paths: set[str], where: str) -> None:
    """A webhook: a path, and a record made from its body or a service it goes to."""
    thing = f"webhook {hook['id']!r}"
    if sum(bool(hook.get(k)) for k in ("model", "forward", "handler")) != 1:
        raise QuillError(
            f"{where}: {thing} makes a record in a model, forwards to a service, or is answered"
            " by a handler: one of them"
        )
    if hook.get("forward") and hook["forward"] not in service_ids:
        raise QuillError(f"{where}: {thing} forwards to a service it does not have")
    path = hook.setdefault("path", hook["id"])
    if not isinstance(path, str) or not HOOK_PATH_RE.match(path):
        raise QuillError(f"{where}: {thing} path is lowercase letters, digits, - and _")
    if path in paths:
        raise QuillError(f"{where}: two webhooks at /hooks/{where}/{path}")
    paths.add(path)
    mapping = hook.get("map", {})
    if (hook.get("forward") or hook.get("handler")) and mapping:
        raise QuillError(f"{where}: {thing} has no map: only a webhook that makes a record maps")
    if not isinstance(mapping, dict):
        raise QuillError(f'{where}: {thing} map is a table: field = "$.path"')
    for name, path_text in mapping.items():
        try:
            parse_path(path_text)
        except PathError as exc:
            raise QuillError(f"{where}: {thing} map {name}: {exc}") from exc
    signature = hook.get("signature", "")
    if signature and not (isinstance(signature, str) and re.match(r"^[A-Za-z0-9-]+$", signature)):
        raise QuillError(f"{where}: {thing} signature is the name of a header")


def _features(head: dict, where: str) -> tuple[str, ...]:
    features = head.get("features", [])
    if not isinstance(features, list) or not all(isinstance(f, str) and f.strip() for f in features):
        raise QuillError(f"{where}: features is a list of one-line sentences")
    return tuple(f.strip() for f in features)


def load_manifest(folder: Path, *, owner: str = "") -> Manifest:
    """The manifest in *folder*, with its `.origin.json`; as *owner*'s own Quill when one is named."""
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
    return personalise(manifest, owner) if owner else manifest
