"""Who else there is: the people a space can be shared with.

Every kit screen with spaces — a channel, a shared calendar — asks the same
question when somebody is added or written to, so it is asked here once
rather than by each Quill. Anybody signed in may ask: on a household server
everybody may write to everybody, and a list of names is not the accounts
panel, which stays an administrator's.

People only: an agent is a program acting for somebody already in the list,
and a screen on a wall reads nobody's messages.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state

router = APIRouter(prefix="/api/people", tags=["records"])


class PersonOut(BaseModel):
    username: str
    display_name: str = ""


def people(state: AppState, *, excluding: str = "") -> list[dict]:
    return [
        {"username": u.username, "display_name": u.display_name or ""}
        for u in state.users.list()
        if u.is_active and u.user_type == "human" and u.username != excluding
    ]


@router.get("", response_model=list[PersonOut])
def list_people(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[PersonOut]:
    """Everyone there is besides you, by account name."""
    return [PersonOut(**row) for row in people(state, excluding=user.username)]
