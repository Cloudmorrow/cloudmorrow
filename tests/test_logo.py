"""The mark: drawn in dots, tinted a column at a time, in colours we chose."""

from __future__ import annotations

from cloudmorrow import pixelfont
from cloudmorrow.logo import (
    WORDMARK_WIDTH,
    banner,
    mark_for_width,
    ramp,
    wordmark,
)
from cloudmorrow.palette import ACCENT, MARK_GRADIENT


def test_the_mark_is_the_word_in_half_blocks():
    text = wordmark()
    lines = text.plain.splitlines()
    # Seven rows of dots, two to a cell: four rows of cells.
    assert len(lines) == 4
    assert {len(line) for line in lines} == {WORDMARK_WIDTH}
    assert set("".join(lines)) <= set(" ▀▄█")
    # And it is the word, not a decoration: eleven letters, six columns each,
    # less the gap that is trimmed off the end.
    assert WORDMARK_WIDTH == 11 * (pixelfont.WIDTH + pixelfont.GAP) - pixelfont.GAP


def test_the_gradient_runs_along_the_word_not_down_it():
    """Every dot in a column is one colour, so no letter is split by it."""
    text = wordmark()
    width = WORDMARK_WIDTH
    by_column: dict[int, set[str]] = {}
    for start, end, style in text._spans:
        column = start % (width + 1)  # +1 for the newline between rows
        by_column.setdefault(column, set()).add(str(style))
        assert end == start + 1
    for column, styles in by_column.items():
        assert len(styles) == 1, f"column {column} came out {len(styles)} colours"


def test_nothing_is_painted_in_a_colour_the_terminal_chooses():
    """Every style on the mark is a hex value, never a name like "cyan"."""
    for _, _, style in wordmark()._spans:
        assert str(style).startswith("#"), style
    assert all(colour.startswith("#") for colour in ramp(MARK_GRADIENT, 65))


def test_the_ramp_starts_and_ends_on_the_stops():
    stops = ("#000000", "#804020", "#ffffff")
    assert ramp(stops, 9)[0] == "#000000"
    assert ramp(stops, 9)[-1] == "#ffffff"
    assert ramp(stops, 9)[4] == "#804020"
    assert len(ramp(stops, 40)) == 40
    # A one-cell mark still has to get a colour rather than divide by zero.
    assert ramp(stops, 1) == ["#000000"]


def test_a_narrow_terminal_gets_the_word_rather_than_a_broken_mark():
    assert mark_for_width(WORDMARK_WIDTH).plain.count("\n") == 3
    narrow = mark_for_width(WORDMARK_WIDTH - 1)
    assert narrow.plain == "CLOUDMORROW"
    assert ACCENT in str(narrow.style)


def test_the_banner_carries_the_mark_the_tagline_and_the_version():
    from cloudmorrow import __version__

    mark, tagline, subtitle = banner(subtitle="api server").renderable.renderables
    assert mark.plain == wordmark().plain
    assert __version__ in tagline.plain
    assert subtitle.plain == "api server"
