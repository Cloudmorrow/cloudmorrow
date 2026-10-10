"""Whose Quills are whose: the shelf each person sees, and the access that follows it.

The registry says what is installed. The shelf says what *this person* has
of it, which is three things laid together (docs/SHARING.md):

1. **The server's Quills**, each for everyone, or for the circles and people
   its administrator chose on the install sheet (`origin.audience`).
2. **Their own Quills**, under `quills-personal/<them>/`.
3. **Quills shared with them** by their owners, once they said yes.

One id, one Quill, per person: a server Quill wins over one shared with
them, which wins over their own of the same id, and what lost is listed as
shadowed rather than lost. The same shelf narrows access: a datamodel of
somebody's own (`~alice.budget.envelope`) is reachable only by the people on
whose shelf that Quill stands, whatever the circles say about `*`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from cloudmorrow.server.circles import NONE, Access, CircleStore
from cloudmorrow.server.datamodels import OWNER_PREFIX
from cloudmorrow.server.db import UserStore
from cloudmorrow.server.quills.manifest import Manifest
from cloudmorrow.server.quills.registry import QuillRegistry
from cloudmorrow.server.quills.sharing import Policy, SharingStore

__all__ = ["Narrowed", "Shelf", "audience_of", "in_audience"]


@dataclass(frozen=True, slots=True)
class Narrowed(Access):
    """A person's access, with everybody else's own datamodels out of reach."""

    reach: frozenset[str] = field(default_factory=frozenset)

    def level(self, model: str) -> str:
        if model.startswith(OWNER_PREFIX) and model not in self.reach:
            return NONE
        return Access.level(self, model)


def audience_of(manifest: Manifest) -> dict:
    """Who a server Quill is for: `{"circles": [...], "people": [...]}`; empty is everyone."""
    audience = manifest.origin.get("audience") or {}
    if not isinstance(audience, dict):
        return {"circles": [], "people": []}
    return {
        "circles": [str(c) for c in audience.get("circles") or []],
        "people": [str(p) for p in audience.get("people") or []],
    }


def in_audience(audience: dict, username: str, circles: Iterable[str]) -> bool:
    """Is *username*, in *circles* (ids or names), one of the people an audience names?"""
    if not audience["circles"] and not audience["people"]:
        return True
    if username in audience["people"]:
        return True
    mine = {c.lower() for c in circles}
    return any(c.lower() in mine for c in audience["circles"])


class Shelf:
    def __init__(
        self,
        registry: QuillRegistry,
        sharing: SharingStore,
        circles: CircleStore | None,
        users: UserStore,
        *,
        enabled: Callable[[str], bool] | None = None,
        policy: Policy | None = None,
    ) -> None:
        self.registry = registry
        self.sharing = sharing
        self.circles = circles
        self.users = users
        # What the server allows: with Quills of people's own switched off,
        # nobody's are on anybody's shelf; with sharing off, only one's own.
        self.policy = policy
        # Is a Quill, by key, switched on for the server? Off, and it is
        # nobody's: the shelf shows it, as a switched-off tab, and the gate
        # still reaches its data, as it always has for a feature.
        self.enabled = enabled or (lambda key: True)

    # -- who is in which circle ------------------------------------------------------------
    def _circles_of(self, username: str) -> list[str]:
        if self.circles is None:
            return []
        try:
            return [c for circle in self.circles.circles_of(username) for c in (circle.id, circle.name)]
        except Exception:
            return []

    def for_server_quill(self, manifest: Manifest, username: str, circles: list[str] | None = None) -> bool:
        return in_audience(audience_of(manifest), username, self._circles_of(username) if circles is None else circles)

    # -- a person's shelf --------------------------------------------------------------------
    def for_user(self, username: str) -> dict[str, Manifest]:
        """The Quills on *username*'s shelf, by id, in the order of their tabs."""
        return {m.id: m for m in self.registry.ordered(self._mine(username)[0])}

    def shadowed(self, username: str) -> list[Manifest]:
        """Quills of theirs, or shared with them, that a Quill of the same id stands in front of."""
        return self._mine(username)[1]

    def _mine(self, username: str) -> tuple[list[Manifest], list[Manifest]]:
        taken: dict[str, Manifest] = {}
        shadowed: list[Manifest] = []
        # Asked once for the whole shelf: the gate asks for a shelf on every read.
        circles = self._circles_of(username)
        for manifest in self.registry.quills.values():
            if self.for_server_quill(manifest, username, circles):
                taken[manifest.id] = manifest
        if self.policy is not None and not self.policy.may_have():
            return list(taken.values()), shadowed
        accepted = self.sharing.accepted_for(username) if self._sharing_on() else set()
        for owner, quill_id in sorted(accepted):
            manifest = self.registry.personal.get(owner, {}).get(quill_id)
            if manifest is None:
                continue
            if manifest.id in taken:
                shadowed.append(manifest)
            else:
                taken[manifest.id] = manifest
        for manifest in self.registry.personal.get(username, {}).values():
            if manifest.id in taken:
                shadowed.append(manifest)
            else:
                taken[manifest.id] = manifest
        return list(taken.values()), shadowed

    def find(self, username: str, quill_id: str) -> Manifest | None:
        """The Quill called *quill_id* on *username*'s shelf, or by its key, if on their shelf."""
        if quill_id.startswith(OWNER_PREFIX):
            found = self.registry.by_key(quill_id)
            return found if found is not None and self.has(username, found) else None
        return self.for_user(username).get(quill_id)

    def _sharing_on(self) -> bool:
        return self.policy is None or self.policy.may_share()

    def has(self, username: str, manifest: Manifest) -> bool:
        """Does this Quill stand on *username*'s shelf (shadowed or not)?"""
        if not manifest.personal:
            return self.for_server_quill(manifest, username)
        if self.policy is not None and not self.policy.may_have():
            return False
        if manifest.owner == username:
            return True
        return self._sharing_on() and (manifest.owner, manifest.id) in self.sharing.accepted_for(username)

    def people_of(self, manifest: Manifest) -> list[str]:
        """Everybody who has this Quill: for a personal one, its owner and whoever
        accepted it; for a server Quill, everybody in its audience."""
        users = self.users.list()
        if manifest.personal:
            if self.policy is not None and not self.policy.may_have():
                return []
            shared = self.sharing.accepted_by(manifest.owner, manifest.id) if self._sharing_on() else []
            people = [manifest.owner, *shared]
        else:
            people = [u.username for u in users if self.for_server_quill(manifest, u.username)]
        active = {u.username for u in users if u.is_active}
        return [p for p in dict.fromkeys(people) if p in active]

    # -- what follows from it ----------------------------------------------------------------
    def reach(self, username: str) -> frozenset[str]:
        """Every datamodel of somebody's own that *username* may use at all."""
        found: set[str] = set()
        mine, shadowed = self._mine(username)
        for manifest in (*mine, *shadowed):
            if manifest.personal:
                found.update(manifest.renamed.values())
                # ...and what such a Quill was let at of another's.
                found.update(m for m in manifest.models if m.startswith(OWNER_PREFIX))
        return frozenset(found)

    def access_for(self, username: str) -> Access:
        """What *username* may do with each datamodel: their circles, narrowed to their shelf."""
        if self.circles is None:
            base = Access(username, {"*": {"*": "write"}})
        else:
            base = self.circles.access_for(username)
        return Narrowed(base.username, base.circles, self.reach(username))

    def owners(self) -> list[str]:
        return sorted(self.registry.personal)
