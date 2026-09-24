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
