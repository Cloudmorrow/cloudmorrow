"""The /brand page: the look, proposed — three themes for the app and the terminal."""

from __future__ import annotations

import json
import re

from cloudmorrow.server.routes.web import WEB, asset_version

BRAND_JS = (WEB / "brand.js").read_text(encoding="utf-8")


def test_brand_page_needs_no_auth_and_carries_no_placeholders(client):
    response = client.get("/brand")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "__ASSET_VERSION__" not in response.text
    # It is a proposal, not something to be found by a search engine.
    assert 'name="robots" content="noindex"' in response.text


def test_brand_page_serves_its_own_two_files(client):
    body = client.get("/brand").text
    for name in ("brand.css", "brand.js"):
        assert f"/app/{asset_version()}/{name}" in body
        asset = client.get(f"/app/{asset_version()}/{name}")
        assert asset.status_code == 200
        assert asset.content


def test_brand_page_stands_alone(client):
    """It argues for a look the app does not have, so it borrows none of it.

    Only the files it names matter — the prose may well mention `core.js`,
    since the last section is about moving the font into it.
    """
    body = client.get("/brand").text
    loaded = re.findall(r'(?:href|src)="([^"]+\.(?:css|js))"', body)
    assert loaded, "the page loads nothing at all"
    assert all(f.endswith(("brand.css", "brand.js")) for f in loaded), loaded
    # And the script pulls in no module of the app's either.
    assert not re.search(r"^\s*import\b", BRAND_JS, re.M)


def test_every_theme_fills_every_palette_slot():
    """A theme that cannot fill all twelve is a mood board, not a theme.

    The names are `palette.py`'s own, which is what makes a theme a drop-in;
    if a slot is ever added there, this fails until the themes catch up.
    """
    from cloudmorrow import palette

    # The gradients are up there too, and they are tuples, not slots.
    slots = [n for n in dir(palette) if n.isupper() and isinstance(getattr(palette, n), str)]
    for block in re.findall(r"colors: \{(.*?)\},\n", BRAND_JS, re.S):
        named = set(re.findall(r"(\w+): \"#[0-9a-f]{6}\"", block))
        assert named == set(slots), f"missing {set(slots) - named}"


def test_the_marks_use_a_font_that_can_spell_every_theme_name():
    """The pixel font is drawn by hand, so a missing glyph is a silent hole."""
    glyphs = set(re.findall(r'^  ("?)([A-Z0-9.\-/\'!?])\1: \[', BRAND_JS, re.M))
    have = {g for _, g in glyphs} | {" "}
    for name in re.findall(r'name: "([A-Z ]+)"', BRAND_JS):
        assert set(name) <= have, f"{name} needs {set(name) - have}"
    assert set("CLOUDMORROW") <= have


def test_the_wordmark_is_the_one_the_app_already_draws():
    """The letters of CLOUDMORROW are copied from core.js; they must match."""
    core = (WEB / "core.js").read_text(encoding="utf-8")

    def glyphs(source: str, marker: str) -> dict[str, list[str]]:
        block = source.split(marker, 1)[1].split("};", 1)[0]
        found = {}
        for letter, rows in re.findall(r'^  "?([A-Z])"?: \[(.*?)\],$', block, re.M):
            found[letter] = json.loads(f"[{rows}]")
        return found

    theirs = glyphs(core, "const GLYPHS = {")
    ours = glyphs(BRAND_JS, "const FONT = {")
    assert theirs, "core.js no longer declares GLYPHS"
    for letter, rows in theirs.items():
        assert ours[letter] == rows, f"{letter} drifted from the app's wordmark"


def test_the_css_block_is_a_drop_in_for_base_css():
    """What the page tells you to paste has to cover what it replaces.

    `base.css` is where the web app's look is declared; if a variable is
    added there, the themes have to name it or pasting one in would leave
    the old palette's value behind on whatever uses it.
    """
    base = (WEB / "base.css").read_text(encoding="utf-8")
    root = base.split(":root {", 1)[1].split("}", 1)[0]
    declared = set(re.findall(r"^\s*(--[a-z0-9-]+):", root, re.M))
    # Not these: the type stack, the phone's own safe areas, and the gap the
    # bar keeps above itself to clear what iOS paints over the top of a Home
    # Screen app. None of them is a thing a palette has an opinion about.
    # Anything else added to :root has to be answered for by every theme.
    declared -= {"--sans", "--mono", "--top", "--bottom", "--bar-top"}
    body = BRAND_JS.split("function cssFor", 1)[1].split("\n}", 1)[0]
    emitted = set(re.findall(r"(--[a-z0-9-]+):", body))
    assert declared <= emitted, f"themes say nothing about {sorted(declared - emitted)}"


def test_the_icons_are_the_ones_the_app_draws():
    """Two copies again: /brand shows the set, core.js draws the tabs with it.

    brand.js has to stand alone, so it cannot import them — which leaves a
    test as the only thing stopping the page and the app disagreeing about
    what a tab looks like.
    """
    core = (WEB / "core.js").read_text(encoding="utf-8")

    def grids(source: str, marker: str) -> dict[str, list[str]]:
        block = source.split(marker, 1)[1].split("\n};", 1)[0]
        return {
            name: re.findall(r'"([X.]+)"', rows)
            for name, rows in re.findall(r"^  (\w+): \[(.*?)\],$", block, re.S | re.M)
        }

    theirs = grids(BRAND_JS, "const ICONS = {")
    ours = grids(core, "const PIXELS = {")
    assert theirs, "brand.js no longer declares ICONS"
    assert set(theirs) == set(ours), f"only one side has {set(theirs) ^ set(ours)}"
    for name, rows in theirs.items():
        assert ours[name] == rows, f"the {name} icon drifted"
        # Eight across and eight down, or it is not on the grid.
        assert len(rows) == 8 and {len(r) for r in rows} == {8}, name


def test_every_tab_is_drawn_with_one_of_them():
    """No tab is left on the line art the pixel set replaced."""
    for name in ("today.js", "notes.js", "tasks.js"):
        source = (WEB / name).read_text(encoding="utf-8")
        tab = re.search(r"registerTab\(\{[^}]*\}\)", source, re.S)
        assert tab, name
        assert "pixelIcon(" in tab.group(0), f"{name} still registers a tab with an <svg>"
