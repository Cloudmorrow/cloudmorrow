"""Keeping one machine's config level with the server's copy.

The agent already has a loop that runs every half minute, so this is a step in
it rather than a daemon of its own: look at what is on disk, look at what the
server has, and do the one thing that follows from the difference.

There are only four situations, and the state file is what tells them apart.
It holds the revision this machine last had in its hands and the hash of every
file as we left it — so a file that differs from that is a local edit, and a
revision that differs from that is somebody else's edit.

    server unclaimed         →  claim it: this machine's copy becomes rev 1
    this machine never synced →  adopt the server's copy
    server ahead of us        →  pull and write it
    files changed under us    →  push, from the revision we hold

A push that comes back stale means another machine pushed in the meantime; the
next pass sees the higher revision and pulls it, so it settles itself.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir

from cloudmorrow.agent import omarchy
from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig

log = logging.getLogger("cloudmorrow.agent.sync")

# Bundle name → what reading and writing it means on this machine.
BUNDLES = {omarchy.BUNDLE: omarchy}


def state_dir() -> Path:
    return Path(user_data_dir("cloudmorrow")) / "sync"


@dataclass(slots=True)
class SyncState:
    """What this machine last had, and where it got it."""

    bundle: str
    revision: int = 0
    files: dict[str, str] = field(default_factory=dict)
    origin: str = ""
    updated_at: str = ""
    path: Path | None = None

    @classmethod
    def load(cls, bundle: str, directory: Path | None = None) -> SyncState:
        path = (directory or state_dir()) / f"{bundle}.json"
        state = cls(bundle=bundle, path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Never synced here, or the file is unreadable. Either way this
            # machine has nothing it can claim to hold, which is the safe answer.
            return state
        state.revision = int(data.get("revision", 0))
        state.files = {str(k): str(v) for k, v in (data.get("files") or {}).items()}
        state.origin = str(data.get("origin", ""))
        state.updated_at = str(data.get("updated_at", ""))
        return state

    def save(self) -> Path:
        path = self.path or (state_dir() / f"{self.bundle}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "bundle": self.bundle,
                    "revision": self.revision,
                    "origin": self.origin,
                    "updated_at": self.updated_at,
                    "files": self.files,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.path = path
        return path

    def clear(self) -> None:
        """Forget everything, so the next pass treats this machine as new."""
        self.revision = 0
        self.files = {}
        self.origin = ""
        self.save()


@dataclass(slots=True)
class SyncOutcome:
    """What one pass over one bundle did, in a shape worth logging."""

    bundle: str
    action: str = "idle"
    revision: int = 0
    detail: str = ""
    # Worth telling the operator about, as opposed to routine "nothing to do".
    notable: bool = False

    def __str__(self) -> str:
        return f"{self.bundle}: {self.action}" + (f" ({self.detail})" if self.detail else "")


def _stamp() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def sync_bundle(
    client: AgentClient,
    config: AgentConfig,
    bundle: str,
    *,
    root: Path | None = None,
    state_directory: Path | None = None,
    notify: bool = True,
) -> SyncOutcome:
    """Bring this machine and the server into line over one bundle."""
    module = BUNDLES.get(bundle)
    if module is None:
        return SyncOutcome(bundle, "skipped", detail="this agent does not know that bundle")
    if not config.allow_config_sync:
        return SyncOutcome(bundle, "refused", detail="allow_config_sync = false on this machine")

    root = root or module.config_root()
    state = SyncState.load(bundle, state_directory)
    local = module.scan(root)
    local_manifest = module.manifest(local)
    remote = client.config_state(bundle)
    revision = int(remote.get("revision", 0))

    # 1. Nobody has claimed it. Whoever gets here first decides.
    if revision == 0:
        if not local:
            return SyncOutcome(bundle, "idle", detail="nothing here to claim it with")
        return _push(client, bundle, local, base=None, state=state, claim=True)

    # 2. This machine has never synced: adopt what is there, whatever is here.
    if state.revision == 0:
        return _pull(
            client, bundle, module, root, state, remote, adopt=True, notify=notify
        )

    # 3. Somebody else moved it. Their revision wins; ours is backed up.
    if revision != state.revision:
        return _pull(
            client, bundle, module, root, state, remote, adopt=False, notify=notify
        )

    # 4. Level with the server, so anything different here is a local edit.
    if local_manifest != state.files:
        return _push(client, bundle, local, base=state.revision, state=state, claim=False)
    return SyncOutcome(bundle, "idle", revision=state.revision)


def _push(
    client: AgentClient,
    bundle: str,
    local: list,
    *,
    base: int | None,
    state: SyncState,
    claim: bool,
) -> SyncOutcome:
    try:
        result = client.push_config(bundle, [f.to_payload() for f in local], base_revision=base)
    except AgentApiError as exc:
        if exc.status_code == 409:
            # Another machine got in first. Next pass sees the new revision
            # and pulls it, so there is nothing to do here but say so.
            return SyncOutcome(
                bundle, "stale", detail="another machine pushed first; pulling next pass"
            )
        raise

    state.revision = int(result.get("revision", 0))
    state.files = {f.path: f.sha256 for f in local}
    state.origin = str(result.get("origin", ""))
    state.updated_at = _stamp()
    state.save()
    action = "claimed" if claim else "pushed"
    outcome = SyncOutcome(
        bundle,
        action,
        revision=state.revision,
        detail=f"{len(local)} files",
        notable=True,
    )
    log.info("config sync %s", outcome)
    # The server writes the notification for a push — it is the one that knows
    # whether the claim stuck — so nothing is posted from here.
    return outcome


def _pull(
    client: AgentClient,
    bundle: str,
    module,
    root: Path,
    state: SyncState,
    remote: dict,
    *,
    adopt: bool,
    notify: bool,
) -> SyncOutcome:
    payload = client.config_files(bundle)
    revision = int(payload.get("revision", 0))
    files = payload.get("files") or []
    if not files:
        return SyncOutcome(bundle, "idle", revision=revision, detail="the bundle is empty")
    try:
        applied = module.apply(files, root=root, known=state.files)
    except module.BundleError as exc:
        if notify:
            _notify(
                client,
                kind="config.failed",
                title=f"could not write the {bundle} config",
                body=str(exc),
            )
        raise

    state.revision = revision
    state.files = {str(f["path"]): str(f["sha256"]) for f in files}
    state.origin = str(payload.get("origin", remote.get("origin", "")))
    state.updated_at = _stamp()
    state.save()

    action = "adopted" if adopt else "updated"
    outcome = SyncOutcome(
        bundle,
        action,
        revision=revision,
        detail=applied.summary(),
        notable=applied.changed or adopt,
    )
    log.info("config sync %s", outcome)
    if notify and outcome.notable:
        body = applied.summary()
        if applied.backed_up:
            body += f"; kept as .cloudmorrow-backup: {', '.join(applied.backed_up[:5])}"
        _notify(
            client,
            kind=f"config.{action}",
            title=(
                f"{bundle} config adopted from {state.origin or 'the server'}"
                if adopt
                else f"{bundle} config updated to revision {revision}"
            ),
            body=body,
        )
    return outcome


def _notify(client: AgentClient, *, kind: str, title: str, body: str) -> None:
    """Leave a note on the server. Never worth failing a sync over."""
    try:
        client.notify(kind=kind, title=title, body=body)
    except AgentApiError as exc:
        log.debug("could not post a notification: %s", exc)


def sync_all(
    client: AgentClient,
    config: AgentConfig,
    bundles: list[str],
    *,
    root: Path | None = None,
    state_directory: Path | None = None,
) -> list[SyncOutcome]:
    """One pass over every bundle this machine has been told to keep."""
    outcomes = []
    for bundle in bundles:
        try:
            outcomes.append(
                sync_bundle(
                    client, config, bundle, root=root, state_directory=state_directory
                )
            )
        except AgentApiError as exc:
            log.warning("config sync %s failed: %s", bundle, exc)
            outcomes.append(SyncOutcome(bundle, "failed", detail=str(exc)))
        except OSError as exc:
            log.warning("config sync %s could not touch the filesystem: %s", bundle, exc)
            outcomes.append(SyncOutcome(bundle, "failed", detail=str(exc)))
    return outcomes
