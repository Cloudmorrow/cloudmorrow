# Roles, approvals and flows: how a procedure is said

A company has operating procedures: time off is asked for and the team lead
says yes; an expense over a limit goes past whoever is responsible for
expenses; a feature is approved by the product owner before it is built.
A household has them too, smaller. Cloudmorrow says these with three
things, each small, each useful alone:

1. **A role** names who is responsible — *Team lead*, *Expense
   Responsible* — without naming the person, so the procedure outlives
   whoever holds the hat this month.
2. **An approval** is a yes or a no asked of whoever holds a role, about a
   record. It is one datamodel, foundational, drawn once under *Waiting
   for you* on every surface, so no Quill builds its own.
3. **A flow** is a trigger and a list of steps a person builds on a screen:
   press a Quill's action, ask a role, change a record, tell somebody,
   wait. It runs as the person who made it, through the gate as them.

Beside those, one small addition to Quill code: an action may hand a
**result** back to whatever pressed it, so a flow can carry what one Quill
found out to the next.

## Roles

A role is a hat. It gives no access to any data — that is a circle's
business ([CIRCLES.md](CIRCLES.md)), and the two are kept apart on
purpose: *Team lead* says who answers for the team, `Sales = write` says
what the team may touch. A role answers one question, **who holds it**.

A role is held **everywhere**, or **within one circle**: Sales and
Warehouse each have a Team lead of their own, and the same role asked in
Sales is answered by the Sales one. Asked for a circle, a role answers
with the people who hold it there and the people who hold it everywhere.

Administrators make roles under *Administration → Roles*, and pick who
holds each. A Quill that expects a role declares it:

```toml
[[roles]]
id = "team_lead"
label = "Team lead"
why = "to approve or decline time off"
```

The role exists, empty, from the moment the Quill is installed, with the
Quill's words on what the holder is for; the install sheet lists it, and
the Roles side says *held by nobody* until an administrator fills it. A
role two Quills declare is one role. Deleting a declared role takes it
away until the Quills are next read, when it comes back empty.

In a Quill's code:

| | |
| --- | --- |
| `ctx.user.roles` | the roles the person the code runs for holds, by id |
| `ctx.people(role="team_lead")` | who holds it, as usernames |
| `ctx.people(role="team_lead", circle="Sales")` | who holds it in Sales, and everywhere |

On the command line: `cm role list`, `cm role add "Team lead"`, `cm role
give team_lead alice [--circle Sales]`, `cm role take`, `cm role delete`.
The API is `/api/roles` (everybody reads, administrators write),
`/api/roles/{id}/holders/{username}?circle=` to give and take, and
`/api/me/roles` for your own.

## Approvals

The `approval` datamodel (`server/core_datamodels/approval.toml`) is on
every server, whichever Quills are installed, like `flow` and `flow_run`
below. A record of it is:

| field | what |
| --- | --- |
| `question` | what is asked |
| `about_model`, `about`, `about_title` | which record it is about, and a line to show for it |
| `role`, `circle` | who is asked: the holders of the role, in the circle when one is named |
| `status` | `requested`, then `approved`, `declined`, or `withdrawn` by the asker |
| `asked_by`, `answered_by`, `answered_at`, `note` | who, when, and a word with the answer |
| `due` | optional |
| `flow_run` | the flow run waiting on it, when a flow asked |

**Who sees it.** The asker's record, as any personal record is — and the
holders of the role see it too, and may answer it. That is a rule of the
datamodel, `seen_by_role = { role = "role", circle = "circle" }`, which
the record store applies in `_visible` and in every listing: a record of
such a datamodel is seen by its owner and by whoever holds the role its
`role` field names, within the circle its `circle` field names if it does.
Nothing else widens; the circles still have to give `approval` to the
people who answer.

**Asking.** From a Quill's code:

```python
asked = ctx.approvals.ask(leave, role="team_lead", question=f"Approve {what}?")
```

Asking needs nothing declared: the question is the core's, not the Quill's
data. Reading approvals back — the hook below — needs `approval` in
`[uses]`. From a flow, an `approval` step. From a person, `POST
/api/approvals` or a *Ask for approval* button later.

**Answering.** Whoever holds the role finds it under *Me → Waiting for
you* on the phone and the web app, as `cm approvals` on the command line,
and answers with *Approve* or *Decline* and a note. The asker sees it
under *Asked by you* until then and may withdraw it. A line goes behind
the bell both ways: the holders hear the question, the asker hears the
answer. `POST /api/approvals/{id}/answer` with `{"status": "approved",
"note": "…"}` is what every surface sends; an approval is answered once.

**Hearing the answer.** It is a change to a record, so a Quill hears it as
any other:

```toml
[[hooks]]
on = "approval"
when = "changed"
fields = ["status"]
handler = "answered"
```

```python
@hook
def answered(ctx, change):
    approval = change.record
    if approval["about_model"] == "leave" and approval["status"] in ("approved", "declined"):
        ctx.records.patch("leave", approval["about"], {"status": approval["status"]})
```

A hook usually runs as whoever made the change. For a record seen through
a role — an approval — it runs as the record's **owner**, the asker: the
answer is news to them, and the Quill acts on their own records with it,
so the guest's personal leave gets its status although the team lead who
answered could never see it. A stranger could not have answered at all.

## The result effect

An action returns effects — `toast`, `open`, `go` — for the screen that
pressed it. One more, `result(**values)`, is for whatever pressed it that
is not a screen:

```python
@action
def request(ctx, employment, what, starts, ends):
    leave = ctx.records.create("leave", employment=employment, what=what, starts=starts, ends=ends)
    asked = ctx.approvals.ask(leave, role="team_lead", question=f"Approve {what}?")
    return [toast(f"Asked about {what}"), result(leave=leave.id, approval=asked.id)]
```

A screen does nothing with it. A flow that pressed the action puts the
values under `steps.<step id>` for the steps after it, and an action
trigger puts them under `trigger.result`. The values are JSON; a record
becomes its id.

## Flows

A flow is a `flow` record a person builds under *Me → Flows*: a name, one
**trigger**, and a list of **steps**. It is nobody's Quill and has no code.
It runs as the person who made it — `Principal("flow", owner)` through the
same gate, over the data their circles give — so a flow can do no more
than its owner could by hand, and everything it writes says `flow` wrote
it. Each run is a `flow_run` record: which step it is at, what it has
gathered, how it ended, listed under the flow.

### Triggers

```json
{"kind": "record", "model": "leave", "when": "created"}
{"kind": "record", "model": "leave", "when": "changed", "field": "status", "value": "approved"}
{"kind": "action", "quill": "tasks", "action": "duplicate"}
{"kind": "schedule", "every": "1d"}
{"kind": "manual"}
```

A record trigger fires on a record the owner may see; a flow's own writes
never fire it again, and chains of flows stop three deep, as hooks do. An
action trigger fires when the action is pressed by anybody, on a record
the owner may see. A schedule fires on the server's clock, every so often
from the last run. A manual flow runs from its *Run it now* button, `cm
flow run`, or `POST /api/flows/{id}/run`.

### Steps

Each step has an `id` (letters and digits, its own in the flow), a `kind`,
and may have `only_if`:

| kind | fields | does |
| --- | --- | --- |
| `action` | `quill`, `action`, `record` (for an action on a record), `fields` | presses the action as the owner; its `result` lands under `steps.<id>` |
| `approval` | `role`, `question`, optional `circle`, `about`, `due` | asks, and the run waits; the answer lands under `approval` and `steps.<id>` |
| `set` | `model`, `record`, `fields` | changes a record |
| `create` | `model`, `fields` | makes a record; it lands under `steps.<id>` |
| `notify` | `to` (usernames) or `role`, `title`, `body` | a line behind their bell |
| `wait` | `for` (`1d`, `2h`) or `until` (a moment) | the run sleeps; the clock wakes it |
| `stop` | | ends the run |

`only_if` is `{"path": "approval.status", "equals": "approved"}` or
`not_equals`: the step runs only when what the run has gathered says so,
and is skipped otherwise. A linear list of steps, each with its
condition, is how a flow branches; most procedures need no more.

Every string in a step may hold `{{a.path}}` into the run's **context**:

| path | what |
| --- | --- |
| `trigger.record.id`, `.owner`, `.fields.<name>` | the record that fired, for record, action and manual triggers |
| `trigger.action`, `trigger.by`, `trigger.fields`, `trigger.result` | an action trigger: what was pressed, by whom, with what, and its result |
| `approval.status`, `.note`, `.by`, `.question` | the answer to the last approval step |
| `steps.<id>.<key>` | an action's result, or the record a `set` or `create` step wrote (`.id`, `.fields.<name>`) |
| `owner`, `now`, `flow.name` | the flow's owner, the time, the flow |

A string that is one placeholder keeps the value's type, so `"record":
"{{trigger.record.id}}"` is the id and `"fields": {"on": "{{approval.status}}"}`
is text.

### The first customer

Leave requests, with the Leave Quill the tests install
(`tests/fixtures/quill-leave`) — or with no Quill at all:

```json
{
  "name": "Leave requests",
  "trigger": {"kind": "record", "model": "leave", "when": "created"},
  "steps": [
    {"id": "ask", "kind": "approval", "role": "team_lead",
     "question": "Approve {{trigger.record.fields.what}}?"},
    {"id": "yes", "kind": "set", "model": "leave", "record": "{{trigger.record.id}}",
     "fields": {"status": "approved"}, "only_if": {"path": "approval.status", "equals": "approved"}},
    {"id": "no", "kind": "set", "model": "leave", "record": "{{trigger.record.id}}",
     "fields": {"status": "declined"}, "only_if": {"path": "approval.status", "equals": "declined"}},
    {"id": "tell", "kind": "notify", "to": "{{trigger.record.owner}}",
     "title": "Your leave was {{approval.status}}", "body": "{{approval.note}}"}
  ]
}
```

### Where it runs

`server/flows.py`. The runner listens on the record store's `on_change`
as the hook runner does, matches triggers, and starts runs on a thread of
its own, so a write never waits on anybody's flow. An `approval` step
leaves the run `waiting` with `waiting_on` the approval's id; when the
approval's `status` changes, the runner picks the run up at the next
step. A `wait` step leaves it `waiting` with `wake_at`; the clock
(`quills/jobs.py`, every half minute) wakes it. A step that fails leaves
the run `failed` with the words in `error`.

## The API, in short

| call | what it does |
| --- | --- |
| `GET /api/roles`, `GET /api/roles/{id}` | every role with who holds it; one |
| `POST /api/roles`, `PATCH /api/roles/{id}`, `DELETE /api/roles/{id}` | make, change, delete (administrators) |
| `PUT`/`DELETE /api/roles/{id}/holders/{username}?circle=` | give and take (administrators) |
| `GET /api/me/roles` | your own |
| `GET /api/approvals` | `{"waiting": […], "asked": […]}` for you; `/count` for the badge |
| `POST /api/approvals` | ask a role yourself |
| `POST /api/approvals/{id}/answer` | `{"status": "approved" / "declined" / "withdrawn", "note": "…"}` |
| `GET /api/flows/kinds`, `POST /api/flows/check` | the vocabulary; is this flow one the runner can run |
| `POST /api/flows/{id}/run` | start one of yours now, on a record if `{"model", "record"}` is given |
| `/api/records/flow`, `/api/records/flow_run` | the flows and their runs: the record API |

## Not yet

- **Fields the answerer may change.** A holder may change any field of an
  approval today; the answer route is what every surface sends, and the
  gate narrows no further.
- **A canvas.** The editor is a list of steps with conditions. A graph of
  branches is a later screen over the same records.
- **The terminal app.** Roles, *Waiting for you* and flows are on the
  phone, the web app and the command line; the terminal app's sections
  are next.
- **Asking from a record's sheet.** `POST /api/approvals` exists; the
  button on every record's sheet does not yet.
