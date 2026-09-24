"""The MCP server: Claude, or any assistant, working in Cloudmorrow as you.

Three things live here, and a client meets them in this order:

1. Discovery. A request to `/mcp` with no token is answered 401 with a
   pointer to `/.well-known/oauth-protected-resource`, which names this
   server as its own authorization server, whose details are at
   `/.well-known/oauth-authorization-server`. That is all a client needs
   to find the rest on its own.
2. OAuth. The client registers itself at `/oauth/register`, sends the
   person to `/oauth/authorize` — a page of ours, where they sign in and
   say yes — and trades the code that comes back at `/oauth/token`.
   Nothing to configure first: adding the server's address to Claude is
   the whole setup.
3. MCP itself, at `/mcp`: JSON-RPC over HTTP, one request per POST, with
   the tools in `mcptools`. Every call runs as the person who said yes.

`/api/mcp/connections` is the person's view of it: which assistants they
have let in, and a way to cut one off.
"""

from __future__ import annotations

import base64
import html
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.server import mcptools
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.mcp import SCOPE, GrantError, MCPStore, RegistrationError
from cloudmorrow.server.routes.install import TEMPLATES, base_url
from cloudmorrow.server.security import TokenError, decode_access_token, verify_password

router = APIRouter(tags=["mcp"])

MCP_PATH = "/mcp"
# The protocol revisions this server speaks. A client names the one it
# wants; it gets that one back if it is here, and the newest otherwise.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

# JSON-RPC's own error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

# Metadata is public by design, and a browser-based client reads it from
# another origin. The MCP endpoint itself is not opened this way: that is
# what `cors_origins` in the server config is for.
PUBLIC = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}


def _store(state: AppState) -> MCPStore:
    return state.mcp


# -- discovery ---------------------------------------------------------------
def resource_metadata(base: str) -> dict[str, Any]:
    return {
        "resource": base + MCP_PATH,
        "authorization_servers": [base],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Cloudmorrow",
    }


def server_metadata(base: str) -> dict[str, Any]:
    return {
        "issuer": base,
        "authorization_endpoint": base + "/oauth/authorize",
        "token_endpoint": base + "/oauth/token",
        "registration_endpoint": base + "/oauth/register",
        "scopes_supported": [SCOPE],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256"],
    }


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def protected_resource(request: Request, state: AppState = Depends(get_state)) -> JSONResponse:
    return JSONResponse(resource_metadata(base_url(request, state)), headers=PUBLIC)


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@router.get("/.well-known/openid-configuration", include_in_schema=False)
def authorization_server(request: Request, state: AppState = Depends(get_state)) -> JSONResponse:
    return JSONResponse(server_metadata(base_url(request, state)), headers=PUBLIC)


@router.options("/.well-known/{path:path}", include_in_schema=False)
@router.options("/oauth/{path:path}", include_in_schema=False)
def preflight() -> Response:
    return Response(
        status_code=204,
        headers={
            **PUBLIC,
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type, MCP-Protocol-Version",
        },
    )


# -- registration --------------------------------------------------------------
@router.post("/oauth/register", include_in_schema=False)
async def register(request: Request, state: AppState = Depends(get_state)) -> JSONResponse:
    """RFC 7591: a client tells us who it is and where codes may go."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _oauth_error("invalid_client_metadata", "the body must be a JSON object")
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not all(isinstance(uri, str) for uri in uris):
        return _oauth_error("invalid_redirect_uri", "redirect_uris must be a list of strings")
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in {"none", "client_secret_post", "client_secret_basic"}:
        return _oauth_error(
            "invalid_client_metadata", f"unsupported token_endpoint_auth_method: {method}"
        )
    name = body.get("client_name") if isinstance(body.get("client_name"), str) else ""
    try:
        client, secret = _store(state).register(
            name or "an MCP client", uris, public=method == "none"
        )
    except RegistrationError as exc:
        return _oauth_error("invalid_redirect_uri", str(exc))
    answer: dict[str, Any] = {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": list(client.redirect_uris),
        "token_endpoint_auth_method": method,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": SCOPE,
    }
    if secret:
        answer["client_secret"] = secret
        answer["client_secret_expires_at"] = 0
    return JSONResponse(answer, status_code=status.HTTP_201_CREATED, headers=PUBLIC)


def _oauth_error(error: str, description: str, code: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description}, status_code=code, headers=PUBLIC
    )


# -- authorization: the page where the person says yes -------------------------
AUTHORIZE_FIELDS = (
    "client_id",
    "redirect_uri",
    "state",
    "scope",
    "code_challenge",
    "code_challenge_method",
    "resource",
)


def _redirect_with(uri: str, params: dict[str, str]) -> RedirectResponse:
    parts = urlsplit(uri)
    query = parts.query + ("&" if parts.query else "") + urlencode(params)
    target = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    return RedirectResponse(
        target, status_code=status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"}
    )


async def _form(request: Request) -> dict[str, str]:
    """A posted form, read by hand: urlencoded is the only kind sent here,
    and reading it needs none of the multipart machinery the server does
    not carry."""
    body = (await request.body()).decode("utf-8", errors="replace")
    return dict(parse_qsl(body, keep_blank_values=True))


def _render(name: str, replacements: dict[str, str]) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def _consent_page(
    params: dict[str, str],
    client_name: str,
    *,
    username: str = "",
    message: str = "",
    code: int = 200,
) -> HTMLResponse:
    hidden = "\n".join(
        f'<input type="hidden" name="{html.escape(key)}"'
        f' value="{html.escape(params.get(key, ""))}">'
        for key in AUTHORIZE_FIELDS
    )
    page = _render(
        "mcp-authorize.html",
        {
            "__CLIENT__": html.escape(client_name or "An assistant"),
            "__HIDDEN__": hidden,
            "__USERNAME__": html.escape(username),
            "__MESSAGE__": html.escape(message),
            "__VERSION__": html.escape(__version__),
        },
    )
    return HTMLResponse(page, status_code=code, headers={"Cache-Control": "no-store"})


def _refusal_page(message: str) -> HTMLResponse:
    page = _render(
        "mcp-refused.html",
        {"__MESSAGE__": html.escape(message), "__VERSION__": html.escape(__version__)},
    )
    return HTMLResponse(
        page, status_code=status.HTTP_400_BAD_REQUEST, headers={"Cache-Control": "no-store"}
    )


def _check_request(state: AppState, params: dict[str, str]):
    """The client and redirect first — a bad one gets a page, not a redirect,
    because there is nowhere safe to send it. Then the rest of the request."""
    client = _store(state).client(params.get("client_id", ""))
    if client is None:
        return None, _refusal_page("Unknown client. Add the server to your assistant again.")
    redirect_uri = params.get("redirect_uri", "")
    if not redirect_uri or not client.allows_redirect(redirect_uri):
        return None, _refusal_page(
            "The assistant asked to be sent back somewhere it did not register."
        )
    if (params.get("response_type") or "code") != "code":
        return client, _redirect_with(
            redirect_uri, _with_state(params, error="unsupported_response_type")
        )
    if not params.get("code_challenge") or params.get("code_challenge_method", "S256") != "S256":
        return client, _redirect_with(
            redirect_uri,
            _with_state(
                params,
                error="invalid_request",
                error_description="a PKCE code_challenge with method S256 is required",
            ),
        )
    return client, None


def _with_state(params: dict[str, str], **query: str) -> dict[str, str]:
    if params.get("state"):
        query["state"] = params["state"]
    return query


@router.get("/oauth/authorize", include_in_schema=False)
def authorize_page(request: Request, state: AppState = Depends(get_state)) -> Response:
    query = request.query_params
    params = {key: query.get(key, "") for key in (*AUTHORIZE_FIELDS, "response_type")}
    if not params["code_challenge_method"]:
        params["code_challenge_method"] = "S256"
    client, refused = _check_request(state, params)
    if refused is not None:
        return refused
    return _consent_page(params, client.client_name)


@router.post("/oauth/authorize", include_in_schema=False)
async def authorize_decide(request: Request, state: AppState = Depends(get_state)) -> Response:
    form = await _form(request)
    params = {key: form.get(key, "") for key in (*AUTHORIZE_FIELDS, "response_type")}
    if not params["code_challenge_method"]:
        params["code_challenge_method"] = "S256"
    client, refused = _check_request(state, params)
    if refused is not None:
        return refused
    redirect_uri = params["redirect_uri"]
    if form.get("decision", "") != "allow":
        return _redirect_with(redirect_uri, _with_state(params, error="access_denied"))
    username = form.get("username", "").strip().lower()
    password = form.get("password", "")
    user = state.users.get(username) if username else None
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return _consent_page(
            params,
            client.client_name,
            username=username,
            message="Wrong username or password.",
            code=status.HTTP_401_UNAUTHORIZED,
        )
    code = _store(state).issue_code(
        client,
        user.username,
        redirect_uri=redirect_uri,
        code_challenge=params["code_challenge"],
        code_challenge_method=params["code_challenge_method"],
        scope=params.get("scope") or SCOPE,
    )
    return _redirect_with(redirect_uri, _with_state(params, code=code))


# -- the token endpoint ------------------------------------------------------------
async def _form_or_json(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "json" in content_type:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        return {str(k): str(v) for k, v in body.items()} if isinstance(body, dict) else {}
    return await _form(request)


def _client_credentials(request: Request, body: dict[str, str]) -> tuple[str, str | None]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
            client_id, _, secret = decoded.partition(":")
            return client_id, secret
        except (ValueError, UnicodeDecodeError):
            pass
    return body.get("client_id", ""), body.get("client_secret") or None


@router.post("/oauth/token", include_in_schema=False)
async def token(request: Request, state: AppState = Depends(get_state)) -> JSONResponse:
    body = await _form_or_json(request)
    client_id, secret = _client_credentials(request, body)
    store = _store(state)
    try:
        client = store.authenticate_client(client_id, secret)
        grant = body.get("grant_type", "")
        if grant == "authorization_code":
            tokens = store.redeem_code(
                client,
                body.get("code", ""),
                redirect_uri=body.get("redirect_uri", ""),
                code_verifier=body.get("code_verifier", ""),
            )
        elif grant == "refresh_token":
            tokens = store.refresh(client, body.get("refresh_token", ""))
        else:
            raise GrantError("unsupported_grant_type", f"unsupported grant_type: {grant!r}")
    except GrantError as exc:
        code = 401 if exc.error == "invalid_client" else 400
        return _oauth_error(exc.error, exc.description, code)
    return JSONResponse(
        {
            "access_token": tokens.access_token,
            "token_type": "Bearer",
            "expires_in": tokens.expires_in,
            "refresh_token": tokens.refresh_token,
            "scope": tokens.scope,
        },
        headers={**PUBLIC, "Pragma": "no-cache"},
    )


# -- the MCP endpoint ---------------------------------------------------------------
def _challenge(request: Request, state: AppState, error: str = "") -> HTTPException:
    metadata = base_url(request, state) + "/.well-known/oauth-protected-resource"
    value = f'Bearer resource_metadata="{metadata}"'
    if error:
        value = f'Bearer error="{error}", resource_metadata="{metadata}"'
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": value},
    )


def mcp_user(request: Request, state: AppState = Depends(get_state)) -> User:
    """Who is calling `/mcp`: the holder of an MCP token, or — for someone
    wiring a client up by hand — of an ordinary access token."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise _challenge(request, state)
    credential = header[7:].strip()
    connection = _store(state).user_for(credential)
    if connection is not None:
        username = connection.username
    else:
        try:
            username = decode_access_token(credential, state.config.ensure_secret_key())
        except TokenError as exc:
            raise _challenge(request, state, "invalid_token") from exc
    user = state.users.get(username)
    if user is None or not user.is_active:
        raise _challenge(request, state, "invalid_token")
    return user


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle_message(state: AppState, user: User, message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message in, one out — or nothing, for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _rpc_error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(method, str):
        # A response, or nothing we understand: there is no one to answer.
        return None if "result" in message or "error" in message else _rpc_error(
            request_id, INVALID_REQUEST, "no method"
        )
    if request_id is None:
        # A notification. `notifications/initialized` and the like: noted.
        return None
    if not isinstance(params, dict):
        return _rpc_error(request_id, INVALID_PARAMS, "params must be an object")
    if method == "initialize":
        wanted = params.get("protocolVersion")
        version = wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _rpc_result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "cloudmorrow", "title": "Cloudmorrow", "version": __version__},
                "instructions": mcptools.INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _rpc_result(request_id, {})
    if method == "tools/list":
        return _rpc_result(
            request_id, {"tools": [tool.to_dict() for tool in mcptools.available(state)]}
        )
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or name not in mcptools.BY_NAME:
            return _rpc_error(request_id, INVALID_PARAMS, f"unknown tool: {name!r}")
        return _rpc_result(request_id, mcptools.call(state, user, name, params.get("arguments")))
    if method in {"resources/list", "resources/templates/list"}:
        key = "resourceTemplates" if method.endswith("templates/list") else "resources"
        return _rpc_result(request_id, {key: []})
    if method == "prompts/list":
        return _rpc_result(request_id, {"prompts": []})
    return _rpc_error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")


@router.post(MCP_PATH, include_in_schema=False)
async def mcp_post(
    request: Request, state: AppState = Depends(get_state), user: User = Depends(mcp_user)
) -> Response:
    try:
        body = json.loads(await request.body())
    except ValueError:
        return JSONResponse(_rpc_error(None, PARSE_ERROR, "the body is not JSON"), status_code=400)
    if isinstance(body, list):
        answers = [a for a in (handle_message(state, user, m) for m in body) if a is not None]
        if not answers:
            return Response(status_code=status.HTTP_202_ACCEPTED)
        return JSONResponse(answers, headers={"Cache-Control": "no-store"})
    answer = handle_message(state, user, body)
    if answer is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(answer, headers={"Cache-Control": "no-store"})


@router.get(MCP_PATH, include_in_schema=False)
@router.delete(MCP_PATH, include_in_schema=False)
def mcp_no_stream(user: User = Depends(mcp_user)) -> Response:
    """No server-to-client stream and no sessions to end: every POST stands alone."""
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})


# -- what the person sees ------------------------------------------------------------
@router.get("/api/mcp/connections", tags=["mcp"])
def list_connections(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[dict]:
    """The assistants you have let in."""
    return [connection.to_dict() for connection in _store(state).connections(user.username)]


@router.delete(
    "/api/mcp/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["mcp"]
)
def revoke_connection(
    connection_id: int,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    """Cut one off. It has to go through the sign-in page again to come back."""
    if not _store(state).revoke(user.username, connection_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such connection")
