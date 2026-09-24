"""First boot, from the browser.

A server with nobody on it has nothing to sign in to. On a box installed by
hand the installer asks the three questions on the terminal; on a Pi image
plugged into a router, or a tenant somebody has just bought, there is no
terminal, and the first visit is the setup. So while the server has no
accounts, `/`, `/install` and `/app` all land here, and one form makes the
cloud's name and its first account, which is the administrator.

The moment an account exists the page is gone: `/setup` answers with a
redirect to the app, and `/api/setup` answers 409. There is nothing to
guess and nothing to race for after that.
"""

from __future__ import annotations

import html
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.logo import LOGO_LARGE
from cloudmorrow.server.db import InvalidUsernameError, UserExistsError
from cloudmorrow.server.deps import AppState, get_state
from cloudmorrow.server.routes.install import TEMPLATES
from cloudmorrow.server.schemas import SetupOut, SetupRequest
from cloudmorrow.server.security import hash_password
from cloudmorrow.server.settings import InvalidNameError, validate_name

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
        page.replace("__LOGO__", html.escape(LOGO_LARGE.strip("\n")))
        .replace("__NAME__", html.escape(state.cloud_name()))
        .replace("__VERSION__", __version__)
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


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
    return SetupOut(name=name, username=user.username)
