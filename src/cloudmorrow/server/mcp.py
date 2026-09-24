"""Letting an assistant in as you: the OAuth side of the MCP server.

Claude — on the desktop, on the web, in the terminal — speaks MCP to a
server it reaches over HTTPS, and signs in to it the way OAuth 2.1 says:
it registers itself as a client, sends you to the server's own page to
sign in and say yes, and trades the code it gets back for a token. That
token is what it carries afterwards, and this module is the bookkeeping
behind it — the clients that registered, the codes that were handed out
and not yet redeemed, and the tokens that are live.

None of the JWTs the app signs for its own clients come near this. An MCP
token is a random string, kept as a hash, that opens `/mcp` and nothing
else; the person can see every one of theirs and cut it off, which a
signed token could not offer. And a code is good once, for ten minutes,
and only to the client that proves — with the PKCE verifier — that it is
the one that asked.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cloudmorrow.server.db import connect

TABLES = """
CREATE TABLE IF NOT EXISTS mcp_clients (
    -- A client that registered itself, and what it said it was.
    client_id          TEXT PRIMARY KEY,
    -- Empty for a public client: one that cannot keep a secret, which is
    -- what every assistant is. Such a client proves itself with PKCE.
    client_secret_hash TEXT NOT NULL DEFAULT '',
    client_name        TEXT NOT NULL DEFAULT '',
    -- Where a code may be sent back to, as a JSON list. Anything else is
    -- refused: a code that lands on the wrong page is a token for whoever
    -- runs that page.
    redirect_uris      TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_codes (
    -- One authorization code, from the moment somebody said yes until the
    -- client redeems it. Kept hashed: the row is a token in waiting.
    code_hash             TEXT PRIMARY KEY,
    client_id             TEXT NOT NULL,
    username              TEXT NOT NULL,
    redirect_uri          TEXT NOT NULL,
    code_challenge        TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL,
    scope                 TEXT NOT NULL DEFAULT '',
    expires_at            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_tokens (
    -- One connection: a client that somebody let in, and the tokens it
    -- holds now. Refreshing rotates the tokens and keeps the row, so the
    -- row is the thing to show as "connected" and the thing to revoke.
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    username           TEXT NOT NULL,
    client_id          TEXT NOT NULL,
    scope              TEXT NOT NULL DEFAULT '',
    access_hash        TEXT NOT NULL UNIQUE,
    access_expires_at  TEXT NOT NULL,
    refresh_hash       TEXT NOT NULL UNIQUE,
    refresh_expires_at TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    last_used_at       TEXT NOT NULL DEFAULT ''
);
"""

# A code is meant to be redeemed at once; ten minutes is generous.
CODE_TTL = dt.timedelta(minutes=10)
# An access token is what every call carries, so it is short-lived; the
# refresh token behind it is what keeps a connection alive for as long as
# it is used — and it dies of neglect after this long.
ACCESS_TTL = dt.timedelta(hours=24)
REFRESH_TTL = dt.timedelta(days=90)

# The one scope there is: everything the person can do themselves.
SCOPE = "cloudmorrow"

LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class RegistrationError(ValueError):
    """A client asked to register with something the server will not have."""


class GrantError(Exception):
    """A code or token exchange that cannot go ahead. `error` is the OAuth word."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


@dataclass(frozen=True, slots=True)
class Client:
    client_id: str
    client_name: str
    redirect_uris: tuple[str, ...]
    # True when the client was given a secret and must present it.
    confidential: bool
    created_at: str

    def allows_redirect(self, uri: str) -> bool:
        """Is *uri* one the client registered?

        Exactly, or — for a loopback address, which a desktop app binds to
        whatever port is free — the same address on any port, as RFC 8252
        allows.
        """
        if uri in self.redirect_uris:
            return True
        given = urlsplit(uri)
        if given.scheme != "http" or given.hostname not in LOOPBACK_HOSTS:
            return False
        for registered in self.redirect_uris:
            known = urlsplit(registered)
            if (
                known.scheme == "http"
                and known.hostname == given.hostname
                and known.path == given.path
                and known.query == given.query
            ):
                return True
        return False


@dataclass(frozen=True, slots=True)
class Tokens:
    """What the token endpoint hands back."""

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


@dataclass(frozen=True, slots=True)
class Connection:
    """One client somebody let in, as the person sees it."""

    id: int
    username: str
    client_id: str
    client_name: str
    scope: str
    created_at: str
    last_used_at: str
    # When the refresh token runs out: the connection's own end, unless it
    # is refreshed before then.
    expires_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "scope": self.scope,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
        }


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _stamp(moment: dt.datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _expired(stamp: str) -> bool:
    return dt.datetime.fromisoformat(stamp) <= _now()


def validate_redirect_uri(uri: str) -> str:
    """A place a code may be sent: https, a loopback http address, or an
    app's own scheme. Plain http to anywhere else is a code on the wire."""
    uri = (uri or "").strip()
    parts = urlsplit(uri)
    if not parts.scheme or parts.fragment:
        raise RegistrationError(f"not a usable redirect URI: {uri!r}")
    if parts.scheme == "https" and parts.netloc:
        return uri
    if parts.scheme == "http":
        if parts.hostname in LOOPBACK_HOSTS:
            return uri
        raise RegistrationError(f"a redirect over plain http must be to localhost: {uri!r}")
    if parts.scheme in {"javascript", "data", "file"}:
        raise RegistrationError(f"not a usable redirect URI: {uri!r}")
    # A private-use scheme: what a desktop app registers with the OS.
    return uri


def pkce_matches(verifier: str, challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return secrets.compare_digest(expected, challenge)
    if method == "plain":
        return secrets.compare_digest(verifier, challenge)
    return False


class MCPStore:
    """The clients, codes and tokens behind the MCP server."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(TABLES)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # -- clients -----------------------------------------------------------
    def register(
        self, name: str, redirect_uris: list[str], *, public: bool = True
    ) -> tuple[Client, str]:
        """Take a client on. Returns it and its secret — empty for a public one."""
        if not redirect_uris:
            raise RegistrationError("at least one redirect_uri is required")
        uris = tuple(dict.fromkeys(validate_redirect_uri(uri) for uri in redirect_uris))
        client_id = secrets.token_urlsafe(24)
        secret = "" if public else secrets.token_urlsafe(32)
        now = _stamp()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mcp_clients (client_id, client_secret_hash, client_name,"
                " redirect_uris, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    client_id,
                    _hash(secret) if secret else "",
                    name.strip()[:200],
                    json.dumps(uris),
                    now,
                ),
            )
        return Client(client_id, name.strip()[:200], uris, not public, now), secret

    def client(self, client_id: str) -> Client | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_clients WHERE client_id = ?", (client_id or "",)
            ).fetchone()
        return self._client(row) if row else None

    @staticmethod
    def _client(row: sqlite3.Row) -> Client:
        return Client(
            client_id=row["client_id"],
            client_name=row["client_name"],
            redirect_uris=tuple(json.loads(row["redirect_uris"])),
            confidential=bool(row["client_secret_hash"]),
            created_at=row["created_at"],
        )

    def authenticate_client(self, client_id: str, client_secret: str | None) -> Client:
        """The client behind a token request, or a GrantError."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_clients WHERE client_id = ?", (client_id or "",)
            ).fetchone()
        if row is None:
            raise GrantError("invalid_client", "unknown client")
        expected = row["client_secret_hash"]
        if expected and not (
            client_secret and secrets.compare_digest(_hash(client_secret), expected)
        ):
            raise GrantError("invalid_client", "wrong client secret")
        return self._client(row)

    # -- codes -------------------------------------------------------------
    def issue_code(
        self,
        client: Client,
        username: str,
        *,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        scope: str = SCOPE,
    ) -> str:
        code = secrets.token_urlsafe(32)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mcp_codes (code_hash, client_id, username, redirect_uri,"
                " code_challenge, code_challenge_method, scope, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _hash(code),
                    client.client_id,
                    username,
                    redirect_uri,
                    code_challenge,
                    code_challenge_method,
                    scope or SCOPE,
                    _stamp(_now() + CODE_TTL),
                ),
            )
        return code

    def redeem_code(
        self, client: Client, code: str, *, redirect_uri: str, code_verifier: str
    ) -> Tokens:
        """Trade a code for tokens, once. Anything wrong is a GrantError."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_codes WHERE code_hash = ?", (_hash(code or ""),)
            ).fetchone()
            if row is not None:
                # Whatever happens next, the code is spent.
                conn.execute("DELETE FROM mcp_codes WHERE code_hash = ?", (row["code_hash"],))
            conn.execute("DELETE FROM mcp_codes WHERE expires_at <= ?", (_stamp(),))
        if row is None or _expired(row["expires_at"]):
            raise GrantError("invalid_grant", "unknown or expired code")
        if row["client_id"] != client.client_id:
            raise GrantError("invalid_grant", "code was issued to another client")
        if redirect_uri and row["redirect_uri"] != redirect_uri:
            raise GrantError("invalid_grant", "redirect_uri does not match")
        if not code_verifier or not pkce_matches(
            code_verifier, row["code_challenge"], row["code_challenge_method"]
        ):
            raise GrantError("invalid_grant", "PKCE verification failed")
        return self._issue(row["username"], client.client_id, row["scope"])

    # -- tokens ------------------------------------------------------------
    def _issue(
        self, username: str, client_id: str, scope: str, *, row_id: int | None = None
    ) -> Tokens:
        access = "bcm_" + secrets.token_urlsafe(32)
        refresh = "bcr_" + secrets.token_urlsafe(32)
        now = _now()
        access_expires = now + ACCESS_TTL
        refresh_expires = now + REFRESH_TTL
        with self._connect() as conn:
            if row_id is None:
                conn.execute(
                    "INSERT INTO mcp_tokens (username, client_id, scope, access_hash,"
                    " access_expires_at, refresh_hash, refresh_expires_at, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        username,
                        client_id,
                        scope,
                        _hash(access),
                        _stamp(access_expires),
                        _hash(refresh),
                        _stamp(refresh_expires),
                        _stamp(now),
                    ),
                )
            else:
                conn.execute(
                    "UPDATE mcp_tokens SET access_hash = ?, access_expires_at = ?,"
                    " refresh_hash = ?, refresh_expires_at = ? WHERE id = ?",
                    (
                        _hash(access),
                        _stamp(access_expires),
                        _hash(refresh),
                        _stamp(refresh_expires),
                        row_id,
                    ),
                )
        return Tokens(access, refresh, int(ACCESS_TTL.total_seconds()), scope)

    def refresh(self, client: Client, refresh_token: str) -> Tokens:
        """New tokens for old. The old refresh token stops working."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mcp_tokens WHERE refresh_hash = ?", (_hash(refresh_token or ""),)
            ).fetchone()
        if row is None or _expired(row["refresh_expires_at"]):
            raise GrantError("invalid_grant", "unknown or expired refresh token")
        if row["client_id"] != client.client_id:
            raise GrantError("invalid_grant", "refresh token belongs to another client")
        return self._issue(row["username"], client.client_id, row["scope"], row_id=row["id"])

    def user_for(self, access_token: str) -> Connection | None:
        """Whose token this is, if it is anyone's — and note that it was used."""
        if not access_token.startswith("bcm_"):
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT t.*, c.client_name FROM mcp_tokens t"
                " LEFT JOIN mcp_clients c ON c.client_id = t.client_id"
                " WHERE t.access_hash = ?",
                (_hash(access_token),),
            ).fetchone()
            if row is None or _expired(row["access_expires_at"]):
                return None
            conn.execute(
                "UPDATE mcp_tokens SET last_used_at = ? WHERE id = ?", (_stamp(), row["id"])
            )
        return self._connection(row)

    @staticmethod
    def _connection(row: sqlite3.Row) -> Connection:
        return Connection(
            id=row["id"],
            username=row["username"],
            client_id=row["client_id"],
            client_name=row["client_name"] or "",
            scope=row["scope"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            expires_at=row["refresh_expires_at"],
        )

    def connections(self, username: str) -> list[Connection]:
        """Every client *username* has let in and not yet cut off."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM mcp_tokens WHERE refresh_expires_at <= ?", (_stamp(),)
            )
            rows = conn.execute(
                "SELECT t.*, c.client_name FROM mcp_tokens t"
                " LEFT JOIN mcp_clients c ON c.client_id = t.client_id"
                " WHERE t.username = ? ORDER BY t.created_at DESC, t.id DESC",
                (username,),
            ).fetchall()
        return [self._connection(row) for row in rows]

    def revoke(self, username: str, connection_id: int) -> bool:
        """Cut a connection off. Its tokens stop working at once."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM mcp_tokens WHERE username = ? AND id = ?",
                (username, connection_id),
            )
        return cursor.rowcount > 0

    def revoke_all(self, username: str) -> int:
        """Every connection *username* has, gone — for when the account goes."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM mcp_tokens WHERE username = ?", (username,))
        return cursor.rowcount
