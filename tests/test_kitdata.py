"""The kit's data and dates, read without a screen: tui/kitdata.py and tui/dates.py."""

from __future__ import annotations

import asyncio
import datetime as dt

from cloudmorrow.client.api import ApiError, AuthError, ConflictError
from cloudmorrow.tui.dates import as_local, days_of, span, wall
from cloudmorrow.tui.kitdata import is_conflict, link_choices, link_rows


class Records:
    """A client that has records of one datamodel, and counts how often it is asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def records(self, model: str) -> list[dict]:
        self.asked.append(model)
        if model == "gone":
            raise ApiError("not yours", status_code=403)
        return [{"id": "r_1", "fields": {"name": "Acme"}}]


MODELS = {
    "company": {"id": "company", "title": "name", "fields": [{"name": "name", "kind": "string"}]},
    "deal": {
        "id": "deal",
        "fields": [
            {"name": "company", "kind": "link", "to": "company"},
            {"name": "billed_to", "kind": "link", "to": "company"},
            {"name": "lost", "kind": "link", "to": "gone"},
            {"name": "title", "kind": "string"},
        ],
    },
}


def test_every_link_is_titled_and_each_datamodel_read_once():
    client = Records()
    choices = asyncio.run(link_choices(client, MODELS, MODELS["deal"]))
    assert choices == {
        "company": [("Acme", "r_1")],
        "billed_to": [("Acme", "r_1")],
        "lost": [],
    }
    assert client.asked == ["company", "gone"]


def test_a_cache_is_read_from_and_a_refusal_is_not_kept():
    client = Records()
    cache: dict[str, list[dict]] = {}
    assert asyncio.run(link_rows(client, "gone", cache)) is None
    asyncio.run(link_rows(client, "company", cache))
    asyncio.run(link_rows(client, "company", cache))
    assert client.asked == ["gone", "company"]
    assert set(cache) == {"company"}


def test_a_conflict_is_a_stale_write_or_a_notes_own():
    taken = ApiError("a share with that name exists", status_code=409)
    assert not is_conflict(taken)
    assert is_conflict(taken, stale=True)
    assert is_conflict(ConflictError("changed", rev="2"))
    assert not is_conflict(AuthError("expired", status_code=401), stale=True)


def test_the_wall_clock_and_the_sheet_agree_about_a_moment():
    assert wall("2026-09-19") == "2026-09-19"
    assert wall("2026-09-19T14:03") == "2026-09-19T14:03"
    assert as_local("2026-09-19") == "2026-09-19"
    assert as_local("2026-09-19T14:03:21") == "2026-09-19 14:03"
    zoned = "2026-09-19T12:00:00+00:00"
    here = dt.datetime.fromisoformat(zoned).astimezone().strftime("%Y-%m-%d %H:%M")
    assert as_local(zoned) == here
    assert wall(zoned) == here.replace(" ", "T")
    assert wall("not a moment at all") == "not a moment at "
    assert as_local("not a moment") == "not a moment"


def test_a_span_is_every_day_and_can_be_capped():
    first = dt.date(2026, 1, 30)
    assert span(first, dt.date(2026, 2, 1)) == [
        dt.date(2026, 1, 30), dt.date(2026, 1, 31), dt.date(2026, 2, 1)
    ]
    assert span(first, dt.date(2025, 1, 1)) == [first]
    assert len(span(first, dt.date(2030, 1, 1), most=366)) == 367
    assert days_of({"starts": "2026-01-30T09:00", "ends": "2026-01-31"}) == [
        dt.date(2026, 1, 30), dt.date(2026, 1, 31)
    ]
