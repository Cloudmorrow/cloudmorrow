"""Approvals: a yes or a no, asked of whoever holds a role.

The one step most procedures come down to — somebody responsible says yes
before it goes on — made foundational once, so no Quill builds its own.
An approval is an `approval` record (core_datamodels/approval.toml): the
question, which record it is about, the role asked and, when it matters,
the circle it is asked in. It is the asker's record, and seen by whoever
holds the role (`seen_by_role`, records.py), who find it under *Waiting
for you* on every surface and answer it there.

A Quill asks with `ctx.approvals.ask(record, role=…, question=…)`, a flow
with an `approval` step, a person from a record's sheet. The answer lands
on the record — `status`, `answered_by`, `note` — and so reaches a Quill as
an ordinary hook on `approval`, and a waiting flow run through flows.py.
The asker hears of the answer behind the bell; the holders hear of the
question the same way. See docs/FLOWS.md.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from cloudmorrow.server.records import DATASET, Principal, Record, RecordError, Refused

if TYPE_CHECKING:
    from cloudmorrow.server.state import AppState

MODEL = "approval"
ANSWERS = frozenset({"approved", "declined"})
OPEN = "requested"


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


class Approvals:
    """Asking, answering, and who is waiting on whom."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        state.records.on_change.append(self._on_change)

    def _holds(self, username: str, record: Record) -> bool:
        roles = self.state.roles
        if roles is None:
            return False
        return roles.holds(username, str(record.fields.get("role") or ""), str(record.fields.get("circle") or ""))

    # -- asking ------------------------------------------------------------------------------
    def ask(
        self,
        principal: Principal,
        *,
        role: str,
        question: str,
        about_model: str = "",
        about: str = "",
        about_title: str = "",
        circle: str = "",
        due: str | None = None,
        flow_run: str = "",
    ) -> Record:
        """Ask the holders of *role* as *principal*. A Quill may ask without
        listing `approval`: the question is the core's, not the Quill's data."""
        roles = self.state.roles
        if roles is None:
            raise RecordError("roles are not set up on this server")
        try:
            found = roles.get(role)
        except LookupError:
            raise RecordError(f"there is no role called {role}; an administrator makes one under Roles") from None
        if not str(question).strip():
            raise RecordError("an approval asks a question")
        if principal.kind == "quill" and MODEL not in principal.models:
            principal = Principal(principal.kind, principal.username, principal.quill, principal.models | {MODEL})
        if about_model and about and not about_title:
            model = self.state.quills.datamodels.get(about_model)
            if model is not None:
                subject = self.state.records.get(principal, about_model, about)
                about_title = str(subject.fields.get(model.title) or "")
        fields = {
            "question": str(question).strip(),
            "about_model": about_model,
            "about": about,
            "about_title": about_title,
            "role": found.id,
            "circle": circle,
            "status": OPEN,
            "asked_by": principal.username,
            "due": due,
            "flow_run": flow_run,
        }
        made = self.state.records.create(principal, MODEL, {k: v for k, v in fields.items() if v not in (None, "")})
        for who in roles.people(found.id, circle):
            if who == principal.username:
                continue
            self.state.notifications.add(
                who,
                kind="approval.asked",
                title=f"{principal.username} asks: {made.fields['question']}",
                body=about_title or "",
            )
        return made

    # -- answering ---------------------------------------------------------------------------
    def answer(self, username: str, approval_id: str, status: str, note: str = "") -> Record:
        """*username* answers: approved or declined by a holder of the role,
        withdrawn by whoever asked. An approval is answered once."""
        if status not in ANSWERS | {"withdrawn"}:
            raise RecordError("an approval is approved, declined, or withdrawn")
        principal = Principal.person(username)
        record = self.state.records.get(principal, MODEL, approval_id)
        if record.fields.get("status") != OPEN:
            raise RecordError(f"this was already {record.fields.get('status')}")
        if status == "withdrawn":
            if record.owner != username:
                raise Refused("only whoever asked may withdraw the question")
        elif not self._holds(username, record):
            raise Refused(f"only whoever holds the role {record.fields.get('role')} may answer")
        return self.state.records.update(
            principal,
            MODEL,
            approval_id,
            {"status": status, "note": note or "", "answered_by": username, "answered_at": _now()},
        )

    # -- what is open -----------------------------------------------------------------------
    def waiting_for(self, username: str) -> list[Record]:
        """The open questions *username* may answer, oldest first."""
        principal = Principal.person(username)
        try:
            found = self.state.records.list(principal, MODEL, {"status": OPEN})
        except LookupError:
            return []
        return [r for r in found if self._holds(username, r)]

    def asked_by(self, username: str) -> list[Record]:
        """What *username* asked and is still open."""
        principal = Principal.person(username)
        try:
            return self.state.records.list(principal, MODEL, {"status": OPEN, "asked_by": username})
        except LookupError:
            return []

    def waiting_count(self, username: str) -> int:
        return len(self.waiting_for(username))

    # -- telling the asker -------------------------------------------------------------------
    def _on_change(self, principal: Principal, action: str, record: Record, before: dict | None) -> None:
        if record.model != MODEL or action != "changed" or principal.kind == DATASET:
            return
        status = str(record.fields.get("status") or "")
        if status not in ANSWERS or (before or {}).get("status") == status:
            return
        asker = str(record.fields.get("asked_by") or record.owner)
        by = str(record.fields.get("answered_by") or principal.username)
        if asker == by:
            return
        body = str(record.fields.get("note") or "")
        self.state.notifications.add(
            asker, kind=f"approval.{status}", title=f"{by} {status}: {record.fields.get('question', '')}", body=body
        )
