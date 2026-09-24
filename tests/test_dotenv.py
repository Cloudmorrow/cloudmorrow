from __future__ import annotations

import pytest

from cloudmorrow import dotenv

SAMPLE = """\
# a comment, and a blank line follow

export DATABASE_URL=postgres://user:pw@db/app
API_KEY="sk-live-abc"
EMPTY=
LITERAL='keeps $VARS and "quotes"'
ESCAPED="one\\ntwo"
MULTILINE="first
second"
TRAILING=value   # not part of it
HASH=#this-is-a-value
"""


def test_parse_covers_the_dialect():
    parsed = dotenv.parse(SAMPLE)
    assert parsed == {
        "DATABASE_URL": "postgres://user:pw@db/app",
        "API_KEY": "sk-live-abc",
        "EMPTY": "",
        "LITERAL": 'keeps $VARS and "quotes"',
        "ESCAPED": "one\ntwo",
        "MULTILINE": "first\nsecond",
        "TRAILING": "value",
        "HASH": "#this-is-a-value",
    }


def test_round_trip_survives_dump():
    parsed = dotenv.parse(SAMPLE)
    assert dotenv.parse(dotenv.dump(parsed)) == parsed


@pytest.mark.parametrize(
    "value",
    ["plain", "", " leading and trailing ", 'quotes " and \' both', "$SHELL", "a\nb", "#hash"],
)
def test_quoting_is_reversible(value):
    assert dotenv.parse(f"K={dotenv.quote(value)}\n") == {"K": value}


def test_later_assignment_wins():
    assert dotenv.parse("K=one\nK=two\n") == {"K": "two"}


def test_a_line_without_an_equals_is_an_error():
    with pytest.raises(dotenv.DotenvError) as caught:
        dotenv.parse("GOOD=1\nnonsense\n")
    assert caught.value.line == 2


def test_a_bad_variable_name_is_an_error():
    with pytest.raises(dotenv.DotenvError):
        dotenv.parse("not-a-name=1\n")


def test_an_unterminated_quote_is_an_error():
    with pytest.raises(dotenv.DotenvError):
        dotenv.parse('K="never closed\n')


def test_dump_writes_a_header():
    rendered = dotenv.dump({"K": "v"}, header="two\nlines")
    assert rendered.startswith("# two\n# lines\n\nK=v")
