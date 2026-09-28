"""The number on the icon, and the pushes that carry it.

The badge is nobody's in particular, so it is in no Quill: it is the one
number on the home-screen icon, and it has to mean everything waiting — what
was written in your spaces since you last looked (a channel's messages,
whichever Quill declared them `unread`), plus notifications you have not
read. The record store counts the one, the notifications the other, and this
adds them up. One number, one place it is worked out, so the page, the
service worker and the push payload can never disagree about it.
"""

from __future__ import annotations

from cloudmorrow.server.records import Principal
from cloudmorrow.server.state import AppState


def unread_models(state: AppState, username: str) -> list[str]:
    """The space datamodels whose unread counts for this person.

    Their own switch counts here as well: a number on the icon for a tab
    they have turned off is a count of something they cannot go and read.
    So a space counts when some Quill that uses it is on for them.
    """
    return [
        model.id
        for model in state.quills.datamodels.values()
        if model.space
        and any(state.features.enabled_for(username, quill) for quill in state.quills.users_of(model.id))
    ]


def badge_for(state: AppState, username: str) -> dict:
    """Everything waiting for one person, as the icon would say it."""
    wanted = unread_models(state, username)
    messages = (
        state.records.unread_total(Principal.person(username), models=wanted) if wanted else 0
    )
    notifications = state.notifications.unread_count(username)
    return {
        "messages": messages,
        "notifications": notifications,
        "badge": messages + notifications,
    }


def notify_message(
    state: AppState,
    usernames: list[str],
    *,
    title: str,
    body: str,
    url: str = "",
    tag: str = "",
) -> int:
    """Push a line to everyone named, each with their own badge number.

    The badge differs per person — it is what *they* have waiting — so this
    cannot be one payload sent to a list. It is a handful of requests to a
    handful of devices, run as a background task after the response has
    gone, so nobody waits on Apple to answer.
    """
    landed = 0
    for who in dict.fromkeys(usernames):
        counts = badge_for(state, who)
        landed += state.push.send(
            [who],
            {
                "title": title,
                "body": body[:200],
                "url": url,
                "tag": tag,
                "badge": counts["badge"],
            },
        )
    return landed
