# Backlog

Work that is decided and not started. Each entry says what is wanted, why,
and what it will take, so whoever picks it up begins from the reasoning
rather than from a one-line wish. An entry leaves this page when the work
lands and the page it belongs on describes it.

## A data access layer, and PostgreSQL as a choice at install

**Wanted.** The server stops being written against SQLite. One layer owns
every statement, and behind it sit two engines: SQLite, which stays the
default and is what a fresh install gets, and PostgreSQL. At install time
the person chooses: the built-in database, a PostgreSQL container the
installer starts beside the server, or a PostgreSQL server they already
have, by connection string. A hosted tenant gets the same choice from its
environment.

**Why.** Today 15 server modules import `sqlite3` directly, 131 places
open a connection, and about 70 of 235 statements use syntax only SQLite
has: `AUTOINCREMENT`, `rowid` and `lastrowid`, `INSERT OR REPLACE`, `?`
placeholders, `json_extract` over the indexed column, `PRAGMA`,
`executescript`, `sqlite3.Row` and `sqlite3.IntegrityError`. The schema
steps and the sealing migration are SQLite scripts. That is a dependence
on one database's dialect spread through the whole server, and it is not
acceptable: a change of engine must be a change of configuration, not of
every store.

**What it is not for.** Speed. The measured ceiling of one cloud is Python
time per request, not the database ([HOSTING.md](HOSTING.md), *How far
one cloud goes*), and a tenant scales by being one container among many.
PostgreSQL is for the person who already runs one, for a cloud too large
for one file, and for the day the server runs as several processes, which
a shared database makes possible and SQLite does not.

**The shape.**

1. *One module owns SQL.* A `database` package with an engine interface —
   connect, execute, a transaction, the last inserted id, the integrity
   error — and a dialect that spells the differences: placeholders,
   upserts, autoincrement, JSON field extraction and its index syntax.
   Every store goes through it; no store imports a driver. The sealer,
   which today rides on the SQLite connection subclass, moves to this
   layer, so sealing is the same on both engines.
2. *Connections with a lifetime.* Per call on SQLite, as now; a pool on
   PostgreSQL. The layer owns both, so the stores never know. The lesson
   of the load measurement — a connection that is not closed is memory
   gone — is enforced here once.
3. *Schema steps that run on both.* The versioned steps stay (schema.py);
   each step is written once in the dialect-neutral subset, or twice where
   it cannot be. The sealing migration the same.
4. *The record store's JSON.* `indexed` is a JSON column on both; the
   dialect gives `json_extract(indexed, '$."f"')` on SQLite and
   `indexed->>'f'` with a `jsonb` expression index on PostgreSQL. The
   visibility and filter clauses are built from the dialect, not written.
5. *What is SQLite's alone.* Write-ahead mode, the busy wait, the clock's
   checkpoint: engine-specific, inside the engine. `BEGIN IMMEDIATE`
   becomes the layer's "take the write lock", which on PostgreSQL is a
   row lock or an advisory lock.
6. *The single process.* The supervisor, the clock and the change feed
   assume one process. Nothing here changes that, but PostgreSQL is the
   first step toward several; `LISTEN`/`NOTIFY` is the change feed's
   path there, and is noted, not built.
7. *The installer.* A question after the five there are: built-in,
   container, or existing server. "Container" writes a `postgres` service
   into the compose file the server already ships with (`deploy/docker/`),
   with its own volume and a generated password in the key directory;
   "existing" asks for the connection string and checks it before going
   on. Both write `database_url` into `server.toml`; blank means SQLite.
   The container image reads `CLOUDMORROW_DATABASE_URL`.
8. *Backups.* "Copy the data directory" stops being the whole truth on
   PostgreSQL. [ENCRYPTION.md](ENCRYPTION.md) and [HOSTING.md](HOSTING.md)
   say so, and the installer's container choice includes a `pg_dump` on
   the same schedule the data directory has. The key stays where it is;
   a dump without it opens nothing, as before.
9. *Tests on both.* The suite runs against SQLite as now, and against a
   PostgreSQL started for the run, in CI and with one flag locally. A
   statement that passes on one and not the other fails the build.

**Size.** Roughly four weeks: a week for the layer and moving the stores
onto it with SQLite only, which is the part that pays for itself whatever
happens next; a week for the PostgreSQL engine, dialect and schema; a week
for the installer, the container, backups and the docs; a week for the
suite on both and what it finds. The first week can land alone, and
should: it is the de-coupling, and the rest is an engine behind it.

**Order.** After the data contract work ([DATAMODELS.md](DATAMODELS.md),
*The plan from here*), which changes what the record store stores; moving
the stores onto a layer while their tables are still moving would be done
twice.
