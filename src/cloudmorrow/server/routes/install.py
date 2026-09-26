"""The install page: one command to copy onto a new machine."""

from __future__ import annotations

import html
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.logo import LOGO_LARGE
from cloudmorrow.server.deps import AppState, get_state

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
VENV_HINT = "~/.local/share/cloudmorrow/venv"

router = APIRouter(tags=["install"])


def base_url(request: Request, state: AppState) -> str:
    """The URL a new machine should curl.

    `public_url` in the config wins, because behind a reverse proxy the request
    the app sees is the proxy's, not the one the user typed.
    """
    if state.config.public_url:
        return state.config.public_url.rstrip("/")
    return str(request.base_url).rstrip("/")


def page_css() -> str:
    """The stylesheet the server's own pages share, inlined into each."""
    return (TEMPLATES / "page.css").read_text(encoding="utf-8")


def _render(name: str, replacements: dict[str, str]) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    text = text.replace("__PAGE_CSS__", page_css())
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/install", response_class=HTMLResponse, include_in_schema=False)
def install_page(request: Request, state: AppState = Depends(get_state)) -> Response:
    if state.users.count() == 0:
        # Nobody to install a client for yet: the first visit is the setup.
        return RedirectResponse("/setup", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return HTMLResponse(
        _render(
            "install.html",
            {
                "__LOGO__": html.escape(LOGO_LARGE.strip("\n")),
                "__NAME__": html.escape(state.cloud_name()),
                "__BASE_URL__": html.escape(base_url(request, state)),
                "__VERSION__": __version__,
                "__VENV_HINT__": VENV_HINT,
            },
        )
    )


@router.get("/install.sh", response_class=PlainTextResponse, include_in_schema=False)
def install_script(request: Request, state: AppState = Depends(get_state)) -> PlainTextResponse:
    script = _render(
        "install.sh",
        {
            "__BASE_URL__": base_url(request, state),
            "__PACKAGE_SPEC__": state.config.resolve_package_spec(
                base_url(request, state)
            ),
        },
    )
    return PlainTextResponse(script, media_type="text/x-shellscript")


@router.get("/api/client", tags=["meta"])
def client_release(request: Request, state: AppState = Depends(get_state)) -> dict:
    """What `cloudmorrow update` should install, and where from.

    The same answer /install.sh bakes into itself, in a shape a running client
    can read. No auth, for the same reason /install.sh needs none: this is how
    a machine gets Cloudmorrow in the first place.
    """
    base = base_url(request, state)
    wheel = state.config.published_wheel()
    return {
        "version": __version__,
        "package": state.config.resolve_package_spec(base),
        "wheel": wheel.name if wheel is not None else "",
        "base_url": base,
    }


@router.get("/dist/{filename}", include_in_schema=False)
def serve_wheel(filename: str, state: AppState = Depends(get_state)) -> FileResponse:
    """Serve a wheel published with `cloudmorrow-server publish`.

    This is what makes the install command work on a server with no route to
    PyPI: the server hands out the package itself.
    """
    if "/" in filename or filename.startswith("."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bad filename")
    path = state.config.dist_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such file")
    return FileResponse(path, media_type="application/octet-stream", filename=filename)
