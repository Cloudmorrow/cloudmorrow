"""FastAPI dependencies: the running state, and who is asking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cloudmorrow.server.agents import Agent
from cloudmorrow.server.db import User
from cloudmorrow.server.quills.tokens import PREFIX as QUILL_TOKEN_PREFIX
from cloudmorrow.server.quills.tokens import runs_as
from cloudmorrow.server.records import Principal
from cloudmorrow.server.secrets import (
    DEFAULT_ENVIRONMENT,
    InvalidEnvironmentError,
    InvalidVaultError,
    validate_environment,
    validate_vault,
)
from cloudmorrow.server.security import TokenError, decode_access_token
from cloudmorrow.server.state import AppState

bearer_scheme = HTTPBearer(auto_error=False)


def get_state(request: Request) -> AppState:
    return request.app.state.cloudmorrow


def get_current_user(
    state: AppState = Depends(get_state),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        username = decode_access_token(credentials.credentials, state.config.ensure_secret_key())
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = state.users.get(username)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown user")
    return user


def get_principal(
    state: AppState = Depends(get_state),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    """Who is asking, where a Quill's service may ask too: the record API, a Quill's APIs.

    A person's token is a person. A Quill's token (`cmq_…`) is the Quill,
    acting for the account it runs as and reaching only the datamodels it
    declared — and only while it is installed and switched on. Every other
    route asks `get_current_user`, which a Quill's token never satisfies:
    it is not a signed token, so it does not decode as one.
    """
    if credentials is not None and credentials.credentials.startswith(QUILL_TOKEN_PREFIX):
        tokens = state.quill_tokens
        quill_id = tokens.quill_for(credentials.credentials) if tokens is not None else None
        manifest = state.quills.quills.get(quill_id or "")
        owner = runs_as(state.users, manifest.origin) if manifest else ""
        if manifest is None or not owner or not state.features.enabled(manifest.id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unknown quill token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return Principal("quill", owner, quill=manifest.id, models=manifest.models)
    user = get_current_user(state, credentials)
    return Principal.person(user.username, admin=user.is_admin)


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


def get_current_agent(
    state: AppState = Depends(get_state),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Agent:
    """Agent tokens are their own credential; they cannot read notes."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    agent = state.agents.by_token(credentials.credentials)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown agent token")
    return agent


@dataclass(slots=True)
class Scope:
    """Who is asking, and which of their vaults they are asking about."""

    owner: str
    vault: str


def get_scope(
    user: User = Depends(get_current_user),
    header: Annotated[str | None, Header(alias="X-Cloudmorrow-Vault")] = None,
    query: Annotated[str | None, Query(alias="vault")] = None,
) -> Scope:
    """The vault a secrets call works in: named, or the default one.

    Sent as a header by the clients; the query parameter is there for curl.
    """
    try:
        vault = validate_vault(header or query)
    except InvalidVaultError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Scope(owner=user.username, vault=vault)


def get_environment(
    env: Annotated[str, Query(alias="env", description="local, test, production, …")] = (DEFAULT_ENVIRONMENT),
) -> str:
    """The environment a secrets call works in, from ?env=."""
    try:
        return validate_environment(env)
    except InvalidEnvironmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
