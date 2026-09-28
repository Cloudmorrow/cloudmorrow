"""Calendar: what its screen cannot do by itself.

The calendars, the events and how every surface draws them are declared in
quill.toml. This is the code behind its one action, run as whoever presses it.
"""

import datetime as dt

from cloudmorrow.quill import action, open, toast

EVENT = "event"
WEEK = dt.timedelta(days=7)


def later(value, by=WEEK):
    """A date or datetime *by* later, written the way it was: a whole day stays a
    day, a wall-clock time stays one, to the minute unless it had seconds."""
    if not value:
        return value
    if len(value) == 10:
        return (dt.date.fromisoformat(value) + by).isoformat()
    moment = dt.datetime.fromisoformat(value) + by
    return moment.isoformat(timespec="seconds" if moment.second else "minutes")


@action("copy_to_next_week")
def copy_to_next_week(ctx, event):
    fields = {name: event.get(name) for name in ("calendar", "title", "all_day", "location", "notes")}
    fields["starts_at"] = later(event["starts_at"])
    fields["ends_at"] = later(event.get("ends_at"))
    copy = ctx.records.create(EVENT, {k: v for k, v in fields.items() if v is not None})
    return [toast(f"{event['title']} is on {fields['starts_at'][:10]} too"), open(copy)]
