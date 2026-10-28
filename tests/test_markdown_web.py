"""The page you write in: Markdown drawn as it reads, the marks shown on the line you are on.

What a browser shows is checked in one (see the screenshots in the change
that made it). What a test holds is what goes wrong quietly: a line whose
drawing is not its own text letter for letter — the caret and the saved
file would drift from what was typed — and what Enter, Tab and a tick
write. markdown_rules.js is pure and runs here under node.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess

import pytest

from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import js_code

MARKDOWN_JS = (WEB / "markdown.js").read_text(encoding="utf-8")
PICTURES_JS = (WEB / "pictures.js").read_text(encoding="utf-8")
EDITOR_JS = (WEB / "kit_editor.js").read_text(encoding="utf-8")
EDITOR_CSS = (WEB / "kit_editor.css").read_text(encoding="utf-8")
MARKDOWN_CSS = (WEB / "markdown.css").read_text(encoding="utf-8")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

RUNNER = """
import * as rules from "%s";
import { readFileSync } from "node:fs";
const calls = JSON.parse(readFileSync(0, "utf8"));
console.log(JSON.stringify(calls.map(([name, ...args]) => rules[name](...args))));
"""


def run(tmp_path, *calls):
    script = tmp_path / "rules.mjs"
    script.write_text(RUNNER % (WEB / "markdown_rules.js").as_uri(), encoding="utf-8")
    done = subprocess.run(["node", str(script)], input=json.dumps(calls), capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def text_of(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup))


def marks_of(markup: str) -> list[str]:
    return [html.unescape(m) for m in re.findall(r'<span class="md-mk[^"]*">([^<]*)</span>', markup)]


LINES = [
    "## A heading with **bold** and `code`",
    "Some *em*, _em_, __strong__, ~~gone~~ and a \\* star",
    "- [ ] a task with a [link](https://example.com)",
    "  - [x] done & dusted <b>",
    "* bullet",
    "12) numbered",
    "> > a quote",
    "---",
    "| a | b |",
    "<https://cloudmorrow.org> and https://cloudmorrow.org/docs, then #tag",
    "![a picture](https://example.com/p.png)",
    "",
    "plain",
]


# -- wired in ------------------------------------------------------------------------
def test_the_body_is_the_markdown_box_not_a_textarea(client):
    assert 'import { markdownArea } from "./markdown.js";' in PICTURES_JS
    assert 'from "./markdown_rules.js"' in MARKDOWN_JS
    assert "textarea" not in js_code(PICTURES_JS).lower()
    assert '@import "./markdown.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    version = asset_version()
    for name in ("markdown.js", "markdown_rules.js", "markdown.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_it_stands_in_for_a_textarea():
    for face in ("value:", "selectionStart:", "selectionEnd:", "placeholder:", "readOnly:", "el.setSelectionRange ="):
        assert face in MARKDOWN_JS, face


def test_its_classes_are_its_own():
    """A class another screen styles (the calendar's .dot) must not land on a line."""
    for name in re.findall(r"\.([a-z][\w-]*)", js_code(MARKDOWN_CSS)):
        assert name.startswith("md") or name in {"editor", "body", "blocks"}, name


def test_the_marks_hide_except_on_the_line_you_are_on():
    css = js_code(MARKDOWN_CSS)
    assert ".md .md-ln:not(.md-on) .md-mk { display: none; }" in css
    assert 'toggle("md-on"' in MARKDOWN_JS


def test_it_never_opens_a_browser_window():
    assert not re.search(r"(?<![.\w])(confirm|prompt|alert)\(", js_code(MARKDOWN_JS))


# -- the list folds away -------------------------------------------------------------
def test_the_list_beside_a_page_folds_and_stays_folded():
    code = js_code(EDITOR_JS)
    assert 'const FOLDED = "editor.folded";' in code
    assert 'store.set(FOLDED, now ? "1" : null)' in code
    assert '<main class="split${folded() ? " folded" : ""}">' in code
    media = js_code(EDITOR_CSS).split("@media (min-width: 900px) and (min-height: 600px)", 1)[1]
    # Folded, the list is its top line alone, with the button that brings it back.
    assert "main.split.folded .side > :not(.side-head), main.split.folded .side-back { display: none; }" in media


# -- the rules, under node ------------------------------------------------------------
@node
def test_every_line_is_drawn_from_its_own_text_letter_for_letter(tmp_path):
    drawn = run(tmp_path, *(["renderLine", line] for line in LINES), ["renderLine", "a <b> & c", True])
    for line, d in zip([*LINES, "a <b> & c"], drawn, strict=True):
        assert text_of(d["html"]) == line, line


@node
def test_what_each_line_is(tmp_path):
    drawn = run(tmp_path, *(["renderLine", line] for line in LINES))
    cls = {line: d["cls"] for line, d in zip(LINES, drawn, strict=True)}
    assert cls["## A heading with **bold** and `code`"] == "md-h2"
    assert cls["- [ ] a task with a [link](https://example.com)"] == "md-task"
    assert cls["  - [x] done & dusted <b>"] == "md-task md-done"
    assert cls["* bullet"] == cls["12) numbered"] == "md-item"
    assert cls["> > a quote"] == "md-quote"
    assert cls["---"] == "md-rule"
    assert cls["| a | b |"] == "md-table"
    assert cls["plain"] == cls[""] == ""


@node
def test_the_marks_are_the_markdown_and_the_words_are_not(tmp_path):
    heading, inline, task, link = run(
        tmp_path,
        ["renderLine", LINES[0]],
        ["renderLine", LINES[1]],
        ["renderLine", LINES[2]],
        ["renderLine", LINES[9]],
    )
    assert marks_of(heading["html"]) == ["## ", "**", "**", "`", "`"]
    assert "<strong>bold</strong>" in heading["html"] and "<code>code</code>" in heading["html"]
    assert marks_of(inline["html"]) == ["*", "*", "_", "_", "__", "__", "~~", "~~", "\\"]
    assert marks_of(task["html"]) == ["- [ ] ", "[", "](https://example.com)"]
    assert '<span class="md-mk md-glyph md-box">' in task["html"]
    assert 'data-href="https://example.com"' in task["html"]
    assert 'data-href="https://cloudmorrow.org"' in link["html"]
    assert 'data-href="https://cloudmorrow.org/docs"' in link["html"]  # the comma is not the address's
    assert '<span class="md-tag">#tag</span>' in link["html"]


@node
def test_only_the_web_and_mail_open_from_a_link(tmp_path):
    (bad,) = run(tmp_path, ["inline", "[x](javascript:alert(1))"])
    assert "data-href" not in bad


@node
def test_fenced_code_is_followed_from_the_top(tmp_path):
    (states,) = run(tmp_path, ["codeStates", ["a", "```js", "# not a heading", "```", "# heading"]])
    assert states == [False, False, True, False, False]
    (drawn,) = run(tmp_path, ["renderLines", ["```", "**x**", "```"]])
    assert [d["cls"] for d in drawn] == ["md-fence", "md-code", "md-fence"]
    assert "<strong>" not in drawn[1]["html"]


@node
def test_enter_carries_the_list_on_and_ends_it_on_an_empty_item(tmp_path):
    got = run(
        tmp_path,
        ["continueLine", "- milk"],
        ["continueLine", "  * eggs"],
        ["continueLine", "- [x] done"],
        ["continueLine", "9. nine"],
        ["continueLine", "3) three"],
        ["continueLine", "> said"],
        ["continueLine", "plain"],
        ["continueLine", "- "],
        ["continueLine", "- ", "rest of the line"],
    )
    assert [g.get("insert") for g in got[:7]] == ["\n- ", "\n  * ", "\n- [ ] ", "\n10. ", "\n4) ", "\n> ", "\n"]
    assert got[7] == {"clear": True, "length": 2}
    assert got[8] == {"insert": "\n- "}


@node
def test_a_tick_flips_the_box_and_nothing_else(tmp_path):
    assert run(
        tmp_path,
        ["toggleTask", "- [ ] buy [milk]"],
        ["toggleTask", "  * [X] done"],
        ["toggleTask", "- not a task [ ]"],
        ["isListLine", "1. one"],
        ["isListLine", "plain"],
    ) == ["- [x] buy [milk]", "  * [ ] done", "- not a task [ ]", True, False]
