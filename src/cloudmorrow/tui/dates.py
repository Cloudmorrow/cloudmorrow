"""Days, months and moments, the way the terminal draws them. Nothing but datetime.

A stored moment is one of three things (docs/QUILLS.md): a bare date, which
is a whole day; a time with no zone, which is the time on the wall and is
drawn exactly as it was typed; or a time with a zone, which is converted to
the clock here. Every screen that draws one — the calendar, a view's month,
the record sheet — reads it through these, so the three agree about what
time it is.

A month is drawn as whole weeks, Monday first, the days either side
belonging to its neighbours.
"""

from __future__ import annotations

import calendar as cal
import datetime as dt


# -- months ------------------------------------------------------------------------
def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def shift_month(day: dt.date, months: int) -> dt.date:
    """The same day-of-month, a month or two along, clamped to a real date."""
    total = (day.year * 12 + day.month - 1) + months
    year, month = divmod(total, 12)
    last = cal.monthrange(year, month + 1)[1]
    return dt.date(year, month + 1, min(day.day, last))


def weeks_of(day: dt.date) -> list[list[dt.date]]:
    """The month *day* is in, as whole weeks — the ends belong to its neighbours."""
    return cal.Calendar(firstweekday=0).monthdatescalendar(day.year, day.month)


# -- days --------------------------------------------------------------------------
def span(first: dt.date, last: dt.date, *, most: int | None = None) -> list[dt.date]:
    """Every day from *first* to *last*, both in; a *last* before *first* is *first* alone.

    *most* caps how many days after the first there may be, for a range
    somebody else's code chose the end of.
    """
    count = (max(first, last) - first).days
    if most is not None:
        count = min(count, most)
    return [first + dt.timedelta(days=step) for step in range(count + 1)]


def days_of(event: dict) -> list[dt.date]:
    """Every day a thing is on, so a month can draw it on each of them."""
    return span(
        dt.date.fromisoformat(event["starts"][:10]), dt.date.fromisoformat(event["ends"][:10])
    )


# -- moments -----------------------------------------------------------------------
def _here(text: str) -> dt.datetime | None:
    """*text* as a moment on the clock here: a zone converted, none left as it is."""
    try:
        moment = dt.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def wall(value: object) -> str:
    """A stored moment as the wall clock here says it: a zone converted; the
    wall clock, and a bare date, exactly as they are."""
    text = str(value or "")
    if len(text) <= 16:
        return text
    moment = _here(text)
    if moment is None:
        return text[:16]
    return moment.strftime("%Y-%m-%dT%H:%M")


def as_local(value: object) -> str:
    """A stored moment as the minute it is here, written with a space: a zone
    converted, the wall clock left as it is, and a whole day a date."""
    text = str(value or "")
    if len(text) == 10:
        return text
    moment = _here(text)
    if moment is None:
        return text
    return moment.strftime("%Y-%m-%d %H:%M")
