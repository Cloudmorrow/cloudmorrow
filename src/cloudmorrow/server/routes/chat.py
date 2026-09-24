"""The chat API: channels, the people in them, and what gets said.

Every call takes the signed-in user and hands it to the store, which decides
whether they may see the channel. Nothing here works out access for itself —
there is one set of rules and it lives in `chat.py`, so a route that forgets
to check cannot exist.

Two things leave this module for the outside world, and both happen after the
response has gone out: a notification row when somebody is added to a
channel, and a push to whoever was not looking. Chat itself never blocks on
a push service being slow.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from cloudmorrow.server.chat import (
    MAX_BODY_CHARS,
    PRIVATE,
    ChannelExistsError,
    InvalidChannelError,
    NotAMemberError,
    UnknownChannelError,
)
from cloudmorrow.server.db import User
from cloudmorrow.server.deps import AppState, get_current_user, get_state
from cloudmorrow.server.routes.push import notify_message

router = APIRouter(prefix="/api/chat", tags=["chat"])


# -- what goes in and out ------------------------------------------------------
class MessageOut(BaseModel):
    id: int
    author: str
    body: str
    created_at: str
    edited_at: str | None = None


class ChannelOut(BaseModel):
    slug: str
    # For a direct channel this is the other person, so it depends on who
    # asked. Every other kind is called the same thing for everybody.
    name: str
    topic: str = ""
    kind: str
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""
    members: list[str] = Field(default_factory=list)
    other: str = ""
    member: bool = True
    unread: int = 0
    last_read: int = 0
    last_message: MessageOut | None = None


class ChannelCreate(BaseModel):
    name: str
    kind: str = PRIVATE
    topic: str = ""
    # Only for a private channel: a public one is everybody's already.
    members: list[str] = Field(default_factory=list)


class ChannelUpdate(BaseModel):
    name: str | None = None
    topic: str | None = None


class MembersIn(BaseModel):
    usernames: list[str] = Field(default_factory=list)


class MembersOut(BaseModel):
    """Who was actually added — the ones already in it are not news."""

    added: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)


class MessageIn(BaseModel):
    body: str = Field(max_length=MAX_BODY_CHARS * 2)


class DirectIn(BaseModel):
    username: str


class ReadIn(BaseModel):
    """How far you have read. Omit it to mean everything."""

    upto: int | None = None


class ReadOut(BaseModel):
    last_read: int
    unread: int
    total: int


class UnreadOut(BaseModel):
    channels: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class PersonOut(BaseModel):
    username: str
    display_name: str = ""


# -- turning the store's complaints into status codes ---------------------------
def _handled(exc: Exception) -> HTTPException:
    if isinstance(exc, UnknownChannelError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no such channel: {exc}")
    if isinstance(exc, NotAMemberError):
        return HTTPException(status.HTTP_403_FORBIDDEN, detail="that channel is not yours")
    if isinstance(exc, ChannelExistsError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=f"there is already a #{exc}")
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _guard(call):
    """Run a store call, answering with a status code instead of a traceback."""
    try:
        return call()
    except (
        UnknownChannelError,
        NotAMemberError,
        ChannelExistsError,
        InvalidChannelError,
    ) as exc:
        raise _handled(exc) from exc


# -- the channels ------------------------------------------------------------------
@router.get("/channels", response_model=list[ChannelOut])
def list_channels(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[ChannelOut]:
    return [ChannelOut(**row) for row in state.chat.channels(user.username)]


@router.post("/channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
def create_channel(
    payload: ChannelCreate,
    background: BackgroundTasks,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ChannelOut:
    channel = _guard(
        lambda: state.chat.create(
            user.username,
            name=payload.name,
            kind=payload.kind,
            topic=payload.topic,
            members=payload.members,
        )
    )
    told = [who for who in channel["members"] if who != user.username]
    _announce(state, background, user.username, channel, told)
    return ChannelOut(**channel)


@router.get("/channels/{slug}", response_model=ChannelOut)
def get_channel(
    slug: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> ChannelOut:
    return ChannelOut(**_guard(lambda: state.chat.get(user.username, slug)))


@router.patch("/channels/{slug}", response_model=ChannelOut)
def update_channel(
    slug: str,
    payload: ChannelUpdate,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ChannelOut:
    return ChannelOut(
        **_guard(
            lambda: state.chat.update(
                user.username, slug, name=payload.name, topic=payload.topic
            )
        )
    )


@router.delete("/channels/{slug}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    slug: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> None:
    _guard(lambda: state.chat.delete(user.username, slug, force=user.is_admin))


@router.post("/direct", response_model=ChannelOut)
def open_direct(
    payload: DirectIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ChannelOut:
    """The channel with one other person, whether or not it existed before."""
    return ChannelOut(**_guard(lambda: state.chat.direct(user.username, payload.username)))


@router.get("/people", response_model=list[PersonOut])
def list_people(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> list[PersonOut]:
    """Everyone there is to talk to. Everybody may write to everybody."""
    return [PersonOut(**row) for row in state.chat.people(excluding=user.username)]


# -- who is in them -------------------------------------------------------------------
@router.post("/channels/{slug}/members", response_model=MembersOut)
def add_members(
    slug: str,
    payload: MembersIn,
    background: BackgroundTasks,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> MembersOut:
    """Put people in a channel. They are in it; there is nothing to accept."""
    added = _guard(lambda: state.chat.add_members(user.username, slug, payload.usernames))
    channel = state.chat.get(user.username, slug)
    _announce(state, background, user.username, channel, added)
    return MembersOut(added=added, members=channel["members"])


@router.post("/channels/{slug}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_channel(
    slug: str, state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> None:
    _guard(lambda: state.chat.leave(user.username, slug))


def _announce(
    state: AppState,
    background: BackgroundTasks,
    actor: str,
    channel: dict,
    told: list[str],
) -> None:
    """Tell people they are in a channel now.

    This is the one part of chat that leaves a notification row. Being added
    to a channel is a thing that happened to you while you were elsewhere,
    which is exactly what the bell is for; a message is not, because it has
    its own count.
    """
    if not told or channel["kind"] == "direct":
        return
    name = channel["name"] or channel["slug"]
    # Everybody is in a public channel by definition, so nobody was added to
    # one — what happened is that it now exists, and that is the news.
    public = channel["kind"] == "public"
    said = f"{actor} made #{name}" if public else f"{actor} added you to #{name}"
    for who in told:
        state.notifications.add(
            who, kind="chat.added", title=said, body=channel["topic"]
        )
    background.add_task(
        notify_message,
        state,
        told,
        title=f"#{name}",
        body="A new channel everyone is in" if public else f"{actor} added you to it",
        url=f"#/chat/{channel['slug']}",
        tag=f"chat-added-{channel['slug']}",
    )


# -- the messages ----------------------------------------------------------------------
@router.get("/channels/{slug}/messages", response_model=list[MessageOut])
def list_messages(
    slug: str,
    limit: int = Query(default=50, ge=1, le=200),
    before: int | None = Query(default=None, description="Older than this message id."),
    after: int | None = Query(default=None, description="Newer than this message id."),
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> list[MessageOut]:
    rows = _guard(
        lambda: state.chat.messages(
            user.username, slug, limit=limit, before=before, after=after
        )
    )
    return [MessageOut(**row) for row in rows]


@router.post(
    "/channels/{slug}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
def post_message(
    slug: str,
    payload: MessageIn,
    background: BackgroundTasks,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> MessageOut:
    posted = _guard(lambda: state.chat.post(user.username, slug, payload.body))
    channel = posted["channel"]
    # A direct channel is called after whoever is reading it, and the person
    # reading this one is not the author — so it is the author's name they
    # should see on their phone.
    heading = user.username if channel.direct else f"#{channel.name or channel.slug}"
    body = posted["message"]["body"]
    background.add_task(
        notify_message,
        state,
        posted["audience"],
        title=heading,
        body=body if channel.direct else f"{user.username}: {body}",
        url=f"#/chat/{channel.slug}",
        # One notification per channel on the phone, replaced as it goes,
        # rather than a stack of forty.
        tag=f"chat-{channel.slug}",
    )
    return MessageOut(**posted["message"])


@router.patch("/channels/{slug}/messages/{message_id}", response_model=MessageOut)
def edit_message(
    slug: str,
    message_id: int,
    payload: MessageIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> MessageOut:
    return MessageOut(
        **_guard(lambda: state.chat.edit(user.username, slug, message_id, payload.body))
    )


@router.delete(
    "/channels/{slug}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_message(
    slug: str,
    message_id: int,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> None:
    _guard(
        lambda: state.chat.delete_message(
            user.username, slug, message_id, force=user.is_admin
        )
    )


# -- what has been read -----------------------------------------------------------------
@router.post("/channels/{slug}/read", response_model=ReadOut)
def mark_read(
    slug: str,
    payload: ReadIn,
    state: AppState = Depends(get_state),
    user: User = Depends(get_current_user),
) -> ReadOut:
    mark = _guard(lambda: state.chat.mark_read(user.username, slug, payload.upto))
    unread = state.chat.unread(user.username)
    return ReadOut(
        last_read=mark, unread=unread["channels"].get(slug, 0), total=unread["total"]
    )


@router.get("/unread", response_model=UnreadOut)
def unread(
    state: AppState = Depends(get_state), user: User = Depends(get_current_user)
) -> UnreadOut:
    return UnreadOut(**state.chat.unread(user.username))
