"""The formatting bar: what each mark does to the words under it.

The bar itself is a few lines of DOM, but what it means is arithmetic on a
string — so that part is a pure function and gets tested here, under node,
without a browser anywhere. Skipped where node is not installed; it is not a
dependency of Cloudmorrow, only of reading its own JavaScript.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from cloudmorrow.server.routes.web import WEB

FORMAT = WEB / "format.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

RUNNER = """
import { applied, edit, ACTIONS } from "%s";
import { readFileSync } from "node:fs";
const input = JSON.parse(readFileSync(0, "utf8"));
if (input.actions) {
  console.log(JSON.stringify({ actions: ACTIONS }));
} else {
  console.log(JSON.stringify(input.cases.map(([name, text, start, end]) => {
    const out = applied(name, text, start, end);
    const step = edit(name, text, start, end);
    return { ...out, selected: out.text.slice(out.start, out.end), from: step.from, to: step.to };
  })));
}
"""


def run(payload: dict, tmp_path) -> object:
    script = tmp_path / "run.mjs"
    script.write_text(RUNNER % FORMAT.as_uri(), encoding="utf-8")
    done = subprocess.run(
        ["node", str(script)],
        input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def cases(tmp_path, *items):
    return run({"cases": list(items)}, tmp_path)


# -- the marks that wrap ---------------------------------------------------------
@node
def test_a_wrap_goes_round_the_words_and_leaves_them_selected(tmp_path):
    (out,) = cases(tmp_path, ["bold", "hello", 0, 5])
    assert out["text"] == "**hello**"
    assert out["selected"] == "hello"


@node
@pytest.mark.parametrize("start,end", [(0, 6), (2, 4)])
def test_a_wrap_comes_off_again_whether_the_marks_are_in_or_out_of_the_selection(
    tmp_path, start, end
):
    (out,) = cases(tmp_path, ["bold", "**hi**", start, end])
    assert out["text"] == "hi"
    assert out["selected"] == "hi"


@node
def test_italic_on_bold_words_does_not_quietly_unbold_them(tmp_path):
    """`*` must not read the inside of a `**` as its own mark."""
    (out,) = cases(tmp_path, ["italic", "**hi**", 2, 4])
    assert out["text"] == "***hi***"


@node
def test_a_wrap_with_nothing_selected_leaves_the_caret_between_the_marks(tmp_path):
    (out,) = cases(tmp_path, ["code", "", 0, 0])
    assert out["text"] == "``"
    assert out["start"] == out["end"] == 1


# -- the marks that go at the head of a line ------------------------------------
@node
def test_a_list_takes_every_line_the_selection_touches(tmp_path):
    # Selection is one character of the first line; both lines get a bullet.
    (out,) = cases(tmp_path, ["bullet", "a\nb", 0, 1])
    assert out["text"] == "- a\nb"
    (both,) = cases(tmp_path, ["bullet", "a\nb", 0, 3])
    assert both["text"] == "- a\n- b"


@node
def test_a_list_comes_off_when_every_line_already_has_it(tmp_path):
    (out,) = cases(tmp_path, ["bullet", "- a\n- b", 0, 7])
    assert out["text"] == "a\nb"


@node
@pytest.mark.parametrize(
    "name,before,after",
    [
        ("check", "- a\n- b", "- [ ] a\n- [ ] b"),
        ("bullet", "- [ ] a\n- [x] b", "- a\n- b"),
        ("numbered", "- a\n- b", "1. a\n2. b"),
        ("quote", "- a", "> a"),
    ],
)
def test_one_line_carries_one_mark_so_a_new_one_replaces_the_old(
    tmp_path, name, before, after
):
    (out,) = cases(tmp_path, [name, before, 0, len(before)])
    assert out["text"] == after


@node
def test_numbering_counts_the_lines_that_get_a_number(tmp_path):
    (out,) = cases(tmp_path, ["numbered", "a\n\nb", 0, 4])
    assert out["text"] == "1. a\n\n2. b"


@node
def test_numbering_comes_off_a_list_that_did_not_start_at_one(tmp_path):
    (out,) = cases(tmp_path, ["numbered", "3. a\n4. b", 0, 9])
    assert out["text"] == "a\nb"


@node
def test_indented_lines_keep_their_indent(tmp_path):
    (out,) = cases(tmp_path, ["bullet", "  a", 0, 3])
    assert out["text"] == "  - a"


# -- headings and links ----------------------------------------------------------
@node
@pytest.mark.parametrize(
    "before,after", [("t", "# t"), ("# t", "## t"), ("## t", "### t"), ("### t", "t")]
)
def test_a_heading_cycles_through_three_levels_and_off(tmp_path, before, after):
    (out,) = cases(tmp_path, ["heading", before, 0, len(before)])
    assert out["text"] == after


@node
def test_a_block_of_lines_takes_the_level_the_first_one_decides(tmp_path):
    (out,) = cases(tmp_path, ["heading", "a\n# b", 0, 5])
    assert out["text"] == "# a\n# b"


@node
def test_a_link_puts_the_selection_on_the_address_so_you_can_type_it(tmp_path):
    (out,) = cases(tmp_path, ["link", "docs", 0, 4])
    assert out["text"] == "[docs](url)"
    assert out["selected"] == "url"


# -- the bar's own shape ---------------------------------------------------------
@node
def test_every_button_on_the_bar_is_a_mark_that_exists(tmp_path):
    actions = run({"actions": True}, tmp_path)["actions"]
    names = [a["name"] for a in actions]
    assert len(names) == len(set(names)), "two buttons share a name"
    assert {"bold", "italic", "bullet", "numbered", "check", "heading", "link"} <= set(names)
    for action in actions:
        assert action["label"] and action["title"], action
    # Every one of them has to do something; `edit` throws on a name it
    # does not know, so this fails rather than silently drawing a dead key.
    run({"cases": [[n, "x", 0, 1] for n in names]}, tmp_path)


def test_the_bar_is_registered_once_and_owns_its_own_files():
    """One feature, one file, one line in each list — as the app is built."""
    assert FORMAT.is_file() and (WEB / "format.css").is_file()
    assert (WEB / "app.js").read_text().count('import "./format.js";') == 1
    assert (WEB / "app.css").read_text().count('@import "./format.css";') == 1
    # It reaches the editors through the DOM, not through their modules.
    assert "import" not in FORMAT.read_text().split("// -- the marks")[0].replace(
        "Imported by node", ""
    )
