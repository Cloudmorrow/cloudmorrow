from __future__ import annotations

import pytest

from cloudmorrow.tui.markdown_render import code_fence_states, render_inline, render_line


def plain(line: str, **kwargs) -> str:
    return render_line(line, **kwargs).plain


def test_heading_markers_are_hidden():
    assert plain("# Title") == "▎ Title"
    assert plain("### Deep") == "▎▎ Deep"


def test_inline_markers_are_hidden():
    assert render_inline("**bold** and *em* and `code`").plain == "bold and em and code"
    assert render_inline("~~gone~~").plain == "gone"


def test_inline_styles_are_applied():
    text = render_inline("a **bold** b")
    styles = {str(span.style) for span in text.spans}
    assert any("bold" in style for style in styles)


def test_escaped_markers_stay_literal():
    assert render_inline(r"\*not em\*").plain == "*not em*"


def test_links_render_as_label():
    assert render_inline("see [docs](https://x.dev)").plain == "see docs ↗"
    assert render_inline("[[wiki page]]").plain == "wiki page"


def test_bullets_and_tasks():
    assert plain("- item") == "• item"
    assert plain("  - nested") == "  ◦ nested"
    assert plain("- [ ] todo") == "☐ todo"
    assert plain("- [x] done") == "☑ done"
    assert plain("3. third") == "3. third"


def test_quote_and_rule():
    assert plain("> quoted") == "▏ quoted"
    assert plain(">> deep") == "▏▏ deep"
    assert set(plain("---", width=10)) == {"─"}


def test_code_block_lines_are_verbatim():
    assert plain("  **not bold**", in_code_block=True) == "  **not bold**"


def test_fence_state_tracking():
    lines = ["intro", "```py", "x = 1", "```", "outro"]
    assert code_fence_states(lines) == [False, False, True, False, False]


def test_unterminated_fence_keeps_rest_of_document_as_code():
    assert code_fence_states(["```", "a", "b"]) == [False, True, True]


@pytest.mark.parametrize("line", ["", "   ", "plain text", "a * b * c", "50% * 3"])
def test_plain_text_is_untouched(line):
    assert plain(line) == line
