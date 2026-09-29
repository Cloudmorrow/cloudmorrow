"""Writing a datamodel's datasets: your first board, the calendar everyone shares.

A Quill ships datasets with its datamodels, to be written per person, per
space, or once per server. They are written the first time the datamodel is
listed, by whoever lists it: through the record API, an assistant's tools,
or a Quill's own code, which all call this.
"""

from __future__ import annotations

from cloudmorrow.server.records import Principal
from cloudmorrow.server.state import AppState


def seed(state: AppState, principal: Principal, model: str) -> None:
    """Write any dataset for *model* not written yet: per person, per space, or once per server."""
    for manifest, dataset in state.quills.seeds_for(model):
        if dataset["seed"] == "per-space":
            state.records.seed_spaces(principal, model, dataset["records"], writer=manifest.id)
            continue
        state.records.seed(
            principal,
            model,
            dataset["records"],
            writer=manifest.id,
            once=dataset["seed"] == "once",
            scope=dataset.get("scope"),
        )
