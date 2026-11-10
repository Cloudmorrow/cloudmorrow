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

# The only selectors allowed to reach the phone: all are for elements that
# did not exist before this file, and all only hide them.
PHONE_SAFE = {
    ".tabs .rail-head",
    ".aside-tabs .tabs, .aside-tabs .subtabs",
    ".tabs .rail-section",
    ".tabs .tab.admin",
    ".tabs .tab.used",
}


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


def test_nothing_reaches_the_phone_but_the_rules_that_hide_the_new_parts() -> None:
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


def test_the_rail_shelves_the_quills_by_their_categories() -> None:
    """A Quill's tabs stand under the catalog's label for its category, the
    shelves in the catalog's order (the server says both, quills/registry.py);
    Today, with no category, before them all; a phone's bar runs them together."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    quills = (WEB / "quills.js").read_text(encoding="utf-8")
    assert 'section: quill.composed ? "" : quill.category_label || titled(quill.category)' in quills
    assert "rank: quill.category_rank" in quills
    assert 'own.filter((t) => !t.section).map(draw).join("")' in core
    assert "shelves(own.filter((t) => t.section)).map((s) => section(s.title, s.tabs))" in core
    assert core.index("shelves(own.filter") < core.index('section("Your cloud"')
    # The heading is the catalog's text, escaped on the way in.
    assert '<div class="rail-section">${esc(title)}</div>' in core


def test_most_used_quills_stand_under_today_on_the_rail_only() -> None:
    """The Quills opened most on this device are copied under Today, in a
    Most used section of the rail — Favorites instead, once there are any;
    the phone's bar hides the rail's copies."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    assert 'section("Favorites", favs, copy("used"))' in core
    assert 'section("Most used", mostUsed(apps), copy("used"))' in core
    assert (
        core.index("own.filter((t) => !t.section).map(draw)")
        < core.index('section("Favorites"')
        < core.index('section("Most used"')
        < core.index("shelves(own.filter")
    )
    assert 'store.set("quills.used", JSON.stringify(uses));' in core
    assert ".tabs .tab.used { display: none; }" in desktop
    assert "  .tabs .tab.used { display: flex; }" in desktop
    # The copies never stand in for the tab itself.
    assert 'app.querySelector(".tabs .tab.active:not(.copy)")' in core


def test_the_phone_bar_is_today_five_apps_and_more() -> None:
    """A phone's bar has no room for every Quill: Today, five copies —
    the favorites, else the most used filled up in the shelves' order — and
    More, which opens them all; the Quills' own tabs are the rail's."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    rail = (WEB / "rail.js").read_text(encoding="utf-8")
    css = (WEB / "rail.css").read_text(encoding="utf-8")
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    assert "const ON_PHONE = 5;" in core
    assert "favs.length ? favs.slice(0, ON_PHONE) : phoneUsed(apps)" in core
    assert '<button type="button" class="tab more' in core
    assert ".tabs .tab.app { display: none; }" in css
    assert "  .tabs .tab.app { display: flex; }" in desktop
    assert "  .tabs .tab.quick, .tabs .tab.more { display: none; }" in desktop
    assert 'import "./rail.js";' in (WEB / "app.js").read_text()
    assert '@import "./rail.css";' in (WEB / "app.css").read_text()
    # More opens a sheet on the page, never a browser window.
    assert "openSheet(" in rail


def test_an_app_has_a_menu_with_favorites_in_it() -> None:
    """The dots on a row of the rail, a right-click, a finger held — on the
    bar or in More — all open the same menu, with the favorite switch."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    rail = (WEB / "rail.js").read_text(encoding="utf-8")
    assert 'contextMenus(app, "nav.tabs > .tab.app, nav.tabs > .tab.copy", choicesFor)' in rail
    assert 'contextMenus(list, ".app-tile"' in rail
    assert '"Add to Favorites"' in rail and '"Remove from Favorites"' in rail
    assert 'store.set("quills.favorites"' in core
    assert '<span class="tab-menu"' in core


def test_the_rail_folds_to_its_icons() -> None:
    """Folded, the rail is a strip of icons and its head the cloud's first
    letter, which turns over to the button that unfolds it."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    assert "--rail: clamp(259px, 24vw, 340px);" in desktop
    assert ":root.rail-folded { --rail: 64px; }" in desktop
    assert ".rail-unfold:hover .rail-flip" in desktop
    assert 'store.set("rail.folded"' in core
    assert 'document.documentElement.classList.toggle("rail-folded"' in core


def test_a_quill_is_one_tab_with_its_screens_under_it() -> None:
    """A Quill with several screens is one tab, the Quill's own, with the
    screens as the items under it: drawn only while one of them is on show,
    nested under the tab in the rail and in a strip above the phone's bar.
    A Quill with one screen is that screen's tab, as it always was."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    quills = (WEB / "quills.js").read_text(encoding="utf-8")
    base = (WEB / "base.css").read_text(encoding="utf-8")
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    # quills.js: the tab is the Quill, its screens under it, each with its own icon.
    assert "name: one ? screens[0].name : quill.id," in quills
    assert "label: one ? screens[0].label : quill.name," in quills
    assert "screens: one ? [] : screens," in quills
    assert "icon: pixelIcon(screen.icon)," in quills
    assert "href: () => screenHash(quill, quill.screens.find(onTab) || quill.screens[0])," in quills
    # core.js: the items only under an open tab, and the strip only for one.
    assert '(open ? t.screens.map(drawItem).join("") : "")' in core
    assert '<a class="tab sub${s.name === active ? " active" : ""}"' in core
    assert '<nav class="subtabs" aria-label="${esc(opened.label)}">' in core
    assert 'data-screens="${t.screens.map((s) => s.name).join(" ")}"' in core
    # Tapping an item lights it and the tab it is under before the screen comes.
    assert '(t.dataset.screens || "").split(" ").includes(name)' in core
    assert 'event.target.closest("nav.tabs > .tab, nav.subtabs > .tab")' in core
    # The items are not in the phone's bar; the strip is not in the rail.
    assert ".tabs .tab.sub { display: none; }" in base
    assert ".subtabs {\n  position: fixed;" in base
    assert "#app:has(> nav.subtabs) main { padding-bottom:" in base
    assert ".subtabs { display: none; }" in desktop
    assert ".tabs .tab.sub {\n    display: flex;" in desktop
