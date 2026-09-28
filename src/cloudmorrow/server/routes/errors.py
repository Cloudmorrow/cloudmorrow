"""What the record store's refusals are over HTTP, for every route that writes records.

`ERRORS` is what to catch around a call to the record store, and
`http_error` the HTTPException each one is: an unknown datamodel or record
is a 404, the gate's no a 403, a stale revision a 409 with the record as it
is now, an error that carries its own status that status, and anything
else that does not fit the datamodel a 400.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from cloudmorrow.server.records import (
    RecordConflictError,
    RecordError,
    Refused,
    UnknownModelError,
    UnknownRecordError,
)

__all__ = ["ERRORS", "http_error"]

ERRORS = (UnknownModelError, UnknownRecordError, Refused, RecordConflictError, RecordError)


def http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownModelError):
        return HTTPException(status.HTTP_404_NOT_FOUND, f"no such datamodel: {exc}")
    if isinstance(exc, UnknownRecordError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "no such record")
    if isinstance(exc, Refused):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    if isinstance(getattr(exc, "status", None), int):
        return HTTPException(exc.status, str(exc))
    if isinstance(exc, RecordConflictError):
        return HTTPException(
            status.HTTP_409_CONFLICT,
            {"message": "changed since you read it", "current": exc.current.to_dict()},
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
