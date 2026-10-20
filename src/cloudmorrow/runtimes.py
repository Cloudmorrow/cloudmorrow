"""Runtimes: programs a Quill's code needs, fetched for it, on a server or a machine.

A Quill that works with video needs ffmpeg; one that talks to a printer
needs its driver. Nobody should have to open a shell on the server for
that, and the server itself runs as an unprivileged user on a read-only
system, so it cannot (and must not) reach for apt. What it can do is fetch
a program *for its own use*, the way it fetches a Quill: the manifest names
the runtime (`[requires] runtimes = ["ffmpeg"]`), the catalog says where a
static build of it is for each OS and architecture and what its SHA-256 is,
and the install downloads it, checks it, unpacks it under
`<data_dir>/runtimes/<id>/` and puts its programs on the PATH of the Quill's
services (quills/services.py). Nothing is installed system-wide, nothing
needs root, and it is the same on bare metal, in a container and on a
Raspberry Pi.

The install sheet says what would be added, with its size, before the yes.
Removing the last Quill that needs a runtime offers to remove it too
(quills/removal.py). A runtime is shared: two Quills naming `ffmpeg` share
one copy, and it stays while either of them is installed.

    [runtimes.ffmpeg]                    # in catalog.toml
    label = "ffmpeg"
    summary = "Reads, writes and converts video and sound."
    version = "7.1.5"
    license = "GPL-3.0-or-later"
    homepage = "https://ffmpeg.org"

    [[runtimes.ffmpeg.builds]]
    os = "linux"
    arch = "x86_64"
    url = "https://…/ffmpeg-n7.1.5-linux64-gpl-7.1.tar.xz"
    sha256 = "c1e6caf4…"
    size = 119007364
    programs = ["ffmpeg", "ffprobe"]     # found by name in what unpacks, linked into bin/
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path

__all__ = [
    "MAX_RUNTIME_DOWNLOAD",
    "RUNTIMES_DIR",
    "RuntimeProblem",
    "RuntimeStore",
    "build_for",
    "check_runtime",
    "platform_of",
    "said_size",
]


class RuntimeProblem(ValueError):
    """A runtime that cannot be had, and why, in words for a person. The server
    raises its QuillError instead (quills/runtimes.py); the agent raises this."""


RUNTIMES_DIR = "runtimes"
INFO = "runtime.json"
# A static ffmpeg is a hundred megabytes; half a gigabyte is the ceiling.
MAX_RUNTIME_DOWNLOAD = 512 * 1024 * 1024
FETCH_TIMEOUT = 60

ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OSES = ("linux", "darwin", "windows")
# How a machine names itself, as the catalog names it.
ARCHES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "armv7",
    "armv6l": "armv6",
    "i686": "x86",
    "i386": "x86",
}


def platform_of() -> tuple[str, str]:
    """This machine's OS and architecture, as a catalog build names them."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    return system, ARCHES.get(machine, machine)


def said_size(size: int) -> str:
    """A download's size as a person reads it: 119 MB, 1.2 GB."""
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    return f"{max(1, round(size / 1_000_000))} MB"


def check_runtime(runtime_id: str, spec: object, error: type[Exception] = RuntimeProblem) -> None:
    """A runtime as the catalog describes it, or why it cannot be used."""
    where = f"runtime {runtime_id!r}"
    if not ID_RE.match(runtime_id):
        raise error(f"{where}: a runtime's id is lowercase letters, digits, - and _")
    if not isinstance(spec, dict):
        raise error(f"{where} is a table")
    if not str(spec.get("label", "")).strip():
        raise error(f"{where} needs a label")
    builds = spec.get("builds")
    if not isinstance(builds, list) or not builds or not all(isinstance(b, dict) for b in builds):
        raise error(f"{where} needs [[runtimes.{runtime_id}.builds]], one per OS and architecture")
    seen: set[tuple[str, str]] = set()
    for build in builds:
        if build.get("os") not in OSES:
            raise error(f"{where}: a build's os is one of {', '.join(OSES)}")
        arch = str(build.get("arch", ""))
        if arch not in set(ARCHES.values()):
            raise error(f"{where}: a build's arch is one of {', '.join(sorted(set(ARCHES.values())))}")
        if (build["os"], arch) in seen:
            raise error(f"{where}: two builds for {build['os']} {arch}")
        seen.add((build["os"], arch))
        url = str(build.get("url", ""))
        if not url:
            raise error(f"{where}: a build has a url")
        if not SHA256_RE.match(str(build.get("sha256", "")).lower()):
            raise error(f"{where}: a build's sha256 is 64 hex digits; the server refuses what does not match")
        size = build.get("size", 0)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise error(f"{where}: a build's size is its bytes")
        programs = build.get("programs")
        if not isinstance(programs, list) or not programs or not all(isinstance(p, str) and p for p in programs):
            raise error(f"{where}: a build's programs is the list of what it puts on the PATH")
        for program in programs:
            if "/" in program or "\\" in program or program.startswith("."):
                raise error(f"{where}: a program is a name, like ffmpeg; it is found in what unpacks")


def build_for(spec: dict, os_name: str, arch: str) -> dict | None:
    """The build of *spec* for an OS and architecture, or None when there is none."""
    for build in spec.get("builds", ()):
        if build.get("os") == os_name and build.get("arch") == arch:
            return build
    return None


def _fetch(
    url: str, target: Path, *, base: Path | None, limit: int, error: type[Exception] = RuntimeProblem
) -> tuple[str, int]:
    """*url* into *target*: a local path copied, an https URL streamed. Returns (sha256, size)."""
    digest = hashlib.sha256()
    size = 0
    if url.startswith(("https://", "http://")):
        request = urllib.request.Request(url, headers={"User-Agent": "cloudmorrow"})
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response, target.open("wb") as out:  # noqa: S310
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise error(f"{url} is bigger than a runtime may be ({said_size(limit)})")
                    digest.update(chunk)
                    out.write(chunk)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise error(f"could not fetch {url}: {exc}") from exc
        return digest.hexdigest(), size
    path = Path(url).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    if not path.is_file():
        raise error(f"{url} is not a file")
    with path.open("rb") as source, target.open("wb") as out:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise error(f"{url} is bigger than a runtime may be ({said_size(limit)})")
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest(), size


def _unpack(archive: Path, into: Path, error: type[Exception] = RuntimeProblem) -> None:
    into.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    # No path may leave the folder; the data filter does this for tar.
                    if Path(member.filename).is_absolute() or ".." in Path(member.filename).parts:
                        raise error(f"{archive.name} unpacks outside its folder")
                bundle.extractall(into)
            return
        with tarfile.open(archive, mode="r:*") as bundle:
            bundle.extractall(into, filter="data")
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise error(f"{archive.name} is not an archive that unpacks: {exc}") from exc


def _find(root: Path, program: str, error: type[Exception] = RuntimeProblem) -> Path:
    """The program in what unpacked: a file of that name, a `bin/` one first."""
    found = sorted(
        (p for p in root.rglob(program) if p.is_file() and not p.is_symlink()),
        key=lambda p: (p.parent.name != "bin", len(p.parts)),
    )
    if not found:
        raise error(f"{program} is not in what unpacked")
    return found[0]


class RuntimeStore:
    """The runtimes on this server, under `<data_dir>/runtimes/<id>/`.

    Each has `bin/` with its programs (links into what unpacked) and a
    `runtime.json` saying which version it is and where it came from.
    """

    def __init__(
        self,
        root: Path,
        fetch: Callable[..., tuple[str, int]] | None = None,
        error: type[Exception] = RuntimeProblem,
    ) -> None:
        self.root = root
        self._fetch = fetch or _fetch
        # What a refusal is raised as: the server's QuillError, the agent's RuntimeProblem.
        self.error = error
        self.os_name, self.arch = platform_of()

    # -- what is there -------------------------------------------------------------------
    def info(self, runtime_id: str) -> dict | None:
        path = self.root / runtime_id / INFO
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def installed(self) -> dict[str, dict]:
        if not self.root.is_dir():
            return {}
        found = {}
        for folder in sorted(self.root.iterdir()):
            info = self.info(folder.name) if folder.is_dir() and not folder.name.startswith(".") else None
            if info is not None:
                found[folder.name] = info
        return found

    def bin_dir(self, runtime_id: str) -> Path:
        return self.root / runtime_id / "bin"

    def path_for(self, names: Iterable[str]) -> list[str]:
        """The folders to put first on a service's PATH, for the runtimes it names."""
        return [str(self.bin_dir(name)) for name in names if self.info(name) is not None]

    def missing(self, names: Iterable[str]) -> list[str]:
        return [name for name in names if self.info(name) is None]

    # -- the install sheet ---------------------------------------------------------------
    def describe(self, names: Iterable[str], catalog_runtimes: dict | None) -> list[dict]:
        """What installing a Quill that needs *names* would add, one row each.

        With no catalog to hand (an offline check), a row is the name and
        says so; nothing is refused here. With one, a name the catalog does
        not have is refused: there is nowhere to get it from.
        """
        rows = []
        for name in names:
            here = self.info(name)
            row = {
                "id": name,
                "label": name,
                "summary": "",
                "version": "",
                "license": "",
                "homepage": "",
                "size": 0,
                "installed": (here or {}).get("version", "") if here else "",
                "available": False,
                "problem": "",
            }
            if catalog_runtimes is None:
                row["problem"] = "not looked up in the catalog here; the install sheet says what it is and how big"
                rows.append(row)
                continue
            spec = catalog_runtimes.get(name)
            if spec is None:
                raise self.error(f"requires runtime {name!r}, which the catalog does not have")
            row.update(
                label=str(spec.get("label", name)),
                summary=str(spec.get("summary", "")),
                version=str(spec.get("version", "")),
                license=str(spec.get("license", "")),
                homepage=str(spec.get("homepage", "")),
            )
            build = build_for(spec, self.os_name, self.arch)
            if build is None:
                row["problem"] = f"there is no build of {row['label']} for this server ({self.os_name} {self.arch})"
            else:
                row["available"] = True
                row["size"] = int(build.get("size", 0))
            rows.append(row)
        return rows

    def describe_for_machines(self, names: Iterable[str], catalog_runtimes: dict | None) -> list[dict]:
        """Runtimes machine handlers need: what a machine would fetch, with the biggest build's
        size, since which machine is not known here. A name the catalog lacks is refused."""
        rows = []
        for name in names:
            row = {"id": name, "label": name, "summary": "", "version": "", "license": "", "size": 0, "problem": ""}
            if catalog_runtimes is None:
                row["problem"] = "not looked up in the catalog here; the install sheet says what it is and how big"
            elif (spec := catalog_runtimes.get(name)) is None:
                raise self.error(f"a machine handler requires runtime {name!r}, which the catalog does not have")
            else:
                row.update(
                    label=str(spec.get("label", name)),
                    summary=str(spec.get("summary", "")),
                    version=str(spec.get("version", "")),
                    license=str(spec.get("license", "")),
                    size=max((int(b.get("size", 0)) for b in spec.get("builds", ())), default=0),
                    platforms=[f"{b.get('os')} {b.get('arch')}" for b in spec.get("builds", ())],
                )
            rows.append(row)
        return rows

    def describe_installed(self, names: Iterable[str]) -> list[dict]:
        """The runtimes an installed Quill requires, as they are here: the same rows as
        `describe`, from what was fetched, with no catalog asked."""
        rows = []
        for name in names:
            info = self.info(name) or {}
            rows.append(
                {
                    "id": name,
                    "label": str(info.get("label") or name),
                    "summary": "",
                    "version": str(info.get("version", "")),
                    "license": str(info.get("license", "")),
                    "homepage": "",
                    "size": int(info.get("size") or 0),
                    "installed": str(info.get("version", "")) if info else "",
                    "available": bool(info),
                    "problem": "" if info else "not on this server: install the Quill again to fetch it",
                }
            )
        return rows

    # -- installing ----------------------------------------------------------------------
    def ensure(self, names: Iterable[str], catalog_runtimes: dict | None, *, base: Path | None = None) -> list[str]:
        """Every runtime in *names* on this server at the catalog's version. Returns what was fetched.

        Refused, before anything is fetched, when a name is not in the catalog
        or has no build for this machine: an install is all or nothing.
        """
        wanted = list(dict.fromkeys(names))
        if not wanted:
            return []
        if catalog_runtimes is None:
            raise self.error(f"needs {', '.join(wanted)}, and the catalog that says where to get it could not be read")
        todo = []
        for name in wanted:
            spec = catalog_runtimes.get(name)
            if spec is None:
                raise self.error(f"requires runtime {name!r}, which the catalog does not have")
            build = build_for(spec, self.os_name, self.arch)
            if build is None:
                raise self.error(
                    f"there is no build of {spec.get('label', name)} for this server ({self.os_name} {self.arch})"
                )
            here = self.info(name)
            if here and here.get("sha256") == str(build["sha256"]).lower():
                continue
            todo.append((name, spec, build))
        for name, spec, build in todo:
            self.install(name, spec, build, base=base)
        return [name for name, _, _ in todo]

    def install(self, runtime_id: str, spec: dict, build: dict, *, base: Path | None = None) -> dict:
        """Fetch one build, check it, unpack it and link its programs; replaces what was there."""
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".{runtime_id}.new"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        try:
            with tempfile.TemporaryDirectory(prefix="runtime-", dir=self.root) as tmp:
                archive = Path(tmp) / "download"
                digest, size = self._fetch(
                    str(build["url"]), archive, base=base, limit=MAX_RUNTIME_DOWNLOAD, error=self.error
                )
                if digest != str(build["sha256"]).lower():
                    raise self.error(
                        f"{spec.get('label', runtime_id)} did not download as the catalog says it should"
                        " (its checksum differs); nothing was installed"
                    )
                _unpack(archive, staging / "files", self.error)
            bin_dir = staging / "bin"
            bin_dir.mkdir()
            programs = {}
            for program in build["programs"]:
                found = _find(staging / "files", program, self.error)
                found.chmod(found.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                (bin_dir / program).symlink_to(os.path.relpath(found, bin_dir))
                programs[program] = str(found.relative_to(staging))
            info = {
                "id": runtime_id,
                "label": str(spec.get("label", runtime_id)),
                "version": str(spec.get("version", "")),
                "license": str(spec.get("license", "")),
                "url": str(build["url"]),
                "sha256": str(build["sha256"]).lower(),
                "size": size,
                "programs": programs,
                "installed_at": dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds"),
            }
            (staging / INFO).write_text(json.dumps(info, indent=2), encoding="utf-8")
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        target = self.root / runtime_id
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        return info

    def remove(self, runtime_id: str) -> bool:
        """Take a runtime away. True when there was one."""
        target = self.root / runtime_id
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        return True
