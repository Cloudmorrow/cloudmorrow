"""Calendars: your own, everybody's, the shared ones, and what goes on them."""

from __future__ import annotations

import datetime as dt

import pytest

from cloudmorrow.server.calendar import day_window, days_of, normalise_when, personal_slug
from tests.conftest import ADMIN, GUEST, token_for


@pytest.fixture()
def guest(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(client, *GUEST)}"}


def calendars(client, auth) -> list[dict]:
    response = client.get("/api/calendar/calendars", headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def calendar(client, auth, name="Household", kind="shared", **extra) -> dict:
    response = client.post(
        "/api/calendar/calendars", json={"name": name, "kind": kind, **extra}, headers=auth
    )
    assert response.status_code == 201, response.text
    return response.json()


def event(client, auth, slug, title="Dentist", starts_at="2026-09-19T10:00", **extra) -> dict:
    response = client.post(
        f"/api/calendar/calendars/{slug}/events",
        json={"title": title, "starts_at": starts_at, **extra},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    return response.json()


def events(client, auth, start="2026-09-01", end="2026-09-30", **params) -> list[dict]:
    response = client.get(
        "/api/calendar/events", params={"from": start, "to": end, **params}, headers=auth
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- the one everybody has -------------------------------------------------------
def test_everybody_has_their_own_and_nobody_else_sees_it(client, auth, guest):
    mine = calendars(client, auth)
    assert [c["kind"] for c in mine] == ["personal"]
    assert mine[0]["slug"] == personal_slug(ADMIN[0])
    assert mine[0]["mine"] is True

    theirs = calendars(client, guest)
    assert [c["slug"] for c in theirs] == [personal_slug(GUEST[0])]
    # And asking for somebody else's by name is a 403, not a listing.
    assert client.get(
        f"/api/calendar/calendars/{personal_slug(ADMIN[0])}", headers=guest
    ).status_code == 403


def test_a_personal_calendar_cannot_be_shared_left_or_deleted(client, auth):
    slug = personal_slug(ADMIN[0])
    added = client.post(
        f"/api/calendar/calendars/{slug}/members",
        json={"usernames": [GUEST[0]]},
        headers=auth,
    )
    assert added.status_code == 400
    assert "make a shared one" in added.json()["detail"]
    assert client.post(f"/api/calendar/calendars/{slug}/leave", headers=auth).status_code == 400
    assert client.delete(f"/api/calendar/calendars/{slug}", headers=auth).status_code == 400


# -- public ----------------------------------------------------------------------
def test_a_public_calendar_is_everybodys(client, auth, guest):
    made = calendar(client, auth, "Holidays", kind="public")
    assert set(made["members"]) == {ADMIN[0], GUEST[0]}
    assert [c["slug"] for c in calendars(client, guest) if c["kind"] == "public"] == ["holidays"]
    # And the guest may write in it, having been asked nothing.
    event(client, guest, "holidays", "Midsummer", "2026-06-20", all_day=True)
    assert [e["title"] for e in events(client, auth, "2026-06-01", "2026-06-30")] == ["Midsummer"]


def test_a_public_calendar_cannot_be_left(client, auth, guest):
    calendar(client, auth, "Holidays", kind="public")
    response = client.post("/api/calendar/calendars/holidays/leave", headers=guest)
    assert response.status_code == 400
    assert "cannot leave" in response.json()["detail"]


def test_a_second_calendar_of_the_same_name_is_refused(client, auth):
    calendar(client, auth, "Household")
    response = client.post(
        "/api/calendar/calendars", json={"name": "household", "kind": "shared"}, headers=auth
    )
    assert response.status_code == 409


def test_a_calendar_cannot_be_named_as_if_it_were_somebodys_own(client, auth):
    response = client.post(
        "/api/calendar/calendars", json={"name": "my bram", "kind": "shared"}, headers=auth
    )
    assert response.status_code == 400
    assert "reserved" in response.json()["detail"]


# -- shared ------------------------------------------------------------------------
def test_a_shared_calendar_is_only_for_the_people_in_it(client, auth, guest):
    made = calendar(client, auth, "Household")
    assert made["members"] == [ADMIN[0]]
    assert "household" not in [c["slug"] for c in calendars(client, guest)]
    assert client.get("/api/calendar/calendars/household", headers=guest).status_code == 403
    # Writing in one you are not in is refused too, not just reading it.
    refused = client.post(
        "/api/calendar/calendars/household/events",
        json={"title": "Sneaky", "starts_at": "2026-09-19T10:00"},
        headers=guest,
    )
    assert refused.status_code == 403


def test_being_added_is_being_in_it(client, auth, guest):
    calendar(client, auth, "Household")
    event(client, auth, "household", "Bins out", "2026-09-19", all_day=True)
    response = client.post(
        "/api/calendar/calendars/household/members",
        json={"usernames": [GUEST[0]]},
        headers=auth,
    )
    assert response.status_code == 200
    assert response.json()["added"] == [GUEST[0]]
    # Nothing was accepted, and what was already written is there to read.
    assert [e["title"] for e in events(client, guest)] == ["Bins out"]
    # And they may write in it, because a calendar you share is one you share.
    event(client, guest, "household", "Boiler service", "2026-09-22T09:00")
    assert len(events(client, auth)) == 2


def test_being_added_leaves_a_notification(client, auth, guest):
    calendar(client, auth, "Household", members=[GUEST[0]])
    bell = client.get("/api/notifications", headers=guest).json()
    assert [note["kind"] for note in bell] == ["calendar.shared"]
    assert "shared Household with you" in bell[0]["title"]


def test_a_calendar_can_be_left_but_not_by_the_person_who_made_it(client, auth, guest):
    calendar(client, auth, "Household", members=[GUEST[0]])
    mine = client.post("/api/calendar/calendars/household/leave", headers=auth)
    assert mine.status_code == 400
    assert "delete it" in mine.json()["detail"]
    assert client.post("/api/calendar/calendars/household/leave", headers=guest).status_code == 204
    assert "household" not in [c["slug"] for c in calendars(client, guest)]


def test_only_its_owner_renames_or_deletes_it(client, auth, guest):
    calendar(client, auth, "Household", members=[GUEST[0]])
    theirs = client.patch(
        "/api/calendar/calendars/household", json={"name": "Mine now"}, headers=guest
    )
    assert theirs.status_code == 403
    assert client.delete("/api/calendar/calendars/household", headers=guest).status_code == 403
    renamed = client.patch(
        "/api/calendar/calendars/household",
        json={"name": "The house", "colour": "violet"},
        headers=auth,
    )
    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["colour"]) == ("The house", "violet")
    assert client.delete("/api/calendar/calendars/household", headers=auth).status_code == 204


def test_deleting_a_calendar_takes_its_events_with_it(client, auth):
    calendar(client, auth, "Household")
    event(client, auth, "household")
    assert client.delete("/api/calendar/calendars/household", headers=auth).status_code == 204
    assert events(client, auth) == []


def test_calendars_get_a_colour_each(client, auth):
    first = calendar(client, auth, "Household")
    second = calendar(client, auth, "Work")
    assert first["colour"] != second["colour"]
    # And one you asked for is the one you get.
    assert calendar(client, auth, "Trips", colour="rose")["colour"] == "rose"


# -- the events ---------------------------------------------------------------------
def test_an_event_with_no_end_is_an_hour_long(client, auth):
    made = event(client, auth, personal_slug(ADMIN[0]))
    assert (made["starts_at"], made["ends_at"]) == ("2026-09-19T10:00", "2026-09-19T11:00")
    assert made["all_day"] is False


def test_an_all_day_event_is_a_date_and_stays_one(client, auth):
    made = event(client, auth, personal_slug(ADMIN[0]), "Away", "2026-09-19", all_day=True,
                 ends_at="2026-09-21")
    assert (made["starts_at"], made["ends_at"]) == ("2026-09-19", "2026-09-21")
    assert made["all_day"] is True


def test_a_zone_is_answered_in_ours(client, auth):
    """One house, one clock: what comes in with an offset comes back without."""
    made = event(client, auth, personal_slug(ADMIN[0]), "Call", "2026-09-19T10:00:00+00:00")
    local = dt.datetime(2026, 9, 19, 10, tzinfo=dt.UTC).astimezone()
    assert made["starts_at"] == local.strftime("%Y-%m-%dT%H:%M")


def test_an_event_cannot_end_before_it_starts(client, auth):
    response = client.post(
        f"/api/calendar/calendars/{personal_slug(ADMIN[0])}/events",
        json={"title": "Backwards", "starts_at": "2026-09-19T10:00", "ends_at": "2026-09-19T09:00"},
        headers=auth,
    )
    assert response.status_code == 400
    assert "before it starts" in response.json()["detail"]


def test_an_event_needs_a_title_and_a_real_date(client, auth):
    slug = personal_slug(ADMIN[0])
    blank = client.post(
        f"/api/calendar/calendars/{slug}/events",
        json={"title": "   ", "starts_at": "2026-09-19T10:00"},
        headers=auth,
    )
    assert blank.status_code == 400
    nonsense = client.post(
        f"/api/calendar/calendars/{slug}/events",
        json={"title": "When?", "starts_at": "next tuesday"},
        headers=auth,
    )
    assert nonsense.status_code == 400
    assert "2026-09-19T14:00" in nonsense.json()["detail"]


def test_the_window_is_what_overlaps_it(client, auth):
    slug = personal_slug(ADMIN[0])
    event(client, auth, slug, "Before", "2026-08-30T10:00")
    event(client, auth, slug, "Inside", "2026-09-10T10:00")
    event(client, auth, slug, "Across", "2026-08-31", all_day=True, ends_at="2026-09-02")
    event(client, auth, slug, "After", "2026-10-02T10:00")
    seen = [e["title"] for e in events(client, auth)]
    assert seen == ["Across", "Inside"], "sorted by when they start, and only these two"


def test_an_event_late_on_the_last_day_is_still_in_the_window(client, auth):
    slug = personal_slug(ADMIN[0])
    event(client, auth, slug, "Late", "2026-09-30T23:30")
    assert [e["title"] for e in events(client, auth)] == ["Late"]


def test_the_events_of_every_calendar_come_back_together(client, auth):
    calendar(client, auth, "Household")
    calendar(client, auth, "Holidays", kind="public")
    event(client, auth, personal_slug(ADMIN[0]), "Dentist", "2026-09-19T10:00")
    event(client, auth, "household", "Bins out", "2026-09-18T08:00")
    event(client, auth, "holidays", "Midsummer", "2026-09-20", all_day=True)
    seen = events(client, auth)
    assert [e["title"] for e in seen] == ["Bins out", "Dentist", "Midsummer"]
    # Each carries the calendar it is on, so a merged view can colour it.
    assert {e["calendar"] for e in seen} == {personal_slug(ADMIN[0]), "household", "holidays"}
    # And one calendar on its own is one calendar's worth.
    assert [e["title"] for e in events(client, auth, calendar="household")] == ["Bins out"]


def test_an_event_can_be_changed_and_moved_to_another_calendar(client, auth):
    calendar(client, auth, "Household")
    made = event(client, auth, personal_slug(ADMIN[0]))
    response = client.patch(
        f"/api/calendar/events/{made['id']}",
        json={"title": "Dentist, moved", "starts_at": "2026-09-19T11:30",
              "calendar": "household", "location": "High Street"},
        headers=auth,
    )
    assert response.status_code == 200
    moved = response.json()
    assert moved["calendar"] == "household"
    assert moved["title"] == "Dentist, moved"
    assert moved["location"] == "High Street"
    # Moving it kept it an hour long rather than leaving its end behind.
    assert (moved["starts_at"], moved["ends_at"]) == ("2026-09-19T11:30", "2026-09-19T12:30")


def test_somebody_elses_event_is_theirs_unless_the_calendar_is_yours(client, auth, guest):
    calendar(client, auth, "Household", members=[GUEST[0]])
    theirs = event(client, guest, "household", "Their thing", "2026-09-19T10:00")
    # A third party in the calendar cannot touch it...
    client.post(
        "/api/calendar/calendars/household/members",
        json={"usernames": []},
        headers=auth,
    )
    # ...but the owner of the calendar can, because a shared calendar with a
    # stale event stuck on it is worse than this rule.
    assert client.patch(
        f"/api/calendar/events/{theirs['id']}", json={"title": "Tidied"}, headers=auth
    ).status_code == 200
    assert client.delete(f"/api/calendar/events/{theirs['id']}", headers=auth).status_code == 204


def test_an_event_in_a_calendar_you_cannot_see_is_not_found_for_you(client, auth, guest):
    made = event(client, auth, personal_slug(ADMIN[0]))
    assert client.get(f"/api/calendar/events/{made['id']}", headers=guest).status_code == 403
    assert client.delete(f"/api/calendar/events/{made['id']}", headers=guest).status_code == 403


def test_what_is_coming_up(client, auth):
    slug = personal_slug(ADMIN[0])
    today = dt.date.today()
    event(client, auth, slug, "Yesterday", (today - dt.timedelta(days=1)).isoformat(),
          all_day=True)
    event(client, auth, slug, "Tomorrow", (today + dt.timedelta(days=1)).isoformat(),
          all_day=True)
    event(client, auth, slug, "Next month", (today + dt.timedelta(days=40)).isoformat(),
          all_day=True)
    soon = client.get("/api/calendar/upcoming", headers=auth).json()
    assert [e["title"] for e in soon] == ["Tomorrow"]


# -- the feature switch ----------------------------------------------------------------
def test_switching_the_calendar_off_closes_its_api(client, auth):
    assert client.patch(
        "/api/server/features/calendar", json={"enabled": False}, headers=auth
    ).status_code == 200
    assert client.get("/api/calendar/calendars", headers=auth).status_code == 403


# -- the plumbing underneath -------------------------------------------------------------
def test_normalise_when_keeps_a_date_a_date_and_a_time_to_the_minute():
    assert normalise_when("2026-09-19", all_day=True) == "2026-09-19"
    assert normalise_when("2026-09-19T14:03:21", all_day=False) == "2026-09-19T14:03"
    # An all-day event given a time keeps the day it was on.
    assert normalise_when("2026-09-19T14:00", all_day=True) == "2026-09-19"


def test_the_window_bounds_reach_the_end_of_the_last_day():
    assert day_window("2026-09-01", "2026-09-30") == ("2026-09-01", "2026-09-30T23:59")
    # Back to front is a window all the same.
    assert day_window("2026-09-30", "2026-09-01") == ("2026-09-01", "2026-09-30T23:59")


def test_an_event_is_on_every_day_it_runs_over():
    assert days_of({"starts_at": "2026-09-19", "ends_at": "2026-09-21"}) == [
        "2026-09-19", "2026-09-20", "2026-09-21",
    ]
    assert days_of({"starts_at": "2026-09-19T23:00", "ends_at": "2026-09-19T23:30"}) == [
        "2026-09-19"
    ]
