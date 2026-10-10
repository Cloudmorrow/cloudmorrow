"""Removing a Quill: what it brought stays, unless the administrator says otherwise.

A Quill's screens and jobs go with it; the records never do, because they
were never its. What it *brought* — the datamodels it introduced, and the
fields it added to foundational ones — stays too, by default: the records
of an introduced datamodel are there again the day the Quill comes back,
and its fields sit on the records, read-only, until another Quill declares
them. An administrator removing the Quill may choose to drop any of that,
records and all, and the sheet says how many records each holds, so the
choice is made knowing what goes (docs/DATAMODELS.md, *Two kinds*).
"""

from __future__ import annotations

from collections.abc import Iterable

from cloudmorrow.server.quills import QuillError, QuillRegistry
from cloudmorrow.server.records import RecordStore

__all__ = ["brought", "remove"]


def brought(registry: QuillRegistry, records: RecordStore, quill_id: str, owner: str = "") -> list[dict]:
    """What *quill_id* brought to this server, with how many records hold each:
    `{"id", "kind": "datamodel" | "field", "label", "model", "records"}`.
    With *owner*, their own Quill of that id."""
    manifest = registry.by_key(f"~{owner}.{quill_id}" if owner else quill_id)
    if manifest is None:
        raise QuillError(f"{quill_id} is not installed")
    found: list[dict] = []
    for model in manifest.introduces:
        if model.backend:
            continue
        found.append(
            {
                "id": model.id,
                "kind": "datamodel",
                "label": model.label,
                "model": model.id,
                "records": records.count_all(model.id),
            }
        )
    for model_id, fields in manifest.extends.items():
        model = registry.datamodels.get(model_id)
        for name in fields:
            field = f"{manifest.id}.{name}"
            spec = model.by_name.get(field) if model else None
            found.append(
                {
                    "id": field,
                    "kind": "field",
                    "label": f"{(spec.label if spec else '') or name.replace('_', ' ').capitalize()}"
                    f" on {model.label if model else model_id}",
                    "model": model_id,
                    "records": records.count_with_field(model_id, field) if model and not model.backend else 0,
                }
            )
    return found


def remove(
    registry: QuillRegistry, records: RecordStore, quill_id: str, drop: Iterable[str] = (), *, owner: str = ""
) -> dict:
    """Take the Quill away, dropping what *drop* names of what it brought — records
    and all — and keeping the rest. Returns `{"dropped": {id: records gone}}`.

    What goes is dropped while the Quill's datamodels are still known, so a
    sealed body can be opened and rewritten; then the Quill is removed.
    """
    wanted = {str(name).strip() for name in drop if str(name).strip()}
    offered = {row["id"]: row for row in brought(registry, records, quill_id, owner)}
    unknown = sorted(wanted - set(offered))
    if unknown:
        raise QuillError(f"{quill_id} did not bring {', '.join(unknown)}")
    dropped: dict[str, int] = {}
    for name in sorted(wanted):
        row = offered[name]
        if row["kind"] == "datamodel":
            dropped[name] = records.drop_model(row["model"])
        else:
            dropped[name] = records.drop_field(row["model"], name)
    registry.uninstall(quill_id, owner)
    return {"dropped": dropped}
