"""Secrets: the person's own keys and passwords, encrypted at rest.

A secret is yours. It lives in a **vault** you name — `default` until you
name one; `home`, `work`, `verticore` — and in an **environment** inside it
(`local`, `production`, whatever you call it), which is what makes a `.env`
file a clean round trip in both directions. Within one vault and environment
a key appears exactly once.

Nothing else in Cloudmorrow owns a secret. An app may be *given* one, by
name, when the person says so; that is the guard's business, and it is the
reason secrets are part of the foundation rather than any one app's.

Values are sealed by `crypto`. Names, vaults, environments, lengths and
keyed fingerprints are stored in the clear, so listing, sorting and "did
this change?" all work without opening anything.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cloudmorrow.dotenv import DEFAULT_ENVIRONMENT, DEFAULT_VAULT, KEY_RE
from cloudmorrow.server.crypto import associated_data, fingerprint, seal, unseal
from cloudmorrow.server.db import connect

# Free-form, but a directory-safe, shell-safe token: it ends up in file names,
# command lines and URLs. A vault is the same shape as an environment.
ENVIRONMENT_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
VAULT_RE = ENVIRONMENT_RE

__all__ = [
    "DEFAULT_ENVIRONMENT",
    "DEFAULT_VAULT",
    "Environment",
    "ImportResult",
    "InvalidEnvironmentError",
    "InvalidSecretNameError",
    "InvalidVaultError",
    "Secret",
    "SecretStore",
    "UnknownSecretError",
    "Vault",
    "validate_environment",
    "validate_key",
    "validate_vault",
]


class InvalidEnvironmentError(ValueError):
    pass


class InvalidVaultError(ValueError):
    pass


class InvalidSecretNameError(ValueError):
    pass


class UnknownSecretError(LookupError):
    pass


@dataclass(slots=True)
class Secret:
    key: str
    environment: str
    vault: str
    length: int
    fingerprint: str
    created_at: str
    updated_at: str
    # Only filled in when the caller asked to reveal it.
    value: str | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "environment": self.environment,
            "vault": self.vault,
            "value": self.value,
            "length": self.length,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Vault:
    vault: str
    secrets: int
    environments: int
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "vault": self.vault,
            "secrets": self.secrets,
            "environments": self.environments,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Environment:
    environment: str
    secrets: int
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "secrets": self.secrets,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class ImportResult:
    """What an import did, or would do — the same shape either way."""

    environment: str
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed(self) -> int:
        return len(self.added) + len(self.updated) + len(self.removed)

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "added": self.added,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "removed": self.removed,
            "dry_run": self.dry_run,
        }


def validate_environment(environment: str) -> str:
    environment = (environment or "").strip().lower()
    if not ENVIRONMENT_RE.match(environment):
        raise InvalidEnvironmentError(
            "environment must be 1-32 chars of lowercase letters, digits, '.', '_' "
            "or '-', starting with a letter or digit"
        )
    return environment


def validate_vault(vault: str | None) -> str:
    """A vault name, or the default one when none was given."""
    vault = (vault or "").strip().lower()
    if not vault:
        return DEFAULT_VAULT
    if not VAULT_RE.match(vault):
        raise InvalidVaultError(
            "a vault name is 1-32 chars of lowercase letters, digits, '.', '_' "
            "or '-', starting with a letter or digit"
        )
    return vault


def validate_key(name: str) -> str:
    name = (name or "").strip()
    if not KEY_RE.match(name):
        raise InvalidSecretNameError(
            f"{name!r} is not a usable variable name: letters, digits and '_', "
            "not starting with a digit"
        )
    return name


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


class SecretStore:
    """All secret operations, for every user, against one database."""

    def __init__(self, db_path: Path, key: bytes) -> None:
        self.db_path = db_path
        self._key = key
        connect(self.db_path).close()

    # -- helpers -----------------------------------------------------------
    def _row_to_secret(self, row: sqlite3.Row, *, reveal: bool) -> Secret:
        secret = Secret(
            key=row["name"],
            environment=row["environment"],
            vault=row["vault"],
            length=row["value_length"],
            fingerprint=row["fingerprint"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        if reveal:
            secret.value = unseal(
                self._key,
                row["sealed"],
                associated_data(row["owner"], row["vault"], row["environment"], row["name"]),
            )
        return secret

    # -- reads -------------------------------------------------------------
    def vaults(self, owner: str) -> list[Vault]:
        """The vaults that hold something, for one person."""
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT vault, COUNT(*) AS n, COUNT(DISTINCT environment) AS envs,"
                " MAX(updated_at) AS updated"
                " FROM secrets WHERE owner = ? GROUP BY vault ORDER BY vault",
                (owner,),
            ).fetchall()
        return [
            Vault(
                vault=row["vault"],
                secrets=row["n"],
                environments=row["envs"],
                updated_at=row["updated"],
            )
            for row in rows
        ]

    def environments(self, owner: str, vault: str) -> list[Environment]:
        """The environments that actually hold something, in this vault."""
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT environment, COUNT(*) AS n, MAX(updated_at) AS updated"
                " FROM secrets WHERE owner = ? AND vault = ?"
                " GROUP BY environment ORDER BY environment",
                (owner, validate_vault(vault)),
            ).fetchall()
        return [
            Environment(environment=row["environment"], secrets=row["n"], updated_at=row["updated"])
            for row in rows
        ]

    def list(
        self,
        owner: str,
        vault: str,
        environment: str | None = None,
        *,
        reveal: bool = False,
    ) -> list[Secret]:
        """Secrets in one environment, or across all of them when it is None."""
        query = "SELECT * FROM secrets WHERE owner = ? AND vault = ?"
        params: list[object] = [owner, validate_vault(vault)]
        if environment is not None:
            query += " AND environment = ?"
            params.append(validate_environment(environment))
        query += " ORDER BY environment, name"
        with connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_secret(row, reveal=reveal) for row in rows]

    def get(
        self, owner: str, vault: str, environment: str, name: str, *, reveal: bool = True
    ) -> Secret | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM secrets WHERE owner = ? AND vault = ? AND environment = ?"
                " AND name = ?",
                (
                    owner,
                    validate_vault(vault),
                    validate_environment(environment),
                    validate_key(name),
                ),
            ).fetchone()
        return self._row_to_secret(row, reveal=reveal) if row else None

    def require(self, owner: str, vault: str, environment: str, name: str) -> Secret:
        secret = self.get(owner, vault, environment, name)
        if secret is None:
            raise UnknownSecretError(name)
        return secret

    def export(self, owner: str, vault: str, environment: str) -> dict[str, str]:
        """Every secret in one environment as plain pairs, ready for a `.env`."""
        return {
            secret.key: secret.value or ""
            for secret in self.list(owner, vault, environment, reveal=True)
        }

    # -- writes ------------------------------------------------------------
    def set(
        self, owner: str, vault: str, environment: str, name: str, value: str
    ) -> tuple[Secret, str]:
        """Create or replace one secret. Returns it with what happened to it."""
        vault = validate_vault(vault)
        environment = validate_environment(environment)
        name = validate_key(name)
        now = _now()
        with connect(self.db_path) as conn:
            action = self._set(conn, owner, vault, environment, name, value, now)
        return self.require(owner, vault, environment, name), action

    def _set(
        self,
        conn: sqlite3.Connection,
        owner: str,
        vault: str,
        environment: str,
        name: str,
        value: str,
        now: str,
    ) -> str:
        existing = conn.execute(
            "SELECT fingerprint FROM secrets WHERE owner = ? AND vault = ? AND"
            " environment = ? AND name = ?",
            (owner, vault, environment, name),
        ).fetchone()
        digest = fingerprint(self._key, value)
        if existing is not None and existing["fingerprint"] == digest:
            return "unchanged"
        sealed = seal(self._key, value, associated_data(owner, vault, environment, name))
        if existing is None:
            conn.execute(
                "INSERT INTO secrets (owner, vault, environment, name, sealed,"
                " fingerprint, value_length, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (owner, vault, environment, name, sealed, digest, len(value), now, now),
            )
            return "created"
        conn.execute(
            "UPDATE secrets SET sealed = ?, fingerprint = ?, value_length = ?, updated_at = ?"
            " WHERE owner = ? AND vault = ? AND environment = ? AND name = ?",
            (sealed, digest, len(value), now, owner, vault, environment, name),
        )
        return "updated"

    def set_many(
        self,
        owner: str,
        vault: str,
        environment: str,
        entries: Mapping[str, str],
        *,
        prune: bool = False,
        overwrite: bool = True,
        dry_run: bool = False,
    ) -> ImportResult:
        """Import a whole environment at once.

        *prune* deletes keys that are not in *entries*, making the environment
        match the file exactly. *overwrite* off keeps values that already exist,
        which is how you fill in what is missing without touching the rest.
        """
        vault = validate_vault(vault)
        environment = validate_environment(environment)
        pairs = {validate_key(name): value for name, value in entries.items()}
        result = ImportResult(environment=environment, dry_run=dry_run)
        now = _now()
        with connect(self.db_path) as conn:
            present = {
                row["name"]: row["fingerprint"]
                for row in conn.execute(
                    "SELECT name, fingerprint FROM secrets WHERE owner = ? AND vault = ?"
                    " AND environment = ?",
                    (owner, vault, environment),
                ).fetchall()
            }
            for name, value in pairs.items():
                if name in present and not overwrite:
                    result.skipped.append(name)
                    continue
                if dry_run:
                    if name not in present:
                        result.added.append(name)
                    elif present[name] == fingerprint(self._key, value):
                        result.unchanged.append(name)
                    else:
                        result.updated.append(name)
                    continue
                action = self._set(conn, owner, vault, environment, name, value, now)
                {"created": result.added, "updated": result.updated}.get(
                    action, result.unchanged
                ).append(name)
            if prune:
                stale = sorted(set(present) - set(pairs))
                result.removed.extend(stale)
                if not dry_run:
                    for name in stale:
                        conn.execute(
                            "DELETE FROM secrets WHERE owner = ? AND vault = ? AND"
                            " environment = ? AND name = ?",
                            (owner, vault, environment, name),
                        )
            if dry_run:
                conn.rollback()
        return result

    def delete(self, owner: str, vault: str, environment: str, name: str) -> None:
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM secrets WHERE owner = ? AND vault = ? AND environment = ?"
                " AND name = ?",
                (
                    owner,
                    validate_vault(vault),
                    validate_environment(environment),
                    validate_key(name),
                ),
            )
        if cursor.rowcount == 0:
            raise UnknownSecretError(name)

    def delete_environment(self, owner: str, vault: str, environment: str) -> int:
        environment = validate_environment(environment)
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM secrets WHERE owner = ? AND vault = ? AND environment = ?",
                (owner, validate_vault(vault), environment),
            )
        return cursor.rowcount

    def delete_vault(self, owner: str, vault: str) -> int:
        """Drop everything a vault held, every environment of it."""
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM secrets WHERE owner = ? AND vault = ?",
                (owner, validate_vault(vault)),
            )
        return cursor.rowcount
