"""Spelling: the dictionaries a server checks words against, and the checks.

The web app's editors — a document, a note — check spelling here rather
than with the browser's own checker, so every phone and computer somebody
signs in on marks the same words, in the languages they chose, with the
words they added kept on them (docs/MANUAL.md, *Spelling*). The engine is
Hunspell, which every office suite checks with, as a wheel with the
library inside (chunspell); the dictionaries are the ones LibreOffice
ships, pinned in the catalog:

    [dictionaries.da]                     # in catalog.toml
    label = "Dansk"
    summary = "Danish"
    license = "GPL-2.0-or-later OR LGPL-2.1-or-later OR MPL-1.1"
    homepage = "https://stavekontrolden.dk"

    [[dictionaries.da.files]]
    name = "da.aff"
    url = "https://…/da_DK.aff"
    sha256 = "ee4fe193…"
    size = 82864

A language is fetched the first time somebody writes in it, the way a
runtime is fetched for a Quill (runtimes.py): checked against its SHA-256,
kept under `<data_dir>/dictionaries/<id>/`, and loaded once into memory.
Nothing is installed on the system, and nothing is fetched until it is
asked for. A dictionary fetched once is there when the catalog is not.

The checks are plain: `check` says which of some words are not in the
dictionary, `suggest` says what a word might have been. What is a word,
which words to skip (a number, a URL, a name a person added) and where
each language applies is the editor's business, in the browser
(web/spelling.js); here is only the dictionary.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from cloudmorrow.runtimes import SHA256_RE, _fetch, said_size
from cloudmorrow.server.quills.manifest import QuillError

__all__ = [
    "DICTIONARIES_DIR",
    "MAX_DICTIONARY_DOWNLOAD",
    "MAX_SUGGESTIONS",
    "MAX_WORDS",
    "DictionaryStore",
    "Speller",
    "SpellingError",
    "check_dictionary",
    "language_id",
]

DICTIONARIES_DIR = "dictionaries"
INFO = "dictionary.json"
# The biggest dictionary LibreOffice ships is under ten megabytes.
MAX_DICTIONARY_DOWNLOAD = 64 * 1024 * 1024
# A check is a screenful of words at a time; a word longer than this is not one.
MAX_WORDS = 500
MAX_WORD_LENGTH = 64
MAX_SUGGESTIONS = 8
# How long a catalog read is kept before it is read again.
CATALOG_FOR = 3600

# A language's id: a language code, with a region when the spelling differs by it.
ID_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?$")
FILE_RE = re.compile(r"^[a-z]{2,3}(-[a-z]{2})?\.(aff|dic)$")


class SpellingError(ValueError):
    """What cannot be checked, and why, in words for a person."""


def language_id(value: object) -> str:
    """A language id as the catalog spells it, or '' for anything else: `da`, `en-gb`."""
    text = str(value or "").strip().lower().replace("_", "-")
    return text if ID_RE.match(text) else ""


def check_dictionary(dictionary_id: str, spec: object, error: type[Exception] = QuillError) -> None:
    """A dictionary as the catalog describes it, or why it cannot be used."""
    where = f"dictionary {dictionary_id!r}"
    if not ID_RE.match(dictionary_id):
        raise error(f"{where}: a dictionary's id is a language code, with a region when it matters: da, en-gb")
    if not isinstance(spec, dict):
        raise error(f"{where} is a table")
    if not str(spec.get("label", "")).strip():
        raise error(f"{where} needs a label: the language's name, in the language")
    files = spec.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, dict) for f in files):
        raise error(f"{where} needs [[dictionaries.{dictionary_id}.files]]: its .aff and its .dic")
    names = set()
    for one in files:
        name = str(one.get("name", ""))
        if not FILE_RE.match(name) or not name.startswith(dictionary_id + "."):
            raise error(f"{where}: a file is named {dictionary_id}.aff or {dictionary_id}.dic")
        if name in names:
            raise error(f"{where}: {name} twice")
        names.add(name)
        if not str(one.get("url", "")):
            raise error(f"{where}: {name} has a url")
        if not SHA256_RE.match(str(one.get("sha256", "")).lower()):
            raise error(f"{where}: {name}'s sha256 is 64 hex digits; the server refuses what does not match")
        size = one.get("size", 0)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise error(f"{where}: {name}'s size is its bytes")
    if names != {dictionary_id + ".aff", dictionary_id + ".dic"}:
        raise error(f"{where} needs both {dictionary_id}.aff and {dictionary_id}.dic")


def _size_of(spec: dict) -> int:
    return sum(int(f.get("size", 0)) for f in spec.get("files", ()))


class DictionaryStore:
    """The dictionaries on this server, under `<data_dir>/dictionaries/<id>/`.

    Each folder holds the language's `.aff` and `.dic` and a
    `dictionary.json` saying what it is and where it came from.
    """

    def __init__(self, root: Path, fetch: Callable[..., tuple[str, int]] | None = None) -> None:
        self.root = root
        self._fetch = fetch or _fetch

    def folder(self, dictionary_id: str) -> Path:
        return self.root / dictionary_id

    def info(self, dictionary_id: str) -> dict | None:
        path = self.folder(dictionary_id) / INFO
        if not path.is_file():
            return None
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None
        # Both files, or it is not a dictionary.
        if not all((self.folder(dictionary_id) / name).is_file() for name in info.get("files", ())):
            return None
        return info

    def installed(self) -> dict[str, dict]:
        if not self.root.is_dir():
            return {}
        found = {}
        for folder in sorted(self.root.iterdir()):
            info = self.info(folder.name) if folder.is_dir() and ID_RE.match(folder.name) else None
            if info is not None:
                found[folder.name] = info
        return found

    def ensure(self, dictionary_id: str, spec: dict, base: Path | None = None) -> Path:
        """The folder with the language's files in it, fetched if they are not there
        yet, or not as the catalog says they are. Refuses a file whose SHA-256 differs."""
        folder = self.folder(dictionary_id)
        here = self.info(dictionary_id)
        wanted = {str(f["name"]): str(f["sha256"]).lower() for f in spec["files"]}
        if here is not None and here.get("sha256") == wanted:
            return folder
        folder.mkdir(parents=True, exist_ok=True)
        for one in spec["files"]:
            name = str(one["name"])
            target = folder / (name + ".part")
            digest, size = self._fetch(
                str(one["url"]), target, base=base, limit=MAX_DICTIONARY_DOWNLOAD, error=SpellingError
            )
            if digest != wanted[name]:
                target.unlink(missing_ok=True)
                raise SpellingError(f"{name} is not the file the catalog says it is (its SHA-256 differs); not kept")
            if int(one.get("size", 0)) and size != int(one["size"]):
                target.unlink(missing_ok=True)
                raise SpellingError(
                    f"{name} is {said_size(size)}, not the {said_size(int(one['size']))} the catalog says"
                )
            target.replace(folder / name)
        info = {
            "id": dictionary_id,
            "label": str(spec.get("label", dictionary_id)),
            "summary": str(spec.get("summary", "")),
            "license": str(spec.get("license", "")),
            "homepage": str(spec.get("homepage", "")),
            "files": sorted(wanted),
            "sha256": wanted,
            "size": _size_of(spec),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (folder / INFO).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        return folder


def _engine():
    """The Hunspell class, or None where the wheel is not installed."""
    try:
        from hunspell import Hunspell
    except ImportError:  # pragma: no cover - the server extra has it
        return None
    return Hunspell


class Speller:
    """The languages, and the checks: one Hunspell per language, loaded when
    first asked for and kept.

    *catalog* answers the catalog's `dictionaries` table and the folder its
    relative paths are under, `(table, base)`, or raises QuillError when the
    catalog cannot be read; it is asked at most once an hour. What was
    fetched before is a language whether or not the catalog can be read.
    """

    def __init__(self, store: DictionaryStore, catalog: Callable[[], tuple[dict, Path | None]]) -> None:
        self.store = store
        self._catalog = catalog
        self._known: tuple[float, dict, Path | None] | None = None
        self._engines: dict[str, object] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._problem = ""

    # -- the languages --------------------------------------------------------------
    def _from_catalog(self) -> tuple[dict, Path | None]:
        """The catalog's dictionaries, read at most once an hour; {} when it cannot be."""
        now = time.monotonic()
        if self._known is not None and now - self._known[0] < CATALOG_FOR:
            return self._known[1], self._known[2]
        try:
            table, base = self._catalog()
            self._problem = ""
        except QuillError as exc:
            table, base = {}, None
            self._problem = f"the catalog could not be read ({exc})"
        self._known = (now, dict(table), base)
        return self._known[1], self._known[2]

    def forget(self) -> None:
        """Read the catalog again next time: a test, or an administrator, changed it."""
        self._known = None

    def specs(self) -> dict[str, dict]:
        """Every language, by id: the catalog's, and whatever was fetched before."""
        table, _ = self._from_catalog()
        specs = {dictionary_id: dict(spec) for dictionary_id, spec in table.items()}
        for dictionary_id, info in self.store.installed().items():
            specs.setdefault(dictionary_id, info)
        return specs

    def languages(self) -> list[dict]:
        """What can be chosen: [{id, label, summary, size, ready}], by label.
        `ready` says the files are here already; the first check fetches them."""
        engine = _engine()
        rows = []
        for dictionary_id, spec in self.specs().items():
            rows.append(
                {
                    "id": dictionary_id,
                    "label": str(spec.get("label", dictionary_id)),
                    "summary": str(spec.get("summary", "")),
                    "size": int(spec.get("size", 0)) or _size_of(spec),
                    "ready": engine is not None and self.store.info(dictionary_id) is not None,
                }
            )
        return sorted(rows, key=lambda r: r["label"].lower())

    def problem(self) -> str:
        """Why no language can be checked, when none can; '' otherwise."""
        if _engine() is None:
            return "the spelling engine is not installed on this server (the chunspell wheel)"
        self._from_catalog()
        if not self.specs():
            return self._problem or "the catalog lists no dictionaries"
        return ""

    # -- the engine for a language --------------------------------------------------
    def engine(self, dictionary_id: str):
        """The loaded Hunspell for a language, fetching and loading it the first time."""
        dictionary_id = language_id(dictionary_id)
        if not dictionary_id:
            raise SpellingError("that is not a language")
        with self._lock:
            lock = self._locks.setdefault(dictionary_id, threading.Lock())
        with lock:
            loaded = self._engines.get(dictionary_id)
            if loaded is not None:
                return loaded
            hunspell = _engine()
            if hunspell is None:
                raise SpellingError("the spelling engine is not installed on this server (the chunspell wheel)")
            table, base = self._from_catalog()
            spec = table.get(dictionary_id)
            if spec is not None:
                folder = self.store.ensure(dictionary_id, spec, base)
            elif self.store.info(dictionary_id) is not None:
                folder = self.store.folder(dictionary_id)
            else:
                raise SpellingError(
                    f"there is no dictionary for {dictionary_id!r}"
                    + (f"; {self._problem}" if self._problem else " in the catalog")
                )
            try:
                loaded = hunspell(dictionary_id, hunspell_data_dir=str(folder))
            except Exception as exc:  # noqa: BLE001 - whatever the library raises on a bad file
                raise SpellingError(f"the {dictionary_id} dictionary could not be loaded: {exc}") from exc
            self._engines[dictionary_id] = loaded
            return loaded

    # -- the checks -------------------------------------------------------------------
    def check(self, dictionary_id: str, words: Iterable[str]) -> list[str]:
        """Of *words*, the ones the language does not know, in the order given, once each."""
        engine = self.engine(dictionary_id)
        lock = self._locks[language_id(dictionary_id)]
        wrong: list[str] = []
        seen: set[str] = set()
        with lock:
            for word in words:
                word = str(word)
                if not word or len(word) > MAX_WORD_LENGTH or word in seen:
                    continue
                seen.add(word)
                if not engine.spell(word):
                    wrong.append(word)
        return wrong

    def suggest(self, dictionary_id: str, word: str) -> list[str]:
        """What *word* might have been: Hunspell's suggestions, the first few."""
        word = str(word)
        if not word or len(word) > MAX_WORD_LENGTH:
            return []
        engine = self.engine(dictionary_id)
        lock = self._locks[language_id(dictionary_id)]
        with lock:
            found = list(engine.suggest(word))
        out: list[str] = []
        for one in found:
            if one and one != word and one not in out:
                out.append(one)
            if len(out) >= MAX_SUGGESTIONS:
                break
        return out
