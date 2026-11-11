"""Spelling: the dictionaries the catalog pins, fetched when first written in,
and the checks the editors make (server/spelling.py). Nothing here reaches the
network: the dictionary is the few words beside the fixture catalog."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from cloudmorrow.quill import docs
from cloudmorrow.server.db import spelling_setting
from cloudmorrow.server.quills import QuillError, load_catalog
from cloudmorrow.server.routes.web import WEB
from cloudmorrow.server.spelling import DictionaryStore, Speller, SpellingError, check_dictionary, language_id
from tests.conftest import QUILL_CATALOG, js_code


def dictionaries():
    catalog = load_catalog(str(QUILL_CATALOG))
    return catalog.dictionaries, catalog.base


def spec() -> dict:
    return json.loads(json.dumps(dictionaries()[0]["en"]))


# -- the catalog --------------------------------------------------------------------
def test_the_catalog_pins_a_dictionary_as_two_files_with_hashes():
    table, base = dictionaries()
    assert set(table) == {"en"}
    assert [f["name"] for f in table["en"]["files"]] == ["en.aff", "en.dic"]
    for one in table["en"]["files"]:
        data = (base / one["url"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == one["sha256"] and len(data) == one["size"]


def test_a_dictionary_the_catalog_describes_badly_is_refused():
    good = spec()
    check_dictionary("en", good)
    with pytest.raises(QuillError, match="language code"):
        check_dictionary("English", good)
    bad = spec()
    bad["files"] = bad["files"][:1]
    with pytest.raises(QuillError, match="both en.aff and en.dic"):
        check_dictionary("en", bad)
    bad = spec()
    bad["files"][0]["sha256"] = "nope"
    with pytest.raises(QuillError, match="64 hex digits"):
        check_dictionary("en", bad)
    bad = spec()
    bad["files"][1]["name"] = "da.dic"
    with pytest.raises(QuillError, match="named en.aff or en.dic"):
        check_dictionary("en", bad)
    del bad["label"]
    with pytest.raises(QuillError, match="label"):
        check_dictionary("en", bad)


def test_language_ids_are_codes():
    assert language_id("da") == "da" and language_id("EN_GB") == "en-gb" and language_id("nb") == "nb"
    assert language_id("english") == "" and language_id("") == "" and language_id("en-") == ""


# -- the store ------------------------------------------------------------------------
def test_the_store_fetches_once_checks_the_hash_and_keeps_what_it_got(tmp_path):
    fetched = []

    def fetch(url, target, *, base, limit, error):
        fetched.append(url)
        data = (base / url).read_bytes()
        target.write_bytes(data)
        return hashlib.sha256(data).hexdigest(), len(data)

    store = DictionaryStore(tmp_path / "dictionaries", fetch)
    table, base = dictionaries()
    assert store.installed() == {} and store.info("en") is None
    folder = store.ensure("en", table["en"], base)
    assert (folder / "en.aff").is_file() and (folder / "en.dic").is_file()
    assert fetched == ["dictionaries/en.aff", "dictionaries/en.dic"]
    info = store.info("en")
    assert info["label"] == "English (test)" and info["files"] == ["en.aff", "en.dic"] and info["size"] > 0
    assert list(store.installed()) == ["en"]
    # Asked again, nothing is fetched: the files are what the catalog says.
    store.ensure("en", table["en"], base)
    assert len(fetched) == 2
    # A file that is not what the catalog says is not kept.
    wrong = spec()
    wrong["files"][1]["sha256"] = "0" * 64
    with pytest.raises(SpellingError, match="SHA-256 differs"):
        store.ensure("en", wrong, base)
    assert not (folder / "en.dic.part").exists()


# -- the speller ------------------------------------------------------------------------
@pytest.fixture()
def speller(tmp_path) -> Speller:
    return Speller(DictionaryStore(tmp_path / "dictionaries"), dictionaries)


def test_it_lists_the_languages_and_checks_words(speller):
    assert speller.problem() == ""
    [english] = speller.languages()
    assert english["id"] == "en" and english["label"] == "English (test)" and english["ready"] is False
    assert speller.check("en", ["hello", "worlds", "helo", "Cloud", "morrow", "helo", ""]) == ["helo"]
    assert speller.languages()[0]["ready"] is True
    assert speller.suggest("en", "helo") == ["hello"]
    assert speller.suggest("en", "") == []


def test_a_language_the_catalog_does_not_have_is_refused(speller):
    with pytest.raises(SpellingError, match="no dictionary for 'da'"):
        speller.check("da", ["hej"])
    with pytest.raises(SpellingError, match="not a language"):
        speller.check("English", ["hello"])


def test_a_language_fetched_before_is_still_there_without_the_catalog(tmp_path):
    first = Speller(DictionaryStore(tmp_path / "dictionaries"), dictionaries)
    first.check("en", ["hello"])

    def gone():
        raise QuillError("no catalog at all")

    later = Speller(DictionaryStore(tmp_path / "dictionaries"), gone)
    assert later.problem() == ""
    assert [row["id"] for row in later.languages()] == ["en"]
    assert later.check("en", ["helo"]) == ["helo"]
    empty = Speller(DictionaryStore(tmp_path / "nothing"), gone)
    assert "catalog could not be read" in empty.problem()
    assert empty.languages() == []


# -- the routes -----------------------------------------------------------------------
def test_the_routes_check_and_suggest(client, auth):
    listed = client.get("/api/spelling/languages", headers=auth)
    assert listed.status_code == 200
    assert listed.json()["problem"] == ""
    assert [row["id"] for row in listed.json()["languages"]] == ["en"]
    checked = client.post(
        "/api/spelling/check", json={"language": "en", "words": ["hello", "helo", "worlds"]}, headers=auth
    )
    assert checked.status_code == 200 and checked.json() == {"wrong": ["helo"]}
    suggested = client.post("/api/spelling/suggest", json={"language": "en", "word": "helo"}, headers=auth)
    assert suggested.status_code == 200 and suggested.json() == {"suggestions": ["hello"]}
    assert (
        client.post("/api/spelling/check", json={"language": "English", "words": ["x"]}, headers=auth).status_code
        == 400
    )
    missing = client.post("/api/spelling/check", json={"language": "da", "words": ["hej"]}, headers=auth)
    assert missing.status_code == 503 and "no dictionary for 'da'" in missing.json()["detail"]
    assert client.get("/api/spelling/languages").status_code == 401


# -- the setting on the person ------------------------------------------------------------
def test_the_setting_is_cleaned():
    assert spelling_setting(None) == {"check": False, "language": "", "words": []}
    cleaned = spelling_setting({"check": 1, "language": " DA ", "words": ["Morrow", " ", "Morrow", 3, "Bram"]})
    assert cleaned == {"check": True, "language": "da", "words": ["Morrow", "Bram"]}


def test_the_setting_is_kept_on_the_person(client, auth):
    assert client.get("/api/auth/me", headers=auth).json()["spelling"] == {"check": False, "language": "", "words": []}
    assert client.get("/api/auth/spelling", headers=auth).json() == {"check": False, "language": "", "words": []}
    saved = client.put(
        "/api/auth/spelling", json={"check": True, "language": "da", "words": ["Morrow", "Morrow"]}, headers=auth
    )
    assert saved.status_code == 200 and saved.json() == {"check": True, "language": "da", "words": ["Morrow"]}
    assert client.get("/api/auth/me", headers=auth).json()["spelling"] == {
        "check": True,
        "language": "da",
        "words": ["Morrow"],
    }


# -- a document's language, and a note's ---------------------------------------------------
def test_a_block_keeps_its_language_and_markdown_says_it_in_comments():
    doc = docs.Doc(
        [
            {"kind": "paragraph", "runs": [{"text": "Hello"}]},
            {"kind": "bullet", "runs": [{"text": "Hallo"}], "lang": "DE"},
            {"kind": "bullet", "runs": [{"text": "Welt"}], "lang": "de"},
            {"kind": "paragraph", "runs": [{"text": "Bye"}], "lang": "nonsense"},
        ]
    )
    assert [b.get("lang", "") for b in doc.blocks] == ["", "de", "de", ""]
    text = docs.to_markdown(doc)
    assert text == "Hello\n\n<!-- lang: de -->\n\n- Hallo\n- Welt\n\n<!-- /lang -->\n\nBye\n"
    assert docs.from_markdown(text).blocks == doc.blocks
    # A part that runs to the end, and one the file says with a region.
    tail = docs.from_markdown("one\n\n<!-- lang: en_GB -->\n\ncolour\n")
    assert [b.get("lang", "") for b in tail.blocks] == ["", "en-gb"]
    assert docs.to_markdown(tail).endswith("colour\n\n<!-- /lang -->\n")


def test_the_web_app_has_the_spellchecker_and_the_browsers_is_off(client):
    spelling = (WEB / "spelling.js").read_text(encoding="utf-8")
    code = js_code(spelling)
    assert 'import "./spelling.js";' in (WEB / "app.js").read_text(encoding="utf-8")
    assert '@import "./spelling.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    # The browser's own checker is off in both editors; the setting turns ours on.
    assert 'spellcheck="false"' in js_code((WEB / "kit_docs.js").read_text(encoding="utf-8"))
    assert "el.spellcheck = false;" in js_code((WEB / "markdown.js").read_text(encoding="utf-8"))
    # It speaks the routes above, and the setting's, and nothing else.
    for address in ("/api/spelling/languages", "/api/spelling/check", "/api/spelling/suggest", "/api/auth/spelling"):
        assert address in code, address
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", code)
    # Nothing in it is named for one Quill.
    for word in ("Notes", "Docs", "Documents"):
        assert not re.search(rf"(?<![\w/]){word}(?![\w])", code), word
    # The language lines a note keeps are the ones a document exports.
    rules = js_code((WEB / "markdown_rules.js").read_text(encoding="utf-8"))
    assert "export function langLine(raw)" in rules and "md-lang-start" in rules
    assert (WEB / "spelling.css").read_text(encoding="utf-8").count("spell-miss") >= 1
