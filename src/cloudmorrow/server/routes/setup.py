"""First boot, from the browser.

A server with nobody on it has nothing to sign in to. On a box installed by
hand the installer asks its questions on the terminal; on a Pi image
plugged into a router, or a tenant somebody has just bought, there is no
terminal, and the first visit is the setup. So while the server has no
accounts, `/`, `/install` and `/app` all land here, and one form makes the
cloud's name, its first account, which is the administrator, and chooses
the standard quills it starts with.

The moment an account exists the page is gone: `/setup` answers with a
redirect to the app, and `/api/setup` answers 409. There is nothing to
guess and nothing to race for after that.
"""

from __future__ import annotations

import html
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.logo import LOGO_LARGE
from cloudmorrow.server.access_control import suggest_name
from cloudmorrow.server.access_ways import AccessError
from cloudmorrow.server.db import InvalidUsernameError, UserExistsError
from cloudmorrow.server.deps import AppState, get_state
from cloudmorrow.server.quills import QuillError
from cloudmorrow.server.routes.install import TEMPLATES, page_css
from cloudmorrow.server.schemas import SetupOut, SetupRequest
from cloudmorrow.server.security import hash_password
from cloudmorrow.server.settings import InvalidNameError, validate_name
from cloudmorrow.server.standard import choices, choose

router = APIRouter(tags=["setup"])

# Two first visits at the same moment must not both make an administrator.
_first_account = threading.Lock()


def needs_setup(state: AppState) -> bool:
    return state.users.count() == 0


@router.get("/setup", response_class=HTMLResponse, include_in_schema=False)
def setup_page(request: Request, state: AppState = Depends(get_state)) -> Response:
    if not needs_setup(state):
        return RedirectResponse("/app", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    page = (TEMPLATES / "setup.html").read_text(encoding="utf-8")
    page = (
        page.replace("__PAGE_CSS__", page_css())
        .replace("__LOGO__", html.escape(LOGO_LARGE.strip("\n")))
        .replace("__NAME__", html.escape(state.cloud_name()))
        .replace("__VERSION__", __version__)
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/api/setup/quills", include_in_schema=False)
def standard_quills(state: AppState = Depends(get_state)) -> dict:
    """The standard quills to offer on the page, while there is a page."""
    if not needs_setup(state):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already set up")
    options, _, problem = choices(state.config)
    return {
        "quills": [{"id": o.id, "name": o.name, "summary": o.summary} for o in options],
        "problem": problem,
    }


@router.get("/api/setup/access", include_in_schema=False)
def access_choice(state: AppState = Depends(get_state)) -> dict:
    """What the page needs to ask how the cloud is reached, while there is a page.

    The zone is not known until a name is claimed; the control server's own
    host without its first label (relay.cloudmorrow.com → cloudmorrow.com)
    is what it will be for the control server everyone uses, and is only
    shown as a hint.
    """
    if not needs_setup(state):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already set up")
    host = urlsplit(state.config.access_control).hostname or ""
    return {
        "suggested_name": suggest_name(state.cloud_name()),
        "zone": host.split(".", 1)[1] if host.count(".") >= 2 else host,
        "control": state.config.access_control,
    }


@router.post("/api/setup", response_model=SetupOut, status_code=status.HTTP_201_CREATED)
def first_account(payload: SetupRequest, state: AppState = Depends(get_state)) -> SetupOut:
    """Name the cloud and make its administrator. Once, ever."""
    with _first_account:
        if not needs_setup(state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this server is already set up; sign in at /app",
            )
        try:
            # Checked first, so a bad name makes no account; saved last, so a
            # bad account leaves no name behind.
            name = validate_name(payload.name)
            user = state.users.create(
                payload.username, hash_password(payload.password), is_admin=True
            )
        except (InvalidNameError, InvalidUsernameError, UserExistsError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        state.settings.set_name(name, changed_by=user.username)
        state.config.notes_root(user.username).mkdir(parents=True, exist_ok=True)
    # The standard quills, after the account: a download that fails leaves a
    # cloud that is set up, with a line saying what to add later.
    note = ""
    if payload.quills is not None:
        try:
            choose(
                state.config, set(payload.quills), by=user.username,
                registry=state.quills, features=state.features, remove_unwanted=True,
            )
        except QuillError as exc:
            note = f"{exc}. Add it later from Administration, Quills."
    # How it is reached, last: a name that is taken or a control server that
    # cannot be reached leaves a cloud that is set up and reached at home,
    # with a line saying where to try again.
    address = ""
    choice = payload.access
    if choice is not None and choice.way != "home" and state.access is not None:
        wanted = choice.name or suggest_name(name)
        try:
            cloud = state.access.claim(
                wanted,
                public=choice.way in ("public", "both"),
                private=choice.way in ("private", "both"),
            )
            address = f"https://{cloud.host}"
        except AccessError as exc:
            said = f"The name could not be set up: {exc}. Try again from Administration, Access."
            note = f"{note} {said}".strip()
    return SetupOut(name=name, username=user.username, note=note, address=address)
