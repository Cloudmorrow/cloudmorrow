"""Snapshots: a frozen copy of a space's records, and the signed word of whoever validated it.

A company closes its books and wants an accountant to say "these, exactly
these, are right". The live ledger keeps moving; what the accountant
validates must not. So a **snapshot** copies the records of one space — a
ledger, a book, an association — at one moment into a **bundle**: one JSON
document, written the same way every time (sorted keys, records by id, no
whitespace), with a SHA-256 **digest** of its bytes. The bundle is kept
sealed in the database like any record; the digest is over the plain
bytes, so anybody holding the bundle recomputes it without this server's
key. The snapshot is a record of the `snapshot` datamodel: a space of its
own, shared with whoever may see it, locked from the moment it is made
(docs/ATTESTATIONS.md).

An **attestation** is what the outside party gives back: a verdict, a
statement, and an Ed25519 signature over the digest with a key of their
own, which this server never holds. The server checks the signature and
the digest before it keeps one, and keeps it locked beside the snapshot.
Anyone with the bundle and the attestation checks both offline:
`cm snapshot verify`.

Three ways in for the outside party: the bundle as a file, signed with
`cm attest sign` and brought back; a **guest link** to the one snapshot,
which reads the bundle and takes an attestation back and reaches nothing
else; or their own Cloudmorrow signing for them (`POST /api/attest`) with
the server's identity key, so they never handle a key.

Nothing here touches a datamodel that did not ask: only `snapshot` and
`attestation` are locked and server-made, and taking a snapshot reads
through the gate as the person asking, so it copies what they may see.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import shutil
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from cloudmorrow.server import crypto
from cloudmorrow.server.database import Database
from cloudmorrow.server.datamodels import Datamodel
from cloudmorrow.server.principal import GUEST, Principal
from cloudmorrow.server.recordfields import iso_stamp, parse_moment, utc_now
from cloudmorrow.server.records import Record, RecordError, RecordStore

__all__ = [
    "ATTESTATION_FORMAT",
    "BUNDLE_FORMAT",
    "SNAPSHOT",
    "ATTESTATION",
    "TABLES",
    "VERDICTS",
    "SnapshotStore",
    "canonical",
    "digest_of",
    "install_datamodels",
    "sign_attestation",
    "verify_attestation",
    "verify_bundle",
]

SNAPSHOT = "snapshot"
ATTESTATION = "attestation"
VERDICTS = ("validated", "qualified", "rejected")

# The first line of a bundle and of an attestation: what they are, and which
# shape. A reader that sees another number stops.
BUNDLE_FORMAT = 1
ATTESTATION_FORMAT = 1

# How long a guest link works unless asked otherwise, and the most it may.
GUEST_DAYS = 30
GUEST_DAYS_MOST = 365
GUEST_TOKEN_PREFIX = "cmg_"

# Made by schema.py, step 6.
TABLES = """
CREATE TABLE IF NOT EXISTS snapshot_bundles (
    -- One bundle per snapshot: the record is the envelope, this is the copy.
    snapshot_id TEXT    PRIMARY KEY,
    digest      TEXT    NOT NULL,
    size        INTEGER NOT NULL,
    -- The bundle's bytes as text, sealed to the snapshot (sealed.py, 5).
    bundle      TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_guests (
    -- A link given to somebody outside: the one snapshot it opens, and until when.
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT    NOT NULL,
    -- Only the hash is kept, as a Quill's token is: the link itself is
    -- shown once, when it is made.
    token_hash  TEXT    NOT NULL UNIQUE,
    label       TEXT    NOT NULL DEFAULT '',
    made_by     TEXT    NOT NULL,
    made_at     TEXT    NOT NULL,
    expires_at  TEXT    NOT NULL,
    used_at     TEXT,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS snapshot_guests_snapshot ON snapshot_guests (snapshot_id);
"""


class SnapshotError(RecordError):
    """Something about the snapshot or the attestation does not hold."""


class NotSigned(SnapshotError):
    """An attestation whose signature, digest or shape is wrong."""


# -- the bytes ---------------------------------------------------------------------
def canonical(document: object) -> bytes:
    """One way to write a document, so the same content is the same bytes."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def verify_bundle(data: bytes) -> dict:
    """The bundle as a document, if it is one and its bytes are canonical."""
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SnapshotError(f"not a bundle: {exc}") from exc
    if not isinstance(document, dict) or document.get("cloudmorrow_snapshot") != BUNDLE_FORMAT:
        raise SnapshotError("not a Cloudmorrow snapshot bundle")
    if canonical(document) != data:
        raise SnapshotError("the bundle's bytes are not canonical: it was rewritten")
    return document


# -- attestations, as documents ----------------------------------------------------
def sign_attestation(
    key,
    *,
    digest: str,
    snapshot: str,
    verdict: str,
    statement: str = "",
    signer_name: str,
    signer_organisation: str = "",
    series: str = "",
    version: int = 0,
    signed_at: str | None = None,
) -> dict:
    """An attestation on one digest, signed with *key*: the document that travels."""
    if verdict not in VERDICTS:
        raise SnapshotError(f"verdict is one of {', '.join(VERDICTS)}")
    if not digest.startswith("sha256:"):
        raise SnapshotError("digest is sha256:<hex>")
    if not signer_name.strip():
        raise SnapshotError("the signer has a name")
    document = {
        "cloudmorrow_attestation": ATTESTATION_FORMAT,
        "snapshot": snapshot,
        "digest": digest,
        "series": series,
        "version": int(version or 0),
        "verdict": verdict,
        "statement": statement,
        "signer": {
            "name": signer_name.strip(),
            "organisation": signer_organisation.strip(),
            "key": crypto.public_key_text(key),
        },
        "signed_at": signed_at or iso_stamp(),
    }
    document["signature"] = crypto.sign(key, canonical(document))
    return document


def verify_attestation(document: object, *, digest: str | None = None, snapshot: str | None = None) -> dict:
    """The attestation, if its shape holds and its signature is its signer's over
    its content — and, when given, if it is on this *digest* and this *snapshot*."""
    if not isinstance(document, dict) or document.get("cloudmorrow_attestation") != ATTESTATION_FORMAT:
        raise NotSigned("not a Cloudmorrow attestation")
    signer = document.get("signer")
    signature = document.get("signature")
    if not isinstance(signer, dict) or not isinstance(signature, str):
        raise NotSigned("the attestation names no signer, or carries no signature")
    for name in ("name", "key"):
        if not isinstance(signer.get(name), str) or not signer[name]:
            raise NotSigned(f"the signer has no {name}")
    if document.get("verdict") not in VERDICTS:
        raise NotSigned(f"the verdict is one of {', '.join(VERDICTS)}")
    if not isinstance(document.get("digest"), str) or not document["digest"].startswith("sha256:"):
        raise NotSigned("the attestation names no digest")
    if parse_moment(str(document.get("signed_at", ""))) is None:
        raise NotSigned("signed_at is a date and time, ISO 8601")
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    try:
        good = crypto.verify_signature(signer["key"], canonical(unsigned), signature)
    except ValueError as exc:
        raise NotSigned(str(exc)) from exc
    if not good:
        raise NotSigned("the signature is not the signer's over this attestation")
    if digest is not None and document["digest"] != digest:
        raise NotSigned("the attestation is on another digest, not this snapshot's")
    if snapshot is not None and document.get("snapshot") not in ("", snapshot):
        raise NotSigned("the attestation names another snapshot")
    return document


# -- the datamodels the core brings ---------------------------------------------------
def install_datamodels(datamodels_dir: Path) -> list[str]:
    """Put `snapshot` and `attestation` with the server's foundational datamodels,
    unless they are there at this version or newer. Returns what was written."""
    written: list[str] = []
    folder = resources.files("cloudmorrow.server") / "foundation"
    for name in (SNAPSHOT, ATTESTATION):
        source = folder / f"{name}.toml"
        target = datamodels_dir / f"{name}.toml"
        if target.exists() and _version_in(target.read_text(encoding="utf-8")) >= _version_in(
            source.read_text(encoding="utf-8")
        ):
            continue
        datamodels_dir.mkdir(parents=True, exist_ok=True)
        with resources.as_file(source) as path:
            shutil.copyfile(path, target)
        written.append(name)
    return written


def _version_in(toml_text: str) -> int:
    import tomllib

    try:
        return int(tomllib.loads(toml_text).get("datamodel", {}).get("version", 0))
    except (tomllib.TOMLDecodeError, TypeError, ValueError):
        return 0


# -- the store ---------------------------------------------------------------------
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SnapshotStore:
    """Takes snapshots, keeps their bundles, checks and keeps attestations, and
    hands out guest links. Every read and write of a record goes through the
    record store, as the principal asking."""

    def __init__(self, db: Database, records: RecordStore, *, identity_key: Path, public_url=None) -> None:
        self.db = db
        self.records = records
        self._identity_path = identity_key
        self._identity = None
        # What a guest link starts with: the server's address, when it has one.
        self._public_url = public_url or (lambda: "")

    # -- identity: the key this server signs with, for its own people ------------
    @property
    def identity(self):
        if self._identity is None:
            self._identity = crypto.load_or_create_signing_key(self._identity_path)
        return self._identity

    def identity_key(self) -> str:
        return crypto.public_key_text(self.identity)

    # -- taking -------------------------------------------------------------------------
    def take(
        self,
        principal: Principal,
        space_model: str,
        space_id: str,
        *,
        title: str = "",
        series: str = "",
        models: Iterable[str] = (),
        period: dict | None = None,
        notes: str = "",
        scope: str | None = None,
        members: Iterable[str] = (),
    ) -> Record:
        """Copy the records of one space into a sealed snapshot. Returns the snapshot.

        *models* are the datamodels in the space to copy; none means every
        one installed. *period* is `{field, from, to}`: on the datamodels
        that have the field, only the records in that range; on those that
        do not, only the records linked to one that was kept — the postings
        of the entries in the year.
        """
        space_def = self.records.model(space_model)
        if not space_def.space:
            raise SnapshotError(f"{space_model} is not a space; a snapshot copies a space")
        space = self.records.get(principal, space_model, space_id)
        wanted = self._models_in(space_def, models)
        period = self._period(wanted, period)
        kept = self._copy(principal, space_def, space, wanted, period)
        document = {
            "cloudmorrow_snapshot": BUNDLE_FORMAT,
            "taken_at": iso_stamp(),
            "taken_by": principal.username,
            "space": {"model": space_def.id, "id": space.id, "fields": dict(space.fields)},
            "period": period,
            "datamodels": {
                m.id: {"version": m.version, "fields": [{"name": f.name, "kind": f.kind} for f in m.fields]}
                for m in [space_def, *wanted.values()]
            },
            "records": {model_id: [_as_copied(r) for r in rows] for model_id, rows in kept.items()},
        }
        data = canonical(document)
        digest = digest_of(data)
        count = sum(len(rows) for rows in kept.values())
        version, previous = self._next_version(principal, series, space.id)
        space_name = str(space.fields.get(space_def.title) or space_def.label)
        fields = {
            "title": title.strip() or f"{space_name} {document['taken_at'][:10]}",
            "series": series.strip(),
            "version": version,
            "supersedes": previous,
            "of_model": space_def.id,
            "of_space": space.id,
            "of_title": str(space.fields.get(space_def.title) or ""),
            "datamodels": list(kept),
            "period": period,
            "records": count,
            "digest": digest,
            "status": "sealed",
            "sealed_at": document["taken_at"],
            "notes": notes,
        }
        made = self.records.create(principal, SNAPSHOT, fields, scope=scope, members=members, by_server=True)
        try:
            with self.db.connect() as conn:
                sealed = conn.seal("snapshot_bundles", "bundle", (made.id,), data.decode("utf-8"))
                conn.execute(
                    "INSERT INTO snapshot_bundles (snapshot_id, digest, size, bundle) VALUES (?, ?, ?, ?)",
                    (made.id, digest, len(data), sealed),
                )
                conn.commit()
            conn.close()
        except Exception:
            # A snapshot without its bundle is nothing: the envelope goes too.
            with self.db.connect() as conn:
                conn.execute("DELETE FROM records WHERE id = ?", (made.id,))
                conn.execute("DELETE FROM record_members WHERE space_id = ?", (made.id,))
                conn.commit()
            conn.close()
            raise
        return made

    def _models_in(self, space_def: Datamodel, asked: Iterable[str]) -> dict[str, Datamodel]:
        installed = self.records.models()
        inside = {m.id: m for m in installed.values() if m.in_space and m.get_field(m.in_space).to == space_def.id}
        asked = [str(m).strip() for m in asked if str(m).strip()]
        if not asked:
            return {k: inside[k] for k in sorted(inside)}
        chosen: dict[str, Datamodel] = {}
        for model_id in asked:
            if model_id not in inside:
                raise SnapshotError(f"{model_id} is not a datamodel in a {space_def.label.lower()}")
            chosen[model_id] = inside[model_id]
        return chosen

    @staticmethod
    def _period(wanted: dict[str, Datamodel], period: dict | None) -> dict | None:
        if not period:
            return None
        if not isinstance(period, dict) or not str(period.get("field", "")).strip():
            raise SnapshotError("period is { field, from, to }")
        name = str(period["field"]).strip()
        start = str(period.get("from") or "").strip()
        end = str(period.get("to") or "").strip()
        if not start and not end:
            raise SnapshotError("period names from, to, or both")
        for moment in (start, end):
            if moment and parse_moment(moment) is None:
                raise SnapshotError("period's from and to are dates, YYYY-MM-DD")
        having = [m for m in wanted.values() if name in m.by_name]
        if not having:
            raise SnapshotError(f"no datamodel copied has a field {name!r}")
        for m in having:
            f = m.get_field(name)
            if not f.indexed or f.kind not in ("date", "datetime"):
                raise SnapshotError(f"{m.id}.{name} is not an indexed date")
        return {"field": name, "from": start or None, "to": end or None}

    def _copy(
        self,
        principal: Principal,
        space_def: Datamodel,
        space: Record,
        wanted: dict[str, Datamodel],
        period: dict | None,
    ) -> dict[str, list[Record]]:
        kept: dict[str, list[Record]] = {}
        filtered: set[str] = set()
        for model_id, model in wanted.items():
            where: dict[str, object] = {model.in_space: space.id}
            if period and period["field"] in model.by_name:
                if period["from"]:
                    where[f"{period['field']}__gte"] = period["from"]
                if period["to"]:
                    where[f"{period['field']}__lte"] = period["to"]
                filtered.add(model_id)
            kept[model_id] = self.records.every(principal, model_id, where)
        if period:
            # What hangs off the period: a posting is in the year its entry is.
            # Repeated until nothing more drops, for links through links.
            ids = {model_id: {r.id for r in rows} for model_id, rows in kept.items()}
            changed = True
            while changed:
                changed = False
                for model_id, model in wanted.items():
                    if model_id in filtered:
                        continue
                    links = [
                        f for f in model.fields if f.kind == "link" and f.to in filtered and f.name != model.in_space
                    ]
                    if not links:
                        continue
                    before = len(kept[model_id])
                    kept[model_id] = [
                        r
                        for r in kept[model_id]
                        if all(not r.fields.get(f.name) or r.fields[f.name] in ids[f.to] for f in links)
                    ]
                    ids[model_id] = {r.id for r in kept[model_id]}
                    filtered.add(model_id)
                    changed = changed or len(kept[model_id]) != before
        for rows in kept.values():
            rows.sort(key=lambda r: r.id)
        return kept

    def _next_version(self, principal: Principal, series: str, space_id: str) -> tuple[int, str | None]:
        if not series.strip():
            return 1, None
        earlier = self.records.list(principal, SNAPSHOT, {"series": series.strip(), "of_space": space_id})
        if not earlier:
            return 1, None
        latest = max(earlier, key=lambda r: (int(r.fields.get("version") or 0), r.created_at))
        return int(latest.fields.get("version") or 0) + 1, latest.id

    # -- reading ------------------------------------------------------------------------
    def get(self, principal: Principal, snapshot_id: str) -> Record:
        return self.records.get(principal, SNAPSHOT, snapshot_id)

    def bundle(self, principal: Principal, snapshot_id: str) -> tuple[bytes, str]:
        """The bundle's bytes and its digest, for whoever may see the snapshot."""
        self.get(principal, snapshot_id)
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM snapshot_bundles WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
            if row is None:
                raise SnapshotError("this snapshot has no bundle")
            text = conn.unseal("snapshot_bundles", "bundle", (snapshot_id,), row["bundle"])
        conn.close()
        return (text or "").encode("utf-8"), row["digest"]

    def attestations(self, principal: Principal, snapshot_id: str) -> list[Record]:
        return self.records.list(principal, ATTESTATION, {"snapshot": snapshot_id})

    def describe(self, principal: Principal, snapshot_id: str, *, guests: bool = True) -> dict:
        """The snapshot, its attestations, and whether its bundle still hashes to its digest."""
        snapshot = self.get(principal, snapshot_id)
        data, stored = self.bundle(principal, snapshot_id)
        intact = digest_of(data) == stored == snapshot.fields.get("digest")
        told = {
            "snapshot": snapshot.to_dict(),
            "digest": snapshot.fields.get("digest"),
            "intact": intact,
            "size": len(data),
            "attestations": [a.to_dict() for a in self.attestations(principal, snapshot_id)],
        }
        if guests and principal.kind != GUEST:
            told["guests"] = self.guests(principal, snapshot_id)
        return told

    def withdraw(self, principal: Principal, snapshot_id: str) -> Record:
        """Mark a snapshot as not to be relied on. It stays, with its attestations."""
        return self.records.update(principal, SNAPSHOT, snapshot_id, {"status": "withdrawn"})

    # -- attesting ---------------------------------------------------------------------
    def attest(self, principal: Principal, snapshot_id: str, document: object) -> Record:
        """Keep an attestation on this snapshot, once its signature and digest check out."""
        snapshot = self.get(principal, snapshot_id)
        if snapshot.fields.get("status") != "sealed":
            raise SnapshotError("this snapshot is withdrawn and takes no attestation")
        checked = verify_attestation(document, digest=str(snapshot.fields.get("digest")), snapshot=snapshot_id)
        signer = checked["signer"]
        fields = {
            "snapshot": snapshot_id,
            "digest": checked["digest"],
            "verdict": checked["verdict"],
            "statement": str(checked.get("statement") or ""),
            "signer_name": signer["name"],
            "signer_organisation": str(signer.get("organisation") or ""),
            "signer_key": signer["key"],
            "signer_fingerprint": crypto.key_fingerprint(signer["key"]),
            "signed_at": checked["signed_at"],
            "signature": checked["signature"],
        }
        return self.records.create(principal, ATTESTATION, fields, by_server=True)

    def sign(self, username: str, display_name: str, organisation: str, **what) -> dict:
        """An attestation signed with this server's identity, for one of its own people."""
        return sign_attestation(
            self.identity,
            signer_name=display_name or username,
            signer_organisation=organisation,
            **what,
        )

    # -- guests ------------------------------------------------------------------------
    def invite(self, principal: Principal, snapshot_id: str, *, label: str = "", days: int = GUEST_DAYS) -> dict:
        """A link that opens this one snapshot to somebody outside, for *days*."""
        snapshot = self.get(principal, snapshot_id)
        if snapshot.owner != principal.username and not principal.admin:
            raise SnapshotError("only whoever took a snapshot gives out links to it")
        if not 1 <= int(days) <= GUEST_DAYS_MOST:
            raise SnapshotError(f"a guest link lasts from 1 to {GUEST_DAYS_MOST} days")
        token = GUEST_TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = utc_now()
        expires = iso_stamp(now + dt.timedelta(days=int(days)))
        with self.db.connect() as conn:
            guest_id = conn.insert(
                "INSERT INTO snapshot_guests (snapshot_id, token_hash, label, made_by, made_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (snapshot_id, _hash(token), label.strip()[:120], principal.username, iso_stamp(now), expires),
            )
            conn.commit()
        conn.close()
        return {
            "id": guest_id,
            "snapshot": snapshot_id,
            "label": label.strip()[:120],
            "token": token,
            "url": self.guest_url(snapshot_id, token),
            "expires_at": expires,
        }

    def guest_url(self, snapshot_id: str, token: str) -> str:
        base = (self._public_url() or "").rstrip("/")
        return f"{base}/api/guest/snapshots/{snapshot_id}?token={token}"

    def guests(self, principal: Principal, snapshot_id: str) -> list[dict]:
        self.get(principal, snapshot_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, label, made_by, made_at, expires_at, used_at, revoked_at FROM snapshot_guests"
                " WHERE snapshot_id = ? ORDER BY id",
                (snapshot_id,),
            ).fetchall()
        conn.close()
        now = iso_stamp()
        return [dict(row) | {"live": row["revoked_at"] is None and row["expires_at"] > now} for row in rows]

    def revoke(self, principal: Principal, snapshot_id: str, guest_id: int) -> None:
        snapshot = self.get(principal, snapshot_id)
        if snapshot.owner != principal.username and not principal.admin:
            raise SnapshotError("only whoever took a snapshot takes its links back")
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE snapshot_guests SET revoked_at = ? WHERE id = ? AND snapshot_id = ? AND revoked_at IS NULL",
                (iso_stamp(), int(guest_id), snapshot_id),
            )
            conn.commit()
        conn.close()

    def guest_for(self, snapshot_id: str, token: str) -> Principal | None:
        """Who a guest link makes its bearer: the snapshot owner's guest, at that
        snapshot and nothing else. None for a link that is wrong, spent or revoked."""
        if not token or not token.startswith(GUEST_TOKEN_PREFIX):
            return None
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM snapshot_guests WHERE token_hash = ?", (_hash(token),)).fetchone()
            spent = row is None or row["snapshot_id"] != snapshot_id or row["revoked_at"]
            if spent or row["expires_at"] <= iso_stamp():
                conn.close()
                return None
            owner = conn.execute("SELECT owner FROM records WHERE id = ?", (snapshot_id,)).fetchone()
            conn.execute("UPDATE snapshot_guests SET used_at = ? WHERE id = ?", (iso_stamp(), row["id"]))
            conn.commit()
        conn.close()
        if owner is None:
            return None
        label = row["label"] or f"link {row['id']}"
        return Principal(GUEST, owner["owner"], quill=f"guest:{label}", models=frozenset({SNAPSHOT, ATTESTATION}))


def _as_copied(record: Record) -> dict:
    """A record as the bundle keeps it: the envelope that does not move, and the fields."""
    return {
        "id": record.id,
        "rev": record.rev,
        "owner": record.owner,
        "position": record.position,
        "written_by": record.written_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "fields": dict(record.fields),
    }
