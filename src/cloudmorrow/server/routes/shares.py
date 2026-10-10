"""Fileshares: make one, share it, list them, forget one. The files themselves
are at `/dav` on the server, and through the file routes beside these.

Anybody makes a share; it is the folder of its name in the Shares folder,
and theirs to share with people and circles. An administrator may also put
a share on another directory on the server, and share with everybody.

The list opens with the caller's own drive, `my-files`: a share in every
way that matters to a client, and not one to this module — it is neither
made nor removed here (`cloudmorrow.server.drive`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from cloudmorrow.server.dav import MOUNT_PATH
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_current_user, get_state
from cloudmorrow.server.drive import is_drive, user_drive
from cloudmorrow.server.routes.install import base_url
from cloudmorrow.server.schemas import (
    ShareCandidatesOut,
    ShareChange,
    ShareCreate,
    ShareFoldersOut,
    ShareMemberIn,
    ShareOut,
    SharePathCheck,
)
from cloudmorrow.server.shares import (
    DRIVE,
    PERSON,
    WRITE,
    InvalidSlugError,
    Share,
    ShareError,
    ShareExistsError,
    ShareRefused,
    UnknownShareError,
)

router = APIRouter(prefix="/api/shares", tags=["shares"])


def share_url(base: str, name: str) -> str:
    """Where a WebDAV client points: the share's own folder, trailing slash and all."""
    return f"{base.rstrip('/')}{MOUNT_PATH}/{name}/"


def share_out(state: AppState, share: Share, user: User, base: str, *, warnings: list[str] | None = None) -> ShareOut:
    """A share as *user* sees it: the path and what is wrong with it only
    for whoever manages it."""
    if share.kind == DRIVE:
        return ShareOut(
            url=share_url(base, share.name),
            owner=user.username,
            access=WRITE,
            can_manage=False,
            **{k: v for k, v in share.to_dict().items() if k not in ("owner", "members")},
        )
    manages = state.shares.may_manage(share, user.username)
    found = list(warnings or [])
    if manages:
        found += [w for w in state.shares.problems(share) if w not in found]
    fields = share.to_dict()
    if not manages:
        fields["path"] = ""
    return ShareOut(
        url=share_url(base, share.name),
        access=state.shares.access_of(share, user.username) or "read",
        can_manage=manages,
        warnings=found if manages else [],
        **fields,
    )


def _failed(exc: Exception) -> HTTPException:
    if isinstance(exc, ShareRefused):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ShareExistsError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="a share with that name exists")
    if isinstance(exc, UnknownShareError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc.args[0]) if exc.args else "")
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


ERRORS = (ShareError, ShareRefused, InvalidSlugError, UnknownShareError)


def _visible(state: AppState, user: User, name: str) -> Share:
    """The share *name*, if the caller has it — the drive included. 404
    otherwise, whether or not somebody else has one of that name."""
    if is_drive(name):
        return user_drive(state.config, user.username)
    share = state.shares.for_user(user.username, name)
    if share is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no such share: {name}")
    return share


def _managed(state: AppState, user: User, name: str) -> Share:
    """The share *name*, for its owner to change."""
    if is_drive(name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{name} is your own drive on the server — it is not shared or removed",
        )
    share = _visible(state, user, name)
    if not state.shares.may_manage(share, user.username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{share.name} is {share.owner}'s; only they decide who has it",
        )
    return share


@router.get("", response_model=list[ShareOut])
def list_shares(
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[ShareOut]:
    """Your drive, then every share you have: yours and the ones shared with you."""
    base = base_url(request, state)
    drive = user_drive(state.config, user.username)
    return [share_out(state, share, user, base) for share in (drive, *state.shares.visible(user.username))]


@router.post("", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def create_share(
    payload: ShareCreate,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareOut:
    """A new share, yours.

    It is the folder of that name in the Shares folder on the server — made
    if it is not there, used as it is if it is. An administrator may give a
    `path` instead: a directory elsewhere on the server, checked as it is
    given, with what is wrong with its permissions in `warnings`. `members`
    shares it with people and circles from the start; with everybody, for
    an administrator.
    """
    try:
        share, warnings = state.shares.create(
            user.username,
            payload.name,
            admin=user.is_admin,
            path=(payload.path or "").strip() or None,
            description=payload.description,
            members=[(m.kind, m.who, m.access) for m in payload.members],
        )
    except ERRORS as exc:
        raise _failed(exc) from exc
    return share_out(state, share, user, base_url(request, state), warnings=warnings)


@router.get("/folders", response_model=ShareFoldersOut)
def share_folders(state: AppState = Depends(get_state), _: User = Depends(get_admin_user)) -> ShareFoldersOut:
    """The Shares folder on the server, and the folders in it that are not
    shares yet — what an administrator copied in, for the new-share dialog
    to offer. Administrators only: they are the ones who put folders there."""
    directory, folders = state.shares.folders()
    return ShareFoldersOut(directory=str(directory), folders=folders)


@router.get("/candidates", response_model=ShareCandidatesOut)
def share_candidates(
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareCandidatesOut:
    """Who a share could be shared with: the people on this server but you,
    the circles, and — for an administrator — everybody."""
    people = [
        {"username": u.username, "display_name": u.display_name or u.username}
        for u in state.users.list()
        if u.is_active and u.user_type == "human" and u.username != user.username
    ]
    circles = [{"id": c.id, "name": c.name} for c in state.circles.list()] if state.circles is not None else []
    return ShareCandidatesOut(
        people=people,
        circles=circles,
        everyone=user.is_admin,
        directory=str(state.shares.shares_dir()),
    )


@router.get("/check", response_model=SharePathCheck)
def check_share_path(
    path: str = Query(description="A directory on the server"),
    share: str = Query(default="", description="The share it would be, when changing one"),
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> SharePathCheck:
    """Could this directory be a share, and what is wrong with it? Asked by a
    dialog as an administrator types, before anything is made."""
    check = state.shares.check_path(path, exclude=share)
    return SharePathCheck(path=str(check.path), ok=check.ok, errors=check.errors, warnings=check.warnings)


@router.get("/{name}", response_model=ShareOut)
def get_share(
    name: str,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareOut:
    return share_out(state, _visible(state, user, name), user, base_url(request, state))


@router.patch("/{name}", response_model=ShareOut)
def change_share(
    name: str,
    payload: ShareChange,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareOut:
    """Change what a share says about itself, or — an administrator's — where it is.

    A `path` moves the share onto that directory, checked as at creation;
    `""` puts it back in its own folder in Shares. Files are not moved:
    the directory it was on is left as it is."""
    share = _managed(state, user, name)
    try:
        share, warnings = state.shares.update(
            share, admin=user.is_admin, path=payload.path, description=payload.description
        )
    except ERRORS as exc:
        raise _failed(exc) from exc
    return share_out(state, share, user, base_url(request, state), warnings=warnings)


@router.put("/{name}/members", response_model=ShareOut)
def add_member(
    name: str,
    payload: ShareMemberIn,
    request: Request,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ShareOut:
    """Share it with a person, a circle, or everybody — or change what they
    may do in it. Its owner's to do; nobody is asked to accept."""
    share = _managed(state, user, name)
    try:
        share = state.shares.add_member(
            share, payload.kind, payload.who, payload.access, by=user.username, admin=user.is_admin
        )
    except ERRORS as exc:
        raise _failed(exc) from exc
    return share_out(state, share, user, base_url(request, state))


@router.delete("/{name}/members/{kind}/{who}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    name: str,
    kind: str,
    who: str,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """Stop sharing it with somebody. Its owner may take anybody off; a
    person shared with by name may take themselves off — leave it."""
    share = _visible(state, user, name)
    leaving = kind == PERSON and who.lower() == user.username.lower()
    if not leaving and not state.shares.may_manage(share, user.username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{share.name} is {share.owner}'s; only they decide who has it",
        )
    try:
        state.shares.remove_member(share, kind, who)
    except ERRORS as exc:
        raise _failed(exc) from exc


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_share(
    name: str,
    remove_files: bool = Query(
        default=False,
        description="also delete its folder in the Shares folder",
    ),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """Forget the share, for everybody it was shared with. Its folder in
    Shares goes only if asked; a directory elsewhere on the server is never
    deleted from here. The drive is nobody's to remove: it is there because
    the account is."""
    share = _managed(state, user, name)
    state.shares.delete(share.name, remove_files=remove_files)
