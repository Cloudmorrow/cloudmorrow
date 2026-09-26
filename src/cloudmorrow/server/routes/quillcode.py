"""The doors to a Quill's code: its APIs, its webhooks, and their administration.

* `/api/q/<quill>/<path>` — a Quill's `[[apis]]`, proxied to the service
  that serves them. Open to anybody signed in, and to the Quill's own token;
  the service is told who is asking in `X-Cloudmorrow-User` and never sees
  the person's token (see `quillproxy`).
* `POST /hooks/<quill>/<path>` — a Quill's `[[webhooks]]`, for the outside
  world, so no account: the webhook's secret instead, as `?token=`,
  `X-Cloudmorrow-Webhook-Token`, or an HMAC of the body in the header the
  manifest names. Either a record is made from the body (`model` + `map`),
  as the Quill, or the request is forwarded to a service (`forward`).
* `/api/quillservices` — for an administrator: what runs, as whom, its
  state and log, each webhook's address and secret, and rotating either.
"""

from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_admin_user, get_principal, get_state
from cloudmorrow.server.quillhooks import MAX_BODY as HOOK_MAX_BODY
from cloudmorrow.server.quillhooks import RateLimit, apply_map, signature_ok
from cloudmorrow.server.quillproxy import MAX_BODY, forward, read_body
from cloudmorrow.server.quills import Manifest
from cloudmorrow.server.quilltokens import runs_as
from cloudmorrow.server.records import Principal
from cloudmorrow.server.routes.records import ERRORS, _refused

api_router = APIRouter(prefix="/api/q", tags=["quill code"])
hooks_router = APIRouter(prefix="/hooks", tags=["quill code"])
admin_router = APIRouter(prefix="/api/quillservices", tags=["quill code"])

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

# One sender gone wrong is slowed, not the server: per webhook, per minute.
hook_rate = RateLimit(limit=120, window=60.0)


def _quill(state: AppState, quill_id: str) -> Manifest:
    manifest = state.quills.quills.get(quill_id)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{quill_id} is not installed")
    if not state.features.enabled(quill_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"{manifest.name} is switched off on this server"
        )
    return manifest


def _port(state: AppState, manifest: Manifest, service: str) -> int:
    port = state.services.port_of(manifest.id, service) if state.services else None
    if port is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"{manifest.name}'s {service} is not running"
        )
    return port


# -- APIs -------------------------------------------------------------------------------
@api_router.api_route("/{quill_id}/{path:path}", methods=METHODS)
async def quill_api(
    quill_id: str,
    path: str,
    request: Request,
    state: AppState = Depends(get_state),
    principal: Principal = Depends(get_principal),
) -> Response:
    """A Quill's own API: the request, to the service that serves it, as who sent it."""
    manifest = _quill(state, quill_id)
    if principal.kind == "quill" and principal.quill != quill_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "a Quill's token opens its own API only")
    api = next(
        (
            a for a in manifest.apis
            if not a.get("prefix") or path == a["prefix"] or path.startswith(a["prefix"] + "/")
        ),
        None,
    )
    if api is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{manifest.name} has no API at {path}")
    port = _port(state, manifest, api["service"])
    body = await read_body(request, MAX_BODY)
    who = (
        {"X-Cloudmorrow-Quill": principal.quill}
        if principal.kind == "quill"
        else {"X-Cloudmorrow-User": principal.username}
    )
    return await forward(request, port, path, body, who | {"X-Cloudmorrow-Api": api["id"]})


# -- webhooks ---------------------------------------------------------------------------
@hooks_router.post("/{quill_id}/{path}")
async def webhook(
    quill_id: str,
    path: str,
    request: Request,
    token: str = Query(default=""),
    state: AppState = Depends(get_state),
) -> Response:
    """Something outside tells the Quill something: a record, or a service's to answer."""
    manifest = state.quills.quills.get(quill_id)
    hook = next((h for h in manifest.webhooks if h["path"] == path), None) if manifest else None
    if manifest is None or hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such webhook")
    if not state.features.enabled(quill_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{manifest.name} is switched off")
    body = await read_body(request, HOOK_MAX_BODY)
    secret = state.quill_tokens.webhook_secret(quill_id, hook["id"])
    sent = token or request.headers.get("x-cloudmorrow-webhook-token", "")
    signed = hook.get("signature") and signature_ok(
        secret, body, request.headers.get(hook["signature"])
    )
    if not (signed or (sent and hmac.compare_digest(sent, secret))):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not this webhook's secret")
    if not hook_rate.allow(f"{quill_id}/{hook['id']}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many, too fast")

    if hook.get("forward"):
        port = _port(state, manifest, hook["forward"])
        return await forward(
            request, port, f"hooks/{hook['path']}", body, {"X-Cloudmorrow-Webhook": hook["id"]},
            drop=("token",),
        )

    owner = runs_as(state.users, manifest.origin)
    if not owner:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{manifest.name} runs as nobody")
    try:
        payload = json.loads(body or b"null")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the body is not JSON") from exc
    fields = apply_map(payload, hook.get("map", {}))
    principal = Principal("quill", owner, quill=manifest.id, models=manifest.models)
    try:
        record = state.records.create(principal, hook["model"], fields)
    except ERRORS as exc:
        raise _refused(exc) from exc
    return JSONResponse({"id": record.id, "model": record.model}, status_code=201)


# -- administration ---------------------------------------------------------------------
def _supervisor(state: AppState):
    if state.services is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no supervisor on this server")
    return state.services


def _base(state: AppState, request: Request) -> str:
    return (state.config.public_url or str(request.base_url)).rstrip("/")


@admin_router.get("")
def services(
    request: Request, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> list[dict]:
    """Every Quill that runs code: its services and their state, jobs, webhooks, APIs."""
    base = _base(state, request)
    rows = _supervisor(state).status()
    for row in rows:
        for hook in row["webhooks"]:
            hook["url"] = f"{base}/hooks/{row['id']}/{hook['path']}"
        for service in row["services"]:
            service["log"] = state.services.tail(row["id"], service["id"], 20)
    return rows


@admin_router.get("/{quill_id}/logs")
def logs(
    quill_id: str,
    service: str = "",
    lines: int = Query(default=100, ge=1, le=5000),
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict[str, list[str]]:
    """The last lines of each service's log, or of the one named."""
    manifest = state.quills.quills.get(quill_id)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{quill_id} is not installed")
    names = [s["id"] for s in manifest.services]
    if service and service not in names:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{quill_id} has no service {service}")
    supervisor = _supervisor(state)
    return {name: supervisor.tail(quill_id, name, lines) for name in ([service] if service else names)}


@admin_router.post("/{quill_id}/token")
def rotate_token(
    quill_id: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    """A new token; the old one stops working now, and the services restart with the new."""
    _quill(state, quill_id)
    _supervisor(state).rotate(quill_id)
    return {"token": state.quill_tokens.info(quill_id)}


@admin_router.post("/{quill_id}/restart")
def restart(
    quill_id: str, state: AppState = Depends(get_state), _: User = Depends(get_admin_user)
) -> dict:
    _quill(state, quill_id)
    _supervisor(state).restart(quill_id)
    return {"restarted": quill_id}


@admin_router.post("/{quill_id}/webhooks/{hook_id}/secret")
def rotate_secret(
    quill_id: str,
    hook_id: str,
    request: Request,
    state: AppState = Depends(get_state),
    _: User = Depends(get_admin_user),
) -> dict:
    """A new secret for one webhook: the sender needs the new one from now."""
    manifest = state.quills.quills.get(quill_id)
    hook = next((h for h in manifest.webhooks if h["id"] == hook_id), None) if manifest else None
    if hook is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such webhook")
    secret = state.quill_tokens.rotate_webhook(quill_id, hook_id)
    return {
        "id": hook_id,
        "secret": secret,
        "url": f"{_base(state, request)}/hooks/{quill_id}/{hook['path']}",
    }
