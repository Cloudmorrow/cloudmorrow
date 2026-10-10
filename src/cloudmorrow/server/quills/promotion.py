"""Somebody's own Quill becoming the server's: promotion, and adoption.

Alice's Budget, shared with two people and worth having for everyone, is
promoted by an administrator: the same folder is installed as a server
Quill, for the audience the administrator picks, and every record of its
datamodels — hers, and the two people's — moves from `~alice.budget.*` to
`budget.*`, sealed again under the new name. Her own copy is then gone,
and so are its shares; the people who had it have the server's now.

Adoption is the same move in the other order: the server Quill arrives
first (from the catalog, say, after Alice published it), and the install
sheet offers to bring her records, and anybody else's own Budget's, into it.

See docs/SHARING.md, *Promoted* and *Published*.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from cloudmorrow.server.quills.catalog import load_catalog
from cloudmorrow.server.quills.manifest import QuillError
from cloudmorrow.server.quills.registry import QuillRegistry
from cloudmorrow.server.quills.sharing import SharingStore
from cloudmorrow.server.records import RecordStore

__all__ = ["adopt", "promote"]


def adopt(registry: QuillRegistry, records: RecordStore, sharing: SharingStore, owner: str, quill_id: str) -> dict:
    """*owner*'s own *quill_id* folds into the server Quill of that id: its records
    become the server datamodels' (every owner's, since it may have been shared),
    its folder goes, and so do its shares. Returns `{datamodel: records moved}`."""
    personal = registry.personal.get(owner, {}).get(quill_id)
    server = registry.quills.get(quill_id)
    if personal is None:
        raise QuillError(f"{owner} has no Quill of their own called {quill_id}")
    if server is None:
        raise QuillError(f"{quill_id} is not a Quill of the server's")
    offered = {m.id for m in server.introduces}
    moved: dict[str, int] = {}
    for plain, prefixed in personal.renamed.items():
        if plain in offered:
            moved[plain] = records.rename_model(prefixed, plain)
    registry.uninstall(quill_id, owner)
    sharing.forget(owner, quill_id)
    return moved


def promote(
    registry: QuillRegistry,
    records: RecordStore,
    sharing: SharingStore,
    owner: str,
    quill_id: str,
    *,
    by: str,
    audience: dict | None = None,
) -> dict:
    """Install *owner*'s *quill_id* as the server's, for *audience* (empty: everyone),
    and adopt their records into it. Returns the install plan, with `moved`."""
    personal = registry.personal.get(owner, {}).get(quill_id)
    if personal is None:
        raise QuillError(f"{owner} has no Quill of their own called {quill_id}")
    if quill_id in registry.quills:
        raise QuillError(f"{quill_id} is a Quill of this server's already")
    folder = personal.folder or registry.folder_of(quill_id, owner)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        try:
            models = registry.datamodels_source(load_catalog(registry.catalog_location), Path(tmp) / "m")
        except QuillError:
            models = None
        plan = registry.install(
            folder,
            models,
            origin={
                "catalog": False,
                "promoted_from": owner,
                "installed_by": by,
                "audience": audience or {"circles": [], "people": []},
            },
        )
    plan["moved"] = adopt(registry, records, sharing, owner, quill_id)
    return plan
