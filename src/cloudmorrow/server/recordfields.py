"""A record's fields: made the kind their datamodel says, filtered, and dated.

Pure helpers the record store checks what is sent with, and anything else
that must read a value the way the store will — a Quill's code, which
checks an action's fields before it runs (quills/code.py).
"""

from __future__ import annotations

import datetime as dt
import json
import re

from cloudmorrow.server.datamodels import Datamodel, Field

__all__ = [
    "RANGES",
    "RecordError",
    "coerce",
    "iso_stamp",
    "parse_filter",
    "parse_moment",
    "reads_as",
    "stored_indexed",
    "utc_now",
]


class RecordError(ValueError):
    """What was sent does not fit the datamodel."""


# -- time ----------------------------------------------------------------------
def utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def iso_stamp(moment: dt.datetime | None = None) -> str:
    return (moment or utc_now()).isoformat(timespec="seconds")


def parse_moment(value: str) -> dt.datetime | None:
    try:
        moment = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


# -- fields --------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def coerce(model: Datamodel, f: Field, value: object) -> object:
    """One value, made the kind its field is, or RecordError."""
    if value is None:
        return None
    where = f"{model.id}.{f.name}"
    kind = f.kind
    if kind in ("string", "text", "markdown", "phone", "url", "link"):
        if not isinstance(value, str | int | float):
            raise RecordError(f"{where} is text")
        text = str(value)
        if kind == "string" and not f.secret:
            text = text.strip()
        return text
    if kind == "email":
        text = str(value).strip()
        if text and not _EMAIL_RE.match(text):
            raise RecordError(f"{where} is not an email address")
        return text
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        raise RecordError(f"{where} is true or false")
    if kind == "int":
        if isinstance(value, bool):
            raise RecordError(f"{where} is a whole number")
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise RecordError(f"{where} is a whole number") from None
    if kind == "decimal":
        try:
            return str(float(value)) if not isinstance(value, str) else str(float(value.strip()))
        except (TypeError, ValueError):
            raise RecordError(f"{where} is a number") from None
    if kind == "date":
        try:
            return dt.date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise RecordError(f"{where} is a date, YYYY-MM-DD") from None
    if kind == "datetime":
        return _wall_or_moment(where, str(value).strip())
    if kind == "enum":
        text = str(value).strip().lower()
        if text not in f.values:
            raise RecordError(f"{where} is one of {', '.join(f.values)}")
        return text
    if kind == "json":
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise RecordError(f"{where} is not JSON") from None
        return value
    raise RecordError(f"{where}: unknown kind {kind}")  # pragma: no cover


_BARE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _wall_or_moment(where: str, text: str) -> str:
    """A datetime field's value, kept the way it was meant.

    With a zone it is a moment, and is kept with its zone. Without one it is
    the time on the wall — "the dentist at ten" — and is kept as typed, to
    the minute, converting nothing: that is what a calendar needs, and a
    server guessing a zone for it would move the dentist twice a year. A
    bare date is a whole day, and stays one. ISO sorts the way time does, so
    all three compare as strings, which is what a range filter does.
    """
    if _BARE_DATE_RE.match(text):
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError:
            raise RecordError(f"{where} is a date, YYYY-MM-DD") from None
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        raise RecordError(f"{where} is a date and time, ISO 8601") from None
    if moment.tzinfo is None:
        exact = moment.second or moment.microsecond
        return moment.isoformat(timespec="seconds" if exact else "minutes")
    return moment.isoformat(timespec="seconds")


def reads_as(value: object, target: str) -> bool:
    """Does a field's value read as *target*? `false` is how TOML says a bool."""
    if isinstance(value, bool):
        return str(value).lower() == target.lower()
    return value is not None and str(value) == target


def stored_indexed(model: Datamodel) -> set[str]:
    """Links are always plain: they are what cascades and filters find by."""
    return {f.name for f in model.fields if f.indexed or f.kind == "link"}


# `?starts_at__lt=2026-10-01`: a range on an indexed field, for anything
# that asks "between these two" — the events in a month, the invoices in a
# quarter. A field that is missing never matches a range.
RANGES = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}


def parse_filter(key: str) -> tuple[str, str]:
    """A filter's field and its comparison: `due` is equal, `due__gte` is at least."""
    name, sep, suffix = key.rpartition("__")
    if sep and suffix in RANGES:
        return name, RANGES[suffix]
    return key, "IS"
