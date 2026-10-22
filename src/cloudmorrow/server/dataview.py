"""Data: every datamodel a person may see, and the records in it, to look at.

A tab on every shelf, beside the Quills, drawn by the kit's `data` element:
the datamodels down one level, the records of the one picked down the next,
and each record on the sheet every record has — read, not written. It is
how somebody sees what is on the server about them without a Quill for
each kind of thing, and where a snapshot and the attestations on it are
seen (docs/ATTESTATIONS.md) until a Quill draws them better.

It is a Quill as a client is told one — the same shape `GET /api/quills`
sends for every other — with no folder, no code and no catalog entry: the
server composes it for whoever asks, from the datamodels their circles give
them (docs/CIRCLES.md), every one of them marked `read` whatever their
circles say, so every surface draws it as a thing looked at. Datamodels a
backend keeps — files, secrets — are left out: those are their Quills'.
"""

from __future__ import annotations

from cloudmorrow.server.circles import NONE, Access
from cloudmorrow.server.features import Feature
from cloudmorrow.server.state import AppState

__all__ = ["DATA", "DATA_FEATURE", "data_quill"]

DATA = "data"
SUMMARY = "Every kind of data here you may see, and what is in it."
# The tab is a feature like a Quill's: an administrator switches it off for
# the server, a person for themselves, and the clients draw it or not.
DATA_FEATURE = Feature(DATA, "Data", SUMMARY, ())

SCREEN = {"id": DATA, "kit": DATA, "label": "Data"}


def data_quill(state: AppState, username: str, access: Access | None) -> dict:
    """The Data tab for *username*, fitted to their *access* (None: everybody everything)."""
    models: dict[str, dict] = {}
    for model_id, model in sorted(state.quills.datamodels.items()):
        if model.backend:
            continue
        level = access.level(model_id) if access is not None else "write"
        if level == NONE:
            continue
        fields = [
            f.to_dict()
            for f in model.fields
            if f.kind != "link" or not f.to or access is None or access.may("read", f.to)
        ]
        models[model_id] = model.to_dict() | {
            "fields": fields,
            "can": state.records.capabilities(model_id),
            # Looked at, whatever the circles give: this tab writes nothing.
            "access": "read",
        }
    enabled = state.features.enabled_for(username, DATA)
    return {
        "id": DATA,
        "key": DATA,
        "name": "Data",
        "version": "",
        "summary": SUMMARY,
        "features": [
            "Every datamodel your circles give you, with its records, to look at",
            "A record's sheet, its history, and what links to it",
            "A snapshot with its digest and the attestations on it",
        ],
        "category": "",
        "icon": "database",
        "publisher": "Cloudmorrow",
        "license": "AGPL-3.0-or-later",
        "uses": list(models),
        "extends": {},
        "introduces": [],
        "grants": [],
        "screens": [dict(SCREEN)],
        "jobs": [],
        "datasets": [],
        "services": [],
        "webhooks": [],
        "apis": [],
        "code": "",
        "sdk": "",
        "actions": [],
        "hooks": [],
        "fetch": [],
        "secrets": [],
        "machine": [],
        "requires": {"runtimes": [], "quills": []},
        "origin": {},
        "owner": "",
        "personal": False,
        "renamed": {},
        "readme": "",
        "data": [
            {
                "id": model_id,
                "label": m["label"],
                "how": "uses",
                "foundation": m["source"] == "foundation",
                "new": False,
            }
            for model_id, m in models.items()
        ],
        "surfaces": ["phone", "web", "terminal", "command line"],
        "installed_version": None,
        "runs_code": [],
        "quill_code": None,
        "runs_as": "",
        "reach": list(models),
        "runtimes": [],
        "models": models,
        "available": bool(models),
        "enabled": enabled and bool(models),
        "mine": False,
        "shared_by": "",
        "audience": {"circles": [], "people": []},
        # Not installed: composed by the server for whoever asks.
        "composed": True,
    }
