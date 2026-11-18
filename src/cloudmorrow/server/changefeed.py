"""The change feed, live: one open connection per screen instead of a request every few seconds.

`GET /api/changes` is a server-sent events stream. Each event names a record
that was made, changed or deleted — its datamodel, its id, the space it is
in, the action and the time — and never a field of it: a screen that hears
one asks the record API for what it has not got (`?_since=`), the same call
it made on a timer before, so nothing is told here that the gate would not
hand over there. Only changes the listener may see are sent: a record of
their own, or one in a space they are in.

    event: hello      {"seq": 41}            the feed's position, first thing
    event: change     {"seq": 42, "model": "message", "id": "…", "space": "…",
                       "owner": "bram", "action": "created", "at": "…"}
    event: quills     {}                     a Quill came, went or was switched:
                                             ask /api/quills again for the menu
    event: bye        {"reason": "restart"}  the server is stopping — an update —
                                             and the stream ends; come back soon
    : ping                                   every so often, so the line stays up

The notices (`quills`, `bye`) are for everybody listening and say nothing
anybody could not ask for: each client asks its own question afterwards.
`bye` goes out the moment the server is told to stop (`going`, from the
signal, in cli.py), before the connections are closed.

A client that drops comes back with `?since=<seq>` and gets what it missed
of the last few thousand changes; before that horizon it asks `_since` for
the records, which it does on every reconnect anyway. `?limit=N` closes the
stream after N events: for a script, or a test.

In one process, which the server is (see quills/services.py): the record
store tells the feed about every committed write through `on_change`, and
the feed wakes whichever streams are waiting. Nothing is written to the
database for it.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from cloudmorrow.server.deps import AppState, get_principal, get_state
from cloudmorrow.server.records import Principal, Record, RecordStore, UnknownModelError

# How many changes the feed remembers for a client coming back.
HELD = 4096
# How long a quiet stream goes between pings. Proxies drop an idle line at
# a minute or so; this keeps under it.
PING_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class Change:
    seq: int
    model: str
    id: str
    # The space the record is in, or is, for a record that is a space.
    space: str
    owner: str
    action: str
    at: str


class ChangeFeed:
    """What the record store has done lately, and who is waiting to hear."""

    def __init__(self, records: RecordStore) -> None:
        self.records = records
        self._lock = threading.Lock()
        self._held: deque[Change] = deque(maxlen=HELD)
        self._seq = 0
        # Each open stream: the loop it runs on, and the event that wakes it.
        self._waiting: set[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = set()
        # Notices for every stream, about no record: (number, event, data).
        self._notes: deque[tuple[int, str, dict]] = deque(maxlen=64)
        self._note = 0
        # Why the server is stopping, once it is: every stream says bye.
        self.leaving = ""

    @property
    def note(self) -> int:
        return self._note

    @property
    def seq(self) -> int:
        return self._seq

    # -- what the record store tells it --------------------------------------------
    def listen(self, principal: Principal, action: str, record: Record, before: dict | None) -> None:
        """A record store listener (`RecordStore.on_change`): called after the write committed."""
        space = ""
        try:
            model = self.records.model(record.model)
        except UnknownModelError:
            model = None
        if model is not None:
            if model.space:
                space = record.id
            elif model.in_space:
                space = str(record.fields.get(model.in_space) or "")
        with self._lock:
            self._seq += 1
            change = Change(self._seq, record.model, record.id, space, record.owner, action, record.updated_at)
            self._held.append(change)
        self._wake()

    def _wake(self) -> None:
        with self._lock:
            waiting = list(self._waiting)
        for loop, event in waiting:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:  # its loop is gone with its stream
                pass

    def tell(self, name: str, data: dict | None = None) -> None:
        """A notice for every open stream: `quills` when the menu should be asked again."""
        with self._lock:
            self._note += 1
            self._notes.append((self._note, name, dict(data or {})))
        self._wake()

    def notes_since(self, note: int) -> list[tuple[int, str, dict]]:
        with self._lock:
            return [n for n in self._notes if n[0] > note]

    def going(self, reason: str = "restart") -> None:
        """The server is stopping: every stream says bye and ends, before the connections go."""
        self.leaving = reason or "restart"
        self._wake()

    # -- what a stream asks ------------------------------------------------------------
    def since(self, seq: int) -> list[Change]:
        with self._lock:
            return [c for c in self._held if c.seq > seq]

    def _news(self, note: int | None) -> bool:
        return bool(self.leaving) or (note is not None and self._note > note)

    async def wait(self, seq: int, timeout: float, note: int | None = None) -> list[Change]:
        """Changes after *seq*, as soon as there is one; none after *timeout* seconds.
        With *note*, it also comes back early for a notice after it, or for bye."""
        found = self.since(seq)
        if found or self._news(note):
            return found
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        with self._lock:
            self._waiting.add((loop, event))
        try:
            # Something may have come between the look and the wait.
            found = self.since(seq)
            if found or self._news(note):
                return found
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except TimeoutError:
                return []
            return self.since(seq)
        finally:
            with self._lock:
                self._waiting.discard((loop, event))

    def may_see(self, principal: Principal, change: Change) -> bool:
        """Would the record API hand this record to the principal? Then they may hear of it."""
        try:
            self.records._check(principal, "read", change.model)
        except Exception:
            return False
        if change.owner == principal.username:
            return True
        if change.space:
            return self.records.may_see_space(principal, change.space)
        return False


# -- the route -------------------------------------------------------------------------------
router = APIRouter(prefix="/api/changes", tags=["records"])


def _event(name: str, data: dict, seq: int | None = None) -> str:
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@router.get("", summary="What changed, as it changes")
async def stream_changes(
    request: Request,
    since: int | None = Query(default=None, ge=0, description="Send what came after this seq first"),
    limit: int | None = Query(default=None, ge=1, description="Close after this many changes"),
    state: AppState = Depends(get_state),
    principal: Principal = Depends(get_principal),
) -> StreamingResponse:
    """A server-sent events stream of the records you may see being made, changed and deleted."""
    feed = state.changes
    assert feed is not None

    async def body() -> AsyncIterator[str]:
        cursor = feed.seq if since is None else since
        note = feed.note
        yield f"retry: 3000\n{_event('hello', {'seq': feed.seq})}"
        sent = 0
        while True:
            if feed.leaving:
                yield _event("bye", {"reason": feed.leaving})
                return
            changes = await feed.wait(cursor, PING_SECONDS, note=note)
            if await request.is_disconnected():
                return
            if feed.leaving:
                continue
            notes = feed.notes_since(note)
            for _, name, data in notes:
                yield _event(name, data)
            if notes:
                note = notes[-1][0]
            if not changes:
                if not notes:
                    yield ": ping\n\n"
                continue
            for change in changes:
                cursor = change.seq
                if not feed.may_see(principal, change):
                    continue
                yield _event("change", asdict(change), seq=change.seq)
                sent += 1
                if limit is not None and sent >= limit:
                    return

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
