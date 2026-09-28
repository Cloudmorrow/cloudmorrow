"""The Quills on this server, the catalog, and installing from it.

`GET /api/quills` is what every client draws its Quill tabs from: each
installed Quill with its screens and the full definition of every datamodel
those screens need, so a client renders the kit without asking twice.

The catalog, the install sheet (`/plan`) and installing are here too.
Anybody signed in may look; only an administrator may install or remove,
because a Quill is part of what the server is.

What a client is sent is fitted to whoever asks (docs/CIRCLES.md): each
datamodel carries their `access`, a datamodel their circles do not give is
left out, and so are the fields that link to it and the screens drawn over
it. A Quill with no screens left comes `available: false`, and is not on.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from cloudmorrow.server.circles import NONE, Access
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.quillhandlers import CodeError
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


# The screen's bindings that say what it is drawn within: a board's boards,
# a calendar's calendars, a thread's channels, a list's groups.
WITHIN = ("group", "subgroup", "space")


def _screen_needs(screen: dict, models: dict[str, dict]) -> set[str]:
    """Every datamodel a screen cannot be drawn without: its own, and what it is within."""
    if screen.get("kit") == "view" and not screen.get("model"):
        return set()
    model = models.get(screen["model"])
    if model is None:
        return {screen["model"]}
    needs = {screen["model"]}
    by_name = {f["name"]: f for f in model["fields"]}
    for name in (*(screen.get(key) for key in WITHIN), model.get("in_space")):
        found = by_name.get(name) if isinstance(name, str) else None
        if found and found["kind"] == "link" and found.get("to"):
            needs.add(found["to"])
    return needs


def fitted(quill: dict, access: Access) -> dict:
    """*quill* as *access* may use it: see the module's docstring."""
    models = quill["models"]
    kept = {}
    for model_id, model in models.items():
        level = access.level(model_id)
        if level == NONE:
            continue
        kept[model_id] = model | {
            "access": level,
            "fields": [
                f for f in model["fields"]
                if f["kind"] != "link" or not f.get("to") or access.may("read", f["to"])
            ],
        }
    screens = [
        screen for screen in quill["screens"]
        if all(needed in kept for needed in _screen_needs(screen, models))
    ]
    own = set(quill["uses"]) | set(quill["introduces"]) | set(quill["extends"])
    available = bool(screens) if quill["screens"] else any(m in kept for m in own)
    # An action on records they cannot see is not theirs to press; one they
    # may only read is shown, and the gate says no if its code writes.
    actions = [a for a in quill.get("actions", []) if not a.get("on") or a["on"] in kept]
    return quill | {
        "models": kept,
        "screens": screens,
        "actions": actions,
        "available": available,
        "enabled": bool(quill.get("enabled", True)) and available,
    }


def _for(state: AppState, user: User, quill: dict) -> dict:
    quill = _with_models(state, quill)
    return fitted(quill, state.circles.access_for(user.username)) if state.circles else quill


@router.get("")
def list_quills(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Every installed Quill, with whether it is on for you, and what it draws."""
    rows = []
    for quill in state.quills.installed():
        quill["enabled"] = state.features.enabled_for(user.username, quill["id"])
        quill["readme"] = ""
        rows.append(_for(state, user, quill))
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
    admin: User = Depends(get_admin_user),
) -> dict:
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        try:
            folder, models, origin = _resolve(state, payload, Path(tmp))
            # Its code, if it has any, runs as whoever said yes.
            return state.quills.install(
                folder, models, origin=origin | {"installed_by": admin.username}
            )
        except QuillError as exc:
            raise _bad(exc) from exc


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload(
    request: Request,
    plan_only: bool = False,
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
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
            return state.quills.install(
                folder, models,
                origin={"catalog": False, "dev": True, "installed_by": admin.username},
            )
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
            return _for(state, user, quill)
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


# -- a Quill's code, pressed and drawn -------------------------------------------------
class ActionIn(BaseModel):
    """An action pressed: on which record (for an action `on` a datamodel), with its form."""

    record: str = ""
    fields: dict = {}


def _code(state: AppState):
    if state.code is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this server runs no Quill code")
    return state.code


def _failed(exc: CodeError) -> HTTPException:
    return HTTPException(exc.status, exc.to_dict())


@router.get("/{quill_id}/views/{screen_id}")
def view(
    quill_id: str,
    screen_id: str,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """A view drawn for whoever asks: the tree of primitives its code returned.

    Query parameters are the view's `ctx.params`; `record` (with `model`, if
    the screen names none) is the record it was opened on.
    """
    params = dict(request.query_params)
    record = params.pop("record", "")
    try:
        tree = _code(state).view(user.username, quill_id, screen_id, params, record=record)
    except CodeError as exc:
        raise _failed(exc) from exc
    return {"quill": quill_id, "screen": screen_id, "tree": tree}


@router.post("/{quill_id}/actions/{action_id}")
def press(
    quill_id: str,
    action_id: str,
    payload: ActionIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Run an action as whoever pressed it: what the surface does next, as effects."""
    try:
        effects = _code(state).action(
            user.username, quill_id, action_id, record=payload.record, fields=payload.fields
        )
    except CodeError as exc:
        raise _failed(exc) from exc
    return {"effects": effects}
