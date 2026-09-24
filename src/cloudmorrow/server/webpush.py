"""Push notifications, so the phone lights up when nobody is looking at it.

A web app on an iOS home screen is not running most of the time. Polling only
works while it is open, and the whole point of a message count on the icon is
that it is right when the app is closed. The only thing that reaches a closed
web app is a push through the browser vendor's service — Apple's, for an app
on an iPhone — which wakes the service worker, which shows the banner and
sets the badge.

Three specifications meet here, and all three are implemented below rather
than pulled in, because the server's dependencies are FastAPI, pyjwt and
cryptography, and these need nothing that is not already in that list:

* **RFC 8030** — the request itself: a POST to the endpoint the browser gave
  us, with `TTL` and an opaque body.
* **RFC 8292 (VAPID)** — who is doing the pushing: an ES256 JWT saying which
  push service it is for and when it expires, signed with a P-256 key that
  lives beside the database. The public half of that key is what the browser
  is handed at subscribe time, which is what ties the two together.
* **RFC 8291 / RFC 8188 (aes128gcm)** — the body: encrypted to the
  subscription's own key, so the push service carries a message it cannot
  read.

The keypair is generated on first use into `<data_dir>/vapid.key` at mode
600. Losing it does not lose any data, but every subscription made under it
stops working, and each device has to be asked again — so it is worth backing
up with the database.

Nothing here knows what a message is. It is handed a title, a body and a
badge number; chat decides what those say.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import socket
import sqlite3
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cloudmorrow.server.db import Connection, connect

__all__ = [
    "PushStore",
    "Subscription",
    "encrypt",
    "load_or_create_vapid_key",
    "public_key_b64",
    "vapid_headers",
]

# How long the push service should hold a message for a phone that is off.
TTL_SECONDS = 24 * 60 * 60
# The JWT's life. RFC 8292 allows at most 24 hours; half a day means a clock
# an hour out is still fine.
JWT_HOURS = 12
# One record, and the payload has to fit in it with room for the tag.
RECORD_SIZE = 4096
MAX_PAYLOAD = RECORD_SIZE - 17
# A subscription that has failed this many times in a row is not coming back.
MAX_FAILURES = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL,
    -- The push service's URL for this one device. Unique: a browser hands
    -- out one per registration, and re-subscribing replaces the row rather
    -- than making a second one that pushes the same phone twice.
    endpoint   TEXT    NOT NULL UNIQUE,
    -- The device's public key and auth secret, base64url, as the browser's
    -- PushSubscription reports them. What the body is encrypted to.
    p256dh     TEXT    NOT NULL,
    auth       TEXT    NOT NULL,
    -- Whatever the browser called itself, so the list in Me is readable.
    label      TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL,
    last_ok    TEXT,
    -- Consecutive failures. Reset on every delivery; at MAX_FAILURES the
    -- row is dropped, because a push service that keeps refusing is telling
    -- us the app is gone.
    failures   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS push_subscriptions_user ON push_subscriptions (username);
"""


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


def b64(raw: bytes) -> str:
    """base64url, unpadded — how every key in this protocol is written."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def unb64(text: str) -> bytes:
    text = text.strip().replace("+", "-").replace("/", "_")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# -- the server's key ---------------------------------------------------------
def load_or_create_vapid_key(path: Path) -> ec.EllipticCurvePrivateKey:
    """The P-256 key this server signs its pushes with, made on first use."""
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    try:
        # Written private, rather than made public and locked down after.
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Two workers booted together; whichever lost reads what won.
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    with os.fdopen(handle, "wb") as file:
        file.write(pem)
    return key


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    """A public key as the 65 uncompressed bytes the web push specs speak in."""
    return key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )


def public_key_b64(key: ec.EllipticCurvePrivateKey) -> str:
    """What the browser is given as `applicationServerKey`."""
    return b64(_point(key.public_key()))


def default_subject(public_url: str = "") -> str:
    """Who to complain to, when a push service wants to.

    RFC 8292 wants a `mailto:` or an `https:` URL that identifies whoever is
    pushing. The server's own address is the truest answer it has.
    """
    if public_url.startswith("https://"):
        return public_url.rstrip("/")
    host = urlsplit(public_url).hostname if public_url else ""
    return f"mailto:cloudmorrow@{host or socket.gethostname() or 'localhost'}"


def vapid_headers(
    key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str
) -> dict[str, str]:
    """The `Authorization` header for one push, good for `JWT_HOURS`.

    The audience is the push service's origin and nothing more of the URL —
    the endpoint's path is the subscription, which the service knows and the
    token has no business naming.
    """
    parts = urlsplit(endpoint)
    token = jwt.encode(
        {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(
                (dt.datetime.now(tz=dt.UTC) + dt.timedelta(hours=JWT_HOURS)).timestamp()
            ),
            "sub": subject,
        },
        key,
        algorithm="ES256",
    )
    return {"Authorization": f"vapid t={token},k={public_key_b64(key)}"}


# -- the body -------------------------------------------------------------------
def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256, for the one-block outputs this protocol asks for."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload: bytes, p256dh: bytes, auth: bytes, *, salt: bytes | None = None,
            private_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Seal *payload* for one subscription: RFC 8291, in the aes128gcm of RFC 8188.

    The result is a whole body, header block and all — salt, record size, the
    ephemeral public key that the recipient needs to do the same maths from
    the other side, and then the ciphertext.

    *salt* and *private_key* are here for the tests, which need a run of this
    to be repeatable. Leave them alone and every push gets its own.
    """
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"a push payload is at most {MAX_PAYLOAD} bytes")
    salt = salt or os.urandom(16)
    server = private_key or ec.generate_private_key(ec.SECP256R1())
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    as_public = _point(server.public_key())

    shared = server.exchange(ec.ECDH(), ua_public)
    # RFC 8291 §3.4. The order of the two keys in key_info is the recipient's
    # then the sender's, and it is not symmetric: swap them and the phone
    # derives a different key and drops the message without a word.
    key_info = b"WebPush: info\x00" + p256dh + as_public
    ikm = hmac.new(auth, shared, hashlib.sha256).digest()
    ikm = hmac.new(ikm, key_info + b"\x01", hashlib.sha256).digest()

    content_key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)

    # 0x02 is the delimiter that says "last record". There is only one.
    ciphertext = AESGCM(content_key).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


# -- the subscriptions ------------------------------------------------------------
@dataclass(slots=True)
class Subscription:
    id: int
    username: str
    endpoint: str
    p256dh: str
    auth: str
    label: str

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "endpoint": self.endpoint}


def _subscription(conn: Connection, row: sqlite3.Row) -> Subscription:
    scope = (row["username"],)
    return Subscription(
        id=row["id"],
        username=row["username"],
        endpoint=row["endpoint"],
        p256dh=conn.unseal("push_subscriptions", "p256dh", scope, row["p256dh"]),
        auth=conn.unseal("push_subscriptions", "auth", scope, row["auth"]),
        label=row["label"],
    )


class PushStore:
    """Which devices to push, and the pushing of them."""

    def __init__(self, db_path: Path, key_path: Path, *, subject: str = "") -> None:
        self.db_path = db_path
        self.key_path = key_path
        self.subject = subject
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
        self._key: ec.EllipticCurvePrivateKey | None = None

    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    @property
    def key(self) -> ec.EllipticCurvePrivateKey:
        if self._key is None:
            self._key = load_or_create_vapid_key(self.key_path)
        return self._key

    @property
    def public_key(self) -> str:
        return public_key_b64(self.key)

    def subscribe(
        self, username: str, *, endpoint: str, p256dh: str, auth: str, label: str = ""
    ) -> Subscription:
        """Remember a device. The same endpoint twice is the same device."""
        endpoint = endpoint.strip()
        if not endpoint.startswith("https://"):
            raise ValueError("a push endpoint is an https URL")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO push_subscriptions (username, endpoint, p256dh, auth,"
                " label, created_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(endpoint) DO UPDATE SET"
                " username = excluded.username, p256dh = excluded.p256dh,"
                " auth = excluded.auth, label = excluded.label, failures = 0",
                (
                    username,
                    endpoint,
                    conn.seal("push_subscriptions", "p256dh", (username,), p256dh.strip()),
                    conn.seal("push_subscriptions", "auth", (username,), auth.strip()),
                    label[:120],
                    _now(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
            ).fetchone()
        return _subscription(conn, row)

    def unsubscribe(self, username: str, endpoint: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM push_subscriptions WHERE username = ? AND endpoint = ?",
                (username, endpoint.strip()),
            )
            return cursor.rowcount

    def forget(self, endpoint: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))

    def list(self, username: str) -> list[Subscription]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM push_subscriptions WHERE username = ? ORDER BY id",
                (username,),
            ).fetchall()
        return [_subscription(conn, row) for row in rows]

    # -- sending ---------------------------------------------------------------
    def _record(self, endpoint: str, ok: bool) -> None:
        with self._connect() as conn:
            if ok:
                conn.execute(
                    "UPDATE push_subscriptions SET last_ok = ?, failures = 0"
                    " WHERE endpoint = ?",
                    (_now(), endpoint),
                )
                return
            conn.execute(
                "UPDATE push_subscriptions SET failures = failures + 1 WHERE endpoint = ?",
                (endpoint,),
            )
            conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ? AND failures >= ?",
                (endpoint, MAX_FAILURES),
            )

    def send_one(self, subscription: Subscription, payload: dict, *, timeout: float = 10.0) -> bool:
        """Push one device. Never raises: a phone that is off is not an error."""
        # Sealing the body comes first and on its own, because it is the one
        # step with no luck in it. If these keys cannot be used once they
        # cannot be used ever, so that is a dead row rather than a failure to
        # count down — retrying it four more times only delays the same end.
        try:
            body = encrypt(
                json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                unb64(subscription.p256dh),
                unb64(subscription.auth),
            )
        except Exception:
            self.forget(subscription.endpoint)
            return False
        try:
            headers = {
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                # Apple and Firefox both take this; it asks the service to
                # wake the device rather than batch the message for later.
                "Urgency": "high",
                **vapid_headers(self.key, subscription.endpoint, self.subject),
            }
            request = urllib.request.Request(
                subscription.endpoint, data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(request, timeout=timeout):
                pass
        except urllib.error.HTTPError as exc:
            # 404 and 410 are the push service saying this subscription is
            # dead — the app was deleted, or the browser dropped it. There is
            # nothing to retry, so the row goes.
            if exc.code in (404, 410):
                self.forget(subscription.endpoint)
            else:
                self._record(subscription.endpoint, ok=False)
            return False
        except Exception:
            # Offline, DNS, a timeout, a key the phone no longer has. Counted,
            # and dropped once it is clearly not coming back.
            self._record(subscription.endpoint, ok=False)
            return False
        self._record(subscription.endpoint, ok=True)
        return True

    def send(self, usernames: list[str], payload: dict) -> int:
        """Push everyone named, on every device they have. Returns how many landed."""
        landed = 0
        for username in dict.fromkeys(usernames):
            for subscription in self.list(username):
                if self.send_one(subscription, payload):
                    landed += 1
        return landed
