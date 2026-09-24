"""The web app on a computer: the rail, and the promise it makes to the phone.

The phone app is finished. The desktop layer is allowed to add to it and
not to change it, which comes down to one rule that a person cannot keep
by hand: nothing in `desktop.css` outside a media query may touch a shape
the phone already draws. These tests are that rule, and the wiring the
rail needs in `core.js`.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB

# The only selectors allowed to reach the phone: both are for elements that
# did not exist before this file, and both only hide them.
PHONE_SAFE = {".tabs .rail-head", ".aside-tabs .tabs"}


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def top_level_rules(css: str) -> list[tuple[str, str]]:
    """Every `selector { … }` at the top of the file, as (selector, body).

    A rule inside `@media` is not one of these: the walk only records what
    opens a block from depth zero, and an at-rule is named as such.
    """
    rules: list[tuple[str, str]] = []
    depth = 0
    start = 0
    head = ""
    for i, char in enumerate(css):
        if char == "{":
            if depth == 0:
                head = css[start:i].strip()
                start = i + 1
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rules.append((head, css[start:i]))
                start = i + 1
    return rules


def test_the_stylesheet_and_the_keys_are_listed() -> None:
    assert '@import "./desktop.css";' in (WEB / "app.css").read_text()
    assert 'import "./desktop.js";' in (WEB / "app.js").read_text()


def test_nothing_reaches_the_phone_but_the_two_rules_that_hide_the_new_parts() -> None:
    css = strip_comments((WEB / "desktop.css").read_text())
    for head, body in top_level_rules(css):
        if head.startswith("@media"):
            continue
        assert head in PHONE_SAFE, f"{head} would change the phone"
        assert body.strip() == "display: none;", f"{head} does more than hide itself"


def test_every_media_query_asks_for_height_as_well_as_width() -> None:
    """A phone held sideways is 932 points wide and 430 tall, and is still a phone."""
    css = strip_comments((WEB / "desktop.css").read_text())
    queries = [head for head, _ in top_level_rules(css) if head.startswith("@media")]
    assert queries
    for query in queries:
        assert "min-width" in query and "min-height: 600px" in query, query


def test_the_shell_gives_every_screen_a_rail() -> None:
    core = (WEB / "core.js").read_text()
    # The wordmark at the head of the rail, drawn with the tabs themselves.
    assert '<nav class="tabs"><div class="rail-head">' in core
    # A screen that drew no tabs of its own gets them, and says so.
    assert 'app.classList.toggle("aside-tabs"' in core
    # And the window is named after the screen, for a browser full of tabs.
    assert "document.title" in core
