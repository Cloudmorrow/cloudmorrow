"""Pydantic wire models."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from cloudmorrow.dotenv import DEFAULT_ENVIRONMENT, DEFAULT_VAULT


class UserOut(BaseModel):
    username: str
    display_name: str = ""
    # 'administrator', 'user' or 'dashboard_displayer'; is_admin says the same
    # thing about the first of those, and is what the older clients read.
    role: str = "user"
    # 'human', 'agent' or 'systems_user'.
    user_type: str = "human"
    is_admin: bool = False
    is_active: bool = True
    system_uid: int | None = None
    created_at: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: dt.datetime
    user: UserOut


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserCreate(BaseModel):
    username: str
    password: str = Field(min_length=8)
    display_name: str = ""
    # The role decides it when it is given; is_admin is still honoured for
    # the clients that were written before roles existed.
    role: str | None = None
    user_type: str = "human"
    is_admin: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: str | None = None
    user_type: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    system_uid: int | None = None


class FeatureOut(BaseModel):
    """One switchable area of the server."""

    key: str
    label: str
    description: str = ""
    enabled: bool = True
    # The kinds of data this app reads and writes: keys from /api/types.
    types: list[str] = Field(default_factory=list)
    # The administrator who last switched it, and when. Empty while nobody has.
    changed_by: str = ""
    updated_at: str = ""


class TypeFieldOut(BaseModel):
    name: str
    kind: str
    description: str = ""
    ref: str | None = None


class TypeOut(BaseModel):
    """One kind of data there is, and who reaches it."""

    key: str
    label: str
    description: str = ""
    provided_by: str
    foundation: bool = False
    scopes: list[str] = Field(default_factory=list)
    fields: list[TypeFieldOut] = Field(default_factory=list)
    sealed: list[str] = Field(default_factory=list)
    assistant: bool = False
    used_by: list[str] = Field(default_factory=list)


class MyFeatureOut(BaseModel):
    """One feature, as the person signed in may switch it.

    No `changed_by`: who threw the server's switch is the administrator's
    business, and what is listed here is only what this account can decide.
    """

    key: str
    label: str
    description: str = ""
    enabled: bool = True


class FeatureUpdate(BaseModel):
    enabled: bool


class NoteWrite(BaseModel):
    content: str
    # Revision the client last saw; omit to force-write.
    rev: str | None = None


class NoteCreate(BaseModel):
    path: str
    content: str = ""


class NoteMove(BaseModel):
    src: str
    dest: str


class NoteOut(BaseModel):
    path: str
    content: str
    rev: str
    size: int
    modified: float


class ImageOut(BaseModel):
    name: str
    # What a note writes to show it: `img/<name>`.
    path: str
    size: int
    content_type: str


class SecretOut(BaseModel):
    key: str
    environment: str
    vault: str = DEFAULT_VAULT
    # Filled in only when the caller asked to reveal it.
    value: str | None = None
    length: int = 0
    # Keyed digest: enough to tell two values apart, never enough to guess one.
    fingerprint: str = ""
    created_at: str = ""
    updated_at: str = ""


class SecretWrite(BaseModel):
    value: str
    environment: str = DEFAULT_ENVIRONMENT


class SecretImport(BaseModel):
    entries: dict[str, str]
    environment: str = DEFAULT_ENVIRONMENT
    # Delete keys the import does not mention, so the environment matches it exactly.
    prune: bool = False
    # Off keeps values that already exist, filling in only what is missing.
    overwrite: bool = True
    # Report what would happen and write nothing.
    dry_run: bool = False


class SecretImportOut(BaseModel):
    environment: str
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    dry_run: bool = False


class EnvironmentOut(BaseModel):
    environment: str
    secrets: int = 0
    updated_at: str = ""


class VaultOut(BaseModel):
    vault: str
    secrets: int = 0
    environments: int = 0
    updated_at: str = ""


class EnrollTokenRequest(BaseModel):
    label: str = ""
    ttl_minutes: int = Field(default=60, ge=1, le=60 * 24)


class EnrollTokenResponse(BaseModel):
    enrollment_token: str
    expires_at: str


class EnrollRequest(BaseModel):
    enrollment_token: str
    name: str
    hostname: str = ""
    platform: str = ""
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)


class EnrollSelfRequest(BaseModel):
    name: str
    hostname: str = ""
    platform: str = ""
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)


class EnrollResponse(BaseModel):
    agent_id: int
    name: str
    agent_token: str


class AgentOut(BaseModel):
    id: int
    name: str
    hostname: str = ""
    platform: str = ""
    version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    last_seen: str | None = None
    enrolled_at: str = ""
    online: bool = False
    # Config bundles this machine keeps in step with the others.
    sync_bundles: list[str] = Field(default_factory=list)
    # Where it serves its machine shares, as last reported; "" when it does not.
    dav_base: str = ""


class AgentSyncUpdate(BaseModel):
    """Which bundles a machine should keep in sync. [] switches it all off."""

    sync_bundles: list[str] = Field(default_factory=list)


class HeartbeatRequest(BaseModel):
    hostname: str = ""
    platform: str = ""
    version: str = ""
    # Re-reported every time, so a machine that grows a capability — Omarchy
    # installed since enrolment — says so without enrolling again.
    capabilities: list[str] = Field(default_factory=list)
    # Where this machine serves its shares, `http://192.168.1.10:8788`, or
    # "" while it serves nothing. None when the agent predates shares.
    dav_base: str | None = None


class HeartbeatShare(BaseModel):
    """A machine share, as the agent that serves it needs to know it."""

    name: str
    path: str


class HeartbeatResponse(BaseModel):
    agent_id: int
    queued_jobs: int
    poll_seconds: int = 30
    # What this machine has been told to keep in sync. The agent asks for
    # nothing else: the tick in the TUI arrives here.
    sync_bundles: list[str] = Field(default_factory=list)
    # The machine shares this agent serves. Same idea: made in the TUI or
    # the CLI, and the agent starts serving on its next heartbeat.
    shares: list[HeartbeatShare] = Field(default_factory=list)


class CredentialsCheck(BaseModel):
    """An agent asking whether a mount's username and password are good."""

    username: str
    password: str


class CredentialsOut(BaseModel):
    valid: bool


class JobCreate(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)


class JobResult(BaseModel):
    status: str = Field(pattern="^(done|failed)$")
    result: dict = Field(default_factory=dict)


class JobOut(BaseModel):
    id: int
    agent_id: int
    type: str
    payload: dict = Field(default_factory=dict)
    status: str
    result: dict | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class SetupRequest(BaseModel):
    """The first visit to a server with nobody on it: a name and an administrator."""

    name: str = Field(min_length=1, max_length=64)
    username: str
    password: str = Field(min_length=8)


class SetupOut(BaseModel):
    name: str
    username: str


class ServerSettingsOut(BaseModel):
    """What the server has been told about itself."""

    name: str


class ServerSettingsUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ServerUpdateRequest(BaseModel):
    """What `cloudmorrow update server` asks the server to deploy."""

    branch: str | None = None
    force: bool = False
    # Off leaves the new code on disk and the old code running, which is what
    # you want when you would rather pick the moment yourself.
    restart: bool = True


class ServerUpdateOut(BaseModel):
    source: str
    branch: str
    old_commit: str
    new_commit: str
    # The release either end, from the tags. "" when nothing is tagged yet, and
    # then the commit is the only name the deploy has.
    old_version: str = ""
    new_version: str = ""
    commit_subject: str = ""
    changed_files: int = 0
    changed: bool = False
    # Commits the checkout had that its remote does not, thrown away to deploy.
    # Nought on an ordinary deploy; a force-push or a rollback makes it more.
    discarded: int = 0
    reinstalled: bool = False
    published_wheel: str = ""
    # Whether the server is on its way down to come back on the new code, and
    # if it is not, why not.
    restarting: bool = False
    restart_blocked: str = ""


class ShareOut(BaseModel):
    name: str
    # "server": a directory on the server, served by the server. "machine":
    # a directory on one of the owner's machines, served by its agent.
    kind: str = "server"
    # The directory: on the server, or on the machine named below.
    path: str
    # In the server's Shares directory, and so deletable with the share.
    # False only for a share made before shares lived there.
    managed: bool
    # The machine that serves a machine share; "" for a server share.
    machine: str = ""
    # Reachable now. Always true for a server share; for a machine share,
    # true while its agent is running and serving.
    online: bool = True
    description: str = ""
    # Where to point a WebDAV client: `<public_url>/dav/<name>/` for a server
    # share, `<machine's address>/dav/<name>/` for a machine share — "" when
    # the machine has never said where it serves.
    url: str
    created_at: str = ""
    updated_at: str = ""


class ShareCreate(BaseModel):
    name: str
    # "server" (admins only) or "machine".
    kind: str = "server"
    # For a machine share: the directory on that machine, absolute. A server
    # share takes none — it is the folder of its name in the owner's Shares
    # directory on the server.
    path: str | None = None
    # For a machine share: the name of the agent that serves it.
    machine: str | None = None
    description: str = ""


class ShareFoldersOut(BaseModel):
    """An admin's Shares directory on the server, and what is in it unshared."""

    directory: str
    # Folders in it that no share is made of yet, by name.
    folders: list[str]


class ConfigFileIn(BaseModel):
    """One file in a bundle, as a machine sends it."""

    path: str
    content: str
    sha256: str = ""
    mode: int = 0o644


class ConfigFileOut(ConfigFileIn):
    pass


class ConfigFileMeta(BaseModel):
    path: str
    sha256: str
    mode: int = 0o644


class BundleOut(BaseModel):
    """The manifest: enough to tell whether you are behind, without the bytes."""

    bundle: str
    revision: int = 0
    origin: str = ""
    claimed_by: str = ""
    claimed_at: str = ""
    updated_at: str = ""
    files: list[ConfigFileMeta] = Field(default_factory=list)


class BundleFilesOut(BaseModel):
    bundle: str
    revision: int
    origin: str = ""
    files: list[ConfigFileOut] = Field(default_factory=list)


class BundlePush(BaseModel):
    """A machine's whole copy of a bundle, and what it thinks it is based on."""

    files: list[ConfigFileIn] = Field(default_factory=list)
    # The revision this machine last had. null claims an unclaimed bundle —
    # true for exactly one machine, the first one to tick the box.
    base_revision: int | None = None


class BundleStatusOut(BundleOut):
    """The bundle, plus which machines are keeping it."""

    machines: list[str] = Field(default_factory=list)


class NotificationOut(BaseModel):
    id: int
    kind: str = "info"
    machine: str = ""
    title: str
    body: str = ""
    created_at: str = ""
    read_at: str | None = None
    unread: bool = True


class NotificationCreate(BaseModel):
    title: str
    kind: str = "info"
    body: str = ""


class NotificationsRead(BaseModel):
    """Which to mark read. Omit the ids to mark the lot."""

    ids: list[int] | None = None


class NotificationsReadOut(BaseModel):
    marked: int
    unread: int
