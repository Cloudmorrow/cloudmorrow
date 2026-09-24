"""Web push: the keys, the sealed body, the devices, and the number on the icon.

The encryption here is the one part of Cloudmorrow whose correctness cannot be
seen by using it: a body derived even slightly wrong is dropped by the push
service without a word, and the only symptom is a phone that stays quiet. So
it is pinned two ways — the shape of the wire format, and a fixed vector that
was checked against `http_ece`, the library the reference Python client uses.
Regenerate the vector only against that library, never against this code.
"""

from __future__ import annotations

import base64
import struct

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from cloudmorrow.server.webpush import (
    MAX_PAYLOAD,
    PushStore,
    Subscription,
    b64,
    default_subject,
    encrypt,
    load_or_create_vapid_key,
    public_key_b64,
    unb64,
    vapid_headers,
)
from tests.conftest import GUEST, token_for

# -- the fixed vector ------------------------------------------------------------
UA_PRIVATE = 0x1122334455667788990011223344556677889900112233445566778899001122
SERVER_PRIVATE = 0x00AABBCCDDEEFF00112233445566778899AABBCCDDEEFF00112233445566778
AUTH = bytes(range(16))
SALT = bytes(range(16, 32))
PAYLOAD = b'{"title":"#general","body":"bram: the fans are loud again","badge":2}'
SEALED = (
    "EBESExQVFhcYGRobHB0eHwAAEABBBBOMFJxgAEL0LUpYrAd3XyHMdhVWuoFIqQoK9H9dwhwLf7Q0BL6r5G3z"
    "_MjNBp0_qivLE8tLbh6-ZKMcAFNaAOguRrfMsdOSp4NpuH0sYokVMsw6C398XZ6nyr60uBuRh5P0hsw5NvbW"
    "wd7X_XRW29gFuM-eROa0dIYpuLBwJe3AQXD6hcEnaKysAdtwOp2oQ4HkPufC4Q"
)


def _point(key) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )


def test_a_sealed_body_matches_the_checked_vector():
    """Byte for byte what `http_ece` decrypted when this was written."""
    ua = ec.derive_private_key(UA_PRIVATE, ec.SECP256R1())
    server = ec.derive_private_key(SERVER_PRIVATE, ec.SECP256R1())
    body = encrypt(PAYLOAD, _point(ua), AUTH, salt=SALT, private_key=server)
    assert b64(body) == SEALED


def test_the_header_block_is_the_shape_rfc_8188_asks_for():
    ua = ec.generate_private_key(ec.SECP256R1())
    body = encrypt(b"hello", _point(ua), AUTH)
    salt, record_size, key_length = body[:16], *struct.unpack("!IB", body[16:21])
    assert len(salt) == 16
    assert record_size == 4096
    # The key id is the sender's public key, uncompressed: 0x04 and two
    # coordinates. It is how the phone works out the same secret.
    assert key_length == 65
    assert body[21] == 0x04
    assert len(body) == 21 + 65 + len(b"hello") + 1 + 16, "payload, delimiter, GCM tag"


def test_the_recipient_can_open_it():
    """The other half of the derivation, written out from the spec.

    Not a round trip through the same function: this walks RFC 8291 from the
    receiving side, so a mistake in the sending side has nowhere to hide.
    """
    import hashlib
    import hmac

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ua = ec.generate_private_key(ec.SECP256R1())
    ua_public = _point(ua)
    body = encrypt(PAYLOAD, ua_public, AUTH)

    salt = body[:16]
    as_public = body[21:86]
    ciphertext = body[86:]

    shared = ua.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    )
    ikm = hmac.new(AUTH, shared, hashlib.sha256).digest()
    ikm = hmac.new(
        ikm, b"WebPush: info\x00" + ua_public + as_public + b"\x01", hashlib.sha256
    ).digest()
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    key = hmac.new(prk, b"Content-Encoding: aes128gcm\x00\x01", hashlib.sha256).digest()[:16]
    nonce = hmac.new(prk, b"Content-Encoding: nonce\x00\x01", hashlib.sha256).digest()[:12]

    opened = AESGCM(key).decrypt(nonce, ciphertext, None)
    assert opened == PAYLOAD + b"\x02"


def test_every_push_is_sealed_differently():
    ua = ec.generate_private_key(ec.SECP256R1())
    first = encrypt(b"same words", _point(ua), AUTH)
    second = encrypt(b"same words", _point(ua), AUTH)
    assert first != second, "a fresh salt and a fresh ephemeral key each time"


def test_a_payload_too_big_for_one_record_is_refused():
    ua = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(ValueError):
        encrypt(b"x" * (MAX_PAYLOAD + 1), _point(ua), AUTH)


def test_base64url_survives_the_padding_a_browser_leaves_off():
    raw = bytes(range(65))
    assert unb64(b64(raw)) == raw
    # Some browsers hand back standard base64; it has to be read the same.
    assert unb64(base64.b64encode(raw).decode()) == raw


# -- the server's key -------------------------------------------------------------
def test_the_vapid_key_is_made_once_and_kept_private(tmp_path):
    path = tmp_path / "vapid.key"
    first = load_or_create_vapid_key(path)
    assert path.stat().st_mode & 0o077 == 0, "nobody else may read the signing key"
    assert public_key_b64(load_or_create_vapid_key(path)) == public_key_b64(first)


def test_the_public_key_is_what_a_browser_can_subscribe_with(tmp_path):
    key = load_or_create_vapid_key(tmp_path / "vapid.key")
    raw = unb64(public_key_b64(key))
    assert len(raw) == 65 and raw[0] == 0x04


def test_the_authorization_header_names_the_service_and_not_the_subscription(tmp_path):
    import jwt

    key = load_or_create_vapid_key(tmp_path / "vapid.key")
    header = vapid_headers(key, "https://web.push.apple.com/abc/def?q=1", "mailto:a@b.c")
    scheme, _, params = header["Authorization"].partition(" ")
    assert scheme == "vapid"
    bits = dict(part.split("=", 1) for part in params.split(","))

    # The key the browser was given has to be the key that signed the token,
    # or the push service rejects it.
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(bits["k"]))
    claims = jwt.decode(
        bits["t"], public, algorithms=["ES256"], audience="https://web.push.apple.com"
    )
    assert claims["aud"] == "https://web.push.apple.com", "the origin, not the path"
    assert claims["sub"] == "mailto:a@b.c"
    assert len(unb64(bits["t"].split(".")[2])) == 64, "JWS wants raw r||s, not DER"


def test_the_subject_falls_back_to_something_a_push_service_will_take():
    assert default_subject("https://cloud.example.com/") == "https://cloud.example.com"
    assert default_subject("http://192.168.1.10:8787") == "mailto:cloudmorrow@192.168.1.10"
    assert default_subject("").startswith("mailto:cloudmorrow@")


# -- the devices -------------------------------------------------------------------
@pytest.fixture()
def store(tmp_path) -> PushStore:
    return PushStore(tmp_path / "db.sqlite", tmp_path / "vapid.key", subject="mailto:a@b.c")


# A real point on the curve: `encrypt` does the ECDH for itself, so sixty-five
# arbitrary bytes are not a stand-in for a key.
DEVICE_KEY = b64(_point(ec.derive_private_key(UA_PRIVATE, ec.SECP256R1())))


def _subscribe(store, username="bram", endpoint="https://push.example.com/one"):
    return store.subscribe(username, endpoint=endpoint, p256dh=DEVICE_KEY, auth=b64(AUTH))


def test_the_same_device_twice_is_one_row(store):
    _subscribe(store)
    _subscribe(store)
    assert len(store.list("bram")) == 1


def test_a_device_that_moves_account_goes_with_it(store):
    _subscribe(store, "bram")
    _subscribe(store, "guest")
    assert store.list("bram") == []
    assert len(store.list("guest")) == 1


def test_an_endpoint_has_to_be_https(store):
    with pytest.raises(ValueError):
        store.subscribe("bram", endpoint="http://push.example.com/x", p256dh="a", auth="b")


def test_a_subscription_the_service_has_buried_is_forgotten(store, monkeypatch):
    import urllib.error

    _subscribe(store)

    def gone(*args, **kwargs):
        raise urllib.error.HTTPError("url", 410, "Gone", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", gone)
    assert store.send(["bram"], {"title": "hi"}) == 0
    assert store.list("bram") == [], "410 means the app is gone; there is nothing to retry"


def test_a_device_whose_keys_are_useless_goes_at_once(store, monkeypatch):
    """No countdown: a key that cannot be used once cannot be used ever."""
    store.subscribe(
        "bram", endpoint="https://push.example.com/bad", p256dh=b64(b"k" * 65), auth=b64(AUTH)
    )
    reached = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: reached.append(1))
    assert store.send(["bram"], {"title": "hi"}) == 0
    assert reached == [], "nothing was even sent"
    assert store.list("bram") == []


def test_a_device_that_keeps_failing_is_dropped_in_the_end(store, monkeypatch):
    _subscribe(store)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
    )
    for _ in range(4):
        store.send(["bram"], {"title": "hi"})
        assert store.list("bram"), "a phone that is off is not a phone that is gone"
    store.send(["bram"], {"title": "hi"})
    assert store.list("bram") == []


def test_a_delivery_forgives_the_failures_before_it(store, monkeypatch):
    import contextlib

    _subscribe(store)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))
    )
    store.send(["bram"], {"title": "hi"})
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: contextlib.nullcontext())
    assert store.send(["bram"], {"title": "hi"}) == 1
    with store._connect() as conn:
        row = conn.execute("SELECT failures, last_ok FROM push_subscriptions").fetchone()
    assert row["failures"] == 0 and row["last_ok"]


def test_what_goes_on_the_wire(store, monkeypatch):
    """One real request, caught on the way out."""
    import contextlib

    ua = ec.generate_private_key(ec.SECP256R1())
    store.subscribe(
        "bram", endpoint="https://push.example.com/one", p256dh=b64(_point(ua)), auth=b64(AUTH)
    )
    sent = {}

    def capture(request, timeout=None):
        sent["headers"] = {k.lower(): v for k, v in request.headers.items()}
        sent["body"] = request.data
        sent["url"] = request.full_url
        return contextlib.nullcontext()

    monkeypatch.setattr("urllib.request.urlopen", capture)
    assert store.send(["bram"], {"title": "#general", "badge": 2}) == 1
    assert sent["url"] == "https://push.example.com/one"
    assert sent["headers"]["content-encoding"] == "aes128gcm"
    assert sent["headers"]["content-type"] == "application/octet-stream"
    assert sent["headers"]["ttl"] == "86400"
    assert sent["headers"]["authorization"].startswith("vapid t=")
    assert sent["body"][:16] != b"\x00" * 16, "a real salt, not an empty one"


# -- the API ---------------------------------------------------------------------------
def test_a_browser_can_fetch_the_key_and_subscribe(client, auth):
    key = client.get("/api/push/key", headers=auth).json()
    assert len(unb64(key["public_key"])) == 65

    subscription = {
        "endpoint": "https://web.push.apple.com/abc",
        "keys": {"p256dh": DEVICE_KEY, "auth": b64(AUTH)},
        "label": "iPhone",
    }
    made = client.post("/api/push/subscribe", json=subscription, headers=auth)
    assert made.status_code == 201
    assert made.json()["label"] == "iPhone"

    assert [d["endpoint"] for d in client.get("/api/push/devices", headers=auth).json()] == [
        "https://web.push.apple.com/abc"
    ]
    assert client.post(
        "/api/push/unsubscribe", json={"endpoint": subscription["endpoint"]}, headers=auth
    ).status_code == 204
    assert client.get("/api/push/devices", headers=auth).json() == []


def test_devices_are_not_shared_between_accounts(client, auth):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://web.push.apple.com/abc",
            "keys": {"p256dh": DEVICE_KEY, "auth": b64(AUTH)},
        },
        headers=auth,
    )
    assert client.get("/api/push/devices", headers=guest).json() == []


# -- the number on the icon -------------------------------------------------------------
def test_the_badge_is_messages_plus_notifications(client, auth):
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    client.post("/api/chat/channels", json={"name": "General", "kind": "public"}, headers=auth)
    client.post("/api/chat/channels/general/messages", json={"body": "one"}, headers=auth)
    client.post("/api/chat/channels/general/messages", json={"body": "two"}, headers=auth)
    # And one notification, from being added to something.
    client.post("/api/chat/channels", json={"name": "Club"}, headers=auth)
    client.post(
        "/api/chat/channels/club/members", json={"usernames": [GUEST[0]]}, headers=auth
    )

    # Two messages, and two notifications: the public channel appearing, and
    # being added to the private one.
    badge = client.get("/api/push/badge", headers=guest).json()
    assert badge == {"messages": 2, "notifications": 2, "badge": 4}

    client.post("/api/chat/channels/general/read", json={}, headers=guest)
    client.post("/api/notifications/read", json={}, headers=guest)
    assert client.get("/api/push/badge", headers=guest).json()["badge"] == 0


def test_the_badge_ignores_chat_when_chat_is_switched_off(client, auth):
    client.post("/api/chat/channels", json={"name": "General", "kind": "public"}, headers=auth)
    client.patch("/api/server/features/chat", json={"enabled": False}, headers=auth)
    assert client.get("/api/push/badge", headers=auth).json()["messages"] == 0


def test_a_new_message_pushes_everybody_else(client, auth, monkeypatch):
    # The guest never signs in here: a public channel is everybody's because
    # the accounts exist, not because they have been anywhere.
    client.post("/api/chat/channels", json={"name": "General", "kind": "public"}, headers=auth)

    pushed = []
    monkeypatch.setattr(
        PushStore, "send", lambda self, who, payload: pushed.append((who, payload)) or 1
    )
    client.post("/api/chat/channels/general/messages", json={"body": "hello"}, headers=auth)

    assert len(pushed) == 1, "the author does not push themselves"
    who, payload = pushed[0]
    assert who == [GUEST[0]]
    assert payload["title"] == "#General"
    assert payload["body"] == "bram: hello"
    assert payload["url"] == "#/chat/general"
    assert payload["tag"] == "chat-general", "one notification per channel, replaced"
    # One message, plus the notification that the channel appeared at all.
    assert payload["badge"] == 2


def test_a_direct_message_is_titled_with_the_person(client, auth, monkeypatch):
    client.post("/api/chat/direct", json={"username": GUEST[0]}, headers=auth)
    pushed = []
    monkeypatch.setattr(
        PushStore, "send", lambda self, who, payload: pushed.append(payload) or 1
    )
    client.post(
        f"/api/chat/channels/dm-bram-{GUEST[0]}/messages",
        json={"body": "are you up"},
        headers=auth,
    )
    assert pushed[0]["title"] == "bram"
    assert pushed[0]["body"] == "are you up", "no name repeated in front of it"


def test_the_test_push_goes_to_yourself(client, auth, monkeypatch):
    pushed = []
    monkeypatch.setattr(
        PushStore, "send", lambda self, who, payload: pushed.append((who, payload)) or 1
    )
    assert client.post("/api/push/test", headers=auth).status_code == 200
    assert pushed[0][0] == ["bram"]
    assert pushed[0][1]["tag"] == "push-test"


# -- the worker ----------------------------------------------------------------------------
def test_the_service_worker_is_served_uncached_at_the_top_of_its_scope(client):
    response = client.get("/app/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    # Not the year-long caching the versioned assets get: the browser reads
    # this file to find out whether the worker has changed.
    assert response.headers["cache-control"] == "no-cache"
    assert "immutable" not in response.headers["cache-control"]
    assert "push" in response.text


def test_the_subscription_dataclass_says_nothing_it_should_not():
    seen = Subscription(
        id=1, username="bram", endpoint="https://x/y", p256dh="p", auth="a", label="iPhone"
    ).to_dict()
    assert "auth" not in seen and "p256dh" not in seen
    assert "username" not in seen
