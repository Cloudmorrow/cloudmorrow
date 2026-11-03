"""Calendar: what its screen cannot do by itself.

The calendars, the events and how every surface draws them are declared in
quill.toml. This is the code behind its actions, its hook and its one job,
run as whoever presses, changes or holds: copying an event a week on, and
calendars subscribed from elsewhere — a reader of iCalendar (RFC 5545)
small enough to live here: the unfolding, the components, whole days and
moments, the zones a feed carries with it, and recurrence.
"""

import datetime as dt
import re

from cloudmorrow.quill import Invalid, Refused, action, error, go, hook, job, open, toast

CALENDAR = "calendar"
EVENT = "event"
URL = "calendar.url"  # the feed a subscribed calendar is read from
REFRESHED = "calendar.refreshed"  # when it was last read
TROUBLE = "calendar.trouble"  # what went wrong the last time, in words; "" when nothing did
UID = "calendar.uid"  # what the feed calls an event — and, recurring, which time of it
WEEK = dt.timedelta(days=7)
HOUR = dt.timedelta(hours=1)
# The colours a calendar can be, as every surface draws them.
COLOURS = ("cyan", "violet", "green", "amber", "rose")
# How far a feed is read: a year back and two years on. A feed carries its
# whole history, and a recurrence with no end would otherwise never stop.
BACK = dt.timedelta(days=365)
AHEAD = dt.timedelta(days=2 * 365)
MOST = 2000  # times one recurring event is drawn, at the very most

# -- the week after ------------------------------------------------------------------


def later(value, by=WEEK):
    """A date or datetime *by* later, written the way it was: a whole day stays a
    day, a wall-clock time stays one, to the minute unless it had seconds."""
    if not value:
        return value
    if len(value) == 10:
        return (dt.date.fromisoformat(value) + by).isoformat()
    moment = dt.datetime.fromisoformat(value) + by
    return moment.isoformat(timespec="seconds" if moment.second or moment.tzinfo else "minutes")


def own_calendar(ctx):
    """The person's own calendar: the first of theirs that is nobody else's and
    read from nowhere."""
    me = ctx.user.username
    for calendar in ctx.records.list(CALENDAR):
        if calendar.owner == me and calendar.scope == "personal" and not calendar.get(URL):
            return calendar
    return None


@action("copy_to_next_week")
def copy_to_next_week(ctx, event):
    fields = {name: event.get(name) for name in ("calendar", "title", "all_day", "location", "notes")}
    fields["starts_at"] = later(event["starts_at"])
    fields["ends_at"] = later(event.get("ends_at"))
    # Off a subscribed calendar — nothing is put on one of those — the copy
    # goes on your own.
    if ctx.records.get(CALENDAR, event["calendar"]).get(URL):
        own = own_calendar(ctx)
        if own is None:
            return error("You have no calendar of your own to copy it to.")
        fields["calendar"] = own.id
    copy = ctx.records.create(EVENT, {k: v for k, v in fields.items() if v is not None})
    return [toast(f"{event['title']} is on {fields['starts_at'][:10]} too"), open(copy)]


# -- subscribing -------------------------------------------------------------------------


class Trouble(Exception):
    """What went wrong reading a feed, in words for the person."""


def host_of(url):
    found = re.match(r"^[a-z]+://([^/?#]+)", url, re.IGNORECASE)
    return found.group(1).lower() if found else url


def as_https(url):
    """`webcal://`, which is how calendars are often handed out, is https."""
    url = str(url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    return url


def read_feed(ctx, url, today):
    """The feed at *url*, read and understood: Trouble, in words, when it cannot be."""
    if not url.lower().startswith("https://"):
        raise Trouble("a feed's address starts with https:// (or webcal://)")
    try:
        answer = ctx.fetch(url, headers={"Accept": "text/calendar, */*;q=0.5"})
    except (Refused, Invalid) as exc:
        raise Trouble(str(exc)) from None
    if not answer.ok:
        raise Trouble(f"{host_of(url)} answered {answer.status}")
    text = answer.text
    if "BEGIN:VCALENDAR" not in text:
        raise Trouble(f"what is at {host_of(url)} is not a calendar")
    return parse_feed(text, since=today - BACK, until=today + AHEAD)


def free_colour(ctx):
    """A colour no calendar the person sees has yet, while there is one."""
    taken = {c.get("colour") for c in ctx.records.list(CALENDAR)}
    return next((c for c in COLOURS if c not in taken), COLOURS[len(taken) % len(COLOURS)])


def note(ctx, calendar, trouble=""):
    """On the calendar's sheet: when the feed was last read, and what went wrong."""
    ctx.records.patch(CALENDAR, calendar.id, {REFRESHED: ctx.now().isoformat(timespec="seconds"), TROUBLE: trouble})


def fill(ctx, calendar, feed):
    """The feed's events, on *calendar*, and nothing else: new ones made, changed
    ones changed, gone ones taken off — anything else on it too, because
    nothing is put on a subscribed calendar by hand."""
    have = {}
    strays = []
    for record in ctx.records.list(EVENT, calendar=calendar.id):
        key = record.get(UID)
        if key and key not in have:
            have[key] = record
        else:
            strays.append(record)
    for key, fields in feed.events.items():
        wanted = {**fields, "calendar": calendar.id, UID: key}
        found = have.pop(key, None)
        if found is None:
            ctx.records.create(EVENT, wanted)
            continue
        changed = {k: v for k, v in wanted.items() if (found.get(k) or "") != (v or "")}
        if changed:
            ctx.records.patch(EVENT, found.id, changed)
    for record in [*have.values(), *strays]:
        ctx.records.delete(EVENT, record.id)
    return len(feed.events)


def refresh_calendar(ctx, calendar):
    """Read *calendar*'s feed again: how many events it has now, and what went
    wrong if anything did — then the ones already here are kept."""
    try:
        feed = read_feed(ctx, str(calendar.get(URL) or ""), ctx.now().date())
    except Trouble as exc:
        kept = len(ctx.records.list(EVENT, calendar=calendar.id))
        note(ctx, calendar, f"{exc}; the {kept} events already here are kept")
        return kept, str(exc)
    count = fill(ctx, calendar, feed)
    note(ctx, calendar)
    return count, ""


@action("subscribe")
def subscribe(ctx, url, name=""):
    url = as_https(url)
    try:
        feed = read_feed(ctx, url, ctx.now().date())
    except Trouble as exc:
        return error(f"Could not read that calendar: {exc}.")
    title = str(name or "").strip() or feed.name or host_of(url)
    calendar = ctx.records.create(CALENDAR, {"name": title, "colour": free_colour(ctx), URL: url}, scope="personal")
    count = fill(ctx, calendar, feed)
    note(ctx, calendar)
    return [toast(f"{title}: {count} events, read again every hour"), go("month")]


@action("refresh")
def refresh(ctx, calendar):
    if not calendar.get(URL):
        return error(f"{calendar['name']} is not subscribed from anywhere; there is nothing to refresh.")
    count, trouble = refresh_calendar(ctx, calendar)
    if trouble:
        return error(f"Could not read {calendar['name']}: {trouble}.")
    return toast(f"{calendar['name']}: {count} events")


@action("unsubscribe")
def unsubscribe(ctx, calendar):
    if not calendar.get(URL):
        return error(f"{calendar['name']} is not subscribed from anywhere.")
    ctx.records.delete(CALENDAR, calendar.id)
    return [toast(f"{calendar['name']} is gone"), go("month")]


@job
def refresh_all(ctx):
    """Every hour, as each person: their own subscriptions, read again."""
    me = ctx.user.username
    for calendar in ctx.records.list(CALENDAR):
        if calendar.get(URL) and calendar.owner == me:
            count, trouble = refresh_calendar(ctx, calendar)
            if trouble:
                ctx.log(f"{calendar['name']}: {trouble}")


@hook
def url_changed(ctx, change):
    """The address on a calendar's sheet changed: the new feed is read — or,
    with the address cleared, the feed's events go and the calendar stays."""
    calendar = ctx.records.get(CALENDAR, change.record.id)
    if calendar.get(URL):
        refresh_calendar(ctx, calendar)
        return
    for record in ctx.records.list(EVENT, calendar=calendar.id):
        if record.get(UID):
            ctx.records.delete(EVENT, record.id)
    if calendar.get(REFRESHED) or calendar.get(TROUBLE):
        ctx.records.patch(CALENDAR, calendar.id, {REFRESHED: None, TROUBLE: ""})


# -- iCalendar ---------------------------------------------------------------------------
# Enough of RFC 5545 for what calendars publish: VEVENT with its moments and
# text, VTIMEZONE for the zones they are in, RRULE, EXDATE, RECURRENCE-ID.


class Feed:
    def __init__(self, name, events):
        self.name = name
        self.events = events  # key → the event's fields, in the order the feed had them


def unfold(text):
    """Lines, with the continuation lines (a space or a tab first) joined back on."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def split_line(line):
    """`NAME;PARAM=a;OTHER="x:y":value` → name, {PARAM: a, OTHER: x:y}, value."""
    quoted = False
    for at, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            head, value = line[:at], line[at + 1 :]
            break
    else:
        head, value = line, ""
    name, *raw = head.split(";")
    params = {}
    for item in raw:
        key, _, val = item.partition("=")
        params[key.upper()] = val.strip('"')
    return name.upper(), params, value


def components(lines):
    """The nesting of BEGIN/END, as {name, props, children}; the root holds VCALENDAR."""
    root = {"name": "", "props": [], "children": []}
    stack = [root]
    for line in lines:
        name, params, value = split_line(line)
        if name == "BEGIN":
            made = {"name": value.strip().upper(), "props": [], "children": []}
            stack[-1]["children"].append(made)
            stack.append(made)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["props"].append((name, params, value))
    return root


def first(component, name):
    return next(((params, value) for n, params, value in component["props"] if n == name), ({}, None))


def every(component, name):
    return [(params, value) for n, params, value in component["props"] if n == name]


def unescape(text):
    out = []
    at = 0
    while at < len(text):
        char = text[at]
        if char == "\\" and at + 1 < len(text):
            nxt = text[at + 1]
            out.append("\n" if nxt in "nN" else nxt)
            at += 2
            continue
        out.append(char)
        at += 1
    return "".join(out)


def moment(value, params):
    """A DATE or DATE-TIME as written: a date, or a naive datetime and its zone —
    "" for a time on the wall, "UTC", or the TZID the feed names."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8])), ""
    utc = value.endswith("Z")
    core = value.rstrip("Zz")
    when = dt.datetime(
        int(core[:4]),
        int(core[4:6]),
        int(core[6:8]),
        int(core[9:11]),
        int(core[11:13]),
        int(core[13:15]) if len(core) >= 15 else 0,
    )
    return when, "UTC" if utc else params.get("TZID", "")


DURATION_RE = re.compile(r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def duration(text):
    found = DURATION_RE.match(text.strip())
    if not found:
        return None
    sign, weeks, days, hours, minutes, seconds = found.groups()
    span = dt.timedelta(
        weeks=int(weeks or 0),
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=int(seconds or 0),
    )
    return -span if sign == "-" else span


# -- zones --------------------------------------------------------------------------------


def offset_of(text):
    """`+0100` → an hour."""
    sign = -1 if text.startswith("-") else 1
    digits = text.lstrip("+-")
    return sign * dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))


class Zone:
    """A VTIMEZONE: when its standard and daylight times start, and what each is."""

    def __init__(self, component):
        self.rules = []
        for part in component["children"]:
            if part["name"] not in ("STANDARD", "DAYLIGHT"):
                continue
            params, value = first(part, "DTSTART")
            start = moment(value, params)[0] if value else None
            if not isinstance(start, dt.datetime):
                continue
            rule = first(part, "RRULE")[1]
            self.rules.append(
                {
                    "start": start,
                    "from": offset_of(first(part, "TZOFFSETFROM")[1] or "+0000"),
                    "to": offset_of(first(part, "TZOFFSETTO")[1] or "+0000"),
                    "rrule": parse_rrule(rule) if rule else None,
                    "rdates": [moment(p, v)[0] for p, v in every(part, "RDATE") for v in v.split(",")],
                }
            )

    def offset(self, local):
        """What the clock on the wall at *local* is ahead of UTC by."""
        if not self.rules:
            return dt.timedelta()
        onsets = []
        for rule in self.rules:
            if rule["rrule"]:
                whens = occurrences(
                    rule["start"],
                    rule["rrule"],
                    since=local.date() - dt.timedelta(days=400),
                    until=local.date() + dt.timedelta(days=1),
                )
            else:
                whens = [rule["start"], *rule["rdates"]]
            onsets.extend((when, rule["to"]) for when in whens if isinstance(when, dt.datetime) and when <= local)
        if not onsets:
            return min(self.rules, key=lambda r: r["start"])["from"]
        return max(onsets)[1]


def to_utc(when, zone, zones):
    """A naive moment in *zone* as a moment in UTC, if the zone is known."""
    if zone == "UTC":
        return when.replace(tzinfo=dt.UTC)
    if zone in zones:
        return (when - zones[zone].offset(when)).replace(tzinfo=dt.UTC)
    if zone:
        try:
            from zoneinfo import ZoneInfo

            return when.replace(tzinfo=ZoneInfo(zone)).astimezone(dt.UTC)
        except Exception:  # no such zone, or no zone data where this runs
            return None
    return None


def stored(when, zone, zones):
    """A moment as the record keeps it: a whole day a date; a moment in a known
    zone in UTC, which every surface shows in the reader's own time; a time on
    the wall, or one in a zone nobody here knows, exactly as the feed wrote it."""
    if not isinstance(when, dt.datetime):
        return when.isoformat()
    exact = to_utc(when, zone, zones)
    if exact is not None:
        return exact.isoformat(timespec="seconds")
    return when.isoformat(timespec="minutes")


def stamp(when, zone, zones):
    """One time of a recurring event, named the same way wherever it is written."""
    if not isinstance(when, dt.datetime):
        return when.strftime("%Y%m%d")
    exact = to_utc(when, zone, zones)
    return (exact.replace(tzinfo=None) if exact is not None else when).strftime("%Y%m%dT%H%M%S")


# -- recurrence ------------------------------------------------------------------------------

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def parse_rrule(text):
    rule = {}
    for item in text.split(";"):
        key, _, value = item.partition("=")
        if key:
            rule[key.strip().upper()] = value.strip()
    return rule


def by_day(text):
    """`-1SU,2MO,TU` → [(-1, 6), (2, 0), (0, 1)]."""
    out = []
    for item in text.split(","):
        item = item.strip().upper()
        if len(item) < 2 or item[-2:] not in WEEKDAYS:
            continue
        ordinal = item[:-2]
        out.append((int(ordinal) if ordinal else 0, WEEKDAYS[item[-2:]]))
    return out


def ints(text):
    return {int(x) for x in text.split(",") if x.strip().lstrip("+-").isdigit()}


def days_in_month(year, month):
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - dt.date(year, month, 1)).days


def month_days(year, month, bymonthday, byday):
    """The days of a month a rule picks: by number (from the end when negative),
    by weekday (every one, or the nth, or the nth from the end)."""
    last = days_in_month(year, month)
    picked = set()
    for number in bymonthday:
        day = number if number > 0 else last + 1 + number
        if 1 <= day <= last:
            picked.add(dt.date(year, month, day))
    for ordinal, weekday in byday:
        matching = [dt.date(year, month, d) for d in range(1, last + 1) if dt.date(year, month, d).weekday() == weekday]
        if ordinal == 0:
            picked.update(matching)
        elif -len(matching) <= ordinal <= len(matching) and ordinal != 0:
            picked.add(matching[ordinal - 1 if ordinal > 0 else ordinal])
    return picked


def year_days(year, byday):
    """The nth weekday of a year, for a yearly rule that says BYDAY and no month."""
    picked = set()
    for ordinal, weekday in byday:
        matching = []
        day = dt.date(year, 1, 1)
        while day.year == year:
            if day.weekday() == weekday:
                matching.append(day)
            day += dt.timedelta(days=1)
        if ordinal == 0:
            picked.update(matching)
        elif -len(matching) <= ordinal <= len(matching):
            picked.add(matching[ordinal - 1 if ordinal > 0 else ordinal])
    return picked


def add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def occurrences(start, rule, *, since, until):
    """When a recurring thing happens, from *start* by *rule*, between *since*
    and *until* (dates): the same kind of value as *start* each time. COUNT
    counts from the start, before *since* is applied, so a window later on
    still shows the right times."""
    freq = rule.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [start]
    interval = max(1, int(rule.get("INTERVAL") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    stop = None
    if rule.get("UNTIL"):
        stop, _ = moment(rule["UNTIL"], {})
        stop = stop if isinstance(stop, dt.date) and not isinstance(stop, dt.datetime) else stop.date()
    whole_day = not isinstance(start, dt.datetime)
    day0 = start if whole_day else start.date()
    bymonth = ints(rule.get("BYMONTH", ""))
    bymonthday = ints(rule.get("BYMONTHDAY", ""))
    byday = by_day(rule.get("BYDAY", ""))
    wkst = WEEKDAYS.get(rule.get("WKST", "MO").upper(), 0)
    if freq in ("MONTHLY", "YEARLY") and not bymonthday and not byday:
        bymonthday = {day0.day}

    def period(n):
        if freq == "DAILY":
            return [day0 + dt.timedelta(days=n * interval)]
        if freq == "WEEKLY":
            week = day0 - dt.timedelta(days=(day0.weekday() - wkst) % 7) + dt.timedelta(days=7 * n * interval)
            wanted = [d for _, d in byday] or [day0.weekday()]
            return sorted(week + dt.timedelta(days=(d - wkst) % 7) for d in wanted)
        if freq == "MONTHLY":
            month = add_months(day0, n * interval)
            return sorted(month_days(month.year, month.month, bymonthday, byday))
        year = day0.year + n * interval
        if byday and not bymonth:
            return sorted(year_days(year, byday))
        days = set()
        for month in sorted(bymonth or {day0.month}):
            days |= month_days(year, month, bymonthday, byday)
        return sorted(days)

    # Without a COUNT there is no need to walk up from a start years back:
    # the period just before *since* is as good a place to begin.
    n0 = 0
    if count is None and since > day0:
        gap = (since - day0).days
        per = {"DAILY": interval, "WEEKLY": 7 * interval}.get(freq)
        if per:
            n0 = max(0, gap // per - 1)
        elif freq == "MONTHLY":
            n0 = max(0, ((since.year - day0.year) * 12 + since.month - day0.month) // interval - 1)
        else:
            n0 = max(0, (since.year - day0.year) // interval - 1)
    found = []
    seen = 0
    n = n0
    while n - n0 < MOST * 4:
        days = period(n)
        n += 1
        if days and days[0] > until:
            break
        for day in days:
            if day < day0:
                continue
            if stop is not None and day > stop:
                return found
            if count is not None and seen >= count:
                return found
            seen += 1
            if day >= since:
                found.append(day if whole_day else dt.datetime.combine(day, start.time()))
            if len(found) >= MOST:
                return found
    return found


# -- the feed ------------------------------------------------------------------------------


def event_fields(component, start, end, zone, zones):
    """What one time of an event is, as a record: its title and two moments,
    where and what about."""
    whole_day = not isinstance(start, dt.datetime)
    last = end
    if whole_day:
        # DTEND is the day after the last day; the record's end is the last day.
        last = max(start, end - dt.timedelta(days=1)) if isinstance(end, dt.date) else start
    fields = {
        "title": unescape(first(component, "SUMMARY")[1] or "").strip() or "Untitled",
        "starts_at": stored(start, zone, zones),
        "ends_at": stored(last, zone, zones),
        "all_day": whole_day,
        "location": unescape(first(component, "LOCATION")[1] or "").strip(),
        "notes": unescape(first(component, "DESCRIPTION")[1] or "").strip(),
    }
    return fields


def parse_feed(text, *, since, until):
    """Every event in the feed between *since* and *until*, keyed so that a
    refresh finds each again: the UID, and for a recurring one the time."""
    root = components(unfold(text))
    calendars = [c for c in root["children"] if c["name"] == "VCALENDAR"] or [root]
    name = ""
    zones = {}
    masters = []
    overrides = []
    for calendar in calendars:
        name = name or unescape(first(calendar, "X-WR-CALNAME")[1] or first(calendar, "NAME")[1] or "").strip()
        for part in calendar["children"]:
            if part["name"] == "VTIMEZONE":
                tzid = first(part, "TZID")[1]
                if tzid:
                    zones[tzid] = Zone(part)
            elif part["name"] == "VEVENT":
                if first(part, "RECURRENCE-ID")[1]:
                    overrides.append(part)
                elif first(part, "DTSTART")[1]:
                    masters.append(part)

    events = {}
    cancelled = set()

    def span_of(part, start):
        params, value = first(part, "DTEND")
        if value:
            end, _ = moment(value, params)
            return end - start if type(end) is type(start) else None
        value = first(part, "DURATION")[1]
        return duration(value) if value else None

    def shown(start, end):
        a = start if not isinstance(start, dt.datetime) else start.date()
        b = end if not isinstance(end, dt.datetime) else end.date()
        return a <= until and b >= since

    for part in masters:
        uid = first(part, "UID")[1] or ""
        if (first(part, "STATUS")[1] or "").upper() == "CANCELLED":
            continue
        params, value = first(part, "DTSTART")
        start, zone = moment(value, params)
        span = span_of(part, start)
        if span is None:
            span = dt.timedelta() if not isinstance(start, dt.datetime) else HOUR
        rule = first(part, "RRULE")[1]
        if not rule:
            if shown(start, start + span):
                events[uid or stamp(start, zone, zones)] = event_fields(part, start, start + span, zone, zones)
            continue
        skipped = {
            stamp(moment(v, p)[0], p.get("TZID", zone) if not v.endswith("Z") else "UTC", zones)
            for p, vs in every(part, "EXDATE")
            for v in vs.split(",")
            if v.strip()
        }
        for when in occurrences(start, parse_rrule(rule), since=since, until=until):
            key = f"{uid}@{stamp(when, zone, zones)}"
            if stamp(when, zone, zones) in skipped or not shown(when, when + span):
                continue
            events[key] = event_fields(part, when, when + span, zone, zones)

    for part in overrides:
        uid = first(part, "UID")[1] or ""
        params, value = first(part, "RECURRENCE-ID")
        was, was_zone = moment(value, params)
        key = f"{uid}@{stamp(was, was_zone, zones)}"
        if (first(part, "STATUS")[1] or "").upper() == "CANCELLED":
            events.pop(key, None)
            cancelled.add(key)
            continue
        params, value = first(part, "DTSTART")
        if not value:
            continue
        start, zone = moment(value, params)
        span = span_of(part, start)
        if span is None:
            span = dt.timedelta() if not isinstance(start, dt.datetime) else HOUR
        if shown(start, start + span):
            events[key] = event_fields(part, start, start + span, zone, zones)
        else:
            events.pop(key, None)
    return Feed(name, events)
