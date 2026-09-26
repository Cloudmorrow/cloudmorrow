# Encryption in Cloudmorrow

Cloudmorrow keeps what you write as ciphertext on the server's disk and only
ever moves it over TLS. You never hold a key: you sign in with a password,
and the server does the rest. This document says exactly what that means,
where the edges are, and what an operator has to do about the key.

## The model in one paragraph

Encryption at rest, not end to end. The server holds one key in a file,
seals every piece of content with it before writing and opens it again when
reading. Someone with the data alone — a copied database, a stolen disk, an
old backup — has nothing. Someone with the data *and* the key file has
everything, and so does the running server, because it is the thing that
hands your notes back to you. The choice was deliberate: an end-to-end
design puts device keys and recovery phrases in users' hands, and the
product's point is that anyone can run it on their own hardware without
any of that. Volume encryption (LUKS, ZFS) would also have kept keys out of
users' hands, but it depends on the operating system, and Cloudmorrow has to
install with `pip` on a Raspberry Pi. So the application does it itself.

## What is sealed

Content is sealed. Metadata the server needs to look things up, sort by, or
range over stays plain.

| Store | Sealed | Plain |
| --- | --- | --- |
| Chat (records) | message bodies, channel names and topics — sealed to the channel | channel kind and scope, who is in a channel, authors, timestamps, when each person last looked |
| Calendar | event titles, notes, locations | calendar slugs and names, colours, members, start and end times, all-day flag |
| Tasks | board titles, task titles and bodies | board slugs, lanes, positions, timestamps |
| Notifications | title and body | kind, machine, timestamps, read state |
| Config sync | the contents of every synced dotfile | bundle name, file paths, hashes, modes, revisions |
| Agent jobs | payload and result | type, status, timestamps |
| Web push | the subscription's `p256dh` and `auth` keys | the endpoint URL (needed to send, and unique) |
| Secrets | values | vaults, key names, environments, lengths, a keyed fingerprint per value |
| Notes | every note's contents, every picture | file names, which are the titles; folder names; sizes and modification times |
| Users | — | usernames, display names, roles; passwords are argon2 hashes, which is not encryption and needs no key |

Not sealed, and known: the files in **My Files** and the **fileshares**.
They are served over WebDAV straight from disk, and a mount expects to
read and write raw bytes with range requests. Sealing them means a WebDAV
provider of our own that decrypts on read and encrypts on write; it is on
the list, not done. Note **file names** are the other gap: a title is how
a note is found and listed, so it is the name on disk.

## How it is sealed

**The cipher.** AES-256-GCM, a fresh 96-bit random nonce per value, from
the `cryptography` package, which ships wheels for every platform
Cloudmorrow installs on. A sealed database value is stored as text:
`s1:<nonce>:<ciphertext>`, both parts URL-safe base64. A sealed file is
bytes: a five-byte magic `\x00CMS1`, the nonce, the ciphertext with its
tag. The magic starts with a NUL, which no text file begins with, so a
plain note left by an older version can be told from a sealed one without
trying the key.

**One key, three subkeys.** The key file holds 32 random bytes. From it,
HKDF-SHA256 derives a subkey for database content
(`cloudmorrow/content/v1`) and one for the notes tree
(`cloudmorrow/notes/v1`). Secrets use the key itself, because they were
sealed under it before the rest existed and their format did not change.
A subkey that leaks opens only its own kind of thing.

**Every seal is bound to its row.** GCM's associated data carries the
table, the column, and the row's *scope* — the channel a message is in,
the owner of a task, the calendar an event is on, the user a push key
belongs to. Moving a ciphertext to another row by editing the database
makes it fail to open. The scopes were chosen to be immutable for a row,
or to be rewritten by the same update that could change them (an event
moved to another calendar is resealed by the move). Secrets are bound to
owner, vault, environment and key name. A note file is bound
to the constant magic only: notes move between folders, and a rename must
not need the key.

**Where in the code.** `src/cloudmorrow/server/sealed.py` is the whole
mechanism: the `Sealer`, the versioned table `SEALED` of which columns are
sealed and by what scope, the boot migration, the notes sweep, and
rotation. `db.connect` returns a connection with `seal` and `unseal`
methods, so a store writes `conn.seal("tasks", "body", (owner,), body)`
and reads with the matching `unseal`. `NoteStore` takes a `Sealer` and
every file goes through it. Nothing else in the server touches ciphertext.

**What it costs.** Sorting on a sealed column is done in Python rather
than SQL; boards are the only case. Searching notes opens each file whole;
a note over two megabytes is skipped by search and gets no preview. A
picture is read into memory to serve it. None of this is noticeable at
the scale of a home server.

## The key

**Where it is.** `key_file` in `server.toml`, or the `CLOUDMORROW_KEY_FILE`
environment variable. Unset, it is `<data_dir>/secrets.key`, which is
where every server had it before this. The installer writes
`/etc/cloudmorrow/cloudmorrow.key` and sets `key_file` to it, so the key
is on a different path from the data in `/var/lib/cloudmorrow`, and a
copy of the data directory on its own opens nothing. The service unit
runs with `ProtectSystem=strict`, so the service cannot write `/etc`; the
installer generates the key as root, owned by the service user, mode 600.
A server that boots without a key file at the configured path generates
one there, if it can write there.

**Back it up with the data, and never instead of it.** Lose the key and
every note, message, event, task, dotfile and secret is gone; there is no
recovery, by design. Keep a copy somewhere that is not the server. Keep
it apart from your backup of the data, or the backup is as good as plain.

**Every command sees the same key.** `cloudmorrow-server` reads the
config and registers the key for the database before it opens it, so
`user create` and the rest seal and open under the service's key. A
program that opens the database through `db.connect` without going through
the config falls back to `secrets.key` beside the database, which is only
right when that is where the key is. Use the config.

**Changing the key.**

```
sudo systemctl stop cloudmorrow
sudo -u cloudmorrow /opt/cloudmorrow/venv/bin/cloudmorrow-server rotate-key
sudo systemctl start cloudmorrow
```

Every sealed row, every secret and its fingerprint, and every sealed file
under every user's notes tree is opened under the key in place and sealed
under a new one, which then replaces the file. The database part is one
transaction; the files are replaced one at a time, each written whole and
renamed into place. The old key is kept as `<key_file>.old` until you
delete it, which you should do once the service is up and you have opened
a note. The service must be stopped: a row written under the old key
while rotation runs is a row nobody can open afterwards.

## Older servers

**The database** is migrated on the first connection after the upgrade.
`schema_meta` holds a `sealed` version; a database below it has every
listed column of every listed table sealed in one `BEGIN IMMEDIATE`
transaction, then the version written. A second worker booting at the
same moment waits on the lock, reads the version, and does nothing. From
then on every read expects ciphertext, and there is no sniffing: a message
that happens to look like `s1:...` is still a message. The table is
versioned so a column sealed in a later release migrates on its own
without touching the rest; an entry that has shipped is never edited.

**The notes** are swept at boot: every user's notes tree, every file not
starting with the magic, sealed in place. Reading is tolerant in the
other direction — a plain file reads as itself — so a file dropped into a
notes directory by hand is readable at once and ciphertext after the next
start. Writing always seals.

## In transit

TLS ends at the reverse proxy, Caddy or nginx, and the server listens on
plain HTTP behind it on the same machine. The proxy is the one plain hop,
and it is on the loopback. Three things make sure it stays the only one.

**The server insists.** `require_tls` is on whenever `public_url` is
https (set it explicitly to override). A request whose scheme is not https
is answered 426 Upgrade Required. The scheme is what uvicorn's
proxy-header handling says it is: `X-Forwarded-Proto` from a trusted proxy
(127.0.0.1 by default; set uvicorn's `forwarded_allow_ips` if the proxy is
another box), else the socket's own. A request from this machine that
carries no proxy header — a `curl 127.0.0.1:8787` on the box, a test
client — is let through: it crosses no wire. Every https answer carries
`Strict-Transport-Security` for a year, so a browser that has seen the app
never tries plain http again.

**The clients refuse.** The TUI, the CLI and the agent will not open a
connection to a plain `http://` address unless it is this machine
(`localhost`, `127.0.0.1`, `::1`) or their config says
`allow_insecure_http = true`. That setting is for a box you have decided
to reach in the clear, on purpose; `cloudmorrow config set
allow_insecure_http true` sets it, and the agent copies it from the
client at enrolment.

**What is not there yet.** A machine share — a directory on one of your
machines, served by the agent there — is served over plain HTTP on the
LAN with Basic auth, because the agent has no certificate anyone trusts.
It is the one place content and credentials still cross a wire
unencrypted. The fix is a small certificate authority on the server,
issuing each agent a certificate at enrolment, with clients trusting that
authority; until then, treat machine shares as LAN-only.

## What this does and does not protect against

| Threat | Covered |
| --- | --- |
| The database file or a backup of it is copied | yes: ciphertext without the key |
| The notes directory or a backup of it is copied | yes, apart from file names |
| The server's disk is lost, stolen or decommissioned | yes, if the key was not on it or was on a different volume; on a single-disk box, put the key in `/etc` and back the data up separately |
| Someone reads traffic on the network | yes, on every hop but a machine share |
| Someone with root on the running server | no: they have the key, and the server itself must be able to read everything |
| Another Cloudmorrow user on the same server | not by encryption: by the access checks in the API, which are the same as before |
| The operator, or Cloudmorrow itself | no; this is not end to end |
| Files in My Files and fileshares | no, not yet |

## For anyone adding a feature

If it stores something a person wrote, seal it. Add the table, its scope
columns and its content columns to `SEALED` under a **new** version in
`sealed.py`, seal on every write with `conn.seal` and open on every read
with `conn.unseal`, and never sort or `LIKE` on a sealed column in SQL.
`tests/test_sealed.py` shows the shape of a test that proves the disk
holds ciphertext.
