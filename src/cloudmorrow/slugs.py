"""Slugs: the id a board or a share goes by.

A slug is a thing's id everywhere: in the API, in a directory name, and as
the argument you type. Both sides of Cloudmorrow derive them the same way.
"""

from __future__ import annotations

import re

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Words that would read as a command or a scope rather than a thing.
RESERVED_SLUGS = {"notes", "projects", "new", "none", "all"}


class InvalidSlugError(ValueError):
    pass


def slugify(name: str) -> str:
    """Turn a project title into a slug, which is also its directory name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:64]
    return slug.rstrip("-")


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise InvalidSlugError(
            "an id must be 1-64 chars of lowercase letters, digits or '-', "
            "starting with a letter or digit"
        )
    if slug in RESERVED_SLUGS:
        raise InvalidSlugError(f"'{slug}' is reserved")
    return slug
