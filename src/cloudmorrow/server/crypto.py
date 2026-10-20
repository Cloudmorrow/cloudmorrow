"""Encryption for secrets at rest.

Secret values are sealed with AES-256-GCM under a key that lives beside the
database, in `<data_dir>/secrets.key` at mode 600. Lose that file and the
values are gone; back it up with the database, not separately from it.

Key names, environments and timestamps stay in the clear so the store can list
and sort without touching the key. Only values are sealed, and each sealed
value is bound to the row it belongs to — owner, vault, environment and key
are the AEAD's associated data — so a value cannot be moved to another row, or
another user's row, without the tamper check failing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12
FORMAT = "v1"


class SealError(RuntimeError):
    """A sealed value could not be opened: wrong key, or it was tampered with."""


def load_or_create_key(path: Path) -> bytes:
    """Return the secrets key, generating one on first use."""
    if path.exists():
        return _read_key(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(KEY_BYTES)
    try:
        # Created private, rather than chmod'ed private a moment later.
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Another worker booted at the same instant and won.
        return _read_key(path)
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write(base64.urlsafe_b64encode(key).decode("ascii") + "\n")
    return key


def _read_key(path: Path) -> bytes:
    try:
        key = base64.urlsafe_b64decode(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError) as exc:
        raise SealError(f"cannot read the secrets key at {path}: {exc}") from exc
    if len(key) != KEY_BYTES:
        raise SealError(f"{path} does not hold a {KEY_BYTES * 8}-bit key")
    return key


def associated_data(owner: str, vault: str, environment: str, name: str) -> bytes:
    """What a sealed value is bound to. Changing any part breaks the seal.

    A vault used to be a project; the column was renamed and the values kept,
    so a value sealed under a project slug opens under the vault of that name.
    """
    return "\x00".join((owner, vault, environment, name)).encode("utf-8")


def seal(key: bytes, plaintext: str, aad: bytes) -> str:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return f"{FORMAT}:{_encode(nonce)}:{_encode(ciphertext)}"


def unseal(key: bytes, blob: str, aad: bytes) -> str:
    version, _, rest = blob.partition(":")
    nonce, _, ciphertext = rest.partition(":")
    if version != FORMAT or not nonce or not ciphertext:
        raise SealError("malformed sealed value")
    try:
        opened = AESGCM(key).decrypt(_decode(nonce), _decode(ciphertext), aad)
    except (InvalidTag, ValueError) as exc:
        raise SealError("cannot open this value with the current key") from exc
    return opened.decode("utf-8")


def fingerprint(key: bytes, plaintext: str) -> str:
    """A short keyed digest, so two values can be compared without revealing either.

    Keyed on purpose: a plain hash of a low-entropy secret is guessable, this
    is not without the key.
    """
    return hmac.new(key, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()[:8]


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# -- signing: a key of one's own, and a signature anybody can check -------------
# An attestation (docs/ATTESTATIONS.md) is signed with Ed25519 by whoever
# gives it, with a key the server holding the data never has. The public
# key travels with the signature as `ed25519:<base64>`, so a bundle, an
# attestation and nothing else is enough to check it, anywhere.
KEY_PREFIX = "ed25519:"


def load_or_create_signing_key(path: Path):
    """The Ed25519 key at *path*, made on first use at mode 600."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    with os.fdopen(handle, "wb") as file:
        file.write(pem)
    return key


def public_key_text(key) -> str:
    """A signing key's public half, as it travels: `ed25519:<base64>`."""
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return KEY_PREFIX + base64.b64encode(raw).decode("ascii")


def key_fingerprint(public_text: str) -> str:
    """A short name for a public key: the first sixteen hex digits of its SHA-256."""
    return hashlib.sha256(_public_bytes(public_text)).hexdigest()[:16]


def sign(key, payload: bytes) -> str:
    """Sign *payload*; the signature, base64."""
    return base64.b64encode(key.sign(payload)).decode("ascii")


def verify_signature(public_text: str, payload: bytes, signature: str) -> bool:
    """Is *signature* the public key's signature over *payload*? Never raises."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        public = Ed25519PublicKey.from_public_bytes(_public_bytes(public_text))
        public.verify(base64.b64decode(signature), payload)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def _public_bytes(public_text: str) -> bytes:
    if not public_text.startswith(KEY_PREFIX):
        raise ValueError(f"a public key reads {KEY_PREFIX}<base64>")
    raw = base64.b64decode(public_text[len(KEY_PREFIX) :])
    if len(raw) != 32:
        raise ValueError("an Ed25519 public key is 32 bytes")
    return raw
