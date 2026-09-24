"""The web app: notes and tasks on a phone, or in any browser, at `/app`.

The API already speaks bearer tokens, so the browser needs nothing the TUI
does not have — it signs in at `/api/auth/login`, keeps the token in local
storage, and reads and writes with it. This module only hands out the page
and the files beside it.

The script and the stylesheet are lists of imports, one file per feature,
so a feature can be worked on without touching the others. The page names
them under `/app/<deploy>/`, and each import is relative, so every file
resolves under the same deploy and may be cached for as long as the
browser likes.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.server.deps import AppState, get_state
from cloudmorrow.server.update import deployed_commit

WEB = Path(__file__).resolve().parent.parent / "web"

# What may be served from `web/`, by extension. The page itself is rendered,
# not served, so `.html` is not here.
MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
}

router = APIRouter(tags=["web"])


def asset_version() -> str:
    """What the page puts in its asset URLs, so a deploy is not cached over.

    The version only moves on a tag, and a `.dev` build keeps it between
    commits, so the commit is what tells two deploys apart.
    """
    commit = deployed_commit()
    return f"{__version__}-{commit[:12]}" if commit else __version__


@router.get("/app", response_class=HTMLResponse, include_in_schema=False)
def app_page(state: AppState = Depends(get_state)) -> Response:
    if state.users.count() == 0:
        # There is nothing to sign in to yet; the first visit sets it up.
        return RedirectResponse("/setup", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    page = (WEB / "app.html").read_text(encoding="utf-8")
    page = (
        page.replace("__NAME__", html.escape(state.cloud_name()))
        .replace("__VERSION__", __version__)
        .replace("__ASSET_VERSION__", asset_version())
    )
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@router.get("/app/manifest.webmanifest", include_in_schema=False)
def app_manifest(state: AppState = Depends(get_state)) -> JSONResponse:
    """The manifest, with the cloud's own name on it.

    What the phone writes under the icon comes from here, so a cloud
    called "The Larsens" is that on the home screen, not a second
    Cloudmorrow beside the first.
    """
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    manifest["name"] = state.cloud_name()
    manifest["short_name"] = state.cloud_name()
    return JSONResponse(
        manifest,
        media_type=MEDIA_TYPES[".webmanifest"],
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/app/version", include_in_schema=False)
def app_deployed_version() -> JSONResponse:
    """Which deploy is being served, for a page to compare itself against.

    An app on a phone's home screen is opened and hidden for weeks without
    ever being loaded again, so a deploy does not reach it until it is force
    closed. This is what it asks, and a different answer than it was built
    from is its cue to reload.
    """
    return JSONResponse(
        {"version": __version__, "deploy": asset_version()},
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/brand", response_class=HTMLResponse, include_in_schema=False)
def brand_page() -> HTMLResponse:
    """The look, proposed: colour themes for the app, the CLI and the TUI.

    Its own page and its own two files, with no sign-in and nothing from the
    app's stylesheet, because it argues for a look the app does not have yet.
    It borrows `/app/<deploy>/` for its script and stylesheet, so they are
    named and cached like every other asset.
    """
    page = (WEB / "brand.html").read_text(encoding="utf-8")
    return HTMLResponse(
        page.replace("__ASSET_VERSION__", asset_version()),
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/login", include_in_schema=False)
@router.get("/notes", include_in_schema=False)
def app_alias() -> RedirectResponse:
    """The addresses someone types by hand, sent where the app lives."""
    return RedirectResponse("/app", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


def _asset(filename: str) -> FileResponse:
    path = WEB / filename
    media_type = MEDIA_TYPES.get(path.suffix)
    if (
        media_type is None
        or "/" in filename
        or filename.startswith(".")
        or path.parent != WEB
        or not path.is_file()
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such file")
    return FileResponse(
        path,
        media_type=media_type,
        # Named with the deploy in the URL, so it may be kept for as long
        # as the browser likes; a deploy names them anew.
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/app/{version}/{filename}", include_in_schema=False)
def app_versioned_asset(version: str, filename: str) -> FileResponse:
    """The script and stylesheet, and everything they import."""
    return _asset(filename)


@router.get("/app/{filename}", include_in_schema=False)
def app_asset(filename: str) -> FileResponse:
    """The manifest and the icons: named without a deploy, since they rarely change."""
    return _asset(filename)
