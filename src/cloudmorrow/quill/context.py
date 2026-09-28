"""`ctx`: everything a handler can reach, and nothing else.

    ctx.user            who it runs for: .username, .name, .admin, .circles
    ctx.quill           this Quill's id
    ctx.params          a view's parameters; .record when opened on one
    ctx.records         list, get, create, patch, move, delete — through the gate
    ctx.fetch(url)      HTTP, to a host the manifest lists in [[fetch]] only
    ctx.secret(key)     a secret the manifest lists in [[secrets]], from the person's vault
    ctx.now()           the time, as an aware datetime in UTC
    ctx.log(...)        a line in the Quill's log
    ctx.folder(name)    on a machine: a folder the person picked, as a Path
    ctx.run([...])      on a machine: a program the manifest lists, if the machine allows it

Each of these is a request to the host — the core on a server, the agent on
a machine, the harness in a test — which answers it or refuses it. A refusal
arrives as an exception: `Refused` (the gate said no), `NotFound`, `Invalid`
(a field the datamodel will not take), `Conflict` (changed since it was read).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from collections.abc import Callable, Iterator, Mapping
from pathlib import PurePosixPath


class HostError(Exception):
    """The host said no. Subclassed by what kind of no."""


class Refused(HostError, PermissionError):
    """The gate refused: a datamodel not declared, or not the person's to change."""


class NotFound(HostError, LookupError):
    """No such record, datamodel, secret or folder."""


class Invalid(HostError, ValueError):
    """A value the datamodel will not take, or a request that makes no sense."""


class Conflict(HostError):
    """The record changed since it was read."""


ERRORS: dict[str, type[HostError]] = {
    "refused": Refused,
    "notfound": NotFound,
    "invalid": Invalid,
    "conflict": Conflict,
}

Host = Callable[[str, dict], object]


# -- a record ----------------------------------------------------------------------
class Record(Mapping):
    """One record: its fields by name, and its envelope as attributes.

    `van["name"]`, `van.get("fleet.odometer")`, `van.id`, `van.rev`.
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict) -> None:
        self._data = data

    # the fields
    def __getitem__(self, name: str):
        return self._data.get("fields", {})[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data.get("fields", {}))

    def __len__(self) -> int:
        return len(self._data.get("fields", {}))

    # the envelope
    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def model(self) -> str:
        return self._data["model"]

    @property
    def fields(self) -> dict:
        return dict(self._data.get("fields", {}))

    @property
    def owner(self) -> str:
        return self._data.get("owner", "")

    @property
    def rev(self):
        return self._data.get("rev")

    @property
    def scope(self) -> str:
        return self._data.get("scope", "")

    @property
    def position(self) -> int:
        return self._data.get("position", 0)

    @property
    def created_at(self) -> str:
        return self._data.get("created_at", "")

    @property
    def updated_at(self) -> str:
        return self._data.get("updated_at", "")

    def to_dict(self) -> dict:
        return dict(self._data)

    def __eq__(self, other) -> bool:
        return isinstance(other, Record) and other._data == self._data

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"Record({self.model} {self.id} {self.fields!r})"


def _fields(fields: dict | None, extra: dict) -> dict:
    merged = dict(fields or {})
    merged.update(extra)
    return merged


class Records:
    """The record API, as the handler's principal: the same calls, the same rules."""

    def __init__(self, host: Host) -> None:
        self._host = host

    def list(self, model: str, *, q: str | None = None, last: int | None = None, **where) -> list[Record]:
        """Records of *model*, in order; `lane="done"`, `due__gte="2026-10-01"` filter."""
        args: dict = {"model": model, "where": {k: _plain(v) for k, v in where.items()}}
        if q:
            args["q"] = q
        if last:
            args["last"] = int(last)
        return [Record(r) for r in self._host("records.list", args)]

    def get(self, model: str, id: str) -> Record:  # noqa: A002
        return Record(self._host("records.get", {"model": model, "id": _plain(id)}))

    def create(self, model: str, fields: dict | None = None, *, index: int | None = None, **values) -> Record:
        """A new record. Fields as keywords, or a dict for names with a dot in them."""
        args = {"model": model, "fields": _plain(_fields(fields, values))}
        if index is not None:
            args["index"] = index
        return Record(self._host("records.create", args))

    def patch(self, model: str, id: str, fields: dict | None = None, *, rev=None, **values) -> Record:  # noqa: A002
        args = {"model": model, "id": _plain(id), "fields": _plain(_fields(fields, values))}
        if rev is not None:
            args["rev"] = rev
        return Record(self._host("records.patch", args))

    def move(self, model: str, id: str, fields: dict | None = None, *, index: int | None = None, **values) -> Record:  # noqa: A002
        return Record(
            self._host(
                "records.move",
                {"model": model, "id": _plain(id), "fields": _plain(_fields(fields, values)), "index": index},
            )
        )

    def delete(self, model: str, id: str) -> int:  # noqa: A002
        return int(self._host("records.delete", {"model": model, "id": _plain(id)}))


# -- HTTP ----------------------------------------------------------------------------
class Response:
    """What `ctx.fetch` got back."""

    def __init__(self, data: dict) -> None:
        self.status: int = data["status"]
        self.headers: dict[str, str] = dict(data.get("headers", {}))
        self.content: bytes = base64.b64decode(data.get("body", ""))

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content or b"null")

    def __repr__(self) -> str:
        return f"Response({self.status})"


class Request:
    """What a webhook or an API handler is given: the request someone sent."""

    def __init__(self, data: dict) -> None:
        self.method: str = data.get("method", "POST")
        self.path: str = data.get("path", "")
        self.query: dict[str, str] = dict(data.get("query", {}))
        self.headers: dict[str, str] = {k.lower(): v for k, v in data.get("headers", {}).items()}
        self.body: bytes = base64.b64decode(data.get("body", ""))
        # Who is asking, for an API: a username, or "" for a webhook.
        self.user: str = data.get("user", "")

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.body or b"null")


class User:
    def __init__(self, data: dict) -> None:
        self.username: str = data.get("username", "")
        self.name: str = data.get("name", "") or self.username
        self.admin: bool = bool(data.get("admin", False))
        self.circles: list[str] = list(data.get("circles", []))

    def __repr__(self) -> str:
        return f"User({self.username})"


class Params(dict):
    """A view's parameters, by name; `.record` is the record it was opened on, if any."""

    record: Record | None = None

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


# -- the context ---------------------------------------------------------------------
class Context:
    def __init__(self, host: Host, data: dict) -> None:
        self._host = host
        self.quill: str = data.get("quill", "")
        self.user = User(data.get("user", {}))
        self.params = Params(data.get("params", {}))
        if data.get("record"):
            self.params.record = Record(data["record"])
        self.records = Records(host)
        # Where it runs: "server", or "machine" in an agent.
        self.where: str = data.get("where", "server")
        self._folders: dict[str, str] = dict(data.get("folders", {}))

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict | None = None,
        body: bytes | str | None = None,
        json: object = None,  # noqa: A002
        timeout: float = 20.0,
    ) -> Response:
        """An HTTP request, to a host the manifest lists in [[fetch]]; anything else is Refused."""
        head = dict(headers or {})
        if json is not None:
            import json as _json

            body = _json.dumps(json)
            head.setdefault("Content-Type", "application/json")
        if isinstance(body, str):
            body = body.encode("utf-8")
        return Response(
            self._host(
                "fetch",
                {
                    "url": url,
                    "method": method.upper(),
                    "headers": head,
                    "body": base64.b64encode(body or b"").decode("ascii"),
                    "timeout": float(timeout),
                },
            )
        )

    def secret(self, key: str) -> str:
        """A secret the manifest names in [[secrets]], from the person's own vault."""
        return str(self._host("secret", {"key": key}))

    def now(self) -> dt.datetime:
        return dt.datetime.fromisoformat(str(self._host("now", {})))

    def log(self, *parts) -> None:
        self._host("log", {"line": " ".join(str(p) for p in parts)})

    # -- on a machine --------------------------------------------------------------
    def folder(self, name: str) -> PurePosixPath:
        """A folder the person picked for this handler on this machine."""
        if name not in self._folders:
            known = ", ".join(self._folders) or "none"
            raise NotFound(f"no folder called {name!r} here; this handler has {known}")
        from pathlib import Path

        return Path(self._folders[name])

    def run(self, command: list[str], *, input: str = "", timeout: float = 60.0) -> dict:  # noqa: A002
        """Start a program the manifest lists, on the machine: {code, out, err}."""
        return dict(self._host("run", {"command": list(command), "input": input, "timeout": timeout}))


def _plain(value):
    if isinstance(value, Record):
        return value.id
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value
