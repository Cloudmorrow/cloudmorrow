"""First boot, from the browser.

A server with nobody on it has nothing to sign in to. On a box installed by
hand the installer asks its questions on the terminal; on a tenant
somebody has just bought there is no terminal, and the first visit is the
setup. So while the server has no accounts, `/`, `/install` and `/app` all
land here, and one form makes the cloud's name, its first account, which
is the administrator, and chooses the standard quills it starts with.

The moment an account exists the page is gone: `/setup` answers with a
redirect to the app, and `/api/setup` answers 409. There is nothing to
guess and nothing to race for after that.

Before then, nobody on the internet gets it. A box linked at install,
before it had an account, is reached at its name from anywhere through
the relay; a visit that came that way (public_way) is told to set the
cloud up from the home network instead, so a stranger cannot claim it.
"""

from __future__ import annotations

import html
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.logo import LOGO_LARGE
from cloudmorrow.server.access_ways import AccessError
from cloudmorrow.server.db import InvalidUsernameError, UserExistsError
from cloudmorrow.server.deps import AppState, get_state
from cloudmorrow.server.public_way import from_anywhere
from cloudmorrow.server.quills import QuillError
from cloudmorrow.server.quills.standard import choices, choose
from cloudmorrow.server.routes.install import TEMPLATES, page_css
from cloudmorrow.server.schemas import SetupOut, SetupRequest
from cloudmorrow.server.security import hash_password
from cloudmorrow.server.settings import InvalidNameError, validate_name

router = APIRouter(tags=["setup"])

# Two first visits at the same moment must not both make an administrator.
_first_account = threading.Lock()
# Until when the page that just set the cloud up may follow its link code.
_link_window = {"until": 0.0}
LINK_WINDOW_SECONDS = 20 * 60


def needs_setup(state: AppState) -> bool:
    return state.users.count() == 0


AT_HOME_ONLY = "this cloud is set up from its home network, not from the internet"


def _at_home_only(request: Request) -> None:
    if from_anywhere(request):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=AT_HOME_ONLY)


@router.get("/setup", response_class=HTMLResponse, include_in_schema=False)
def setup_page(request: Request, state: AppState = Depends(get_state)) -> Response:
    if not needs_setup(state):
        return RedirectResponse("/app", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    template = "setup-at-home.html" if from_anywhere(request) else "setup.html"
    page = (TEMPLATES / template).read_text(encoding="utf-8")
    page = (
        page.replace("__PAGE_CSS__", page_css())
        .replace("__LOGO__", html.escape(LOGO_LARGE.strip("\n")))
        .replace("__NAME__", html.escape(state.cloud_name()))
        .replace("__VERSION__", __version__)
    )
    code = status.HTTP_404_NOT_FOUND if from_anywhere(request) else status.HTTP_200_OK
    return HTMLResponse(page, status_code=code, headers={"Cache-Control": "no-store"})


@router.get("/api/setup/quills", include_in_schema=False)
def standard_quills(request: Request, state: AppState = Depends(get_state)) -> dict:
    """The standard quills to offer on the page, while there is a page."""
    _at_home_only(request)
    if not needs_setup(state):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already set up")
    options, _, problem = choices(state.config)
    return {
        "quills": [{"id": o.id, "name": o.name, "summary": o.summary} for o in options],
        "problem": problem,
    }


@router.get("/api/setup/link", include_in_schema=False)
def link_progress(request: Request, state: AppState = Depends(get_state)) -> dict:
    """Whether the code the page shows was entered yet: for twenty minutes after setup, no more.

    The page has no sign-in to ask with, so this says only what the page
    shows anyway: waiting, linked (and as what), or expired.
    """
    _at_home_only(request)
    access = state.access
    if access is None or time.monotonic() > _link_window["until"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="nothing to follow here")
    shown = access.status(admin=True)
    return {
        "state": shown["link_state"] or "none",
        "host": shown["host"],
        "on_mesh": shown["mesh"]["on"],
        "error": shown["setup_error"],
    }


@router.post("/api/setup", response_model=SetupOut, status_code=status.HTTP_201_CREATED)
def first_account(payload: SetupRequest, request: Request, state: AppState = Depends(get_state)) -> SetupOut:
    """Name the cloud and make its administrator. Once, ever."""
    _at_home_only(request)
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
            user = state.users.create(payload.username, hash_password(payload.password), is_admin=True)
        except (InvalidNameError, InvalidUsernameError, UserExistsError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        state.settings.set_name(name, changed_by=user.username)
        state.config.notes_root(user.username).mkdir(parents=True, exist_ok=True)
    # The standard quills, after the account: a download that fails leaves a
    # cloud that is set up, with a line saying what to add later.
    note = ""
    if payload.quills is not None:
        try:
            choose(
                state.config,
                set(payload.quills),
                by=user.username,
                registry=state.quills,
                features=state.features,
                remove_unwanted=True,
            )
        except QuillError as exc:
            note = f"{exc}. Add it later from Administration, Quills."
    # Linking, last: a relay that cannot be reached leaves a cloud that is
    # set up and reached at home, with a line saying where to try again.
    link = None
    if payload.link and state.access is not None:
        try:
            link = state.access.link()
            _link_window["until"] = time.monotonic() + LINK_WINDOW_SECONDS
        except AccessError as exc:
            said = f"It could not be linked yet: {exc}. Try again from Administration, Access."
            note = f"{note} {said}".strip()
    return SetupOut(name=name, username=user.username, note=note, link=link)
