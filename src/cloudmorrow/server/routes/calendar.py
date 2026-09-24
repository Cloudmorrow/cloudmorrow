"""The calendar API: the calendars, who they are shared with, and what is on them.

Every call takes the signed-in user and hands it to the store, which decides
whether they may see the calendar. Nothing here works out access for itself —
there is one set of rules and it lives in `calendar.py`.

The one thing that leaves this module for the outside world is a notification
when somebody is added to a shared calendar, sent after the response has gone
out. Events do not notify: a house calendar that pinged everybody for every
appointment would be one nobody reads.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from cloudmorrow.server.calendar import (
    COLOURS,
    MAX_NOTES_CHARS,
    SHARED,
    CalendarExistsError,
    InvalidCalendarError,
    InvalidEventError,
    NotAMemberError,
    UnknownCalendarError,
    UnknownEventError,
    today,
)
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.routes.push import notify_message

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


# -- what goes in and out --------------------------------------------------------
class CalendarOut(BaseModel):
    slug: str
    name: str
    kind: str
    colour: str = "cyan"
    owner: str = ""
    created_at: str = ""
    updated_at: str = ""
    members: list[str] = Field(default_factory=list)
    member: bool = True
    # Yours to rename, to share and to throw away.
    mine: bool = False
    events: int = 0


class CalendarCreate(BaseModel):
    name: str
    kind: str = SHARED
    colour: str = ""
    # Only for a shared calendar: a public one is everybody's already.
    members: list[str] = Field(default_factory=list)


class CalendarUpdate(BaseModel):
    name: str | None = None
    colour: str | None = None


class MembersIn(BaseModel):
    usernames: list[str] = Field(default_factory=list)


class MembersOut(BaseModel):
    added: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)


class EventOut(BaseModel):
    id: int
    calendar: str
    calendar_name: str = ""
    colour: str = "cyan"
    title: str
    notes: str = ""
    location: str = ""
    # Wall-clock: '2026-09-19T14:00', or '2026-09-19' when all_day.
    starts_at: str
    ends_at: str
    all_day: bool = False
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class EventIn(BaseModel):
    title: str
    starts_at: str
    # Left out, an event is an hour long — or the whole of the day it is on.
    ends_at: str | None = None
    all_day: bool = False
    notes: str = Field(default="", max_length=MAX_NOTES_CHARS * 2)
    location: str = ""


class EventUpdate(BaseModel):
    title: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    all_day: bool | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTES_CHARS * 2)
    location: str | None = None
    # Moving an event from one calendar to another, by naming the new one.
    calendar: str | None = None


class PersonOut(BaseModel):
    username: str
    display_name: str = ""


class ColoursOut(BaseModel):
    colours: list[str] = Field(default_factory=list)


# -- turning the store's complaints into status codes ------------------------------
def _handled(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownCalendarError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no such calendar: {exc}")
    if isinstance(exc, UnknownEventError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no such event: {exc}")
    if isinstance(exc, NotAMemberError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc) or "not yours")
    if isinstance(exc, CalendarExistsError):
        return HTTPException(
            status.HTTP_409_CONFLICT, detail=f"there is already a calendar called {exc}"
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _guard(call):
    """Run a store call, answering with a status code instead of a traceback."""
    try:
        return call()
    except (
        UnknownCalendarError,
        UnknownEventError,
        NotAMemberError,
        CalendarExistsError,
        InvalidCalendarError,
        InvalidEventError,
    ) as exc:
        raise _handled(exc) from exc


# -- the calendars ------------------------------------------------------------------
@router.get("/calendars", response_model=list[CalendarOut])
def list_calendars(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[CalendarOut]:
    return [CalendarOut(**row) for row in state.calendar.calendars(user.username)]


@router.post("/calendars", response_model=CalendarOut, status_code=status.HTTP_201_CREATED)
def create_calendar(
    payload: CalendarCreate,
    background: BackgroundTasks,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> CalendarOut:
    calendar = _guard(
        lambda: state.calendar.create(
            user.username,
            name=payload.name,
            kind=payload.kind,
            colour=payload.colour,
            members=payload.members,
        )
    )
    told = [who for who in calendar["members"] if who != user.username]
    _announce(state, background, user.username, calendar, told)
    return CalendarOut(**calendar)


@router.get("/calendars/{slug}", response_model=CalendarOut)
def get_calendar(
    slug: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> CalendarOut:
    return CalendarOut(**_guard(lambda: state.calendar.get(user.username, slug)))


@router.patch("/calendars/{slug}", response_model=CalendarOut)
def update_calendar(
    slug: str,
    payload: CalendarUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> CalendarOut:
    return CalendarOut(
        **_guard(
            lambda: state.calendar.update(
                user.username, slug, name=payload.name, colour=payload.colour
            )
        )
    )


@router.delete("/calendars/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar(
    slug: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> None:
    _guard(lambda: state.calendar.delete(user.username, slug, force=user.is_admin))


@router.get("/people", response_model=list[PersonOut])
def list_people(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[PersonOut]:
    """Everyone a calendar could be shared with."""
    return [PersonOut(**row) for row in state.calendar.people(excluding=user.username)]


@router.get("/colours", response_model=ColoursOut)
def list_colours(_user: User = Depends(get_current_user)) -> ColoursOut:
    """The colours a calendar may be, so a client need not hard-code them."""
    return ColoursOut(colours=list(COLOURS))


# -- who is in them --------------------------------------------------------------------
@router.post("/calendars/{slug}/members", response_model=MembersOut)
def add_members(
    slug: str,
    payload: MembersIn,
    background: BackgroundTasks,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> MembersOut:
    """Share a calendar with people. They are in it; there is nothing to accept."""
    added = _guard(lambda: state.calendar.add_members(user.username, slug, payload.usernames))
    calendar = state.calendar.get(user.username, slug)
    _announce(state, background, user.username, calendar, added)
    return MembersOut(added=added, members=calendar["members"])


@router.post("/calendars/{slug}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_calendar(
    slug: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> None:
    _guard(lambda: state.calendar.leave(user.username, slug))


def _announce(
    state: AppState,
    background: BackgroundTasks,
    actor: str,
    calendar: dict,
    told: list[str],
) -> None:
    """Tell people a calendar of theirs has appeared.

    Being given a calendar is a thing that happened to you while you were
    elsewhere, which is what the bell is for. What is written in it is not,
    and does not come through here.
    """
    if not told:
        return
    name = calendar["name"] or calendar["slug"]
    public = calendar["kind"] == "public"
    said = f"{actor} made the {name} calendar" if public else f"{actor} shared {name} with you"
    for who in told:
        state.notifications.add(who, kind="calendar.shared", title=said, body="")
    background.add_task(
        notify_message,
        state,
        told,
        title=name,
        body="A calendar everyone is in" if public else f"{actor} shared it with you",
        url=f"#/calendar/{calendar['slug']}",
        tag=f"calendar-shared-{calendar['slug']}",
    )


# -- what is on them ----------------------------------------------------------------------
@router.get("/events", response_model=list[EventOut])
def list_events(
    start: str = Query(default="", alias="from", description="The first day, as 2026-09-01."),
    end: str = Query(default="", alias="to", description="The last day, as 2026-09-30."),
    calendar: str | None = Query(
        default=None, description="One calendar's events rather than all of them."
    ),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[EventOut]:
    """Everything in a window of days, across every calendar you can see.

    With no window it is today: a client that wants a month asks for one, and
    one that just wants to know what is on does not have to.
    """
    first = start or today()
    last = end or first
    rows = _guard(
        lambda: state.calendar.events(user.username, start=first, end=last, calendar=calendar)
    )
    return [EventOut(**row) for row in rows]


@router.get("/upcoming", response_model=list[EventOut])
def upcoming(
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=200),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[EventOut]:
    """The next few things, for a screen with room for a line of them."""
    return [
        EventOut(**row) for row in state.calendar.upcoming(user.username, days=days, limit=limit)
    ]


@router.post(
    "/calendars/{slug}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED
)
def add_event(
    slug: str,
    payload: EventIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> EventOut:
    return EventOut(
        **_guard(
            lambda: state.calendar.add_event(
                user.username,
                slug,
                title=payload.title,
                starts_at=payload.starts_at,
                ends_at=payload.ends_at,
                all_day=payload.all_day,
                notes=payload.notes,
                location=payload.location,
            )
        )
    )


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(
    event_id: int,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> EventOut:
    return EventOut(**_guard(lambda: state.calendar.event(user.username, event_id)))


@router.patch("/events/{event_id}", response_model=EventOut)
def edit_event(
    event_id: int,
    payload: EventUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> EventOut:
    return EventOut(
        **_guard(
            lambda: state.calendar.edit_event(
                user.username,
                event_id,
                title=payload.title,
                starts_at=payload.starts_at,
                ends_at=payload.ends_at,
                all_day=payload.all_day,
                notes=payload.notes,
                location=payload.location,
                calendar=payload.calendar,
                force=user.is_admin,
            )
        )
    )


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    _guard(lambda: state.calendar.delete_event(user.username, event_id, force=user.is_admin))
