"""The 5x7 font, and that its two copies have not drifted apart."""

from __future__ import annotations

import json
import re

from cloudmorrow import pixelfont
from cloudmorrow.server.routes.web import WEB


def _js_font(source: str, marker: str) -> dict[str, list[str]]:
    block = source.split(marker, 1)[1].split("\n};", 1)[0]
    return {key: json.loads(f"[{rows}]") for key, rows in re.findall(r'^  "?(.)"?: \[(.*?)\],$', block, re.M)}


def test_every_glyph_is_five_across_and_seven_down():
    for char, glyph in pixelfont.GLYPHS.items():
        assert len(glyph) == pixelfont.ROWS, char
        assert {len(row) for row in glyph} == {pixelfont.WIDTH}, char
        assert set("".join(glyph)) <= {"X", "."}, char


def test_the_font_matches_the_one_the_web_app_draws_with():
    """Three copies, one drawing. The mark has to be the same in every place:
    the brand page's, and the app's own, which spells the cloud's name."""
    for name, marker in (("brand.js", "const FONT = {"), ("core.js", "const GLYPHS = {")):
        theirs = _js_font((WEB / name).read_text(encoding="utf-8"), marker)
        assert theirs, f"{name} no longer declares the font"
        assert set(theirs) == set(pixelfont.GLYPHS), name
        for char, rows in theirs.items():
            assert list(pixelfont.GLYPHS[char]) == rows, f"{char} drifted in {name}"


def test_the_font_spells_a_danish_name():
    assert {"Æ", "Ø", "Å"} <= set(pixelfont.GLYPHS)
    assert pixelfont.rows("SØREN") != pixelfont.rows("SREN")


def test_the_app_puts_the_clouds_name_at_the_head_of_the_rail():
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert '<div class="rail-head">${wordmark(CLOUD_NAME)}</div>' in core
    assert '<div class="center">${wordmark(CLOUD_NAME)}' in core
    # Any name: upper-cased, an accent dropped to its letter, a space narrower
    # than a letter, and a mark the font cannot spell left out, not left blank.
    assert "text.toUpperCase()" in core
    assert 'GLYPHS[char.normalize("NFD")[0]]' in core
    assert "const SPACE = 3;" in core


def test_half_blocks_pack_two_rows_of_dots_into_one_cell():
    # A column with only its top dot set is an upper half block, and so on.
    assert pixelfont.rows("I")[0][2] == "█"  # both dots of the stem
    assert pixelfont.rows("L")[-1][0] == "▀"  # row 6 set, row 7 does not exist
    assert " " in pixelfont.rows("CLOUDMORROW")[0]


def test_a_word_is_its_letters_with_one_column_between_them():
    assert len(pixelfont.rows("AB")[0]) == 2 * pixelfont.WIDTH + pixelfont.GAP
    # A trailing gap would put the gradient's last stop on empty space.
    assert not pixelfont.rows("AB")[0].endswith(" ")


def test_a_character_the_font_cannot_spell_is_left_out_not_left_blank():
    assert pixelfont.rows("A~B") == pixelfont.rows("AB")


def test_a_space_is_narrower_than_a_letter():
    gap = len(pixelfont.rows("A B")[0]) - len(pixelfont.rows("AB")[0])
    assert gap == pixelfont.SPACE
    assert pixelfont.SPACE < pixelfont.WIDTH
