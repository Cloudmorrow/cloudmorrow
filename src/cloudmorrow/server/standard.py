"""The standard quills: what a new cloud is offered, and choosing among them.

Two kinds, one list, because a person choosing does not care which is which:

* **Catalog quills** marked `foundation = true` in the Quill Catalog —
  Tasks and Files today. Choosing one installs it; leaving one out installs nothing.
* **Built-in features** that are still part of the core while the kit
  grows to draw them — Notes, Calendar, Chat, Secrets. Choosing one
  leaves it on; leaving one out switches it off for the server, which an
  administrator can undo from Administration. As each moves into a repo of
  its own it leaves `features.FEATURES` and turns up in the catalog, and
  this list follows without a change here.

A choice is made once, by the installer (or `cloudmorrow-server quill
choose`), before the server first starts. It is remembered, so the boot
work that would otherwise install every foundation Quill on a fresh server
stands aside.
"""

from __future__ import annotations

from dataclasses import dataclass

from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.features import FEATURES, FeatureStore
from cloudmorrow.server.quilljobs import FILES_QUILL, SEEDED, read_meta, write_meta
from cloudmorrow.server.quills import Catalog, QuillError, QuillRegistry, load_catalog


@dataclass(frozen=True, slots=True)
class Choice:
    id: str
    name: str
    summary: str
    # "quill": installed from the catalog. "built-in": part of the core, on or off.
    kind: str


def choices(config: ServerConfig) -> tuple[list[Choice], Catalog | None, str]:
    """Every standard quill, the catalog they came from, and why it could not be read, if so."""
    found: list[Choice] = []
    catalog: Catalog | None = None
    problem = ""
    try:
        catalog = load_catalog(config.quill_catalog)
    except QuillError as exc:
        problem = str(exc)
    if catalog is not None:
        found += [
            Choice(entry["id"], entry.get("name", entry["id"]), entry.get("summary", ""), "quill")
            for entry in catalog.quills
            if entry.get("foundation")
        ]
    taken = {c.id for c in found}
    found += [
        Choice(feature.key, feature.label, feature.description, "built-in")
        for feature in FEATURES
        if feature.key not in taken
    ]
    # By name: a person choosing reads a list, not an architecture.
    found.sort(key=lambda c: c.name.casefold())
    return found, catalog, problem


def chosen_already(config: ServerConfig) -> bool:
    return bool(read_meta(config.db_path, SEEDED))


def choose(
    config: ServerConfig,
    wanted: set[str],
    *,
    by: str = "installer",
    registry: QuillRegistry | None = None,
    features: FeatureStore | None = None,
    remove_unwanted: bool = False,
) -> dict[str, list[str]]:
    """Install the wanted catalog quills and switch off the built-ins left out.

    *registry* and *features* are a running server's own, when it is the
    one choosing (the first-boot page); from the shell they are made here.
    *remove_unwanted* takes away a catalog quill that is installed but not
    wanted — only for a server nobody has used yet, where the boot work may
    have installed it a moment before the choice was made.

    Returns what was done, by kind. Raises QuillError if a wanted quill cannot
    be installed; built-ins are switched first, so a failed download leaves a
    server that is otherwise as chosen.
    """
    options, catalog, problem = choices(config)
    known = {c.id for c in options}
    unknown = wanted - known
    if unknown:
        raise QuillError(f"not a standard quill: {', '.join(sorted(unknown))}")
    done: dict[str, list[str]] = {"installed": [], "removed": [], "on": [], "off": []}
    features = features or FeatureStore(config.db_path)
    for option in options:
        if option.kind != "built-in":
            continue
        features.set(option.id, option.id in wanted, changed_by=by)
        done["on" if option.id in wanted else "off"].append(option.id)
    registry = registry or QuillRegistry(config.quills_dir, config.datamodels_dir, config.quill_catalog)
    # The choice is remembered before the downloads, so the boot work does
    # not install what was just left out while they run.
    write_meta(config.db_path, SEEDED, ",".join(sorted(wanted)) or "-")
    # Files was built in once; a server choosing now has chosen about it too.
    write_meta(config.db_path, FILES_QUILL, "chosen")
    for option in options:
        if option.kind != "quill":
            continue
        if option.id in wanted and option.id not in registry.quills:
            if catalog is None:
                raise QuillError(f"cannot install {option.name}: {problem}")
            registry.install_from_catalog(option.id, catalog)
            done["installed"].append(option.id)
        elif option.id not in wanted and option.id in registry.quills and remove_unwanted:
            registry.uninstall(option.id)
            done["removed"].append(option.id)
    return done
