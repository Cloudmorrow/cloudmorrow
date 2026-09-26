"""Application state and FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cloudmorrow.server.agents import Agent, AgentStore, JobStore
from cloudmorrow.server.config import ServerConfig
from cloudmorrow.server.configsync import ConfigStore
from cloudmorrow.server.db import User, UserStore
from cloudmorrow.server.features import FeatureStore
from cloudmorrow.server.mcp import MCPStore
from cloudmorrow.server.notes import NoteStore, ensure_notes_layout
from cloudmorrow.server.notifications import NotificationStore
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.server.records import RecordStore
from cloudmorrow.server.sealed import Sealer
from cloudmorrow.server.secrets import (
    DEFAULT_ENVIRONMENT,
    InvalidEnvironmentError,
    InvalidVaultError,
    SecretStore,
    validate_environment,
    validate_vault,
)
from cloudmorrow.server.security import TokenError, decode_access_token
from cloudmorrow.server.settings import SettingsStore
from cloudmorrow.server.shares import ShareStore
from cloudmorrow.server.today import Weather
from cloudmorrow.server.webpush import PushStore

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class AppState:
    config: ServerConfig
    users: UserStore
    agents: AgentStore
    jobs: JobStore
    secrets: SecretStore
    config_sync: ConfigStore
    notifications: NotificationStore
    features: FeatureStore
    shares: ShareStore
    push: PushStore
    # The assistants people have let in over MCP, and their tokens.
    mcp: MCPStore
    # The forecast for the place in the config, for the app's front page.
    weather: Weather
    # Is this a good username and password, or token, for an account? What
    # the WebDAV side asks on every request, and what an agent serving a
    # machine share asks through the API.
    credential_check: Callable[[str, str], bool]
    # What seals content at rest: the notes stores are handed it; the
    # database stores find it through their connection.
    sealer: Sealer
    # What somebody told the server about itself from the app: its name.
    settings: SettingsStore
    # The installed Quills and datamodels, and the records of every one.
    quills: QuillRegistry
    records: RecordStore

    def cloud_name(self) -> str:
        """What this cloud is called: set from the app, else from the config."""
        return self.settings.name(self.config.name)

    def note_store(self, user: User) -> NoteStore:
        ensure_notes_layout(self.config.user_base(user.username))
        return NoteStore(self.config.notes_root(user.username), self.sealer)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown agent token"
        )
    return agent


def get_note_store(
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> NoteStore:
    """Notes are the user's: one tree each, and nothing else scopes them."""
    return state.note_store(user)


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
    env: Annotated[str, Query(alias="env", description="local, test, production, …")] = (
        DEFAULT_ENVIRONMENT
    ),
) -> str:
    """The environment a secrets call works in, from ?env=."""
    try:
        return validate_environment(env)
    except InvalidEnvironmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
