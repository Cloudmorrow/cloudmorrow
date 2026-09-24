"""Agents and their job queue.

An agent is a small process running on one of my machines. It enrols once with
a single-use token, then polls for jobs and reports results. Agent tokens are
separate from user tokens and are stored hashed, so the database never holds a
credential that would let someone act as a machine.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.server.db import Connection, connect

AGENT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
TOKEN_PREFIX = "bca_"
ENROLL_PREFIX = "bce_"
DEFAULT_ENROLL_TTL_MINUTES = 60

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"
# A job nobody picked up within this window is assumed lost.
JOB_STALE_MINUTES = 30


class AgentExistsError(ValueError):
    pass


class UnknownAgentError(LookupError):
    pass


class InvalidAgentNameError(ValueError):
    pass


class EnrollmentError(ValueError):
    """The enrolment token is unknown, already used or expired."""


class UnknownJobError(LookupError):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _stamp() -> str:
    return _now().isoformat(timespec="seconds")


def hash_token(token: str) -> str:
    """Agent credentials are random 256-bit strings, so a plain hash is enough."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(prefix: str = TOKEN_PREFIX) -> str:
    return prefix + secrets.token_urlsafe(32)


def validate_agent_name(name: str) -> str:
    name = name.strip()
    if not AGENT_NAME_RE.match(name):
        raise InvalidAgentNameError(
            "agent name must be 1-64 chars of letters, digits, '.', '_' or '-'"
        )
    return name


@dataclass(slots=True)
class Agent:
    id: int
    owner: str
    name: str
    hostname: str
    platform: str
    version: str
    capabilities: list[str]
    last_seen: str | None
    enrolled_at: str
    # Config bundles this machine has been told to keep in sync. The agent
    # learns them from its heartbeat, so a tick in the TUI is all it takes.
    sync_bundles: list[str] = field(default_factory=list)
    # Where this machine serves its shares — `http://192.168.1.10:8788` —
    # as it last reported. Empty when it serves nothing.
    dav_base: str = ""

    @property
    def online(self) -> bool:
        """Seen within the last three heartbeat intervals."""
        if not self.last_seen:
            return False
        seen = dt.datetime.fromisoformat(self.last_seen)
        return (_now() - seen) < dt.timedelta(minutes=3)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "hostname": self.hostname,
            "platform": self.platform,
            "version": self.version,
            "capabilities": self.capabilities,
            "last_seen": self.last_seen,
            "enrolled_at": self.enrolled_at,
            "online": self.online,
            "sync_bundles": self.sync_bundles,
            "dav_base": self.dav_base,
        }


@dataclass(slots=True)
class Job:
    id: int
    agent_id: int
    owner: str
    project: str | None
    type: str
    payload: dict
    status: str
    result: dict | None
    created_at: str
    started_at: str | None
    finished_at: str | None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "project": self.project,
            "type": self.type,
            "payload": self.payload,
            "status": self.status,
            "result": self.result,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _list(raw: str | None) -> list[str]:
    return [part for part in (raw or "").split(",") if part]


def _agent(row: sqlite3.Row) -> Agent:
    return Agent(
        id=row["id"],
        owner=row["owner"],
        name=row["name"],
        hostname=row["hostname"],
        platform=row["platform"],
        version=row["version"],
        capabilities=[c for c in row["capabilities"].split(",") if c],
        last_seen=row["last_seen"],
        enrolled_at=row["enrolled_at"],
        sync_bundles=_list(row["sync_bundles"]),
        dav_base=row["dav_base"] or "",
    )


def _job(conn: Connection, row: sqlite3.Row) -> Job:
    scope = (row["owner"],)
    payload = conn.unseal("jobs", "payload", scope, row["payload"])
    result = conn.unseal("jobs", "result", scope, row["result"])
    return Job(
        id=row["id"],
        agent_id=row["agent_id"],
        owner=row["owner"],
        project=row["project"],
        type=row["type"],
        payload=json.loads(payload or "{}"),
        status=row["status"],
        result=json.loads(result) if result else None,
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


class AgentStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        connect(self.db_path).close()

    # -- enrolment ---------------------------------------------------------
    def create_enrollment_token(
        self, owner: str, *, label: str = "", ttl_minutes: int = DEFAULT_ENROLL_TTL_MINUTES
    ) -> tuple[str, str]:
        """Return (token, expires_at). The plaintext is never stored."""
        token = new_token(ENROLL_PREFIX)
        expires_at = (_now() + dt.timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds")
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO enrollment_tokens (owner, token_hash, label, expires_at, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (owner, hash_token(token), label, expires_at, _stamp()),
            )
        return token, expires_at

    def enroll(
        self,
        enrollment_token: str,
        *,
        name: str,
        hostname: str = "",
        platform: str = "",
        version: str = "",
        capabilities: list[str] | None = None,
    ) -> tuple[Agent, str]:
        """Consume an enrolment token and return the new agent and its token."""
        name = validate_agent_name(name)
        token_hash = hash_token(enrollment_token)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM enrollment_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                raise EnrollmentError("unknown enrolment token")
            if row["used_at"]:
                raise EnrollmentError("enrolment token has already been used")
            if dt.datetime.fromisoformat(row["expires_at"]) < _now():
                raise EnrollmentError("enrolment token has expired")

            owner = row["owner"]
            agent_token = new_token()
            try:
                conn.execute(
                    "INSERT INTO agents (owner, name, token_hash, hostname, platform, version,"
                    " capabilities, enrolled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        owner,
                        name,
                        hash_token(agent_token),
                        hostname,
                        platform,
                        version,
                        ",".join(capabilities or []),
                        _stamp(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AgentExistsError(name) from exc
            conn.execute(
                "UPDATE enrollment_tokens SET used_at = ? WHERE id = ?", (_stamp(), row["id"])
            )
            agent_row = conn.execute(
                "SELECT * FROM agents WHERE owner = ? AND name = ?", (owner, name)
            ).fetchone()
        return _agent(agent_row), agent_token

    # -- lookup ------------------------------------------------------------
    def enroll_for_user(
        self,
        owner: str,
        *,
        name: str,
        hostname: str = "",
        platform: str = "",
        version: str = "",
        capabilities: list[str] | None = None,
    ) -> tuple[Agent, str]:
        """Enrol a machine on behalf of an already-authenticated user.

        No enrolment token: the user proved who they are with their own
        credentials. Re-enrolling the same name rotates its token, so
        reinstalling a machine just works instead of colliding.
        """
        name = validate_agent_name(name)
        agent_token = new_token()
        caps = ",".join(capabilities or [])
        with connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM agents WHERE owner = ? AND name = ?", (owner, name)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE agents SET token_hash = ?, hostname = ?, platform = ?,"
                    " version = ?, capabilities = ? WHERE id = ?",
                    (
                        hash_token(agent_token),
                        hostname,
                        platform,
                        version,
                        caps,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO agents (owner, name, token_hash, hostname, platform,"
                    " version, capabilities, enrolled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        owner,
                        name,
                        hash_token(agent_token),
                        hostname,
                        platform,
                        version,
                        caps,
                        _stamp(),
                    ),
                )
            row = conn.execute(
                "SELECT * FROM agents WHERE owner = ? AND name = ?", (owner, name)
            ).fetchone()
        return _agent(row), agent_token

    def by_token(self, token: str) -> Agent | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE token_hash = ?", (hash_token(token),)
            ).fetchone()
        return _agent(row) if row else None

    def list(self, owner: str) -> list[Agent]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM agents WHERE owner = ? ORDER BY name", (owner,)
            ).fetchall()
        return [_agent(row) for row in rows]

    def get(self, owner: str, agent_id: int) -> Agent | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE owner = ? AND id = ?", (owner, agent_id)
            ).fetchone()
        return _agent(row) if row else None

    def require(self, owner: str, agent_id: int) -> Agent:
        agent = self.get(owner, agent_id)
        if agent is None:
            raise UnknownAgentError(str(agent_id))
        return agent

    def touch(self, agent_id: int, **fields: str | list[str] | None) -> None:
        """Record a heartbeat, refreshing whatever the agent reported with it.

        A field left out or empty keeps its value — except `dav_base`, where
        empty is the report: the machine serves nothing now.
        """
        allowed = {"hostname", "platform", "version", "capabilities"}
        updates = {
            key: ",".join(value) if isinstance(value, list) else value
            for key, value in fields.items()
            if key in allowed and value
        }
        if fields.get("dav_base") is not None:
            updates["dav_base"] = str(fields["dav_base"])
        assignments = "".join(f", {key} = ?" for key in updates)
        with connect(self.db_path) as conn:
            conn.execute(
                f"UPDATE agents SET last_seen = ?{assignments} WHERE id = ?",
                (_stamp(), *updates.values(), agent_id),
            )

    def set_sync_bundles(self, owner: str, agent_id: int, bundles: list[str]) -> Agent:
        """Tell a machine which config bundles to keep in step with the others."""
        cleaned = sorted({b.strip().lower() for b in bundles if b.strip()})
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE agents SET sync_bundles = ? WHERE owner = ? AND id = ?",
                (",".join(cleaned), owner, agent_id),
            )
            if cursor.rowcount == 0:
                raise UnknownAgentError(str(agent_id))
        return self.require(owner, agent_id)

    def syncing(self, owner: str, bundle: str) -> list[Agent]:
        """Every machine of this owner's that is keeping *bundle* in sync."""
        return [agent for agent in self.list(owner) if bundle in agent.sync_bundles]

    def delete(self, owner: str, agent_id: int) -> None:
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM agents WHERE owner = ? AND id = ?", (owner, agent_id)
            )
            if cursor.rowcount == 0:
                raise UnknownAgentError(str(agent_id))


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        connect(self.db_path).close()

    def create(
        self,
        agent_id: int,
        owner: str,
        job_type: str,
        payload: dict | None = None,
        *,
        project: str | None = None,
    ) -> Job:
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO jobs (agent_id, owner, project, type, payload, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    agent_id,
                    owner,
                    project,
                    job_type,
                    conn.seal("jobs", "payload", (owner,), json.dumps(payload or {})),
                    JOB_QUEUED,
                    _stamp(),
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _job(conn, row)

    def claim_next(self, agent_id: int) -> Job | None:
        """Hand the agent its oldest queued job, marking it running."""
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE agent_id = ? AND status = ? ORDER BY id LIMIT 1",
                (agent_id, JOB_QUEUED),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = ?, started_at = ? WHERE id = ? AND status = ?",
                (JOB_RUNNING, _stamp(), row["id"], JOB_QUEUED),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        return _job(conn, claimed)

    def finish(self, agent_id: int, job_id: int, *, status: str, result: dict | None) -> Job:
        if status not in {JOB_DONE, JOB_FAILED}:
            raise ValueError(f"invalid terminal status: {status}")
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ? AND agent_id = ?", (job_id, agent_id)
            ).fetchone()
            if row is None:
                raise UnknownJobError(str(job_id))
            conn.execute(
                "UPDATE jobs SET status = ?, result = ?, finished_at = ?"
                " WHERE id = ? AND agent_id = ?",
                (
                    status,
                    conn.seal("jobs", "result", (row["owner"],), json.dumps(result or {})),
                    _stamp(),
                    job_id,
                    agent_id,
                ),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _job(conn, row)

    def list_for_agent(
        self, owner: str, agent_id: int, *, limit: int = 50, project: str | None = None
    ) -> list[Job]:
        query = "SELECT * FROM jobs WHERE owner = ? AND agent_id = ?"
        params: list[object] = [owner, agent_id]
        if project is None:
            query += " AND project IS NULL"
        else:
            query += " AND project = ?"
            params.append(project)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with connect(self.db_path) as conn:
            return [_job(conn, row) for row in conn.execute(query, params).fetchall()]

    def get(self, owner: str, job_id: int) -> Job | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE owner = ? AND id = ?", (owner, job_id)
            ).fetchone()
        return _job(conn, row) if row else None

    def queued_count(self, agent_id: int) -> int:
        with connect(self.db_path) as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM jobs WHERE agent_id = ? AND status = ?",
                    (agent_id, JOB_QUEUED),
                ).fetchone()["n"]
            )

    def reap_stale(self) -> int:
        """Fail jobs an agent claimed but never reported back on."""
        cutoff = (_now() - dt.timedelta(minutes=JOB_STALE_MINUTES)).isoformat(timespec="seconds")
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, result = ?"
                " WHERE status = ? AND started_at < ?",
                (
                    JOB_FAILED,
                    _stamp(),
                    json.dumps({"error": "agent never reported back"}),
                    JOB_RUNNING,
                    cutoff,
                ),
            )
            return cursor.rowcount
