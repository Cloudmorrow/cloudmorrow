"""A Quill's code on a person's own machine: what the agent there asks the server.

A `[[machine]]` handler runs in the agent, in the same sandbox as on the
server, on a machine whose owner switched it on there (in that machine's
`agent.toml`, never from here). Everything the code asks for that is not on
the machine — records, the time, a fetch, a secret — comes here, with the
agent's token, and is answered as the machine's owner, through the gate,
bound by the Quill's manifest exactly as on the server:

* `GET  /api/agent/quills` — the installed Quills that have machine handlers,
  and what each needs; the agent runs only the ones switched on locally.
* `GET  /api/agent/quills/{id}/code` — the installed copy, as a tarball.
* `POST /api/agent/quills/{id}/host` — one request from the code: `{op, args}`.
"""

from __future__ import annotations

import io
import tarfile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from cloudmorrow.quill import context as sdk
from cloudmorrow.server.agents import Agent
from cloudmorrow.server.deps import AppState, get_current_agent, get_state
from cloudmorrow.server.quills import ORIGIN, Manifest
from cloudmorrow.server.quills.code import HostCalls

router = APIRouter(prefix="/api/agent/quills", tags=["agents"])

# What a machine handler may ask the server for. `run` is answered on the
# machine itself; nothing else is anybody's to ask for.
OPS = frozenset(
    {
        "records.list",
        "records.get",
        "records.create",
        "records.patch",
        "records.move",
        "records.delete",
        "now",
        "log",
        "fetch",
        "secret",
    }
)


class HostIn(BaseModel):
    op: str
    args: dict = {}
    machine: str = ""


def _shelf(state: AppState, username: str) -> list[Manifest]:
    return list(state.shelf.for_user(username).values()) if state.shelf else list(state.quills.quills.values())


def _machine_quill(state: AppState, agent: Agent, quill_id: str) -> Manifest:
    manifest = next((m for m in _shelf(state, agent.owner) if m.id == quill_id), None)
    if manifest is None or not manifest.machine or not manifest.code:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{quill_id} has no code for a machine")
    if not state.features.enabled_for(agent.owner, manifest.key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{manifest.name} is switched off")
    if state.code is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this server runs no Quill code")
    return manifest


@router.get("")
def machine_quills(state: AppState = Depends(get_state), agent: Agent = Depends(get_current_agent)) -> list[dict]:
    """Every Quill with a machine handler that is on for this machine's owner."""
    rows = []
    for manifest in _shelf(state, agent.owner):
        if not manifest.machine or not manifest.code:
            continue
        if not state.features.enabled_for(agent.owner, manifest.key):
            continue
        rows.append(
            {
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                # Changes when it is installed again: the agent fetches the code anew.
                "stamp": str(manifest.origin.get("installed_at", "")) + manifest.version,
                "code": manifest.code,
                "owner": agent.owner,
                "machine": list(manifest.machine),
            }
        )
    return rows


@router.get("/{quill_id}/code")
def machine_code(
    quill_id: str, state: AppState = Depends(get_state), agent: Agent = Depends(get_current_agent)
) -> Response:
    manifest = _machine_quill(state, agent, quill_id)
    folder = manifest.folder or state.quills.folder_of(quill_id, manifest.owner)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder)
            if relative.parts[0] in (ORIGIN, ".git", "__pycache__") or "__pycache__" in relative.parts:
                continue
            if path.is_file():
                archive.add(path, arcname=str(relative))
    return Response(buffer.getvalue(), media_type="application/gzip")


@router.post("/{quill_id}/host")
def machine_host(
    quill_id: str,
    payload: HostIn,
    state: AppState = Depends(get_state),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    """One request from a machine handler, answered as the machine's owner."""
    manifest = _machine_quill(state, agent, quill_id)
    if payload.op not in OPS:
        return {"ok": False, "kind": "refused", "message": f"{payload.op} is not the server's to answer"}
    principal = state.code.principal_for(manifest, agent.owner, via="person")
    calls = HostCalls(state.code, manifest, principal, via="person")
    args = dict(payload.args)
    if payload.op == "log":
        args["line"] = f"[{agent.name}{' ' + payload.machine if payload.machine else ''}] {args.get('line', '')}"
    try:
        return {"ok": True, "value": calls(payload.op, args)}
    except sdk.HostError as exc:
        kind = next((k for k, cls in sdk.ERRORS.items() if isinstance(exc, cls)), "refused")
        return {"ok": False, "kind": kind, "message": str(exc)}
