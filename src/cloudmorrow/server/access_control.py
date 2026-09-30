"""The relay, and what this cloud is to it.

A linked cloud is a record at the relay (`access_control` in the config,
`https://relay.cloudmorrow.tech` unless somebody runs their own relay
repository). The box never picks its own name: it asks the relay for a
link code (`POST /v1/links`), a person enters the code on the website and
picks the name there, and the box's poll (`POST /v1/links/poll`) gets back
an id, a token, the name and the acme-dns account for its certificate. The
token is the cloud's only credential at the relay, so it is kept sealed,
under the same key as everything else a person writes (`sealed.SEALED`,
version 4), and never leaves the box except in the `Authorization` header
of a `/v1` call.

Nothing about the cloud's people goes to the relay: no username, no label,
no device name. The calls below have no field to carry one.

This module is the two halves of that: `AccessStore`, the rows the database
keeps (the cloud's record, and a link code still waiting for a person), and
`Control`, the calls. Neither decides anything; `access_ways.Access` does,
and the routes and the server's CLI go through it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from cloudmorrow.server.db import connect

TABLES = """
CREATE TABLE IF NOT EXISTS access_cloud (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    cloud_id      TEXT NOT NULL,
    token         TEXT NOT NULL,
    name          TEXT NOT NULL,
    zone          TEXT NOT NULL,
    login_server  TEXT NOT NULL DEFAULT '',
    mesh_address  TEXT NOT NULL DEFAULT '',
    acme          TEXT,
    control       TEXT NOT NULL DEFAULT '',
    set_up        INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_link (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    code          TEXT NOT NULL,
    poll          TEXT NOT NULL,
    url           TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    interval      INTEGER NOT NULL DEFAULT 5,
    control       TEXT NOT NULL DEFAULT ''
);
"""

# What the relay accepts as a name (the website checks it too, and reserved
# names are the relay's to know). The core only displays a name, but it
# writes it into Caddy's config, so anything else is refused.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{3,38}[a-z0-9]$")
ZONE_RE = re.compile(r"^(?=.{1,200}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ControlError(RuntimeError):
    """The relay said no, or could not be reached. The message is its sentence."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def valid_name(name: str) -> bool:
    """5–40 of `a-z 0-9 -`, not starting or ending with `-`, and no `--`."""
    return bool(NAME_RE.match(name or "")) and "--" not in name


def valid_zone(zone: str) -> bool:
    return bool(ZONE_RE.match(zone or ""))


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _stamp() -> str:
    return _now().isoformat(timespec="seconds")


@dataclass(slots=True)
class Cloud:
    """This cloud's record at the relay, as the box remembers it."""

    cloud_id: str
    token: str
    name: str
    zone: str
    login_server: str = ""
    mesh_address: str = ""
    # The acme-dns account Caddy gets the certificate through: the link's
    # `acme_dns` answer (username, password, subdomain, server_url).
    acme: dict[str, Any] | None = None
    # Which relay this record is at.
    control: str = ""
    # Linked, and then on the mesh with Caddy holding the site: False until
    # that has worked once, so a box restarted halfway finishes it.
    set_up: bool = False
    updated_at: str = field(default_factory=_stamp)

    @property
    def host(self) -> str:
        """The cloud's real name: `larsens.cloudmorrow.tech`."""
        return f"{self.name}.{self.zone}"


@dataclass(slots=True)
class PendingLink:
    """A link code shown to a person and not yet entered: what the box polls with."""

    code: str
    poll: str
    url: str
    expires_at: str
    interval: int = 5
    control: str = ""

    @property
    def link(self) -> str:
        """The page with the code filled in, for a click or a QR code."""
        joiner = "&" if "?" in self.url else "?"
        return f"{self.url}{joiner}code={self.code}"

    @property
    def expired(self) -> bool:
        try:
            when = dt.datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        return when <= _now()

    def shown(self) -> dict:
        """What a screen shows: never the poll secret."""
        return {
            "code": self.code,
            "url": self.url,
            "link": self.link,
            "expires_at": self.expires_at,
            # "cloudmorrow.com/link", for the sentence that says where to go.
            "place": self.url.split("://", 1)[-1].rstrip("/"),
        }


class AccessStore:
    """Two one-row tables: the cloud's record, and a link code waiting to be entered."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(TABLES)
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # -- the cloud ----------------------------------------------------------------
    def get(self) -> Cloud | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM access_cloud WHERE id = 1").fetchone()
            if row is None:
                return None
            scope = (row["cloud_id"],)
            token = conn.unseal("access_cloud", "token", scope, row["token"]) or ""
            acme = conn.unseal("access_cloud", "acme", scope, row["acme"])
        finally:
            conn.close()
        return Cloud(
            cloud_id=row["cloud_id"],
            token=token,
            name=row["name"],
            zone=row["zone"],
            login_server=row["login_server"],
            mesh_address=row["mesh_address"],
            acme=json.loads(acme) if acme else None,
            control=row["control"],
            set_up=bool(row["set_up"]),
            updated_at=row["updated_at"],
        )

    def save(self, cloud: Cloud) -> Cloud:
        cloud.updated_at = _stamp()
        with self._connect() as conn:
            scope = (cloud.cloud_id,)
            conn.execute(
                "INSERT OR REPLACE INTO access_cloud (id, cloud_id, token, name, zone,"
                " login_server, mesh_address, acme, control, set_up, updated_at)"
                " VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cloud.cloud_id,
                    conn.seal("access_cloud", "token", scope, cloud.token),
                    cloud.name,
                    cloud.zone,
                    cloud.login_server,
                    cloud.mesh_address,
                    conn.seal("access_cloud", "acme", scope, json.dumps(cloud.acme) if cloud.acme else None),
                    cloud.control,
                    int(cloud.set_up),
                    cloud.updated_at,
                ),
            )
        conn.close()
        return cloud

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM access_cloud")
        conn.close()

    # -- a link code on its way -----------------------------------------------------
    def pending(self) -> PendingLink | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM access_link WHERE id = 1").fetchone()
            if row is None:
                return None
            poll = conn.unseal("access_link", "poll", (row["code"],), row["poll"]) or ""
        finally:
            conn.close()
        return PendingLink(
            code=row["code"],
            poll=poll,
            url=row["url"],
            expires_at=row["expires_at"],
            interval=int(row["interval"]),
            control=row["control"],
        )

    def save_pending(self, link: PendingLink) -> PendingLink:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO access_link (id, code, poll, url, expires_at, interval, control)"
                " VALUES (1, ?, ?, ?, ?, ?, ?)",
                (
                    link.code,
                    conn.seal("access_link", "poll", (link.code,), link.poll),
                    link.url,
                    link.expires_at,
                    link.interval,
                    link.control,
                ),
            )
        conn.close()
        return link

    def clear_pending(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM access_link")
        conn.close()


class Control:
    """The `/v1` calls, one method each. Synchronous: routes run them on a worker thread.

    *http* is for tests, which hand in a client wired to a fake relay; left
    out, a real one is made for *base_url*.
    """

    def __init__(self, base_url: str, token: str = "", http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = http
        self._own = http is None

    def __enter__(self) -> Control:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._own and self._http is not None:
            self._http.close()
            self._http = None

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "cloudmorrow-server"})
        return self._http

    def _send(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"} if auth and self.token else {}
        try:
            response = self._client().request(method, self.base_url + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ControlError(f"cannot reach {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if isinstance(detail, list):
                # A 422 from a FastAPI relay: its sentences, joined.
                detail = "; ".join(
                    str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in detail
                )
            if not isinstance(detail, str) or not detail:
                detail = f"{self.base_url} answered {response.status_code}"
            raise ControlError(detail, response.status_code)
        return response

    def _call(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        return _json(self._send(method, path, auth=auth, **kwargs), self.base_url)

    # -- linking ----------------------------------------------------------------------
    def start_link(self) -> dict:
        """`POST /v1/links`, no token and nothing in the body: a code for a person to enter."""
        return self._call("POST", "/v1/links", auth=False)

    def poll_link(self, poll: str) -> dict | None:
        """`POST /v1/links/poll`: None while nobody has entered the code, the link once they have.

        ControlError with 410 when it expired or the person said no.
        """
        response = self._send("POST", "/v1/links/poll", auth=False, json={"poll": poll})
        if response.status_code == 202:
            return None
        return _json(response, self.base_url)

    # -- the cloud ----------------------------------------------------------------------
    def me(self) -> dict:
        """`GET /v1/clouds/me`: {cloud_id, name, zone, mesh_address, login_server, public, relay_addresses}."""
        return self._call("GET", "/v1/clouds/me")

    def set_public(self, public: bool) -> dict:
        """`PATCH /v1/clouds/me {public}`: whether the relay passes visitors through to the box."""
        return self._call("PATCH", "/v1/clouds/me", json={"public": public})

    def unlink(self) -> None:
        self._call("DELETE", "/v1/clouds/me")

    # -- the mesh -------------------------------------------------------------------------
    def mesh_key(self, *, ephemeral: bool = False, expires_in: int = 600) -> dict:
        """A one-time pre-auth key. Whose device it is for is the box's to know, not the relay's."""
        return self._call("POST", "/v1/clouds/me/mesh/keys", json={"ephemeral": ephemeral, "expires_in": expires_in})

    def invite(self) -> dict:
        """An invite code: six characters, ten minutes, once. {code, expires_at, login_server}."""
        return self._call("POST", "/v1/clouds/me/mesh/invites")

    def devices(self) -> list[dict]:
        """The devices on the mesh: {id, address, online, last_seen}, nothing about whose."""
        answer = self._call("GET", "/v1/clouds/me/mesh/devices")
        # A bare list, or wrapped: either is read.
        if isinstance(answer, dict):
            answer = answer.get("devices", [])
        return [d for d in answer if isinstance(d, dict)]

    def remove_device(self, device_id: str) -> None:
        self._call("DELETE", f"/v1/clouds/me/mesh/devices/{device_id}")


def _json(response: httpx.Response, base_url: str) -> Any:
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise ControlError(f"{base_url} did not answer in JSON") from exc


def pending_from(answer: dict, control: str) -> PendingLink:
    """What is kept while a link code waits, from what `POST /v1/links` answered."""
    try:
        return PendingLink(
            code=str(answer["code"]),
            poll=str(answer["poll"]),
            url=str(answer.get("url") or "https://cloudmorrow.com/link"),
            expires_at=str(answer.get("expires_at") or ""),
            interval=max(1, min(60, int(answer.get("interval") or 5))),
            control=control,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ControlError(f"the relay's link answer is missing {exc}") from exc


def cloud_from_link(answer: dict, control: str) -> Cloud:
    """The record kept once a person entered the code, from the poll's 200."""
    try:
        cloud = Cloud(
            cloud_id=str(answer["cloud_id"]),
            token=str(answer["token"]),
            name=str(answer["name"]),
            zone=str(answer["zone"]),
            login_server=str(answer.get("login_server") or ""),
            acme=answer.get("acme_dns") if isinstance(answer.get("acme_dns"), dict) else None,
            control=control,
        )
    except KeyError as exc:
        raise ControlError(f"the relay's answer has no {exc.args[0]}") from exc
    if not valid_name(cloud.name) or not valid_zone(cloud.zone):
        raise ControlError(f"the relay named this cloud {cloud.name}.{cloud.zone}, which is not a usable name")
    return cloud
