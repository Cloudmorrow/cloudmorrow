"""Quills of people's own: yours, the ones offered to you, what you asked for, and
what the server allows (docs/SHARING.md).

Under `/api/quills`, beside the server's Quills (routes/quills.py), and
included before them so `mine`, `offers`, `requests`, `policy`, `promote`
and `all` are not read as a Quill's id:

* `/api/quills/mine` — your own Quills: install one (from the catalog, a
  source, or an upload), remove one, share it, export it, fork one you have.
* `/api/quills/offers/…` — a Quill somebody offered you: yes, no, or leave.
* `/api/quills/requests` — asking an administrator for a Quill, and their answer.
* `/api/quills/policy` — the four switches an administrator sets, for the
  server and, under `/policy/{username}`, for one person in particular.
* `/api/quills/promote`, `/api/quills/all` — an administrator's: somebody's
  Quill made the server's, and everything there is, whose it is and who has it.

Everything a person does here is to their own shelf, and runs as them; the
gate says the rest.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.quills import MANIFEST, MAX_DOWNLOAD, QuillError, load_catalog, promotion, removal
from cloudmorrow.server.quills import export as exporting
from cloudmorrow.server.quills.manifest import Manifest
from cloudmorrow.server.quills.sharing import (
    ACCEPTED,
    APPROVED,
    DECLINED,
    INHERIT,
    OFFERED,
    POLICY,
    WITHDRAWN,
    SharingError,
)
from cloudmorrow.server.quills.shelf import audience_of
from cloudmorrow.server.records import Principal
from cloudmorrow.server.routes.install import base_url
from cloudmorrow.server.routes.quills import QuillSource, _resolve

router = APIRouter(prefix="/api/quills", tags=["quills"])


class Audience(BaseModel):
    """Who a server Quill is for: nobody named is everybody."""

    circles: list[str] = []
    people: list[str] = []


class ShareIn(BaseModel):
    people: list[str] = []
    circles: list[str] = []
    # What each of them may do with the datamodels of the Quill's own, by the
    # name the server knows them by (`~alice.budget.envelope`) or the plain
    # one (`budget.envelope`): write or read. Nothing named is write. Offered
    # again to somebody who has it, this changes their rules and nothing else.
    rules: dict[str, str] = {}


class RequestIn(BaseModel):
    kind: str = "install"  # install, promote
    id: str = ""
    source: str = ""
    ref: str = ""
    note: str = ""


class Approval(BaseModel):
    audience: Audience = Audience()
    # Circles that get write on the datamodels it introduces, as the install sheet asks.
    give_to: list[str] = []
    note: str = ""


class Decline(BaseModel):
    note: str = ""


class ForkIn(BaseModel):
    id: str
    new_id: str
    name: str = ""


class PolicyIn(BaseModel):
    personal_quills: str | None = None
    personal_quill_code: str | None = None
    personal_quill_sharing: str | None = None
    personal_quill_create: str | None = None


class PromoteIn(BaseModel):
    owner: str
    id: str
    audience: Audience = Audience()
    give_to: list[str] = []


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _shelf(state: AppState):
    if state.shelf is None or state.sharing is None or state.policy is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "this server keeps no shelves")
    return state.shelf


def _may(state: AppState, user: User) -> dict:
    """What the policy means for this person: the server's answers, with what an
    administrator said about them in particular in front."""
    policy = state.policy.get_for(user.username)
    return {
        "have": state.policy.may_have(user.username),
        "install": state.policy.may_install(user.username),
        "ask": policy["personal_quills"] == "ask",
        "code": state.policy.may_code(user.username),
        "share": state.policy.may_share(user.username),
        "create": state.policy.may_create(user.username),
        "admin": user.is_admin,
    }


def _check_personal_plan(state: AppState, plan: dict, user: User) -> None:
    """What the policy says about a Quill of somebody's own, before it is installed."""
    if plan.get("code") and not state.policy.may_code(user.username):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Quills of your own may not run code on this server")


def _require_create(state: AppState, user: User) -> None:
    """Making a Quill of one's own — from a folder, a source, a fork — rather than
    taking one from the catalog, when the policy allows that for this person."""
    if not state.policy.may_create(user.username):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "making Quills of your own is switched off for you on this server; the catalog is open",
        )


def _holder(state: AppState, user: User, owner: str, quill_id: str) -> Manifest:
    """*owner*'s Quill, which stands with *user*: theirs, or shared with them and accepted."""
    manifest = state.quills.personal.get(owner, {}).get(quill_id)
    if manifest is None or user.username not in state.shelf.holders(manifest):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{owner}'s {quill_id} is not on your shelf")
    return manifest


def _describe_mine(state: AppState, manifest: Manifest, request: Request | None = None) -> dict:
    row = state.quills.describe(manifest)
    row["shared_with"] = state.sharing.shared_with(manifest.owner, manifest.id)
    row["enabled"] = state.features.enabled(manifest.key)
    # Who it stands with, and whether its owner took it off their own shelf.
    row["holders"] = state.shelf.holders(manifest)
    row["owner_left"] = state.sharing.owner_left(manifest.owner, manifest.id)
    if request is not None and manifest.webhooks and state.quill_tokens is not None:
        base = base_url(request, state)
        row["webhook_urls"] = [
            {
                "id": h["id"],
                "url": f"{base}/hooks/{manifest.key}/{h['path']}",
                "secret": state.quill_tokens.webhook_secret(manifest.key, h["id"]),
            }
            for h in manifest.webhooks
        ]
    return row


# -- the policy --------------------------------------------------------------------------
@router.get("/policy")
def policy(state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """What this server lets people do with Quills of their own, and what that means for you."""
    _shelf(state)
    return {**state.policy.get(), "may": _may(state, user)}


@router.put("/policy")
def set_policy(payload: PolicyIn, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)) -> dict:
    _shelf(state)
    try:
        for key, value in payload.model_dump().items():
            if value is not None:
                state.policy.set(key, value, changed_by=admin.username)
    except SharingError as exc:
        raise _bad(exc) from exc
    return {**state.policy.get(), "may": _may(state, admin)}


def _person_policy(state: AppState, username: str) -> dict:
    return {
        "username": username,
        "server": state.policy.get(),
        "own": state.policy.overrides(username),
        "effective": state.policy.get_for(username),
        "settings": {key: [*values, INHERIT] for key, values in POLICY.items()},
    }


@router.get("/policy/{username}")
def person_policy(username: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """What stands for one person: the server's settings, what was said about them in
    particular (`own`), and the two together (`effective`)."""
    _shelf(state)
    if state.users.get(username) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such account: {username}")
    return _person_policy(state, username)


@router.put("/policy/{username}")
def set_person_policy(
    username: str, payload: PolicyIn, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)
) -> dict:
    """Say something about one person: a value per setting, or `inherit` for the server's."""
    _shelf(state)
    if state.users.get(username) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such account: {username}")
    try:
        for key, value in payload.model_dump().items():
            if value is not None:
                state.policy.set_for(username, key, value, changed_by=admin.username)
    except SharingError as exc:
        raise _bad(exc) from exc
    return _person_policy(state, username)


# -- mine ----------------------------------------------------------------------------------
@router.get("/mine")
def mine(request: Request, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """Your shelf's own part: your Quills and who has them, what you were offered, what you asked for."""
    shelf = _shelf(state)
    own = state.quills.personal.get(user.username, {})
    return {
        "may": _may(state, user),
        # Theirs, the ones they took off their shelf while others still have
        # them included, said so (`owner_left`).
        "quills": [_describe_mine(state, m, request) for m in state.quills.ordered(own.values())],
        "shadowed": [{"id": m.id, "owner": m.owner, "name": m.name} for m in shelf.shadowed(user.username)],
        "offers": _offers(state, user.username),
        "requests": state.sharing.requests(username=user.username, open_only=False),
        "broken": {k: v for k, v in state.quills.broken.items() if k.startswith(f"~{user.username}.")},
    }


def _offers(state: AppState, username: str) -> list[dict]:
    rows = []
    for share in state.sharing.of_person(username):
        manifest = state.quills.personal.get(share["owner"], {}).get(share["quill"])
        if manifest is None:
            continue
        rows.append(
            share
            | {
                "name": manifest.name,
                "summary": manifest.summary,
                "version": manifest.version,
                "key": manifest.key,
            }
        )
    return rows


def _require_install(state: AppState, user: User) -> None:
    if not state.policy.may_install(user.username):
        if state.policy.may_have(user.username):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "on this server a Quill of your own comes through a request: ask with POST /api/quills/requests",
            )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Quills of your own are switched off on this server")


@router.post("/mine/plan")
def plan_mine(
    payload: QuillSource, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    """What installing would add, as a Quill of your own, without installing."""
    _shelf(state)
    _require_install(state, user)
    if payload.source:
        _require_create(state, user)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        try:
            # A Quill of one's own runs no services, so it has no runtimes: the catalog is not needed.
            folder, models, _origin, _catalog = _resolve(state, payload, Path(tmp))
            plan = state.quills.plan(folder, models, owner=user.username)
        except QuillError as exc:
            raise _bad(exc) from exc
    _check_personal_plan(state, plan, user)
    return plan


@router.post("/mine", status_code=status.HTTP_201_CREATED)
def install_mine(
    payload: QuillSource, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    """Install a Quill from the catalog or a source, as your own: on your shelf and nobody else's —
    or again, which is how it is updated, for everybody it stands with."""
    _shelf(state)
    _require_install(state, user)
    if payload.source:
        _require_create(state, user)
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        try:
            folder, models, origin, _catalog = _resolve(state, payload, Path(tmp))
            _check_personal_plan(state, state.quills.plan(folder, models, owner=user.username), user)
            return state.quills.install(
                folder, models, origin=origin | {"installed_by": user.username}, owner=user.username
            )
        except QuillError as exc:
            raise _bad(exc) from exc


@router.post("/mine/upload", status_code=status.HTTP_201_CREATED)
async def upload_mine(
    request: Request,
    plan_only: bool = False,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """A folder you are working on, as a .tar.gz, installed as your own: `cm quill dev` for anybody."""
    _shelf(state)
    _require_install(state, user)
    _require_create(state, user)
    data = await request.body()
    if len(data) > MAX_DOWNLOAD:
        raise HTTPException(413, "bigger than a Quill should be")
    with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
        root = Path(tmp) / "q"
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                archive.extractall(root, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"not a .tar.gz of a Quill: {exc}") from exc
        manifests = sorted(root.rglob(MANIFEST), key=lambda p: len(p.parts))
        if not manifests:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"there is no {MANIFEST} in what was sent")
        folder = manifests[0].parent
        try:
            models = state.quills.datamodels_source(load_catalog(state.config.quill_catalog), Path(tmp) / "m")
        except QuillError:
            models = None
        try:
            plan = state.quills.plan(folder, models, owner=user.username)
            _check_personal_plan(state, plan, user)
            if plan_only:
                return plan
            return state.quills.install(
                folder,
                models,
                origin={"catalog": False, "dev": True, "installed_by": user.username},
                owner=user.username,
            )
        except QuillError as exc:
            raise _bad(exc) from exc


def _own(state: AppState, user: User, quill_id: str) -> Manifest:
    manifest = state.quills.personal.get(user.username, {}).get(quill_id)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"you have no Quill of your own called {quill_id}")
    return manifest


@router.get("/mine/{quill_id}")
def get_mine(
    quill_id: str, request: Request, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    _shelf(state)
    return _describe_mine(state, _own(state, user, quill_id), request)


@router.get("/mine/{quill_id}/brought")
def brought_mine(
    quill_id: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """What your Quill brought — the datamodels it introduced — and how many records hold each:
    the Quill's, from everybody it stands with. The choice of what goes with it is the last
    holder's; until then the Quill, and all of it, stays."""
    _shelf(state)
    _own(state, user, quill_id)
    try:
        return removal.brought(state.quills, state.records, quill_id, user.username)
    except QuillError as exc:
        raise _bad(exc) from exc


@router.get("/offers/{owner}/{quill_id}/brought")
def brought_shared(
    owner: str, quill_id: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """The same, for a Quill shared with you: what it brought, for the day you are the last
    to have it and choose what goes."""
    _shelf(state)
    _holder(state, user, owner, quill_id)
    try:
        return removal.brought(state.quills, state.records, quill_id, owner)
    except QuillError as exc:
        raise _bad(exc) from exc


def _take_off_shelf(state: AppState, user: User, manifest: Manifest, drop: str) -> dict:
    """Take a personal Quill off *user*'s shelf. The last to have it takes it off the server,
    dropping what *drop* names of what it brought; anybody before that leaves it standing,
    the Quill's data and all, for the others (docs/SHARING.md, rule 8)."""
    others = [p for p in state.shelf.holders(manifest) if p != user.username]
    if others:
        if user.username == manifest.owner:
            state.sharing.leave_owner(manifest.owner, manifest.id)
        else:
            state.sharing.revoke(manifest.owner, manifest.id, user.username)
        return {"left": manifest.key, "stays_with": others}
    try:
        done = removal.remove(
            state.quills, state.records, manifest.id, [d for d in drop.split(",") if d], owner=manifest.owner
        )
    except QuillError as exc:
        raise _bad(exc) from exc
    state.sharing.forget(manifest.owner, manifest.id)
    return {**done, "removed": manifest.key}


@router.delete("/mine/{quill_id}")
def remove_mine(
    quill_id: str, drop: str = "", state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    """Take your Quill off your shelf. While others still have it, it stays for them — the
    Quill's data and all — and comes off the server when the last of them takes it off
    theirs; then `?drop=` names a datamodel of its own to go with it, records and all."""
    _shelf(state)
    manifest = _own(state, user, quill_id)
    if state.sharing.owner_left(user.username, quill_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{quill_id} is off your shelf already; others still have it")
    return _take_off_shelf(state, user, manifest, drop)


# -- sharing -----------------------------------------------------------------------------------
def _people_of(state: AppState, payload: ShareIn) -> list[str]:
    people = list(payload.people)
    if payload.circles and state.circles is not None:
        for key in payload.circles:
            try:
                people += state.circles.get(key).members
            except Exception as exc:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no circle {key}") from exc
    known = {u.username for u in state.users.list() if u.is_active}
    unknown = sorted(set(people) - known)
    if unknown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such account: {', '.join(unknown)}")
    return list(dict.fromkeys(people))


@router.put("/mine/{quill_id}/share")
def share_mine(
    quill_id: str, payload: ShareIn, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Offer your Quill to people, or to everybody in a circle, with what each may do with its
    own datamodels (`rules`: write, or read; nothing named is write). Each says yes before it
    is theirs. Offered again to somebody who has it, only their rules change."""
    _shelf(state)
    manifest = _own(state, user, quill_id)
    if not state.policy.may_share(user.username):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "sharing Quills of your own is switched off for you")
    if state.sharing.owner_left(user.username, quill_id):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{quill_id} is off your shelf; it is not yours to offer")
    rules = {}
    for model, access in payload.rules.items():
        prefixed = manifest.resolve(model) if not model.startswith("~") else model
        if prefixed not in manifest.renamed.values():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{model} is not a datamodel {quill_id} introduces")
        rules[prefixed] = access
    for who in _people_of(state, payload):
        if who == user.username:
            continue
        try:
            share = state.sharing.offer(user.username, quill_id, who, by=user.username, rules=rules)
        except SharingError as exc:
            raise _bad(exc) from exc
        if share["state"] == OFFERED:
            state.notifications.add(
                who,
                kind="quill.offered",
                title=f"{user.display_name or user.username} shared {manifest.name} with you",
                body="Say yes under Me, Your Quills, and it is on your shelf: its data, shared, as they set it.",
            )
    return state.sharing.shared_with(user.username, quill_id)


@router.delete("/mine/{quill_id}/share/{username}")
def unshare_mine(
    quill_id: str, username: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Take your Quill back from somebody. What they wrote in it stays the Quill's."""
    _shelf(state)
    _own(state, user, quill_id)
    if username == user.username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to take it off your own shelf, remove it")
    state.sharing.revoke(user.username, quill_id, username)
    return state.sharing.shared_with(user.username, quill_id)


@router.get("/mine/{quill_id}/export")
def export_mine(
    quill_id: str, datasets: str = "", state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> Response:
    """Your Quill as a repository would hold it, as a .tar.gz: the folder in the template's
    shape, and — with `?datasets=` naming datamodels of its own — your records of each as
    a dataset it comes with. Nothing else of yours, or of the server's, goes with it."""
    _shelf(state)
    manifest = _own(state, user, quill_id)
    chosen: dict[str, list[dict]] = {}
    for plain in (d for d in datasets.split(",") if d):
        prefixed = manifest.resolve(plain)
        if prefixed not in manifest.renamed.values():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{plain} is not a datamodel {quill_id} introduces")
        chosen[plain] = [r.fields for r in state.records.list(Principal.person(user.username), prefixed, {})]
    with tempfile.TemporaryDirectory(prefix="quill-export-") as tmp:
        into = Path(tmp) / f"quill-{quill_id}"
        try:
            exporting.export(
                manifest.folder or state.quills.folder_of(quill_id, user.username), manifest, into, datasets=chosen
            )
        except QuillError as exc:
            raise _bad(exc) from exc
        data = exporting.tarball(into, f"quill-{quill_id}")
    return Response(
        data,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="quill-{quill_id}.tar.gz"'},
    )


@router.post("/mine/fork", status_code=status.HTTP_201_CREATED)
def fork_mine(payload: ForkIn, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """A Quill on your shelf — the server's, shared with you, or your own — copied into one of
    your own under a new id, to change. Its records are not copied: a fork over foundational
    datamodels works on the same records; one over the original's own datamodels starts empty."""
    shelf = _shelf(state)
    _require_install(state, user)
    _require_create(state, user)
    original = shelf.find(user.username, payload.id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{payload.id} is not on your shelf")
    with tempfile.TemporaryDirectory(prefix="quill-fork-") as tmp:
        try:
            folder = exporting.fork(
                original.folder or state.quills.folder_of(original.id, original.owner),
                original,
                payload.new_id,
                Path(tmp) / payload.new_id,
                name=payload.name,
            )
            try:
                models = state.quills.datamodels_source(load_catalog(state.config.quill_catalog), Path(tmp) / "m")
            except QuillError:
                models = None
            _check_personal_plan(state, state.quills.plan(folder, models, owner=user.username), user)
            return state.quills.install(
                folder,
                models,
                origin={"catalog": False, "forked_from": original.key, "installed_by": user.username},
                owner=user.username,
            )
        except QuillError as exc:
            raise _bad(exc) from exc


# -- offers --------------------------------------------------------------------------------------
@router.post("/offers/{owner}/{quill_id}/accept")
def accept_offer(
    owner: str, quill_id: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    """Yes: the Quill is on your shelf — its data shared, as its owner set it — run as you."""
    _shelf(state)
    if not state.policy.may_have(user.username):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Quills of people's own are switched off on this server")
    if quill_id in state.quills.quills or quill_id in state.quills.personal.get(user.username, {}):
        raise HTTPException(status.HTTP_409_CONFLICT, f"you have a Quill called {quill_id} already")
    try:
        return state.sharing.answer(owner, quill_id, user.username, True)
    except SharingError as exc:
        raise _bad(exc) from exc


@router.post("/offers/{owner}/{quill_id}/decline")
def decline_offer(
    owner: str, quill_id: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> dict:
    _shelf(state)
    try:
        return state.sharing.answer(owner, quill_id, user.username, False)
    except SharingError as exc:
        raise _bad(exc) from exc


@router.delete("/offers/{owner}/{quill_id}")
def leave_offer(
    owner: str,
    quill_id: str,
    drop: str = "",
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> dict:
    """Leave a Quill somebody shared with you, or decline what was offered. What you wrote in
    it stays the Quill's. The last to have it takes it off the server, and `?drop=` names a
    datamodel of its own to go with it, records and all."""
    _shelf(state)
    manifest = state.quills.personal.get(owner, {}).get(quill_id)
    if manifest is not None and user.username in state.shelf.holders(manifest):
        return _take_off_shelf(state, user, manifest, drop)
    state.sharing.revoke(owner, quill_id, user.username)
    return {"left": f"~{owner}.{quill_id}"}


# -- requests --------------------------------------------------------------------------------------
@router.get("/requests")
def requests(
    all: bool = False, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """Open requests: everybody's for an administrator, your own for anybody else. `?all=true`
    includes the answered ones."""
    _shelf(state)
    if user.is_admin:
        return state.sharing.requests(open_only=not all)
    return state.sharing.requests(username=user.username, open_only=not all)


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def ask(payload: RequestIn, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    """Ask an administrator for a Quill: one from the catalog or a source to be installed, or
    one of your own to be promoted for everyone."""
    _shelf(state)
    if payload.kind == "promote":
        _own(state, user, payload.id)
    try:
        made = state.sharing.ask(
            user.username, payload.kind, quill=payload.id, source=payload.source, ref=payload.ref, note=payload.note
        )
    except SharingError as exc:
        raise _bad(exc) from exc
    what = payload.id or payload.source
    for admin in (u for u in state.users.list() if u.is_admin and u.is_active and u.username != user.username):
        state.notifications.add(
            admin.username,
            kind="quill.requested",
            title=f"{user.display_name or user.username} asks for {what}"
            + (" to be promoted" if payload.kind == "promote" else ""),
            body=payload.note or "Under Administration, Quills.",
        )
    return made


@router.post("/requests/{request_id}/approve")
def approve(
    request_id: int, payload: Approval, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)
) -> dict:
    """Yes, as an administrator: the Quill is installed for the audience given — everyone, circles,
    people, or only the one who asked — or, for a promotion, made the server's."""
    _shelf(state)
    try:
        found = state.sharing.request(request_id)
    except SharingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    audience = payload.audience.model_dump()
    try:
        if found["kind"] == "promote":
            plan = promotion.promote(
                state.quills,
                state.records,
                state.sharing,
                found["username"],
                found["quill"],
                by=admin.username,
                audience=audience,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="quill-") as tmp:
                source = QuillSource(id=found["quill"], source=found["source"], ref=found["ref"])
                folder, models, origin, catalog = _resolve(state, source, Path(tmp))
                plan = state.quills.install(
                    folder,
                    models,
                    origin=origin | {"installed_by": admin.username, "audience": audience},
                    catalog=catalog,
                )
        _give(state, plan, payload.give_to)
        done = state.sharing.settle(
            request_id, APPROVED, by=admin.username, answer={"audience": audience, "note": payload.note}
        )
    except (QuillError, SharingError) as exc:
        raise _bad(exc) from exc
    state.notifications.add(
        found["username"],
        kind="quill.approved",
        title=f"{plan['name']} is installed" + (" for everyone" if not any(audience.values()) else ""),
        body=payload.note,
    )
    return done | {"installed": plan["id"], "version": plan["version"]}


def _give(state: AppState, plan: dict, circles: list[str]) -> None:
    """Write on what the Quill introduced, for the circles the administrator ticked."""
    if state.circles is None:
        return
    for key in circles:
        for model_id in plan.get("introduces", []):
            state.circles.set_rule(key, model_id, "write")


@router.post("/requests/{request_id}/decline")
def decline(
    request_id: int, payload: Decline, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)
) -> dict:
    _shelf(state)
    try:
        found = state.sharing.request(request_id)
        done = state.sharing.settle(request_id, DECLINED, by=admin.username, answer={"note": payload.note})
    except SharingError as exc:
        raise _bad(exc) from exc
    state.notifications.add(
        found["username"],
        kind="quill.declined",
        title=f"{found['quill'] or found['source']}: not this time",
        body=payload.note,
    )
    return done


@router.delete("/requests/{request_id}")
def withdraw(request_id: int, state: AppState = Depends(get_state), user: User = Depends(get_current_user)) -> dict:
    _shelf(state)
    try:
        found = state.sharing.request(request_id)
        if found["username"] != user.username and not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your request")
        return state.sharing.settle(request_id, WITHDRAWN, by=user.username)
    except SharingError as exc:
        raise _bad(exc) from exc


# -- an administrator's view ----------------------------------------------------------------------
@router.get("/all")
def everything(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> dict:
    """Every Quill on the server, whose it is, and who has it: the server's with their audience,
    and everybody's own with who they are shared with."""
    _shelf(state)
    server = []
    for manifest in state.quills.ordered(state.quills.quills.values()):
        row = state.quills.describe(manifest)
        row["audience"] = audience_of(manifest)
        row["enabled"] = state.features.enabled(manifest.key)
        server.append(row)
    personal = []
    for owner in state.shelf.owners():
        for manifest in state.quills.ordered(state.quills.personal[owner].values()):
            row = _describe_mine(state, manifest)
            row["owner_active"] = any(u.username == owner and u.is_active for u in state.users.list())
            personal.append(row)
    return {
        "policy": state.policy.get(),
        "server": server,
        "personal": personal,
        "requests": state.sharing.requests(),
        "broken": state.quills.broken,
    }


@router.post("/promote", status_code=status.HTTP_201_CREATED)
def promote(payload: PromoteIn, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)) -> dict:
    """Somebody's own Quill, made the server's: installed for the audience given, with every
    record of its datamodels — theirs and those of the people they shared it with — moved
    under the server's name for it."""
    _shelf(state)
    try:
        plan = promotion.promote(
            state.quills,
            state.records,
            state.sharing,
            payload.owner,
            payload.id,
            by=admin.username,
            audience=payload.audience.model_dump(),
        )
        _give(state, plan, payload.give_to)
    except QuillError as exc:
        raise _bad(exc) from exc
    state.notifications.add(
        payload.owner,
        kind="quill.promoted",
        title=f"{plan['name']} is the server's now",
        body="Everybody it is for has it; your records went with it.",
    )
    return plan


def _theirs(state: AppState, owner: str, quill_id: str) -> Manifest:
    manifest = state.quills.personal.get(owner, {}).get(quill_id)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{owner} has no Quill of their own called {quill_id}")
    return manifest


@router.get("/personal/{owner}/{quill_id}/brought")
def brought_theirs(
    owner: str, quill_id: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> list[dict]:
    """What somebody's own Quill brought, and how many records hold each: for an administrator
    choosing what goes with it."""
    _shelf(state)
    _theirs(state, owner, quill_id)
    try:
        return removal.brought(state.quills, state.records, quill_id, owner)
    except QuillError as exc:
        raise _bad(exc) from exc


@router.delete("/personal/{owner}/{quill_id}")
def remove_theirs(
    owner: str,
    quill_id: str,
    drop: str = "",
    state: AppState = Depends(get_state),
    admin: User = Depends(get_admin_user),
) -> dict:
    """Somebody's own Quill, taken off the server by an administrator: off every shelf it is on
    at once, as when its last holder removes it — its records kept unless `?drop=` names what
    it brought to go with it. Everybody who had it is told."""
    _shelf(state)
    manifest = _theirs(state, owner, quill_id)
    holders = state.shelf.holders(manifest)
    try:
        done = removal.remove(
            state.quills, state.records, manifest.id, [d for d in drop.split(",") if d], owner=manifest.owner
        )
    except QuillError as exc:
        raise _bad(exc) from exc
    state.sharing.forget(manifest.owner, manifest.id)
    for person in {owner, *holders} - {admin.username}:
        state.notifications.add(
            person,
            kind="quill.removed",
            title=f"{manifest.name} is gone",
            body=f"{admin.username} took {owner}'s {manifest.name} off this server.",
        )
    return {**done, "removed": manifest.key}


@router.post("/adopt/{owner}/{quill_id}")
def adopt(
    owner: str, quill_id: str, state: AppState = Depends(get_state), admin: User = Depends(get_admin_user)
) -> dict:
    """Somebody's own Quill folded into the server Quill of the same id, records and all."""
    _shelf(state)
    try:
        return {"moved": promotion.adopt(state.quills, state.records, state.sharing, owner, quill_id)}
    except QuillError as exc:
        raise _bad(exc) from exc


# What a share's states are called, for a client. ACCEPTED is what puts a Quill on a shelf.
STATES = (OFFERED, ACCEPTED, DECLINED)
