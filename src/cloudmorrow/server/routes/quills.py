"""The Quills on this server, the catalog, and installing from it.

`GET /api/quills` is what every client draws its Quill tabs from: each
installed Quill with its screens and the full definition of every datamodel
those screens need, so a client renders the kit without asking twice.

The catalog, the install sheet (`/plan`) and installing are here too.
Anybody signed in may look; only an administrator may install or remove,
because a Quill is part of what the server is.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.quills import MANIFEST, MAX_DOWNLOAD, QuillError, fetch, load_catalog

router = APIRouter(prefix="/api/quills", tags=["quills"])


class QuillSource(BaseModel):
    """A Quill from the catalog by id, or from a source: a folder or a repository."""

    id: str = ""
    source: str = ""
    ref: str = ""
    # For a source: where its foundational datamodels come from. Empty, the
    # catalog's datamodels.
    datamodels: str = ""


def _bad(exc: QuillError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _with_models(state: AppState, quill: dict) -> dict:
    """A Quill as a client draws it: its datamodels in full beside it."""
    wanted = set(quill["uses"]) | set(quill["introduces"]) | set(quill["extends"])
    wanted |= {g["model"] for g in quill["grants"]}
    # Links from those, so a board's chips can be titled.
    for model_id in list(wanted):
        model = state.quills.datamodels.get(model_id)
        if model:
            wanted |= {f.to for f in model.fields if f.kind == "link"}
    quill["models"] = {
        model_id: state.quills.datamodels[model_id].to_dict()
        # What the record API does for it besides the five calls: search,
        # and folders and attachments where its backend has them.
        | {"can": state.records.capabilities(model_id)}
        for model_id in sorted(wanted)
        if model_id in state.quills.datamodels
    }
    return quill


@router.get("")
def list_quills(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Every installed Quill, with whether it is on for you, and what it draws."""
    rows = []
    for quill in state.quills.installed():
        quill["enabled"] = state.features.enabled_for(user.username, quill["id"])
        quill["readme"] = ""
        rows.append(_with_models(state, quill))
    return rows


@router.get("/catalog")
def catalog(state: AppState = Depends(get_state), _: User = Depends(get_current_user)) -> dict:
    """The catalog, as this server reads it, with what is installed marked."""
    try:
        found = load_catalog(state.config.quill_catalog)
    except QuillError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    installed = {q.id: q.version for q in state.quills.quills.values()}
    return {
        "categories": found.categories,
        "quills": [
            {**entry, "installed_version": installed.get(entry["id"])} for entry in found.quills
        ],
    }


def _resolve(state: AppState, payload: QuillSource, tmp: Path) -> tuple[Path, Path | None, dict]:
    """The folder a request names, the datamodels to go with it, and where it came from."""
    if bool(payload.id) == bool(payload.source):
        raise QuillError("name a Quill from the catalog, or a source, one of them")
    if payload.id:
        found = load_catalog(state.config.quill_catalog)
        entry = found.entry(payload.id)
        folder = fetch(entry["repo"], str(entry.get("ref", "")), base=found.base, into=tmp / "q")
        models = state.quills.datamodels_source(found, tmp / "m")
        return folder, models, {
            "catalog": True, "repo": entry["repo"], "ref": entry.get("ref", ""),
            "position": found.quills.index(entry),
        }
    folder = fetch(payload.source, payload.ref, into=tmp / "q")
    if payload.datamodels:
        models = fetch(payload.datamodels, "", into=tmp / "m")
    else:
        try:
            models = state.quills.datamodels_source(
                load_catalog(state.config.quill_catalog), tmp / "m"
            )
        except QuillError:
            models = None
    return folder, models, {"catalog": False, "repo": payload.source, "ref": payload.ref}


@router.post("/plan")
def plan(
    payload: QuillSource,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """What installing would add, without installing: the install sheet."""
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        try:
            folder, models, _origin = _resolve(state, payload, Path(tmp))
            return state.quills.plan(folder, models)
        except QuillError as exc:
            raise _bad(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def install(
    payload: QuillSource,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        try:
            folder, models, origin = _resolve(state, payload, Path(tmp))
            return state.quills.install(folder, models, origin=origin)
        except QuillError as exc:
            raise _bad(exc) from exc


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    plan_only: bool = False,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """Install a folder somebody is working on, sent as a .tar.gz: `cm quill dev`.

    The same install as any other, marked as a development Quill. With
    `?plan_only=true` it is the install sheet and nothing is installed.
    """
    data = await request.body()
    if len(data) > MAX_DOWNLOAD:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "bigger than a Quill should be"
        )
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        root = Path(tmp) / "q"
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                archive.extractall(root, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"not a .tar.gz of a Quill: {exc}"
            ) from exc
        manifests = sorted(root.rglob(MANIFEST), key=lambda p: len(p.parts))
        if not manifests:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"there is no {MANIFEST} in what was sent"
            )
        folder = manifests[0].parent
        try:
            models = state.quills.datamodels_source(
                load_catalog(state.config.quill_catalog), Path(tmp) / "m"
            )
        except QuillError:
            models = None
        try:
            if plan_only:
                return state.quills.plan(folder, models)
            return state.quills.install(folder, models, origin={"catalog": False, "dev": True})
        except QuillError as exc:
            raise _bad(exc) from exc


@router.get("/{quill_id}")
def get_quill(
    quill_id: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    for quill in state.quills.installed():
        if quill["id"] == quill_id:
            quill["enabled"] = state.features.enabled_for(user.username, quill_id)
            return _with_models(state, quill)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"{quill_id} is not installed")


@router.delete("/{quill_id}", status_code=status.HTTP_204_NO_CONTENT)
def uninstall(
    quill_id: str,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> None:
    """Take a Quill away. Its records stay: they were never its."""
    try:
        state.quills.uninstall(quill_id)
    except QuillError as exc:
        raise _bad(exc) from exc
