"""Flows: when something happens, do these steps — as whoever made the flow.

A flow is a `flow` record a person builds on a screen (core_datamodels/
flow.toml): one trigger and a list of steps. Nothing about it is a Quill,
and no code is written for one. It is how an operating procedure is said:

    when a leave is created
      ask the Team lead: "Approve {{trigger.record.fields.what}}?"
      only if approval.status is approved: set the leave's status to approved
      only if approval.status is approved: create an event on the calendar
      only if approval.status is declined: tell {{trigger.record.owner}}

The trigger is one of:

    {"kind": "record", "model": "leave", "when": "created"}
    {"kind": "record", "model": "leave", "when": "changed", "field": "status", "value": "approved"}
    {"kind": "action", "quill": "tasks", "action": "duplicate"}
    {"kind": "schedule", "every": "1d"}
    {"kind": "manual"}

Each step has an `id`, a `kind`, and may have `only_if`, a condition on
what the run has gathered so far, so a linear list still branches on an
answer. The kinds:

    action    press a Quill's action: quill, action, record, fields
    approval  ask a role: role, question, circle, about (a record id)
    set       change a record: model, record, fields
    create    make a record: model, fields
    notify    a line behind somebody's bell: to (a username, or a role), title, body
    wait      for a duration ("for": "1d") or until a moment ("until": "…")
    stop      end the run here

Every string in a step may hold `{{a.path}}`, read from the run's context:
`trigger.record.fields.title`, `approval.status`, `steps.<id>.<key>` (what
an action's `result(...)` handed back, or the record a `create` made),
`owner`, `now`. A string that is one placeholder keeps the value's type.

A run is a `flow_run` record: which step it is at, what it has gathered,
why it stopped. A flow runs as the person who made it, through the gate
as them (`Principal("flow", owner)`), so it reaches no more than they do,
and its writes say `flow` wrote them. Steps run on a thread of their own
(as hooks do), a run waiting on an approval or the clock is picked up when
the answer or the time comes, a flow's own writes never start it again,
and chains of flows stop three deep. See docs/FLOWS.md.
"""

from __future__ import annotations

import datetime as dt
import logging
import queue
import re
import threading
import time
from typing import TYPE_CHECKING

from cloudmorrow.server.datamodels import parse_duration
from cloudmorrow.server.principal import DATASET, Principal
from cloudmorrow.server.records import (
    Record,
    RecordConflictError,
    Refused,
    UnknownModelError,
    UnknownRecordError,
)

if TYPE_CHECKING:
    from cloudmorrow.server.state import AppState

log = logging.getLogger("cloudmorrow.flows")

FLOW = "flow"
RUN = "flow_run"
APPROVAL = "approval"
KIND = "flow"
DEPTH = 3
TRIGGER_KINDS = ("record", "action", "schedule", "manual")
STEP_KINDS = ("action", "approval", "set", "create", "notify", "wait", "stop")
WHEN = ("created", "changed", "deleted")

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


class FlowError(ValueError):
    """A flow or a step that does not say something the runner can do."""


def _now() -> str:
    return dt.datetime.now(tz=dt.UTC).isoformat(timespec="seconds")


# -- what a step may say ----------------------------------------------------------------------
def check_trigger(trigger: object) -> dict:
    if not isinstance(trigger, dict) or trigger.get("kind") not in TRIGGER_KINDS:
        raise FlowError(f"a trigger is one of {', '.join(TRIGGER_KINDS)}")
    kind = trigger["kind"]
    if kind == "record":
        if not trigger.get("model"):
            raise FlowError("a record trigger names a datamodel")
        when = trigger.get("when", "created")
        when = [when] if isinstance(when, str) else when
        if not isinstance(when, list) or any(w not in WHEN for w in when) or not when:
            raise FlowError(f"a record trigger's when is {', '.join(WHEN)}")
        return {**trigger, "when": when}
    if kind == "action" and not (trigger.get("quill") and trigger.get("action")):
        raise FlowError("an action trigger names a Quill and one of its actions")
    if kind == "schedule":
        try:
            parse_duration(str(trigger.get("every", "")))
        except ValueError as exc:
            raise FlowError(f"a schedule's every: {exc}") from exc
    return dict(trigger)


def check_steps(steps: object) -> list[dict]:
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
        raise FlowError("steps are a list of tables")
    seen: set[str] = set()
    out = []
    for i, step in enumerate(steps):
        kind = step.get("kind")
        if kind not in STEP_KINDS:
            raise FlowError(f"step {i + 1}: kind is one of {', '.join(STEP_KINDS)}")
        step_id = str(step.get("id") or f"step{i + 1}")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$", step_id) or step_id in seen:
            raise FlowError(f"step {i + 1}: every step has an id of its own, letters and digits")
        seen.add(step_id)
        if kind == "action" and not (step.get("quill") and step.get("action")):
            raise FlowError(f"step {step_id}: an action step names a Quill and an action")
        if kind == "approval" and not (step.get("role") and step.get("question")):
            raise FlowError(f"step {step_id}: an approval step names a role and asks a question")
        if kind in ("set", "create") and not step.get("model"):
            raise FlowError(f"step {step_id}: a {kind} step names a datamodel")
        if kind == "set" and not step.get("record"):
            raise FlowError(f"step {step_id}: a set step names the record, like {{{{trigger.record.id}}}}")
        if kind == "notify" and not (step.get("to") or step.get("role")) or kind == "notify" and not step.get("title"):
            raise FlowError(f"step {step_id}: a notify step names who (to, or a role) and a title")
        if kind == "wait":
            if bool(step.get("for")) == bool(step.get("until")):
                raise FlowError(f"step {step_id}: a wait step says for how long, or until when, one of them")
            if step.get("for"):
                try:
                    parse_duration(str(step["for"]))
                except ValueError as exc:
                    raise FlowError(f"step {step_id}: {exc}") from exc
        condition = step.get("only_if")
        if condition is not None and (
            not isinstance(condition, dict)
            or not condition.get("path")
            or not ({"equals", "not_equals", "set", "empty"} & set(condition))
        ):
            raise FlowError(f"step {step_id}: only_if is {{ path, equals }} or {{ path, not_equals }}")
        out.append({**step, "id": step_id})
    return out


# -- reading the context ---------------------------------------------------------------------------
def lookup(context: dict, path: str):
    """`trigger.record.fields.title` in *context*; None where the path ends early."""
    found = context
    for part in path.split("."):
        if isinstance(found, dict):
            found = found.get(part)
        elif isinstance(found, list) and part.isdigit() and int(part) < len(found):
            found = found[int(part)]
        else:
            return None
        if found is None:
            return None
    return found


def render(value, context: dict):
    """*value* with every `{{path}}` filled in from *context*, through lists and
    tables. A string that is one placeholder keeps the value's type."""
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value.strip())
        if whole:
            return lookup(context, whole.group(1))
        return _PLACEHOLDER.sub(lambda m: _text(lookup(context, m.group(1))), value)
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    return value


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def applies(step: dict, context: dict) -> bool:
    """Does the step's `only_if` hold? A step without one always applies."""
    condition = step.get("only_if")
    if not condition:
        return True
    found = lookup(context, str(condition["path"]))
    if "equals" in condition:
        return _text(found) == _text(condition["equals"])
    if "not_equals" in condition:
        return _text(found) != _text(condition["not_equals"])
    if "set" in condition:
        return (found not in (None, "", [], {})) == bool(condition["set"])
    if "empty" in condition:
        return (found in (None, "", [], {})) == bool(condition["empty"])
    return True


def _record_context(record: Record | dict) -> dict:
    data = record.to_dict() if isinstance(record, Record) else dict(record)
    return {
        "id": data.get("id"),
        "model": data.get("model"),
        "owner": data.get("owner"),
        "fields": dict(data.get("fields") or {}),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


# -- the runner ------------------------------------------------------------------------------------
class FlowRunner:
    """Starts runs when their triggers fire, and carries each through its steps."""

    def __init__(self, state: AppState) -> None:
        self.state = state
        self._queue: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self._local = threading.local()
        self._lock = threading.RLock()
        self._flows: list[Record] | None = None
        self._scheduled: dict[str, dt.datetime] = {}
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        state.records.on_change.append(self._on_change)

    # -- life ----------------------------------------------------------------------------------
    def start(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, name="flows", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)

    def drain(self, timeout: float = 30.0) -> None:
        """Wait until every queued change is matched and every run has gone as far
        as it can: tests, and a manual run."""
        if self._worker is None:
            while not self._queue.empty():
                item = self._queue.get()
                if item is not None:
                    self._handle(item)
            return
        deadline = time.monotonic() + timeout
        while (self._busy.is_set() or not self._queue.empty()) and time.monotonic() < deadline:
            time.sleep(0.02)

    def _work(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            try:
                self._handle(item)
            except Exception:
                log.exception("a flow run failed")
            finally:
                if self._queue.empty():
                    self._busy.clear()

    def _handle(self, item: tuple) -> None:
        """One thing off the queue: a change to match against the triggers, or a run to carry on."""
        if item[0] == "change":
            self._changed(*item[1:])
        else:
            self._run_safely(*item[1:])

    def _enqueue(self, owner: str, run_id: str, depth: int) -> None:
        self._busy.set()
        self._queue.put(("run", owner, run_id, depth))

    # -- the flows there are -----------------------------------------------------------------------
    def _principal(self, owner: str) -> Principal:
        return Principal(KIND, owner)

    def flows(self) -> list[Record]:
        """Every flow that is switched on, whoever made it."""
        with self._lock:
            if self._flows is not None:
                return list(self._flows)
            found: list[Record] = []
            for user in self.state.users.list():
                if not user.is_active:
                    continue
                try:
                    found.extend(self.state.records.list(self._principal(user.username), FLOW, {"on": True}))
                except Exception:  # their circles do not give them flows
                    continue
            self._flows = found
            return list(found)

    def forget(self) -> None:
        with self._lock:
            self._flows = None

    # -- triggers --------------------------------------------------------------------------------
    def _on_change(self, principal: Principal, action: str, record: Record, before: dict | None) -> None:
        """The record store's listener: quick, since the write waits on it. The
        matching is done on the runner's thread, with what the writer's thread
        knew — how deep in flows it was, and which flow it was running for."""
        if principal.kind == DATASET or record.model == RUN:
            return
        if record.model == FLOW:
            self.forget()
            return
        depth = getattr(self._local, "depth", 0)
        running = getattr(self._local, "flow", "")
        self._busy.set()
        self._queue.put(("change", action, record, before, depth, running))

    def _changed(self, action: str, record: Record, before: dict | None, depth: int, running: str) -> None:
        if record.model == APPROVAL and action == "changed":
            self._approval_changed(record, before, depth)
        after = record.fields
        changed = (
            sorted(k for k in set(after) | set(before or {}) if (before or {}).get(k) != after.get(k))
            if before is not None
            else sorted(after)
        )
        for flow in self.flows():
            trigger = flow.fields.get("trigger") or {}
            if trigger.get("kind") != "record" or not self._record_matches(trigger, action, record, changed):
                continue
            if flow.id == running:
                continue  # a flow's own writes do not start it again
            if depth >= DEPTH:
                log.info("flow %s not started: %d flows deep already", flow.fields.get("name"), DEPTH)
                continue
            if not self._sees(flow.owner, action, record):
                continue
            context = {
                "trigger": {
                    "kind": "record",
                    "action": action,
                    "record": _record_context(record),
                    "before": dict(before or {}),
                    "changed": changed,
                }
            }
            self._start(flow, context, depth=depth + 1)

    @staticmethod
    def _record_matches(trigger: dict, action: str, record: Record, changed: list[str]) -> bool:
        if trigger.get("model") != record.model:
            return False
        when = trigger.get("when", ["created"])
        when = [when] if isinstance(when, str) else when
        if action not in when:
            return False
        field = trigger.get("field")
        if field:
            if action == "changed" and field not in changed:
                return False
            if "value" in trigger and _text(record.fields.get(field)) != _text(trigger["value"]):
                return False
        return True

    def _sees(self, owner: str, action: str, record: Record) -> bool:
        """Would the flow's owner see the record that fired? Else it is not theirs to act on."""
        if record.owner == owner:
            return True
        if action == "deleted":
            return False
        try:
            self.state.records.get(self._principal(owner), record.model, record.id)
        except Exception:
            return False
        return True

    def on_action(
        self, username: str, quill: str, action: str, record: dict | None, fields: dict, effects: list
    ) -> None:
        """An action was pressed: the flows waiting for that one start, as whoever pressed it may see."""
        depth = getattr(self._local, "depth", 0)
        if depth >= DEPTH:
            return
        results: dict = {}
        for effect in effects:
            if effect.get("effect") == "result":
                results.update(effect.get("values") or {})
        for flow in self.flows():
            trigger = flow.fields.get("trigger") or {}
            if trigger.get("kind") != "action" or trigger.get("quill") != quill or trigger.get("action") != action:
                continue
            if flow.owner != username:
                # Somebody else's press: only when the owner may see what it was on.
                if not record or not self._sees(flow.owner, "changed", _as_record(record)):
                    continue
            context = {
                "trigger": {
                    "kind": "action",
                    "quill": quill,
                    "action": action,
                    "by": username,
                    "record": _record_context(record) if record else None,
                    "fields": dict(fields or {}),
                    "result": results,
                }
            }
            self._start(flow, context, depth=depth + 1)

    def run_due(self) -> list[str]:
        """On the clock: scheduled flows whose time has come, and runs whose wait is over."""
        started: list[str] = []
        now = dt.datetime.now(tz=dt.UTC)
        for flow in self.flows():
            trigger = flow.fields.get("trigger") or {}
            if trigger.get("kind") != "schedule":
                continue
            try:
                every = parse_duration(str(trigger.get("every", "")))
            except ValueError:
                continue
            last = self._scheduled.get(flow.id) or self._last_run(flow)
            if last is not None and now - last < every:
                continue
            self._scheduled[flow.id] = now
            self._start(flow, {"trigger": {"kind": "schedule", "at": now.isoformat(timespec="seconds")}})
            started.append(flow.id)
        for user in self.state.users.list():
            principal = self._principal(user.username)
            try:
                waiting = self.state.records.list(
                    principal, RUN, {"status": "waiting", "wake_at__lte": now.isoformat()}
                )
            except Exception:
                continue
            for run in waiting:
                if not run.fields.get("wake_at"):
                    continue
                self.state.records.update(
                    principal,
                    RUN,
                    run.id,
                    {"status": "running", "wake_at": None, "step": int(run.fields.get("step") or 0) + 1},
                )
                self._enqueue(user.username, run.id, 0)
                started.append(run.id)
        return started

    def _last_run(self, flow: Record) -> dt.datetime | None:
        try:
            runs = self.state.records.list(self._principal(flow.owner), RUN, {"flow": flow.id}, last=1)
        except Exception:
            return None
        for run in runs:
            try:
                return dt.datetime.fromisoformat(str(run.fields.get("started_at") or run.created_at))
            except ValueError:
                return None
        return None

    # -- starting and resuming -------------------------------------------------------------------
    def _start(self, flow: Record, context: dict, *, depth: int = 0) -> Record:
        principal = self._principal(flow.owner)
        context = {
            "owner": flow.owner,
            "flow": {"id": flow.id, "name": flow.fields.get("name")},
            "steps": {},
            **context,
        }
        run = self.state.records.create(
            principal,
            RUN,
            {
                "flow": flow.id,
                "name": f"{flow.fields.get('name', 'Flow')} · {_now()[:16].replace('T', ' ')}",
                "status": "running",
                "step": 0,
                "context": context,
                "started_at": _now(),
            },
        )
        self._enqueue(flow.owner, run.id, depth)
        return run

    def run_now(
        self, username: str, flow_id: str, *, model: str = "", record: str = "", timeout: float = 30.0
    ) -> Record:
        """Start a flow by hand, as its owner, and wait for it to go as far as it can."""
        principal = self._principal(username)
        flow = self.state.records.get(principal, FLOW, flow_id)
        context: dict = {"trigger": {"kind": "manual", "by": username, "record": None}}
        if model and record:
            found = self.state.records.get(principal, model, record)
            context["trigger"]["record"] = _record_context(found)
        run = self._start(flow, context)
        self.drain(timeout)
        return self.state.records.get(principal, RUN, run.id)

    def _approval_changed(self, approval: Record, before: dict | None, depth: int = 0) -> None:
        status = str(approval.fields.get("status") or "")
        run_id = str(approval.fields.get("flow_run") or "")
        if not run_id or status == "requested" or (before or {}).get("status") == status:
            return
        principal = self._principal(approval.owner)
        try:
            run = self.state.records.get(principal, RUN, run_id)
        except Exception:
            return
        if run.fields.get("status") != "waiting" or run.fields.get("waiting_on") != approval.id:
            return
        context = dict(run.fields.get("context") or {})
        answer = {
            "id": approval.id,
            "status": status,
            "note": approval.fields.get("note") or "",
            "by": approval.fields.get("answered_by") or "",
            "question": approval.fields.get("question") or "",
        }
        context["approval"] = answer
        steps = self._flow_steps(principal, run) or [{}]
        index = int(run.fields.get("step") or 0)
        if index < len(steps):
            context.setdefault("steps", {})[steps[index].get("id", f"step{index + 1}")] = answer
        self.state.records.update(
            principal, RUN, run.id, {"context": context, "status": "running", "waiting_on": "", "step": index + 1}
        )
        self._enqueue(approval.owner, run.id, depth)

    def _flow_steps(self, principal: Principal, run: Record) -> list[dict]:
        try:
            flow = self.state.records.get(principal, FLOW, str(run.fields.get("flow")))
        except Exception:
            return []
        return list(flow.fields.get("steps") or [])

    # -- the steps ---------------------------------------------------------------------------------
    def _run_safely(self, owner: str, run_id: str, depth: int) -> None:
        principal = self._principal(owner)
        try:
            run = self.state.records.get(principal, RUN, run_id)
        except Exception:
            return
        if run.fields.get("status") != "running":
            return
        self._local.depth, self._local.flow = depth, str(run.fields.get("flow"))
        try:
            self._execute(principal, run)
        except Exception as exc:
            log.exception("flow run %s failed", run_id)
            try:
                self.state.records.update(
                    principal, RUN, run_id, {"status": "failed", "error": _words(exc)[:2000], "finished_at": _now()}
                )
            except Exception:
                pass
        finally:
            self._local.depth, self._local.flow = 0, ""

    def _execute(self, principal: Principal, run: Record) -> None:
        steps = check_steps(self._flow_steps(principal, run))
        context = dict(run.fields.get("context") or {})
        context.setdefault("steps", {})
        index = int(run.fields.get("step") or 0)
        while index < len(steps):
            step = steps[index]
            context["now"] = _now()
            if not applies(step, context):
                index += 1
                continue
            outcome = self._step(principal, run, step, context)
            if outcome is not None:
                self.state.records.update(principal, RUN, run.id, {"step": index, "context": context, **outcome})
                return
            index += 1
        self.state.records.update(
            principal, RUN, run.id, {"step": index, "context": context, "status": "done", "finished_at": _now()}
        )

    def _step(self, principal: Principal, run: Record, step: dict, context: dict) -> dict | None:
        """One step. Returns nothing to go on, or the fields that put the run on hold."""
        kind = step["kind"]
        filled = render({k: v for k, v in step.items() if k not in ("id", "kind", "only_if")}, context)
        owner = principal.username
        if kind == "stop":
            return {"status": "stopped", "finished_at": _now()}
        if kind == "action":
            code = self.state.code
            if code is None:
                raise FlowError("this server runs no Quill code")
            from cloudmorrow.server.quills.code import CodeError

            try:
                effects = code.action(
                    owner,
                    str(filled["quill"]),
                    str(filled["action"]),
                    record=_text(filled.get("record") or ""),
                    fields={k: v for k, v in (filled.get("fields") or {}).items() if v not in (None, "")},
                    via="flow",
                )
            except CodeError as exc:
                raise FlowError(f"{step['id']}: {exc.message}") from exc
            values: dict = {}
            for effect in effects:
                if effect.get("effect") == "result":
                    values.update(effect.get("values") or {})
                elif effect.get("effect") == "error":
                    raise FlowError(f"{step['id']}: {effect.get('text')}")
            context["steps"][step["id"]] = values
            context["last"] = values
            return None
        if kind == "approval":
            approvals = self.state.approvals
            if approvals is None:
                raise FlowError("approvals are not set up on this server")
            about = context.get("trigger", {}).get("record") or {}
            about_id = _text(filled.get("about") or about.get("id") or "")
            about_model = _text(
                filled.get("about_model") or (about.get("model") if about_id == about.get("id") else "")
            )
            asked = approvals.ask(
                principal,
                role=_text(filled["role"]),
                question=_text(filled["question"]),
                about_model=about_model,
                about=about_id,
                about_title=_text(filled.get("about_title") or ""),
                circle=_text(filled.get("circle") or ""),
                due=_text(filled.get("due") or "") or None,
                flow_run=run.id,
            )
            context["approval"] = {"id": asked.id, "status": "requested", "question": asked.fields["question"]}
            return {"status": "waiting", "waiting_on": asked.id}
        if kind == "set":
            fields = {k: v for k, v in (filled.get("fields") or {}).items()}
            if not fields:
                raise FlowError(f"{step['id']}: a set step changes at least one field")
            changed = self.state.records.update(principal, _text(filled["model"]), _text(filled["record"]), fields)
            context["steps"][step["id"]] = _record_context(changed)
            return None
        if kind == "create":
            made = self.state.records.create(principal, _text(filled["model"]), dict(filled.get("fields") or {}))
            context["steps"][step["id"]] = _record_context(made)
            context["last"] = context["steps"][step["id"]]
            return None
        if kind == "notify":
            people: list[str] = []
            to = filled.get("to")
            if isinstance(to, list):
                people.extend(_text(t) for t in to)
            elif to:
                people.extend(p.strip() for p in _text(to).split(",") if p.strip())
            if filled.get("role") and self.state.roles is not None:
                people.extend(self.state.roles.people(_text(filled["role"]), _text(filled.get("circle") or "")))
            known = {u.username for u in self.state.users.list()}
            for who in dict.fromkeys(people):
                if who in known:
                    self.state.notifications.add(
                        who,
                        kind="flow",
                        title=_text(filled.get("title") or run.fields.get("name")),
                        body=_text(filled.get("body") or ""),
                    )
            return None
        if kind == "wait":
            if filled.get("for"):
                wake = dt.datetime.now(tz=dt.UTC) + parse_duration(_text(filled["for"]))
            else:
                wake = _moment(_text(filled.get("until") or ""))
                if wake is None:
                    raise FlowError(f"{step['id']}: until {filled.get('until')!r} is not a date or a time")
            if wake <= dt.datetime.now(tz=dt.UTC):
                return None
            return {"status": "waiting", "wake_at": wake.isoformat(timespec="seconds")}
        raise FlowError(f"{step['id']}: no such kind of step: {kind}")


def _words(exc: Exception) -> str:
    """Why a run failed, as a person reads it in the run's `error`."""
    if isinstance(exc, UnknownModelError):
        return f"no such datamodel: {exc}"
    if isinstance(exc, UnknownRecordError):
        return f"no such record: {exc}"
    if isinstance(exc, Refused):
        return f"refused: {exc}"
    if isinstance(exc, RecordConflictError):
        return "the record changed while the step ran"
    return str(exc) or type(exc).__name__


def _moment(text: str) -> dt.datetime | None:
    text = text.strip()
    if not text:
        return None
    try:
        found = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if found.tzinfo is None:
        found = found.replace(tzinfo=dt.UTC)
    return found


def _as_record(data: dict) -> Record:
    return Record(
        id=str(data.get("id", "")),
        model=str(data.get("model", "")),
        owner=str(data.get("owner", "")),
        scope=str(data.get("scope", "personal")),
        rev=data.get("rev", 1),
        position=int(data.get("position") or 0),
        fields=dict(data.get("fields") or {}),
        written_by=str(data.get("written_by", "")),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
    )


__all__ = [
    "FlowError",
    "FlowRunner",
    "STEP_KINDS",
    "TRIGGER_KINDS",
    "applies",
    "check_steps",
    "check_trigger",
    "render",
]
