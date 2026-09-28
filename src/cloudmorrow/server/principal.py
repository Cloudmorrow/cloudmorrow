"""Who is asking, and the gate that says what they may reach at all.

A principal is a person, an assistant acting for one, or a Quill acting for
one; `check` is the first question every read and write of a record asks.
Which records of a datamodel it then reaches is the record store's to say.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ACTIONS", "DATASET", "NEVER_FOR_ASSISTANTS", "Principal", "Refused", "check"]


class Refused(PermissionError):
    """The gate said no."""


# -- who is asking -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Principal:
    """A person, an assistant acting as one, or a Quill acting for one.

    Every principal acts for an account: the records it reaches are that
    account's. What differs is what it may reach of them.
    """

    kind: str  # person, assistant, quill; dataset for a Quill's seed
    username: str
    # For a Quill: its id, and the datamodels it declared or was granted.
    quill: str = ""
    models: frozenset[str] = field(default_factory=frozenset)
    # An administrator may manage any shared or public space, as on a server
    # they are responsible for; it lets them see no personal record.
    admin: bool = False

    @classmethod
    def person(cls, username: str, *, admin: bool = False) -> Principal:
        return cls("person", username, admin=admin)

    @classmethod
    def assistant(cls, username: str, *, admin: bool = False) -> Principal:
        return cls("assistant", username, admin=admin)

    @property
    def writer(self) -> str:
        return self.quill or self.kind


# A Quill's dataset being written for somebody (`RecordStore.seed`): not a
# person acting, so their circles do not narrow it.
DATASET = "dataset"

# Datamodels no assistant is ever let at, whatever the person allows.
NEVER_FOR_ASSISTANTS = frozenset({"secret"})

ACTIONS = frozenset({"read", "write"})


def check(principal: Principal, action: str, model: str) -> None:
    """The gate. Raises Refused, or returns having said yes.

    Personal scope means a principal only ever reaches its own account's
    records, and that is enforced by the store taking the owner from the
    principal rather than from the request. What is decided here is the
    rest: which datamodels each kind of principal may touch at all.
    """
    if action not in ACTIONS:
        raise Refused(f"no such action: {action}")
    if principal.kind == "assistant" and model in NEVER_FOR_ASSISTANTS:
        raise Refused(f"assistants never reach {model}")
    if principal.kind == "quill" and model not in principal.models:
        raise Refused(f"{principal.quill} did not ask for {model}")
