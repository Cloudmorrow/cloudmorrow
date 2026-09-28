"""Secrets as records: a vault's environments and keys, served from the secret store."""

from __future__ import annotations

from cloudmorrow.server.backends.base import decode_id, encode_id
from cloudmorrow.server.datamodels import Datamodel
from cloudmorrow.server.records import (
    Principal,
    Record,
    RecordConflictError,
    RecordError,
    UnknownRecordError,
)
from cloudmorrow.server.secrets import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_VAULT,
    InvalidEnvironmentError,
    InvalidSecretNameError,
    InvalidVaultError,
    Secret,
    SecretStore,
    UnknownSecretError,
    validate_environment,
    validate_key,
    validate_vault,
)

_BAD_NAME = (InvalidVaultError, InvalidEnvironmentError, InvalidSecretNameError)


class VaultsBackend:
    """Secrets as records: one per key, in a vault and an environment.

    Fields: `vault`, `environment` and `key` — which together are the id —
    `value`, and `length`. The value is a `secret` field: it is never in a
    listing, where it is null, and only reading one secret puts it in. The
    store is the one `cm secret` and `/api/secrets` have always used, sealed
    under the key itself; nothing here seals or opens anything of its own.

    Changing `vault`, `environment` or `key` moves the secret, value and all;
    `length` is the store's to say. No assistant ever gets this far: the
    record store's gate refuses the `secret` datamodel to every assistant
    before a backend is asked.
    """

    PREFIX = "s_"
    WRITABLE = frozenset({"vault", "environment", "key", "value"})
    FILTERS = frozenset({"vault", "environment", "key"})

    def __init__(self, store: SecretStore) -> None:
        self._store = store

    @staticmethod
    def _rev(secret: Secret) -> str:
        # The keyed fingerprint moves with the value and says nothing about it.
        return secret.fingerprint[:16]

    def _record(self, model: Datamodel, owner: str, secret: Secret) -> Record:
        return Record(
            id=encode_id(self.PREFIX, f"{secret.vault}/{secret.environment}/{secret.key}"),
            model=model.id,
            owner=owner,
            scope="personal",
            rev=self._rev(secret),
            position=0,
            fields={
                "vault": secret.vault,
                "environment": secret.environment,
                "key": secret.key,
                "value": secret.value,
                "length": secret.length,
            },
            written_by="secrets",
            created_at=secret.created_at,
            updated_at=secret.updated_at,
        )

    def _where(self, record_id: str) -> tuple[str, str, str]:
        vault, _, rest = decode_id(self.PREFIX, record_id).partition("/")
        environment, _, key = rest.partition("/")
        if not (vault and environment and key):
            raise UnknownRecordError(record_id)
        return vault, environment, key

    def _find(self, owner: str, where: tuple[str, str, str], record_id: str) -> Secret:
        try:
            secret = self._store.get(owner, *where, reveal=True)
        except _BAD_NAME:
            raise UnknownRecordError(record_id) from None
        if secret is None:
            raise UnknownRecordError(record_id)
        return secret

    def _taken(self, owner: str, where: tuple[str, str, str]) -> None:
        """Refuse to write over another secret: that is `cm secret set`'s job, not a record's."""
        try:
            there = self._store.get(owner, *where, reveal=False)
        except _BAD_NAME as exc:
            raise RecordError(str(exc)) from None
        if there is not None:
            raise RecordError(f"{there.key} is already in {there.vault} · {there.environment}")

    @staticmethod
    def _target(fields: dict, vault: str, environment: str, key: str) -> tuple[str, str, str]:
        return (
            str(fields.get("vault") or vault).strip().lower(),
            str(fields.get("environment") or environment).strip().lower(),
            str(fields.get("key") or key).strip(),
        )

    def list(self, principal: Principal, model: Datamodel, where: dict, *, q: str = "",
             previews: bool = False) -> list[Record]:
        """Secrets, filtered; `q` finds by key, never by value. No previews: nothing to show."""
        unknown = set(where) - self.FILTERS
        if unknown:
            raise RecordError(
                "secrets are filtered by vault, environment and key, not "
                + ", ".join(sorted(unknown))
            )
        owner = principal.username
        try:
            vaults = (
                [str(where["vault"])] if "vault" in where
                else [v.vault for v in self._store.vaults(owner)]
            )
            found = [
                secret
                for vault in vaults
                for secret in self._store.list(owner, vault, where.get("environment"))
            ]
        except _BAD_NAME as exc:
            raise RecordError(str(exc)) from None
        if "key" in where:
            found = [s for s in found if s.key == str(where["key"])]
        if q:
            found = [s for s in found if q.casefold() in s.key.casefold()]
        # Never the value, whatever was asked: a listing describes, it does not hand over.
        return [self._record(model, owner, secret) for secret in found]

    def get(self, principal: Principal, model: Datamodel, record_id: str) -> Record:
        where = self._where(record_id)
        return self._record(model, principal.username, self._find(principal.username, where, record_id))

    def _write(self, owner: str, where: tuple[str, str, str], value: object) -> None:
        if value is not None and not isinstance(value, str):
            raise RecordError("a secret's value is text")
        try:
            self._store.set(owner, *where, value or "")
        except _BAD_NAME as exc:
            raise RecordError(str(exc)) from None

    def _check_fields(self, fields: dict) -> None:
        unknown = set(fields) - self.WRITABLE
        if unknown:
            raise RecordError(f"a secret's {', '.join(sorted(unknown))} is not written directly")

    def create(self, principal: Principal, model: Datamodel, fields: dict) -> Record:
        self._check_fields(fields)
        if not str(fields.get("key") or "").strip():
            raise RecordError("a secret needs a key: the variable name, like DATABASE_URL")
        owner = principal.username
        where = self._target(fields, DEFAULT_VAULT, DEFAULT_ENVIRONMENT, "")
        self._taken(owner, where)
        self._write(owner, where, fields.get("value"))
        return self.get(principal, model, encode_id(self.PREFIX, "/".join(self._stored(where))))

    @staticmethod
    def _stored(where: tuple[str, str, str]) -> tuple[str, str, str]:
        """The names as the store keeps them, once it has checked them."""
        return validate_vault(where[0]), validate_environment(where[1]), validate_key(where[2])

    def update(self, principal: Principal, model: Datamodel, record_id: str, fields: dict,
               rev: object) -> Record:
        self._check_fields(fields)
        owner = principal.username
        here = self._where(record_id)
        current = self._find(owner, here, record_id)
        if rev not in (None, "") and str(rev) != self._rev(current):
            raise RecordConflictError(self._record(model, owner, current))
        target = self._target(fields, *here)
        moving = target != here
        if moving:
            self._taken(owner, target)
        self._write(owner, target, fields["value"] if "value" in fields else current.value)
        target = self._stored(target)
        if moving:
            self._store.delete(owner, *here)
        return self.get(principal, model, encode_id(self.PREFIX, "/".join(target)))

    def delete(self, principal: Principal, model: Datamodel, record_id: str) -> int:
        where = self._where(record_id)
        try:
            self._store.delete(principal.username, *where)
        except (UnknownSecretError, *_BAD_NAME):
            raise UnknownRecordError(record_id) from None
        return 1
