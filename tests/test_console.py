"""The terminal's colours are ours: 24-bit, and never one of its sixteen names."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cloudmorrow import palette
from cloudmorrow.console import COMPOUND, NAMED, TITLE, console

SOURCE = Path(__file__).resolve().parent.parent / "src" / "cloudmorrow"
HEX = re.compile(r"^#[0-9a-f]{6}$")


def test_a_console_sends_twenty_four_bit_colour():
    """Otherwise the sixteen names are all a terminal is offered, and it
    picks what they look like."""
    assert console(force_terminal=True).color_system == "truecolor"
    assert console(force_terminal=True, stderr=True, highlight=False).color_system == "truecolor"
    # And nothing is forced when there is no terminal to force it on.
    assert console().color_system is None


@pytest.mark.parametrize("name", sorted(NAMED))
def test_every_name_a_terminal_would_answer_for_resolves_to_a_value_we_chose(name):
    style = console().get_style(name)
    assert style.color is not None, name
    assert style.color.triplet is not None, f"{name} did not come out as RGB"
    assert f"#{style.color.triplet.hex.lstrip('#')}" in vars(palette).values()


@pytest.mark.parametrize("name", sorted(COMPOUND))
def test_the_compound_styles_resolve_too(name):
    """rich reads "bold cyan" in one piece, so it never reaches the names
    above and has to be spelled out separately."""
    style = console().get_style(name)
    assert style.color is not None and style.color.triplet is not None, name


def test_the_palette_is_hex_and_nothing_else():
    for name, value in vars(palette).items():
        if not name.isupper():
            continue
        values = [value] if isinstance(value, str) else list(value)
        assert all(HEX.match(v) for v in values), name


def test_no_console_is_built_without_going_through_us():
    """A bare rich Console negotiates its own colour system and ignores the
    theme, which is the whole thing this module exists to prevent."""
    offenders = []
    for path in SOURCE.rglob("*.py"):
        if path.name == "console.py":
            continue
        if re.search(r"^\s*(\w+ = )?Console\(", path.read_text(), re.M):
            offenders.append(path.relative_to(SOURCE))
    assert not offenders, f"build these with cloudmorrow.console.console(): {offenders}"


def test_titles_are_not_spelled_bold_cyan_by_hand():
    assert TITLE.endswith(palette.ACCENT)


def test_colour_is_dropped_when_nobody_is_looking(capsys):
    """`cloudmorrow secret get KEY > file` has to come out as the secret and
    not as the secret wrapped in escapes."""
    console(width=40).print("[green]s3cret[/]")
    out = capsys.readouterr().out
    assert out.strip() == "s3cret"
    assert "\x1b" not in out


def test_colour_is_twenty_four_bit_when_somebody_is(capsys):
    console(force_terminal=True, width=40).print("[green]OK[/]")
    out = capsys.readouterr().out
    assert "\x1b[38;2;" in out
    # ...and never one of the sixteen the terminal gets to interpret.
    assert not re.search(r"\x1b\[[0-9;]*?\b3[0-7]m", out)
