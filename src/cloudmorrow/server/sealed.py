"""Content encrypted at rest, under a key the server holds.

Everything a person writes into Cloudmorrow — a chat message, an event, a
task, a note, a picture — is sealed with AES-256-GCM before it is stored and
opened again when it is read, so the database and the notes directory hold
ciphertext. Users never see a key: the server has one, in a file, and that
is the whole model. It is encryption at rest, not end to end. Someone with
the key file and the data has everything; someone with the data alone has
nothing.

One key file, three subkeys derived from it with HKDF: `content` for the
database columns listed in SEALED, `notes` for the files in a notes tree,
and the key itself for the secrets store, which was sealing values before
this module existed and keeps its format. The derivation means a subkey
that leaks (a note file's key, say) opens nothing else.

What stays plain is what the server has to look things up, sort or range
by: usernames, slugs, timestamps, lanes, positions, who is in a channel.
That is metadata, and it is the same trade the secrets store makes when it
keeps key names in the clear and seals the values.

**Where the key comes from.** `db.connect` opens a connection that can seal
and unseal, and finds the key through `key_for`: the one registered for
that database by `use_key` — `create_app` and the CLI do this from the
config — or, failing that, `secrets.key` beside the database, which is the
default place for it. Registering is what lets the key live somewhere other
than beside the data it protects, which is what a fresh install does.

**Migration.** The first connection to a database that predates sealing
seals every row in every listed table, in one transaction, and writes the
sealing version into `schema_meta`. From then on every read unseals, with no
guessing about whether a value is plain: a message that happens to look
like ciphertext is still a message. Note files carry a magic prefix, so a
plain one left on disk by an older version reads as itself until
`seal_tree` has been over it, which happens at boot.
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from cloudmorrow.server import crypto
from cloudmorrow.server.crypto import KEY_BYTES, NONCE_BYTES, SealError, load_or_create_key

__all__ = [
    "FILE_MAGIC",
    "SEALED",
    "SealError",
    "Sealer",
    "is_sealed_file",
    "key_for",
    "migrate",
    "rotate",
    "seal_tree",
    "sealer_for",
    "use_key",
]

# The columns that hold content, by table, and what each row's seal is bound
# to. A value moved to a row with a different scope — another channel,
# another owner — fails to open. Scopes are columns that never change for a
# row, or that every update rewrites the content columns under anyway (an
# event moved to another calendar is re-sealed by the same UPDATE).
#
# Versioned so a column sealed in a later release is migrated on its own:
# a database at version 1 gets the version 2 entries sealed and nothing
# re-sealed. Never edit an entry that has shipped; add a version.
SEALED: dict[int, tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]] = {
    1: (
        ("chat_channels", ("slug",), ("topic",)),
        ("chat_messages", ("channel_id",), ("body",)),
        ("calendar_events", ("calendar_id",), ("title", "notes", "location")),
        ("boards", ("owner",), ("title",)),
        ("tasks", ("owner",), ("title", "body")),
        ("notifications", ("owner",), ("title", "body")),
        ("config_files", ("owner", "bundle"), ("content",)),
        ("projects", ("owner",), ("description",)),
        ("jobs", ("owner",), ("payload", "result")),
        ("push_subscriptions", ("username",), ("p256dh", "auth")),
    ),
    # The record store, where every Quill's data lives. Born sealed, so the
    # migration finds nothing to do; listed so a new key re-seals it.
    2: (("records", ("model", "owner", "id"), ("body",)),),
    # A Quill's webhook secrets (quilltokens): born sealed, listed so a new
    # key re-seals them.
    3: (("quill_webhooks", ("quill", "hook"), ("secret",)),),
}
SEALED_VERSION = max(SEALED)

TEXT_FORMAT = "s1"
# A sealed file starts with a NUL, which no text file does, so a plain
# note left by an older version is told apart from a sealed one without
# trying the key on it.
FILE_MAGIC = b"\x00CMS1"
FILE_OVERHEAD = len(FILE_MAGIC) + NONCE_BYTES + 16  # magic, nonce, GCM tag

_INFO_CONTENT = b"cloudmorrow/content/v1"
_INFO_NOTES = b"cloudmorrow/notes/v1"


def _derive(master: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=info).derive(master)


class Sealer:
    """The seal and unseal operations, for one master key."""

    def __init__(self, master: bytes) -> None:
        if len(master) != KEY_BYTES:
            raise SealError(f"the key is not {KEY_BYTES * 8} bits")
        self.master = master
        self._content = AESGCM(_derive(master, _INFO_CONTENT))
        self._notes = AESGCM(_derive(master, _INFO_NOTES))

    # -- database columns ----------------------------------------------------
    @staticmethod
    def _aad(table: str, column: str, scope: Iterable[object]) -> bytes:
        return "\x00".join((table, column, *(str(part) for part in scope))).encode("utf-8")

    def seal(
        self, table: str, column: str, scope: Iterable[object], text: str | None
    ) -> str | None:
        """Seal one column's value for one row. None stays None."""
        if text is None:
            return None
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._content.encrypt(nonce, text.encode("utf-8"), self._aad(table, column, scope))
        return f"{TEXT_FORMAT}:{_encode(nonce)}:{_encode(sealed)}"

    def unseal(
        self, table: str, column: str, scope: Iterable[object], blob: str | None
    ) -> str | None:
        if blob is None:
            return None
        version, _, rest = blob.partition(":")
        nonce, _, sealed = rest.partition(":")
        if version != TEXT_FORMAT or not nonce or not sealed:
            raise SealError(f"{table}.{column} holds a value that is not sealed")
        try:
            opened = self._content.decrypt(
                _decode(nonce), _decode(sealed), self._aad(table, column, scope)
            )
        except (InvalidTag, ValueError) as exc:
            raise SealError(f"cannot open {table}.{column} with the current key") from exc
        return opened.decode("utf-8")

    # -- files ---------------------------------------------------------------
    def seal_file(self, data: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return FILE_MAGIC + nonce + self._notes.encrypt(nonce, data, FILE_MAGIC)

    def unseal_file(self, data: bytes) -> bytes:
        """The file's contents. A file that was never sealed is returned as it is."""
        if not is_sealed_file(data):
            return data
        start = len(FILE_MAGIC)
        nonce, sealed = data[start : start + NONCE_BYTES], data[start + NONCE_BYTES :]
        try:
            return self._notes.decrypt(nonce, sealed, FILE_MAGIC)
        except (InvalidTag, ValueError) as exc:
            raise SealError("cannot open this file with the current key") from exc


def is_sealed_file(data: bytes) -> bool:
    return data.startswith(FILE_MAGIC)


def plain_size(stored: int) -> int:
    """How long a sealed file's contents are, from how long the file is."""
    return max(0, stored - FILE_OVERHEAD)


# -- which key ---------------------------------------------------------------------
_keys: dict[Path, bytes] = {}
_lock = threading.Lock()


def use_key(db_path: Path, key_path: Path) -> Sealer:
    """Say which key file seals *db_path*. Generates the key on first use."""
    key = load_or_create_key(key_path)
    with _lock:
        _keys[Path(db_path).resolve()] = key
    return Sealer(key)


def key_for(db_path: Path) -> bytes:
    """The key sealing *db_path*: the registered one, else `secrets.key` beside it."""
    resolved = Path(db_path).resolve()
    with _lock:
        key = _keys.get(resolved)
    if key is None:
        key = load_or_create_key(resolved.parent / "secrets.key")
        with _lock:
            _keys.setdefault(resolved, key)
    return key


_sealers: dict[bytes, Sealer] = {}


def sealer_for(db_path: Path) -> Sealer:
    """The sealer for a database. Connections are opened per call, so this is cached."""
    key = key_for(db_path)
    with _lock:
        sealer = _sealers.get(key)
        if sealer is None:
            sealer = _sealers[key] = Sealer(key)
    return sealer


# -- the migration -------------------------------------------------------------------
def migrate(conn: sqlite3.Connection, sealer: Sealer) -> None:
    """Seal what an older database holds plain. Cheap when there is nothing to do."""
    current = _sealed_version(conn)
    if current >= SEALED_VERSION:
        return
    # One writer at a time: a second connection booting alongside waits here,
    # then reads the version this one wrote and does nothing.
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = _sealed_version(conn)
        for version in sorted(SEALED):
            if version <= current:
                continue
            for table, scope_cols, columns in SEALED[version]:
                if not _table_exists(conn, table):
                    continue
                _seal_table(conn, sealer, table, scope_cols, columns)
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('sealed', ?)",
            (str(SEALED_VERSION),),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _sealed_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'sealed'").fetchone()
    return int(row[0]) if row else 0


def _record_scopes(row: sqlite3.Row) -> list[tuple]:
    """What a record's body may be sealed to: its owner, or the space it is in.

    A record in a space (a message in a channel) is sealed to the space, and
    which of its links is the space is the datamodel's to say — which this
    module does not read. So each link it has is tried; a wrong one fails to
    open rather than opening as something else, and the right one is kept.
    """
    scopes = [(row["model"], row["owner"], row["id"])]
    try:
        indexed = json.loads(row["indexed"] or "{}")
    except ValueError:
        indexed = {}
    for value in indexed.values():
        if isinstance(value, str) and value.startswith("r_"):
            scopes.append((row["model"], "space", value, row["id"]))
    return scopes


def _rotate_records(conn: sqlite3.Connection, old: Sealer, new: Sealer) -> int:
    rows = 0
    for row in conn.execute("SELECT rowid, id, model, owner, indexed, body FROM records").fetchall():
        for scope in _record_scopes(row):
            try:
                text = old.unseal("records", "body", scope, row["body"])
            except SealError:
                continue
            conn.execute(
                "UPDATE records SET body = ? WHERE rowid = ?",
                (new.seal("records", "body", scope, text), row["rowid"]),
            )
            rows += 1
            break
        else:
            raise SealError(f"cannot open record {row['id']} with the old key")
    return rows


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _seal_table(
    conn: sqlite3.Connection,
    sealer: Sealer,
    table: str,
    scope_cols: tuple[str, ...],
    columns: tuple[str, ...],
) -> None:
    select = ", ".join(("rowid", *scope_cols, *columns))
    rows = conn.execute(f"SELECT {select} FROM {table}").fetchall()
    assignments = ", ".join(f"{column} = ?" for column in columns)
    for row in rows:
        scope = tuple(row[1 : 1 + len(scope_cols)])
        values = row[1 + len(scope_cols) :]
        sealed = [
            sealer.seal(table, column, scope, value)
            for column, value in zip(columns, values, strict=True)
        ]
        conn.execute(f"UPDATE {table} SET {assignments} WHERE rowid = ?", (*sealed, row[0]))


def seal_tree(root: Path, sealer: Sealer) -> int:
    """Seal every file under a notes root that is not sealed yet.

    Returns how many were sealed. Hidden files are left alone: the `.tmp`
    files a write goes through, and anything a person's editor keeps.
    """
    sealed = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        with path.open("rb") as handle:
            if is_sealed_file(handle.read(len(FILE_MAGIC))):
                continue
        data = path.read_bytes()
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(sealer.seal_file(data))
        os.replace(tmp, path)
        sealed += 1
    return sealed


# -- a new key -----------------------------------------------------------------------
def rotate(db_path: Path, note_roots: Iterable[Path], old: Sealer, new: Sealer) -> dict[str, int]:
    """Open everything with *old* and seal it again with *new*.

    Every listed column, the secrets store's values and fingerprints, and
    every sealed file under the note roots. The database part is one
    transaction; the files are one at a time, each replaced whole. Run it
    with the service stopped — a row written under the old key while this
    runs would be a row nobody can open afterwards. Returns what it did.
    """
    rows = 0
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        for version in sorted(SEALED):
            for table, scope_cols, columns in SEALED[version]:
                if not _table_exists(conn, table):
                    continue
                if table == "records":
                    rows += _rotate_records(conn, old, new)
                    continue
                select = ", ".join(("rowid", *scope_cols, *columns))
                assignments = ", ".join(f"{column} = ?" for column in columns)
                for row in conn.execute(f"SELECT {select} FROM {table}").fetchall():
                    scope = tuple(row[1 : 1 + len(scope_cols)])
                    blobs = row[1 + len(scope_cols) :]
                    values = [
                        new.seal(table, column, scope, old.unseal(table, column, scope, blob))
                        for column, blob in zip(columns, blobs, strict=True)
                    ]
                    conn.execute(
                        f"UPDATE {table} SET {assignments} WHERE rowid = ?", (*values, row[0])
                    )
                    rows += 1
        if _table_exists(conn, "secrets"):
            for row in conn.execute(
                "SELECT id, owner, vault, environment, name, sealed FROM secrets"
            ).fetchall():
                aad = crypto.associated_data(
                    row["owner"], row["vault"], row["environment"], row["name"]
                )
                value = crypto.unseal(old.master, row["sealed"], aad)
                conn.execute(
                    "UPDATE secrets SET sealed = ?, fingerprint = ? WHERE id = ?",
                    (
                        crypto.seal(new.master, value, aad),
                        crypto.fingerprint(new.master, value),
                        row["id"],
                    ),
                )
                rows += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    files = 0
    for root in note_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            data = path.read_bytes()
            if not is_sealed_file(data):
                continue
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_bytes(new.seal_file(old.unseal_file(data)))
            os.replace(tmp, path)
            files += 1
    return {"rows": rows, "files": files}


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
