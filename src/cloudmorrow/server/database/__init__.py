"""The database: one layer every store goes through, and an engine behind it.

Two engines. SQLite is the default and what a fresh install gets: one file
in the data directory, a connection per call. PostgreSQL is chosen at
install — `database_url` in server.toml, `CLOUDMORROW_DATABASE_URL` in a
container — and is a pool of connections. A store sees neither. It asks
`Database.connect()` for a connection, writes its statements with `?`
placeholders in the SQL both engines speak, and leaves what differs to the
dialect (a JSON field, the next number in a sequence, what names a row)
and to the connection (the last inserted id, the write lock, the schema
version, which tables and columns there are). No store imports a driver.

The sealer rides here too (sealed.py): `conn.seal` and `conn.unseal` are
the same on both engines, and the key is the database's — `use_key`
says which file, else `secrets.key` beside a SQLite file.

What a connection does on opening: the engine's own setup (the pragmas on
SQLite), the schema steps the database has not run (schema.py), and the
sealing migration (sealed.py). SQLite checks on every connection, which
costs one pragma and keeps a file somebody replaced honest; PostgreSQL
once per process, since a pooled connection is not a database being born.

`open` is how a database is found: a `Path` is a SQLite file, a URL is
`sqlite:///...` or `postgresql://...`, and the same target gives the same
`Database` — one pool, one key — for the life of the process.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from cloudmorrow.server.sealed import Sealer

__all__ = [
    "Connection",
    "Cursor",
    "Database",
    "DatabaseError",
    "Dialect",
    "Engine",
    "IntegrityError",
    "OperationalError",
    "Row",
    "connect",
    "forget",
    "open",
]


class DatabaseError(Exception):
    """The engine refused a statement. The engine's own error is the cause."""


class IntegrityError(DatabaseError):
    """A unique or a foreign key said no."""


class OperationalError(DatabaseError):
    """The database could not be reached, is busy, or has no such table."""


class Row(Protocol):
    """A row as every store reads one: by column name, by index, by slice."""

    def __getitem__(self, key: int | str | slice) -> Any: ...
    def keys(self) -> Iterable[str]: ...
    def __iter__(self) -> Any: ...
    def __len__(self) -> int: ...


class Cursor(Protocol):
    """What `execute` answers with. Rows come out of it once."""

    rowcount: int

    def fetchone(self) -> Row | None: ...
    def fetchall(self) -> list[Row]: ...
    def __iter__(self) -> Any: ...


class Dialect:
    """How this engine spells what the two spell differently.

    Everything a store writes itself is the shared subset; what is here is
    what cannot be: the DDL types the engine has its own word for, reading
    a field out of a JSON column, the next number in a column that counts,
    and what names a row when nothing else does.
    """

    name: str
    # The SQL that names one row for an UPDATE of it, when a table has no
    # key worth the name: SQLite's rowid, PostgreSQL's ctid.
    row_address: str

    def ddl(self, sql: str) -> str:
        """A table definition in the shared vocabulary, in this engine's words.

        The vocabulary: `INTEGER PRIMARY KEY AUTOINCREMENT` for a key the
        engine hands out; `JSON` for a column holding JSON the engine can
        read into; `INTEGER AUTONUMBER` for a column that counts the rows
        as they are written, filled through `next_number`.
        """
        raise NotImplementedError

    def json_text(self, column: str, field: str) -> str:
        """The text of *field* in the JSON *column*; NULL when it is not there or null.

        What a listing narrows by, and what an index is made on: the same
        text in both, which is what makes the index the one used.
        """
        raise NotImplementedError

    def json_compare(self, column: str, field: str, op: str, value: object) -> tuple[str, list[object]]:
        """`field op value` on a JSON column, typed as the value is: a number
        against a number, text against text. `IS` is null-safe equality."""
        raise NotImplementedError

    def next_number(self, table: str, column: str) -> str:
        """The expression an INSERT writes into an `INTEGER AUTONUMBER` column."""
        raise NotImplementedError


class Engine:
    """One database engine: how it is reached, and what is its own.

    A subclass holds the driver. The layer calls these with the driver's
    raw connection; nothing else touches it.
    """

    name: str
    dialect: Dialect
    # Whether the schema version is read on every connection. SQLite: one
    # pragma, and the file may be one somebody put there. PostgreSQL: once.
    checks_every_connect: bool

    def acquire(self) -> Any:
        """A raw connection, set up: new on SQLite, from the pool on PostgreSQL."""
        raise NotImplementedError

    def release(self, raw: Any) -> None:
        """The raw connection is done with: closed, or back in the pool."""
        raise NotImplementedError

    def close(self) -> None:
        """The engine is done with: the pool closes."""

    def prepare(self, raw: Any) -> None:
        """Once per process, before the schema steps: what the engine needs of its own."""

    def execute(self, raw: Any, sql: str, params: Sequence[object]) -> Cursor:
        raise NotImplementedError

    def executemany(self, raw: Any, sql: str, rows: Iterable[Sequence[object]]) -> None:
        raise NotImplementedError

    def executescript(self, raw: Any, script: str) -> None:
        """Several statements, no parameters: a table definition, in this engine's words already."""
        raise NotImplementedError

    def insert(self, raw: Any, sql: str, params: Sequence[object], key: str) -> int:
        """Run an INSERT and answer the *key* the engine gave the row."""
        raise NotImplementedError

    def lock(self, raw: Any) -> None:
        """Take the write lock for the rest of this transaction."""
        raise NotImplementedError

    def schema_version(self, raw: Any) -> int:
        raise NotImplementedError

    def set_schema_version(self, raw: Any, version: int) -> None:
        raise NotImplementedError

    def table_exists(self, raw: Any, name: str) -> bool:
        raise NotImplementedError

    def columns(self, raw: Any, table: str) -> set[str]:
        raise NotImplementedError

    def in_transaction(self, raw: Any) -> bool:
        raise NotImplementedError

    def commit(self, raw: Any) -> None:
        raw.commit()

    def rollback(self, raw: Any) -> None:
        raw.rollback()

    def translate(self, exc: BaseException) -> DatabaseError | None:
        """The driver's error as the layer's, or None when it is not the driver's."""
        raise NotImplementedError

    def checkpoint(self) -> bool:
        """Housekeeping on the clock: fold SQLite's log back in. True when done."""
        return True


class Connection:
    """One connection, for one call: `with db.connect() as conn:`.

    Leaving the block commits, or rolls back on an exception, and gives the
    connection back — closed on SQLite, to the pool on PostgreSQL. Rows read
    inside are still good outside, and so are `seal` and `unseal`.
    """

    __slots__ = ("_raw", "db")

    def __init__(self, db: Database, raw: Any) -> None:
        self.db = db
        self._raw = raw

    @property
    def engine(self) -> Engine:
        return self.db.engine

    @property
    def dialect(self) -> Dialect:
        return self.db.engine.dialect

    @property
    def raw(self) -> Any:
        if self._raw is None:
            raise OperationalError("the connection is closed")
        return self._raw

    def _run(self, call: Callable[..., Any], *args: object) -> Any:
        try:
            return call(self.raw, *args)
        except DatabaseError:
            raise
        except Exception as exc:
            translated = self.engine.translate(exc)
            if translated is None:
                raise
            raise translated from exc

    # -- statements --------------------------------------------------------------
    def execute(self, sql: str, params: Sequence[object] = ()) -> Cursor:
        return self._run(self.engine.execute, sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[object]]) -> None:
        self._run(self.engine.executemany, sql, rows)

    def executescript(self, script: str) -> None:
        """Table definitions in the shared vocabulary (see `Dialect.ddl`)."""
        self._run(self.engine.executescript, self.dialect.ddl(script))

    def insert(self, sql: str, params: Sequence[object] = (), *, key: str = "id") -> int:
        """An INSERT, answered with the *key* the engine gave the new row."""
        return self._run(self.engine.insert, sql, params, key)

    def lock(self) -> None:
        """Take the write lock: nobody else writes until this transaction ends.

        What a read-then-write that must not race takes — a revision check,
        a secret made the first time it is asked for, a migration.
        """
        self._run(self.engine.lock)

    # -- what the database is like ---------------------------------------------
    def schema_version(self) -> int:
        return self._run(self.engine.schema_version)

    def set_schema_version(self, version: int) -> None:
        self._run(self.engine.set_schema_version, int(version))

    def table_exists(self, name: str) -> bool:
        """Is there a table called *name*? A yes is remembered: tables are never dropped."""
        if name in self.db._tables:
            return True
        found = bool(self._run(self.engine.table_exists, name))
        if found:
            self.db._tables.add(name)
        return found

    def columns(self, table: str) -> set[str]:
        """The names of *table*'s columns; empty when there is no such table."""
        return set(self._run(self.engine.columns, table))

    # -- the transaction -----------------------------------------------------------
    def commit(self) -> None:
        self._run(self.engine.commit)

    def rollback(self) -> None:
        self._run(self.engine.rollback)

    def close(self) -> None:
        """Give the connection back. Safe to call twice."""
        raw, self._raw = self._raw, None
        if raw is not None:
            self.engine.release(raw)

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if self._raw is not None:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            self.close()

    # -- sealing -------------------------------------------------------------------
    def seal(self, table: str, column: str, scope: Iterable[object], text: str | None) -> str | None:
        return self.db.sealer.seal(table, column, scope, text)

    def unseal(self, table: str, column: str, scope: Iterable[object], blob: str | None) -> str | None:
        return self.db.sealer.unseal(table, column, scope, blob)


class Database:
    """One database: its engine, its key, and the connections to it."""

    def __init__(self, engine: Engine, *, key: str, path: Path | None, url: str) -> None:
        self.engine = engine
        # What `open` was given, normalised: one Database per key.
        self.key = key
        # The SQLite file; for another engine, the place a SQLite file would
        # have been, which is where a key is looked for when none is given.
        self.path = path
        self.url = url
        self._sealer: Sealer | None = None
        self._ready = False
        self._ready_lock = threading.Lock()
        # Tables known to be there (Connection.table_exists).
        self._tables: set[str] = set()

    def __repr__(self) -> str:
        return f"Database({self.describe()!r})"

    def describe(self) -> str:
        """What to show somebody: the file, or the URL with no password in it."""
        if self.path is not None and self.engine.name == "sqlite":
            return str(self.path)
        return _without_password(self.url)

    @property
    def dialect(self) -> Dialect:
        return self.engine.dialect

    # -- the key ---------------------------------------------------------------------
    def use_key(self, key_path: Path) -> Sealer:
        """Say which key file seals this database. Generates the key on first use."""
        from cloudmorrow.server.crypto import load_or_create_key
        from cloudmorrow.server.sealed import sealer_with

        self._sealer = sealer_with(load_or_create_key(key_path))
        return self._sealer

    @property
    def sealer(self) -> Sealer:
        """What seals this database's content: the key registered, else
        `secrets.key` beside the file — the default place for it."""
        if self._sealer is None:
            if self.path is None:
                raise OperationalError(
                    f"no key is registered for the database at {self.describe()}: use_key says which file"
                )
            from cloudmorrow.server.crypto import load_or_create_key
            from cloudmorrow.server.sealed import sealer_with

            self._sealer = sealer_with(load_or_create_key(self.path.parent / "secrets.key"))
        return self._sealer

    # -- connections -----------------------------------------------------------------
    def connect(self) -> Connection:
        """A connection with the schema at the version this code expects, and the key."""
        if self.path is not None and self.engine.name == "sqlite":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = Connection(self, self.engine.acquire())
        try:
            if self.engine.checks_every_connect:
                self._bring_up(conn)
            elif not self._ready:
                with self._ready_lock:
                    if not self._ready:
                        self._bring_up(conn)
                        self._ready = True
        except BaseException:
            conn.close()
            raise
        return conn

    def _bring_up(self, conn: Connection) -> None:
        from cloudmorrow.server import schema, sealed

        if not self._ready:
            conn._run(self.engine.prepare)
        schema.upgrade(conn)
        sealed.migrate(conn, self.sealer)

    def checkpoint(self) -> bool:
        """The engine's housekeeping on the clock (quills/jobs.py)."""
        return self.engine.checkpoint()

    def close(self) -> None:
        self.engine.close()


# -- finding one ------------------------------------------------------------------------
_registry: dict[str, Database] = {}
_registry_lock = threading.Lock()

# A stand-in for a SQLite file, so the test suite runs its every test, which
# names a file, against the other engine. Set by the suite's conftest.
stand_in: Callable[[Path], Database] | None = None


def _without_password(url: str) -> str:
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    account, _, host = rest.rpartition("@")
    user = account.partition(":")[0]
    return f"{scheme}://{user}@{host}" if user else f"{scheme}://{host}"


def open(target: Database | Path | str, *, path: Path | None = None) -> Database:  # noqa: A001
    """The Database for *target*: a SQLite file, a `sqlite:///` or
    `postgresql://` URL, or a Database already (answered as it is).

    The same target answers the same Database for the life of the process.
    *path* is where a SQLite file would have been, for another engine
    standing in for one (the key beside it; see `Database.path`).
    """
    if isinstance(target, Database):
        return target
    if isinstance(target, Path):
        if stand_in is not None:
            return stand_in(target)
        resolved = target.expanduser().resolve()
        key = str(resolved)
        make = lambda: _sqlite(resolved)  # noqa: E731
    else:
        url = str(target).strip()
        scheme = url.partition("://")[0].lower()
        if scheme == "sqlite":
            file = url[len("sqlite://") :]
            if not file or file == "/":
                raise OperationalError("a sqlite URL names a file: sqlite:////var/lib/cloudmorrow/cloudmorrow.db")
            return open(Path(file))
        if scheme not in ("postgresql", "postgres"):
            raise OperationalError(f"the database URL must be sqlite:/// or postgresql://, not {url!r}")
        key = url
        make = lambda: _postgres(url, path)  # noqa: E731
    with _registry_lock:
        db = _registry.get(key)
        if db is None:
            db = _registry[key] = make()
    return db


def _sqlite(file: Path) -> Database:
    from cloudmorrow.server.database.sqlite import SQLiteEngine

    return Database(SQLiteEngine(file), key=str(file), path=file, url=f"sqlite:///{file}")


def _postgres(url: str, path: Path | None) -> Database:
    try:
        from cloudmorrow.server.database.postgres import PostgresEngine
    except ImportError as exc:
        raise OperationalError(
            "PostgreSQL needs its driver, which the postgres extra brings: pip install 'cloudmorrow[postgres]'"
        ) from exc
    return Database(PostgresEngine(url), key=url, path=path, url=url)


def connect(target: Database | Path | str) -> Connection:
    """`open(target).connect()`: one connection, for one call."""
    return open(target).connect()


def forget(db: Database) -> None:
    """Close *db* and let `open` make a new one for its target. For tests."""
    with _registry_lock:
        if _registry.get(db.key) is db:
            del _registry[db.key]
    db.close()
