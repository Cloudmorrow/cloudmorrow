"""The 5x7 font, and that its two copies have not drifted apart."""

from __future__ import annotations

import json
import re

from cloudmorrow import pixelfont
from cloudmorrow.server.routes.web import WEB


def _js_font(source: str, marker: str) -> dict[str, list[str]]:
    block = source.split(marker, 1)[1].split("\n};", 1)[0]
    return {
        key: json.loads(f"[{rows}]")
        for key, rows in re.findall(r'^  "?(.)"?: \[(.*?)\],$', block, re.M)
    }


def test_every_glyph_is_five_across_and_seven_down():
    for char, glyph in pixelfont.GLYPHS.items():
        assert len(glyph) == pixelfont.ROWS, char
        assert {len(row) for row in glyph} == {pixelfont.WIDTH}, char
        assert set("".join(glyph)) <= {"X", "."}, char


def test_the_font_matches_the_one_the_web_app_draws_with():
    """Two copies, one drawing. The mark has to be the same in both places."""
    theirs = _js_font((WEB / "brand.js").read_text(encoding="utf-8"), "const FONT = {")
    assert theirs, "brand.js no longer declares FONT"
    assert set(theirs) == set(pixelfont.GLYPHS)
    for char, rows in theirs.items():
        assert list(pixelfont.GLYPHS[char]) == rows, f"{char} drifted"


def test_half_blocks_pack_two_rows_of_dots_into_one_cell():
    # A column with only its top dot set is an upper half block, and so on.
    assert pixelfont.rows("I")[0][2] == "█"   # both dots of the stem
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
