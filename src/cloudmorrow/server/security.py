"""Password hashing and access tokens."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

ALGORITHM = "HS256"
MIN_PASSWORD_LENGTH = 8


class TokenError(Exception):
    """Raised when a token is missing, malformed or expired."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@dataclass(slots=True)
class IssuedToken:
    token: str
    expires_at: dt.datetime


def create_access_token(username: str, secret_key: str, ttl_hours: int) -> IssuedToken:
    now = dt.datetime.now(tz=dt.UTC)
    expires_at = now + dt.timedelta(hours=ttl_hours)
    token = jwt.encode(
        {"sub": username, "iat": int(now.timestamp()), "exp": int(expires_at.timestamp())},
        secret_key,
        algorithm=ALGORITHM,
    )
    return IssuedToken(token=token, expires_at=expires_at)


def decode_access_token(token: str, secret_key: str) -> str:
    """Return the username carried by *token*, or raise TokenError."""
    try:
        claims = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if claims.get("use"):
        # A media link's token opens one record's bytes and nothing else.
        raise TokenError("invalid token")
    username = claims.get("sub")
    if not username:
        raise TokenError("token has no subject")
    return str(username)


# A link to one record's bytes, for what cannot send the app's token: a
# browser's <video> and <audio>, which ask for ranges as they play.
MEDIA_TTL = dt.timedelta(hours=6)


def create_media_token(username: str, model: str, record_id: str, secret_key: str) -> IssuedToken:
    now = dt.datetime.now(tz=dt.UTC)
    expires_at = now + MEDIA_TTL
    claims = {"sub": username, "use": "media", "model": model, "id": record_id, "exp": int(expires_at.timestamp())}
    return IssuedToken(token=jwt.encode(claims, secret_key, algorithm=ALGORITHM), expires_at=expires_at)


def decode_media_token(token: str, secret_key: str) -> tuple[str, str, str]:
    """(username, model, record id) of a media link's token, or TokenError."""
    try:
        claims = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("link expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid link") from exc
    if claims.get("use") != "media" or not all(claims.get(k) for k in ("sub", "model", "id")):
        raise TokenError("invalid link")
    return str(claims["sub"]), str(claims["model"]), str(claims["id"])
