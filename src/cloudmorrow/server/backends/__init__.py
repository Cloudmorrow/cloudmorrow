"""Backends: datamodels whose records live somewhere other than the record store.

The protocol a backend keeps, and what every backend shares, is `base`; the
two there are — shares and their files, and the secrets' vaults — are a
module each. See `base` for what a backend is.
"""

from cloudmorrow.server.backends.base import (
    AttachmentTooBig,
    Backend,
    ContentBackend,
    ContentError,
)
from cloudmorrow.server.backends.shares import SharesBackend
from cloudmorrow.server.backends.vaults import VaultsBackend

__all__ = [
    "AttachmentTooBig",
    "Backend",
    "ContentBackend",
    "ContentError",
    "SharesBackend",
    "VaultsBackend",
]
