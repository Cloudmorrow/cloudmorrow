# Snapshots and attestations: a frozen copy, and somebody's signed word on it

A company keeps its books in Cloudmorrow and wants an accountant to say
"these, exactly these, are right". The live ledger keeps moving; what the
accountant validates must not. And the accountant's word has to be theirs:
a stamp the company's own server could write for them is worth nothing to
anybody reading the annual report.

So: a **snapshot** is a frozen copy of one space's records at one moment —
the ledger at year end, the member roll on 31 December, a book of
customers at handover — with a **digest** of it that never changes. An
**attestation** is what an outside party gives back: a verdict and a
statement, signed over that digest with a key of their own, which the
company's server never holds. Both are records, kept beside the data
they are about, and both are locked the moment they are made.

Nothing here touches how anything else works. Only the two datamodels on
this page are locked or server-made; taking a snapshot copies what the
person taking it may see, through the gate, and changes nothing it copies.

## The words

| word | what it is |
| --- | --- |
| **snapshot** | A record of the `snapshot` datamodel: a space of its own, shared with whoever may see it, naming the space it copies, the datamodels and period it kept, the digest, and the number of records. Made by the server only (`POST /api/snapshots`), sealed from the start. |
| **bundle** | The copy itself: one JSON document — the space, the datamodels' shapes, every record copied with its id, revision, owner and fields — written the same way every time (sorted keys, records by id, no whitespace). Kept sealed in the database like any record; served as bytes, exactly as hashed. |
| **digest** | `sha256:<hex>` of the bundle's bytes. The one thing a stamp binds to: anybody holding the bundle recomputes it without this server's key. |
| **series** | What a snapshot is one version of: "Books 2025". The server counts versions in a series and links each to the one before, so a snapshot rejected, corrected and taken again is version 2, superseding version 1. |
| **attestation** | A record of the `attestation` datamodel, in the snapshot's space: a verdict (`validated`, `qualified`, `rejected`), a statement, who signed, their public key, and an Ed25519 signature over the digest. Checked by the server before it is kept; locked once it is. |
| **guest link** | A link to one snapshot for somebody with no account here: it reads the snapshot and its bundle, and takes an attestation back, and reaches nothing else on the server. Lasts as long as it was given (thirty days unless said), and can be taken back. |
| **identity** | The Ed25519 key a server signs with, for its own people validating a snapshot somebody sent *them* — so an accountant who runs Cloudmorrow never handles a key. `<data_dir>/identity.key`, made on first use. |
| **locked** | What a datamodel says when a record of it is never changed or deleted again: `locked = true` from the moment it is made, or `locked = { field, value, allow }` once a field takes a value, with the one move the lock allows. Opt-in, per datamodel. |

## The rules

1. **A snapshot is a copy, not a view.** The records table keeps no history
   of values — the change log says who touched which fields, never what
   they were — so the bundle is the only record of how things stood. The
   live space moves on; the snapshot does not. Taken through the gate as
   the person asking: it holds what they may see, and nothing else.
2. **The digest is over plain bytes.** The bundle is sealed at rest under
   the server's key like every record, but what is hashed, and what is
   signed, is the plain canonical JSON. Bundle, attestation, nothing else:
   `cm snapshot verify books-2025.json books-2025.attestation.json` checks
   both on any machine with no server at all.
3. **Locked means locked.** A sealed snapshot takes one change — its status
   to `withdrawn`, meaning *do not rely on this* — and from then none. It
   is never deleted. An attestation is locked from the moment it is kept.
   The record store refuses every other change and every delete with
   `423 Locked`, from the generic API and from a Quill's code alike. (An
   administrator with the database file can still alter the stored bundle:
   that is why the digest, not the lock, is what the stamp binds to — the
   bundle then fails to hash to its digest, and `intact` says so.)
4. **The stamp is the signer's, not the server's.** An attestation is an
   Ed25519 signature with the signer's own key over the digest, the
   verdict, the statement and the signer's name. The server that holds the
   data verifies it against the snapshot's digest before keeping it, and
   cannot make one. A stamp by the server's own identity is for the other
   direction: *this* server's people validating a snapshot sent to them.
5. **A guest reaches one snapshot.** A guest link is a capability, kept as
   a hash like a Quill's token: its bearer is the snapshot owner's guest at
   that snapshot, may read it and its bundle and leave an attestation, and
   is refused at every other address — the records API included.
6. **Circles rule it.** Whoever may `write` the `snapshot` datamodel may
   take one of a space they can see. A snapshot is its taker's, or shared
   with named people, or public, like any space; its attestations are seen
   by whoever sees it. A circle that gives no `snapshot` sees none.
7. **Only `snapshot` and `attestation` are locked and server-made.** The
   lock and `server_made` are settings a datamodel declares; nothing
   declares them but these two. `journal_entry`'s "posted, then never
   changed" is a candidate for `locked` in a later datamodels release, and
   is deliberately not changed by this.

## The flows

**Closing the books.** The bookkeeper takes a snapshot of the ledger for
the year:

```
cm snapshot take ledger r_1a2b3c --series "Books 2025" --period on:2025-01-01:2025-12-31
cm snapshot bundle r_9f8e7d books-2025.json
```

`--period field:from:to` keeps, on the datamodels that have the field,
only the records in that range — and on those that do not, only the
records linked to one that was kept: the postings of the entries in the
year. Either date may be left blank. Without `--period`, everything in the
space. `--model` names which datamodels in the space to copy; none means
every one.

**The accountant, with a file.** They get `books-2025.json` by whatever
means, read it, and sign:

```
cm attest sign books-2025.json --verdict validated --statement "Reviewed against the bank statements." --name "Jane Doe" --organisation "Acme Accounting"
```

A key of their own is made on first use at `<config dir>/identity.key`;
`cm attest key` prints its public half for anybody who wants to check their
stamps. `books-2025.attestation.json` is written beside the bundle and
sent back; the bookkeeper keeps it with the snapshot:

```
cm snapshot attest r_9f8e7d books-2025.attestation.json
cm snapshot show r_9f8e7d
```

The server verifies the signature over the digest before it keeps it.
Anybody may check the pair offline: `cm snapshot verify books-2025.json
books-2025.attestation.json`.

**The accountant, with a link.** No file, no account:

```
cm snapshot guest r_9f8e7d --label "Acme Accounting" --days 60       # the bookkeeper; the link is shown once
cm attest sign https://cloud.example/api/guest/snapshots/r_9f8e7d?token=cmg_… --verdict validated   # the accountant
```

The second command fetches the bundle through the link, checks it hashes
to the digest the server states, signs, and sends the attestation back
through the same link. `cm snapshot guests` lists the links given out,
with whether each was used; `cm snapshot revoke` takes one back.

**The accountant with a Cloudmorrow of their own** signs with their
server's identity instead of a key on their machine:

```
cm attest sign books-2025.json --verdict qualified --via-server
```

Their server signs in their name, with their cloud's name as the
organisation; `GET /api/identity` on it is the public key a reader checks
against.

**When it is wrong.** The accountant rejects version 1 with a statement
saying why. The bookkeeper fixes the live ledger and takes the series
again: version 2, superseding 1. The accountant validates version 2. Each
stamp names one digest, so there is never doubt which state was validated;
version 1 stays, locked, with its rejection on it. A snapshot that should
not be relied on at all is withdrawn (`cm snapshot withdraw`): it stays,
with its attestations, and takes no more.

## The bundle

```json
{
  "cloudmorrow_snapshot": 1,
  "taken_at": "2026-01-05T09:12:00+00:00",
  "taken_by": "bram",
  "space": { "model": "ledger", "id": "r_1a2b3c", "fields": { "name": "Bramlabs", "currency": "EUR", … } },
  "period": { "field": "on", "from": "2025-01-01", "to": "2025-12-31" },
  "datamodels": { "ledger": { "version": 1, "fields": [ { "name": "name", "kind": "string" }, … ] }, "journal_entry": { … }, … },
  "records": {
    "account": [ { "id": "r_…", "rev": 3, "owner": "bram", "position": 0, "written_by": "books", "created_at": "…", "updated_at": "…", "fields": { … } }, … ],
    "journal_entry": [ … ],
    "posting": [ … ]
  }
}
```

Canonical: keys sorted, records in each datamodel sorted by id, no
whitespace, UTF-8, non-ASCII left as it is. `cloudmorrow_snapshot` is the
shape's number; a reader that sees another stops. A `secret` field's value
is never copied. The bundle is also the first whole export of a space
Cloudmorrow has: what it holds is what a person's records of those
datamodels are.

## The attestation

```json
{
  "cloudmorrow_attestation": 1,
  "snapshot": "r_9f8e7d",
  "digest": "sha256:…",
  "series": "Books 2025",
  "version": 1,
  "verdict": "validated",
  "statement": "Reviewed against the bank statements.",
  "signer": { "name": "Jane Doe", "organisation": "Acme Accounting", "key": "ed25519:<base64>" },
  "signed_at": "2026-01-20T15:00:00+00:00",
  "signature": "<base64>"
}
```

The signature is Ed25519 over the canonical JSON of everything but
`signature`. The server keeps every field of it on the `attestation`
record, with the key's fingerprint (the first sixteen hex digits of its
SHA-256) for reading. A signer's key is theirs to publish; the registry
naming verified signers, so a stamp reads "Acme Accounting, verified" and
not a fingerprint, is *not yet* (below).

## The API

| call | what |
| --- | --- |
| `POST /api/snapshots` | `{space_model, space_id, title?, series?, models?, period?, notes?, scope?, members?}`: take one; answers as the next call does |
| `GET /api/snapshots/{id}` | the snapshot, its digest, `intact` (the bundle still hashes to it), its size, its attestations, and its guest links |
| `GET /api/snapshots/{id}/bundle` | the bundle's bytes, with `X-Snapshot-Digest` and a filename |
| `POST /api/snapshots/{id}/withdraw` | mark it as not to be relied on |
| `POST /api/snapshots/{id}/attestations` | bring an attestation back; 400 with why when it does not check out |
| `POST`/`GET` `/api/snapshots/{id}/guests`, `DELETE …/guests/{n}` | `{label?, days?}`: a link, shown once; the links given out; take one back |
| `GET /api/guest/snapshots/{id}?token=`, `…/bundle`, `POST …/attestations` | what a guest link opens; the token as `?token=` or a bearer |
| `GET /api/identity` | this server's signing key, public half, and its fingerprint |
| `POST /api/attest` | `{digest, verdict, statement?, snapshot?, series?, version?}`: an attestation signed with this server's identity, in your name |
| `GET /api/records/snapshot`, `GET /api/records/attestation` | the records themselves, through the record API like any other; writing them there is refused (`server_made`), changing them is `423` |

On the command line it is `cm snapshot take | list | show | bundle |
attest | guest | guests | revoke | withdraw | verify` and `cm attest
sign | verify | key`.

## Storage

Two tables beside `records`:

```
snapshot_bundles(snapshot_id, digest, size, bundle SEALED)   -- bound to the snapshot
snapshot_guests(id, snapshot_id, token_hash, label, made_by, made_at, expires_at, used_at, revoked_at)
```

The snapshot and attestation records are rows in `records` like any
other's, sealed to the snapshot. The identity key is
`<data_dir>/identity.key`, PEM, mode 600: back it up with the data, since a
stamp given under it names its public half. The two datamodels are shipped
with the core (`server/foundation/`) and put with the server's
foundational datamodels at boot, so a server needs no catalog release to
have them; the same files are in `Cloudmorrow/datamodels` under the
Attestations domain, for the registry page and for Quills that use them.

## Not yet

- **Screens.** A Quill over `snapshot` and `attestation` — a list, a sheet
  with the badge "validated by Jane Doe, Acme Accounting, 20 January", a
  "close the year" action on the accounting Quill — is the kit's work and
  waits for an accounting Quill to put it on. The API and the command line
  are whole without it.
- **Verified signers.** The registry publishing signers' keys, so a stamp
  carries a name a reader can trust rather than a fingerprint to compare.
- **A statement page.** A printable page of a snapshot's digest and its
  attestations, which is what gets cited in a report.
- **Locking `journal_entry`.** `locked = { field = "status", value =
  "posted", allow = ["void"] }` is what its description already says; it
  goes in a datamodels release, not here.
- **What hangs off a period, through a space.** A record in the period is
  found by its own date field, or by a link to one that was; a record
  linked only through a third datamodel that has no date is kept whole.

## Where the code is

| part | where |
| --- | --- |
| `locked` and `server_made` on a datamodel | `server/datamodels.py` (`Lock`, `_lock`) |
| the lock enforced, the server-made refusal, the uncapped listing a copy reads | `server/records.py` (`_unlocked`, `create(by_server=)`, `every`, `RecordLockedError`) |
| the guest principal | `server/principal.py` (`GUEST`) |
| signing: the key, the public half, sign and verify | `server/crypto.py` |
| taking, the bundle, the digest, attestations checked and kept, guest links, the identity | `server/snapshots.py` |
| the datamodels the core brings | `server/foundation/snapshot.toml`, `attestation.toml` |
| the routes | `server/routes/snapshots.py` |
| the sealed column and the tables | `server/sealed.py` (5), `server/schema.py` (step 6) |
| the command line and the client | `cli/snapshot.py`, `cli/attest.py`, `client/api.py` |
| the tests | `tests/test_snapshots.py` |
