"""Fetching a Quill, and the catalog it is fetched from.

The catalog is a `catalog.toml`, read from `quill_catalog` in the config: a
URL, or a local path. A Quill is fetched as the tarball of its pinned ref,
so a server needs no git; a local path is used as it is, which is how one is
developed.
"""

from __future__ import annotations

import io
import re
import tarfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cloudmorrow.server.quills.manifest import QuillError

FETCH_TIMEOUT = 30
MAX_DOWNLOAD = 50 * 1024 * 1024


# -- fetching --------------------------------------------------------------------------
_GITHUB_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def tarball_url(repo: str, ref: str) -> str:
    """Where a release of *repo* at *ref* is downloaded from, as a tarball."""
    match = _GITHUB_RE.match(repo)
    if match:
        return f"https://codeload.github.com/{match.group(1)}/{match.group(2)}/tar.gz/{urllib.parse.quote(ref)}"
    if repo.endswith((".tar.gz", ".tgz")):
        return repo
    raise QuillError(f"{repo} is not a GitHub repository or a tarball URL")


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "cloudmorrow"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
            data = response.read(MAX_DOWNLOAD + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise QuillError(f"could not fetch {url}: {exc}") from exc
    if len(data) > MAX_DOWNLOAD:
        raise QuillError(f"{url} is bigger than a Quill should be")
    return data


def fetch(source: str, ref: str = "", *, base: Path | None = None, into: Path) -> Path:
    """A folder holding *source*: a local path as it is, or a release unpacked into *into*.

    *base* is what a relative local path is relative to: the catalog's own folder.
    """
    if not source.startswith(("https://", "http://")):
        path = Path(source).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        if not path.is_dir():
            raise QuillError(f"{source} is not a folder")
        return path.resolve()
    if not ref:
        raise QuillError(f"{source}: a release is fetched at a pinned ref")
    data = _download(tarball_url(source, ref))
    into.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            archive.extractall(into, filter="data")
    except (tarfile.TarError, OSError) as exc:
        raise QuillError(f"{source}@{ref} is not a tarball that unpacks: {exc}") from exc
    tops = [p for p in into.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else into


# -- the catalog -----------------------------------------------------------------------
@dataclass(slots=True)
class Catalog:
    categories: list[dict]
    quills: list[dict]
    datamodels: dict
    # The folder relative paths in it are relative to, when it is local.
    base: Path | None = None

    def entry(self, quill_id: str) -> dict:
        for entry in self.quills:
            if entry.get("id") == quill_id:
                return entry
        raise QuillError(f"{quill_id} is not in the catalog")


def parse_catalog(data: dict, base: Path | None = None) -> Catalog:
    quills = data.get("quills", [])
    for entry in quills:
        if not entry.get("id") or not entry.get("repo"):
            raise QuillError("every Quill in the catalog has an id and a repo")
    return Catalog(
        categories=list(data.get("categories", [])),
        quills=list(quills),
        datamodels=dict(data.get("datamodels", {})),
        base=base,
    )


def load_catalog(location: str) -> Catalog:
    if location.startswith(("https://", "http://")):
        text = _download(location).decode("utf-8")
        base = None
    else:
        path = Path(location).expanduser()
        if path.is_dir():
            path = path / "catalog.toml"
        if not path.is_file():
            raise QuillError(f"no catalog at {location}")
        text = path.read_text(encoding="utf-8")
        base = path.parent
    try:
        return parse_catalog(tomllib.loads(text), base)
    except tomllib.TOMLDecodeError as exc:
        raise QuillError(f"the catalog does not parse: {exc}") from exc
