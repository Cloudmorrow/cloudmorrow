"""Quills: reading a manifest, fetching a release, installing it, and what it adds.

A Quill is a folder with a `quill.toml` — a checkout, a release tarball, or a
folder somebody is working in. This package reads the manifest and checks it
against the datamodels there are; lists everything the Quill would add, for
the install sheet; copies it into `<data_dir>/quills/<id>/` with the
foundational datamodels it uses into `<data_dir>/datamodels/`; and keeps the
registry of what is installed, which the record store, the jobs, the routes
and every client read.

The catalog is a `catalog.toml`, read from `quill_catalog` in the config: a
URL, or a local path. A Quill is fetched as the tarball of its pinned ref,
so a server needs no git; a local path is used as it is, which is how one is
developed.

Nothing here runs code from a Quill. Services, webhooks, APIs and `run`
jobs are read, checked and listed here, and run by `quills.services` — only
for a Quill that is installed, and as the administrator who installed it,
whose name the install routes write into the Quill's `.origin.json`.

See docs/QUILLS.md for the format.
"""

from cloudmorrow.server.quills.catalog import (
    MAX_DOWNLOAD,
    Catalog,
    fetch,
    load_catalog,
    parse_catalog,
    tarball_url,
)
from cloudmorrow.server.quills.checks import code_summary, describe, runs_code
from cloudmorrow.server.quills.manifest import (
    KIT,
    KIT_READY,
    MANIFEST,
    ORIGIN,
    Manifest,
    QuillError,
    load_manifest,
    parse_manifest,
)
from cloudmorrow.server.quills.registry import QuillRegistry

__all__ = [
    "KIT",
    "KIT_READY",
    "MANIFEST",
    "MAX_DOWNLOAD",
    "ORIGIN",
    "Catalog",
    "Manifest",
    "QuillError",
    "QuillRegistry",
    "code_summary",
    "describe",
    "fetch",
    "load_catalog",
    "load_manifest",
    "parse_catalog",
    "parse_manifest",
    "runs_code",
    "tarball_url",
]
