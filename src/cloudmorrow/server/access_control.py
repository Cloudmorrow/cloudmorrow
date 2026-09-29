"""The control server, and what this cloud is to it.

A public or private name is a record at a control server (`access_control`
in the config, `https://relay.cloudmorrow.com` unless somebody runs their
own relay repository): the box claims a name once, `POST /v1/clouds`, and
gets back an id and a token. The token is the cloud's only credential
there, so it is kept sealed, under the same key as everything else a
person writes (`sealed.SEALED`, version 4), and never leaves the box except
in the `Authorization` header of a `/v1` call and the tunnel's first line.

This module is the two halves of that: `AccessStore`, the one row the
database keeps about it, and `Control`, the calls. Neither decides
anything; `access_ways.Access` does, and the routes and the server's CLI
go through it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from cloudmorrow.server.db import connect

TABLE = """
CREATE TABLE IF NOT EXISTS access_cloud (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    cloud_id      TEXT NOT NULL,
    token         TEXT NOT NULL,
    name          TEXT NOT NULL,
    zone          TEXT NOT NULL,
    public_host   TEXT NOT NULL DEFAULT '',
    relay_host    TEXT NOT NULL DEFAULT '',
    login_server  TEXT NOT NULL DEFAULT '',
    public        INTEGER NOT NULL DEFAULT 0,
    private       INTEGER NOT NULL DEFAULT 0,
    mesh_address  TEXT NOT NULL DEFAULT '',
    acme          TEXT,
    control       TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL
);
"""

# What the control server accepts as a name, so a typo is refused here
# with the same sentence rather than a round trip later.
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class ControlError(RuntimeError):
    """The control server said no, or could not be reached. The message is its sentence."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalise_name(name: str) -> str:
    """The label a person typed, as the control server wants it: `Larsens` → `larsens`."""
    cleaned = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not NAME_RE.match(cleaned):
        raise ControlError("a name is 3 to 40 letters, digits or dashes, like larsens", 400)
    return cleaned


def suggest_name(cloud_name: str) -> str:
    """A first guess at a name from what the cloud is called: "The Larsens" → `the-larsens`."""
    try:
        return normalise_name(cloud_name)[:40].strip("-")
    except ControlError:
        return "my-cloud"


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


@dataclass(slots=True)
class Cloud:
    """This cloud's record at the control server, as the box remembers it."""

    cloud_id: str
    token: str
    name: str
    zone: str
    public_host: str = ""
    relay_host: str = ""
    login_server: str = ""
    public: bool = False
    private: bool = False
    mesh_address: str = ""
    # The acme-dns account Caddy renews a private-only certificate through.
    acme: dict[str, Any] | None = None
    # Which control server this record is at: a record from another one is
    # not used against this one after `access_control` changes.
    control: str = ""
    updated_at: str = field(default_factory=_now)

    @property
    def host(self) -> str:
        """The cloud's real name: `larsens.cloudmorrow.com`."""
        return self.public_host or f"{self.name}.{self.zone}"

    @property
    def reachable(self) -> bool:
        """Whether the name is in use: public or private, it has a certificate."""
        return self.public or self.private


class AccessStore:
    """One row: the cloud's record, the token and the acme account sealed."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with self._connect() as conn:
            conn.executescript(TABLE)
        conn.close()

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

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
            public_host=row["public_host"],
            relay_host=row["relay_host"],
            login_server=row["login_server"],
            public=bool(row["public"]),
            private=bool(row["private"]),
            mesh_address=row["mesh_address"],
            acme=json.loads(acme) if acme else None,
            control=row["control"],
            updated_at=row["updated_at"],
        )

    def save(self, cloud: Cloud) -> Cloud:
        cloud.updated_at = _now()
        with self._connect() as conn:
            scope = (cloud.cloud_id,)
            conn.execute(
                "INSERT OR REPLACE INTO access_cloud (id, cloud_id, token, name, zone,"
                " public_host, relay_host, login_server, public, private, mesh_address,"
                " acme, control, updated_at) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cloud.cloud_id,
                    conn.seal("access_cloud", "token", scope, cloud.token),
                    cloud.name,
                    cloud.zone,
                    cloud.public_host,
                    cloud.relay_host,
                    cloud.login_server,
                    int(cloud.public),
                    int(cloud.private),
                    cloud.mesh_address,
                    conn.seal(
                        "access_cloud", "acme", scope,
                        json.dumps(cloud.acme) if cloud.acme else None,
                    ),
                    cloud.control,
                    cloud.updated_at,
                ),
            )
        conn.close()
        return cloud

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM access_cloud")
        conn.close()


class Control:
    """The `/v1` calls, one method each. Synchronous: routes run them on a worker thread.

    *http* is for tests, which hand in a client wired to a fake control
    server; left out, a real one is made for *base_url*.
    """

    def __init__(
        self, base_url: str, token: str = "", http: httpx.Client | None = None
    ) -> None:
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
            self._http = httpx.Client(
                timeout=TIMEOUT, headers={"User-Agent": "cloudmorrow-server"}
            )
        return self._http

    def _call(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if auth and self.token else {}
        try:
            response = self._client().request(
                method, self.base_url + path, headers=headers, **kwargs
            )
        except httpx.HTTPError as exc:
            raise ControlError(f"cannot reach {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            if isinstance(detail, list):
                # A 422 from a FastAPI control server: its sentences, joined.
                detail = "; ".join(
                    str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                    for item in detail
                )
            if not isinstance(detail, str) or not detail:
                detail = f"{self.base_url} answered {response.status_code}"
            raise ControlError(detail, response.status_code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ControlError(f"{self.base_url} did not answer in JSON") from exc

    # -- the cloud ------------------------------------------------------------
    def claim(self, name: str, public: bool = True) -> dict:
        """`POST /v1/clouds`: the name, an id and a token."""
        return self._call(
            "POST", "/v1/clouds", auth=False, json={"name": name, "public": public}
        )

    def me(self) -> dict:
        return self._call("GET", "/v1/clouds/me")

    def update(self, **fields: Any) -> dict:
        """`PATCH /v1/clouds/me`: `name=` to rename, `public=` to turn it on or off."""
        return self._call("PATCH", "/v1/clouds/me", json=fields)

    def release(self) -> None:
        self._call("DELETE", "/v1/clouds/me")

    # -- the mesh -------------------------------------------------------------
    def mesh_key(
        self, label: str, owner: str = "", *, ephemeral: bool = False, expires_in: int = 600
    ) -> dict:
        body: dict[str, Any] = {"for": label, "ephemeral": ephemeral, "expires_in": expires_in}
        if owner:
            body["owner"] = owner
        return self._call("POST", "/v1/clouds/me/mesh/keys", json=body)

    def pair(self, label: str, owner: str = "") -> dict:
        body: dict[str, Any] = {"for": label}
        if owner:
            body["owner"] = owner
        return self._call("POST", "/v1/clouds/me/mesh/pair", json=body)

    def devices(self) -> list[dict]:
        answer = self._call("GET", "/v1/clouds/me/mesh/devices")
        # A bare list, or wrapped: either is read.
        if isinstance(answer, dict):
            answer = answer.get("devices", [])
        return [d for d in answer if isinstance(d, dict)]

    def remove_device(self, device_id: str) -> None:
        self._call("DELETE", f"/v1/clouds/me/mesh/devices/{device_id}")

    def report_address(self, address: str) -> None:
        self._call("PUT", "/v1/clouds/me/mesh/address", json={"address": address})

    def acme_register(self) -> dict:
        """acme-dns credentials for this cloud's `_acme-challenge` record."""
        return self._call("POST", "/v1/acme-dns/register")


def cloud_from_claim(answer: dict, control: str, public: bool) -> Cloud:
    """The record kept after a claim, from what the control server answered."""
    try:
        return Cloud(
            cloud_id=str(answer["cloud_id"]),
            token=str(answer["token"]),
            name=str(answer["name"]),
            zone=str(answer["zone"]),
            public_host=str(answer.get("public_host") or ""),
            relay_host=str(answer.get("relay_host") or ""),
            login_server=str(answer.get("login_server") or ""),
            public=public,
            control=control,
        )
    except KeyError as exc:
        raise ControlError(f"the control server's answer has no {exc.args[0]}") from exc


def public_view(cloud: Cloud | None) -> dict:
    """The record without its secrets, for status screens and logs."""
    if cloud is None:
        return {}
    data = asdict(cloud)
    data.pop("token", None)
    data["acme"] = bool(cloud.acme)
    data["host"] = cloud.host
    return data
