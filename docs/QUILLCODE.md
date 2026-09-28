# Quill code: everything a Quill does, in the Quill

A Quill is TOML and Python. `quill.toml` declares everything it is and does
— its data, its screens, what can be done in it, and when its code runs —
and `quill.py` holds the code: its views, actions, hooks, jobs, webhooks,
APIs and machine handlers. The code runs inside the server in a sandbox,
through the same gate as everybody, and the Quill is still one description
for the phone, the web app, the terminal, the command line and an
assistant.

This page is the contract for a Quill's code. [QUILLS.md](QUILLS.md) is the
contract for the rest — datamodels, the kit, the catalog — and where the two
meet, both say the same.

## The words

| word | what it is |
| --- | --- |
| **Quill code** | `quill.py` (or a `quill/` package), named by `[quill] code`: Python functions the manifest names. |
| **SDK** | `cloudmorrow.quill`, in the `cloudmorrow` package: the decorators, `ui`, the effects, and the test harness. Quill code imports nothing else of Cloudmorrow's. |
| **Handler** | A function the core calls: a view, an action, a hook, a job, a webhook, an API, a machine handler. |
| **View** | A handler that returns a screen, as a tree of primitives. |
| **Primitive** | One of the fixed building blocks a view is made of — `stack`, `table`, `button` — drawn by every surface. |
| **Action** | Something a person can do, with a form, that runs a handler: a button everywhere, a `cm` command, an assistant's tool. |
| **Effect** | What a handler asks the surface to do after it ran: a toast, open a record, go to a screen, confirm, show an error. |
| **Sandbox** | CPython compiled to WebAssembly, run by wasmtime, that Quill code runs in. Nobody writing a Quill sees it. |

## The rules

Rules 1 and 4 of [QUILLS.md](QUILLS.md) read, with code:

1. **A Quill never ships per-surface UI.** Its screens are kit elements, or
   views that return primitives, which every surface draws its own way.
   There is no HTML, CSS, JavaScript or Textual in a Quill. When the
   primitives cannot say something, the primitives grow, for every surface.
4. **Declarative first, then Python.** A Quill with no code is still the
   normal case. Code is for what cannot be declared, and runs in the
   sandbox, inside the gate. A `[[services]]` program, outside the sandbox,
   is the last resort.

And one more:

7. **The manifest says everything the code may do.** Every action, view,
   hook, job, webhook, API and machine handler is declared in `quill.toml`
   with the handler that implements it, and so is every host it may fetch
   from and every secret it may read. Every button in a view runs a declared
   action or goes to a declared screen. The install sheet, `cm quill check`
   and the catalog read the manifest, and the handlers' names from the
   source, and never run the code to find out what a Quill is.

## A Quill with code

```
quill-fleet/
  quill.toml          what it is, what it uses, what it shows and does
  quill.py            the handlers; a quill/ package when it grows
  datamodels/         datamodels it introduces
  datasets/           records it comes with
  tests/              pytest, against the harness
  pyproject.toml      for development only: `uv sync` gets Cloudmorrow and pytest
  README.md           the catalog page
  CLAUDE.md           how an assistant works on it
  .claude/skills/     skills for the assistant: screens, actions, data, automation, machine, testing, publishing
  .github/workflows/  check and test on every push; a release on a tag
```

The manifest (the fixture `tests/fixtures/quill-fleet` has one of each):

```toml
[quill]
id = "fleet"
name = "Fleet"
version = "0.3.0"
code = "quill.py"                     # the module, or package, the handlers are in
sdk = "1"                             # the SDK's major version; "1" when left out

[uses]
datamodels = ["vehicle"]

[[extends]]
model = "vehicle"
[extends.fields]
odometer = { kind = "int", indexed = true }

[[screens]]
id = "garage"
label = "Garage"
view = "garage"                       # a view in quill.py, instead of kit = …
model = "vehicle"                     # what it is about: circles fit it by this

[[actions]]
id = "log-service"
label = "Log a service"
on = "vehicle"                        # done to one vehicle, wherever one is drawn
handler = "log_service"               # the id with _ for -, when left out
confirm = "Log it?"                   # optional: asked first
tone = "primary"                      # neutral, primary, danger
assistant = true                      # false: not an assistant's tool
[actions.fields]
date = { kind = "date", required = true }
km   = { kind = "int", required = true }

[[hooks]]
on = "fleet.visit"
when = "created"                      # created, changed, deleted, or a list of them
fields = ["km"]                       # optional: for changed, only when one of these did
handler = "visit_logged"

[[jobs]]
id = "reminders"
action = "call"                       # call a handler, every `every`
handler = "remind"
every = "1d"

[[webhooks]]
id = "tracker"
handler = "tracker_ping"              # or model + map, or forward to a service

[[apis]]
id = "summary"
handler = "summary"                   # or service = …

[[fetch]]
host = "api.example-tracker.com"      # or *.example.com; the only hosts its code reaches
why = "to read each van's odometer from the tracker"

[[secrets]]
key = "TRACKER_KEY"                   # a secret its code may read from the person's vault
why = "to sign in to the tracker"

[[machine]]
id = "import-exports"
why = "to read the tracker's CSV exports into your vans"
every = "15m"
[machine.needs]
folders = [{ name = "exports", access = "read" }]
run = []                              # programs it may start there
```

And `quill.py`:

```python
from cloudmorrow.quill import action, hook, job, machine, ui, view, toast


@view("garage")
def garage(ctx):
    vans = ctx.records.list("vehicle")
    return ui.stack(
        ui.row(ui.stat("Vans", len(vans))),
        ui.table(vans, columns=["name", ("Odometer", "fleet.odometer")], actions=["log-service"]),
        ui.button("Add a van", action="add-van", tone="primary"),
    )


@action("log_service")
def log_service(ctx, vehicle, date, km):
    ctx.records.create("fleet.visit", vehicle=vehicle.id, date=date, km=km)
    return toast(f"Logged {vehicle['name']} at {km} km")


@hook
def visit_logged(ctx, change):
    van = ctx.records.get("vehicle", change.record["vehicle"])
    ctx.records.patch("vehicle", van.id, {"fleet.odometer": change.record["km"]})
```

A decorator registers a function under a name — its own, or the one it is
given — and returns it unchanged. What the handler *is* is in the manifest.
`cm quill check` reads the decorators from the source, without running it,
and fails a manifest that names a handler the code does not have.

### Who it acts as, and what it gets

| handler | called with | acts as | returns |
| --- | --- | --- | --- |
| view | `ctx` (`ctx.params`, `.record` when opened on one) | the person looking | a tree of primitives |
| action | `ctx`, the record (for `on`), the form's fields as keywords | the person pressing | effects |
| hook | `ctx`, `change` (`.action`, `.record`, `.before`, `.changed`) | whoever made the change | nothing |
| job (`call`) | `ctx` | the administrator who installed it | nothing |
| webhook | `ctx`, `request` (`.json()`, `.text`, `.headers`, `.query`) | the administrator who installed it | `respond(...)`, a dict (JSON), or nothing (204) |
| API | `ctx`, `request` (… and `.user`, who asked) | the administrator who installed it | the same |
| machine | `ctx` | the machine's owner, on their machine | anything JSON |

Every principal is `Principal("quill", <them>, quill=<id>, models=<declared>)`:
the gate refuses a datamodel the Quill did not declare, and the person's
circles narrow what is left. A child pressing a button in a family Quill
can do no more with it than by hand. When an assistant is the one pressing
(an action as an MCP tool), the code is an assistant's too: the datamodels
no assistant may reach are out of its reach, and it is given no secret. A
hook started by an assistant's change is the same.

`ctx`:

| | what |
| --- | --- |
| `ctx.user` | who it runs for: `.username`, `.name`, `.admin`, `.circles` |
| `ctx.quill`, `ctx.where` | this Quill's id; `"server"` or `"machine"` |
| `ctx.params` | a view's parameters, by name and as attributes; `.record` when opened on one |
| `ctx.records` | `list(model, q=, last=, **where)`, `get`, `create(model, fields=None, **values)`, `patch(model, id, fields, rev=)`, `move(model, id, fields, index=)`, `delete` — the record API, through the gate |
| `ctx.fetch(url, method=, headers=, json=, body=)` | https to a host in `[[fetch]]`, and there only after a redirect too; a `Response` (`.status`, `.ok`, `.json()`, `.text`) |
| `ctx.secret(key)` | a key in `[[secrets]]`, from the person's own vault |
| `ctx.now()`, `ctx.log(...)` | the time; a line in the Quill's log |
| `ctx.folder(name)`, `ctx.run([...])` | on a machine: a folder the person picked; a program the manifest lists and the machine allows |

A refusal arrives as an exception: `Refused`, `NotFound`, `Invalid`,
`Conflict`. A record is a `Record`: its fields by name (`van["name"]`,
`van.get("fleet.odometer")`) and its envelope as attributes (`van.id`,
`van.rev`). `print` goes to the Quill's log.

### Actions, on every surface

One declaration, drawn everywhere by the core:

| surface | an action is |
| --- | --- |
| phone and web app | a button on the record's sheet (for `on`) or on the Quill's screens; its form as a sheet |
| terminal | the same, in the record modal and the Quill's pane |
| command line | `cm fleet log-service <vehicle> date=2026-09-28 km=1200`; `cm fleet actions` lists them |
| assistant | an MCP tool, `fleet_log_service`, with the form as its schema and the record's id |
| a view | `ui.button(…, action="log-service")`, `ui.form("log-service")`, `ui.table(…, actions=[…])` |

The form is checked before the code runs — required fields, kinds, enum
values, links to records the person can see — and an action `on` a
datamodel is only ever given a record the person can see. `on` may name
another Quill's datamodel the Quill uses or was granted: that is how one
Quill adds a button to another's records.

`POST /api/quills/<quill>/actions/<action>` with `{record, fields}` answers
`{effects: [...]}`; a refusal is 400 (invalid), 403 (refused) or 404, with
`{kind, message}`.

### Views and primitives

`GET /api/quills/<quill>/views/<screen>?record=…&<params>` answers `{tree}`.
The primitives are `cloudmorrow.quill.ui`, and every surface draws every
one:

| primitive | what it is |
| --- | --- |
| `stack`, `row`, `columns`, `tabs` | layout; columns stack on a phone, rows wrap |
| `text(style=)`, `markdown`, `image`, `badge`, `stat`, `empty`, `divider` | content |
| `field(record, name, edit=)` | one field of a record, with its kind's widget; editable saves as it changes |
| `form(action, values=, record=)` | an action's form, drawn in place |
| `button(label, action= \| open= \| go=)`, `menu` | run an action, open a record, go to a screen |
| `table(records, columns=, actions=)`, `cards(records, title=, …)` | records, a row or a card each; opening one shows its sheet |
| `lanes(records, field=, title=)` | records in columns by an enum; dragging moves the record, as a board does |
| `month(records, date=, title=)` | records on a month |

There is no event handler of a view's own: everything that can be pressed
runs a declared action, opens a record, or goes to a declared screen, and
the core checks every tree against the manifest before a surface sees it
(`ui.check`). A view is drawn again after every action pressed on it.

The kit's screens (`kit = "board"` and the rest) stay as they are. Once
the primitives can draw one as well as the kit does, it may become a view
written with them, and move out of the core into the Quill that uses it.

### Effects

| effect | does |
| --- | --- |
| `toast("…")` | a line that goes away |
| `open(record)` | the record's sheet |
| `go(screen, **params)` | another screen of this Quill |
| `confirm("…", then=action, **fields)` | ask first, then run another action with those fields |
| `error("…")` | the form stays open with the message |
| nothing, `redraw()` | the screen is drawn again |

## The sandbox

A Quill's code runs in CPython's own WASI build (3.14, pinned by hash in
`cloudmorrow/sandbox.py`) under [wasmtime](https://wasmtime.dev), a wheel
from PyPI that runs on a Raspberry Pi. The runtime is about 14 MB, fetched
once and checked against its hash; the compiled module is kept beside it,
so a sandbox starts in a tenth of a second.

Each Quill gets one interpreter, in a process of its own (`python -m
cloudmorrow.sandbox`), started on its first call and kept warm; it is
stopped when the Quill is reinstalled, switched off or removed, and after
ten idle minutes. It sees the standard library at `/lib`, the SDK at `/sdk`
and the Quill at `/quill`, all read-only — and on a machine, the folders the
person picked at `/folders/<name>`. It has no sockets, no processes and
none of the host's environment, and at most 256 MB. A call has fifteen
seconds (a job two minutes, a machine handler five); one that runs past its
time is stopped with its process, and the next call starts a fresh one.

The host and the interpreter speak JSON lines over its standard input and
output (`cloudmorrow.quill.guest`): the core sends a call, and every
`ctx.records`, `ctx.fetch` and `ctx.secret` is a request back, which the
core answers through the gate (`server/quillhandlers.py`, `HostCalls`).
What the handler prints is caught and logged.

Hooks are queued as records change and run one at a time on a thread of
their own, so a write never waits for somebody's code. A Quill's hooks are
not told what its own hooks wrote, and a chain of hooks across Quills stops
three deep.

What the sandbox cannot do that a service can: hold a connection open, run
all the time, use a package with C in it. `[[services]]` stays for those, as
it is, outside the sandbox and trusted like it is now. On a server whose
config says `quill_code = "trusted"` the code runs in the server's own
interpreter instead; that is for tests and nothing else.

## Code on a person's own machine

A `[[machine]]` handler runs in the Cloudmorrow agent on somebody's own
computer, in the same sandbox. Nothing runs there because a server says so:

1. The person switches it on, on that machine, and picks the folders it may
   see: `cm quill machine enable fleet import-exports --folder exports=~/Tracker`.
   They are shown what it wants (its `why`, its folders, the programs it
   would start) and asked. It is written into that machine's `agent.toml`;
   `allow_quill_code = false` there says no to all of it.
2. The agent fetches the installed copy of the Quill from the server
   (`GET /api/agent/quills/<id>/code`), runs the handler on its `every`, or
   when asked (an agent job of type `quill`, or `cm quill machine run`).
3. What the code asks for besides its folders goes to the server with the
   agent's token (`POST /api/agent/quills/<id>/host`), and is answered as the
   machine's owner, through the gate, bound by the manifest.
4. `ctx.run` starts a program only when it is in the handler's `needs.run`
   and in the machine's own `quill_programs`. It is the one thing outside
   the sandbox, and the switching-on says so.

## Testing a Quill locally

Three steps, from fastest to most real. None needs an account anywhere.

**1. Tests, with the harness.** `cloudmorrow.quill.testing.Harness` is a
server with nobody else on it, in a temporary folder: the Quill installed
the way a server installs it, the foundational datamodels it uses (fetched
once and cached, or `CLOUDMORROW_DATAMODELS`), the real record store, gate
and circles, and its code, in this interpreter — a Python traceback, and a
debugger that stops in it.

```python
from cloudmorrow.quill.testing import Harness


def test_logging_a_service_moves_the_odometer():
    q = Harness(".", circles={"Kids": {"vehicle": "read"}})
    van = q.seed("vehicle", name="Van", **{"fleet.odometer": 1000})
    done = q.act("log-service", van, date="2026-09-28", km=1200)
    assert done.toast == "Logged Van at 1200 km"
    assert q.get("vehicle", van.id)["fleet.odometer"] == 1200
    assert q.as_user("sam", circles=["Kids"]).act("log-service", van, date="2026-09-28", km=1).refused
    assert "Van" in q.view("garage").text()
```

`q.seed`, `get`, `list`, `change`, `delete` (as the person; hooks run),
`q.act` (→ `.ok`, `.toast`, `.error`, `.refused`, `.opened`, `.effects`),
`q.view` (→ `.text()`, `.find(kind)`, `.buttons`, `.tree`), `q.as_user`,
`q.secret`, `q.fetch.add(url, json=)` (nothing else reaches the network),
`q.run_job`, `q.webhook`, `q.api`, `q.machine(id, folders=)`, `q.log`. Code
that raises fails the test with `HandlerFailed` and the Quill's own traceback.

**2. `cm quill test`.** `check`, then pytest in the Quill's `.venv` (`uv
sync` makes it). `cm quill test --sandbox` runs the same tests with every
handler inside the sandbox, the way the server will — the step that catches
an import the sandbox does not have.

**3. `cm quill dev --local`.** A throwaway server on this machine: a
temporary folder, the Quill installed from the folder and reinstalled when
a file changes, and two people to sign in as — you, an administrator, and
sam, in a circle that may read everything and change nothing. It prints the
address for the browser (and the phone on the same Wi-Fi) and the
`CLOUDMORROW_CONFIG_DIR` for a `cm` signed in to it. Without `--local`, `cm
quill dev` installs on your own server as it does now.

And between them, `cm quill preview garage [--as sam]`: a view drawn as
text, from a server with nothing on it but the Quill and its datasets.

## Publishing

1. **Start** from `Cloudmorrow/quill-template` with GitHub's *Use this
   template* (not a fork: a fork stays tied to the template, cannot be
   private, and sends pull requests to us), or `cm quill new fleet`.
2. **Build** it, with `cm quill test` and `cm quill test --sandbox` passing.
3. **Release** with a tag (`v1.2.0`, the same as `version`). The template's
   release workflow checks, tests in the sandbox, and publishes the release.
4. **Submit** it: a pull request on `Cloudmorrow/quill-catalog` adding its
   `repo`, `ref` and `category`. cloudmorrow.com/publish lists it on the
   site meanwhile; opening the pull request from there is still to come.

Ours go the same way. Every standard Quill is a `quill-*` repository in the
same shape as the template, released and added by the same kind of pull
request; the only thing ours have that nobody else's do is `foundation =
true` in the catalog.

A repository made from a template does not get the template's later
changes, so the template holds as little as it can: the SDK is a dependency
(`cloudmorrow` in `pyproject.toml`, `sdk = "1"` in the manifest), and an
update to a Quill is a version bump, not a merge.

## Building one with an assistant

`CLAUDE.md` says: declare first, then Python, a test for it, and `cm quill
check`, `test`, `test --sandbox` until they pass. The skills in
`.claude/skills/` go deeper, one each: **quill-screens** (kit screen or view,
and the primitives), **quill-actions** (forms and effects), **quill-data**
(use, extend, introduce), **quill-automation** (hooks, jobs, webhooks, APIs,
fetch, secrets), **quill-machine**, **quill-testing** and **quill-publish**.
An assistant writes the TOML, the Python and the tests; nothing it touches is
WebAssembly.

## What it costs, honestly

- **A round trip per click.** On loopback and a home network that is
  nothing; over the relay it is noticeable. Nothing a view draws works
  offline.
- **An interpreter per busy Quill.** CPython in WebAssembly takes tens of
  megabytes; on a Pi with many Quills, idle ones are stopped and started
  again, which costs a moment on the first click.
- **The standard library only,** and pure Python: see *Open*.
- **The primitives are a ceiling,** as the kit was, and each new one is
  drawn on every surface. It is the same pressure, one level lower.
- **One sandbox, one call at a time, per Quill.** Enough for a household;
  a pool per Quill when it is not.

## Open

- **Packages.** Pure-Python dependencies from PyPI, listed in the manifest
  and vendored into the release by the template's workflow, so the server
  never runs pip.
- **Per-person code.** A job, webhook or API runs as the installer; a job
  per person is the same *next* as services.
- **Services in the sandbox.** A handler that is allowed to loop, with
  `ctx.fetch` as its only way out, would take most services inside the gate.
- **A server asking a machine.** A server handler queueing a machine
  handler (`ctx.machines.run`) — today that is an agent job of type `quill`,
  queued by a person.
- **Other languages.** A JavaScript template, on QuickJS, behind the same
  JSON lines. Only after Python is right.

## Where the code is

| part | where |
| --- | --- |
| the SDK: decorators, `ctx`, effects, primitives, dispatch, the sandbox's side | `quill/__init__.py`, `registry.py`, `context.py`, `effects.py`, `ui.py`, `dispatch.py`, `guest.py` |
| a view as text | `quill/text.py` |
| the harness, and what `preview` and `dev --local` run | `quill/testing.py`, `quill/devtools.py` |
| the sandbox: the runtime, a warm interpreter per Quill, the process | `sandbox.py` |
| the manifest's code half, and finding handlers in the source | `server/codespec.py` |
| running handlers: principals, `HostCalls`, hooks, `call` jobs, webhooks, APIs | `server/quillhandlers.py` |
| the routes: views and actions; webhooks and APIs answered by code | `server/routes/quills.py`, `server/routes/quillcode.py` |
| a machine's side of it, on the server and in the agent | `server/routes/agentquills.py`, `agent/quills.py`, `cm quill machine` in `cli/quill.py` |
| actions as MCP tools | `server/mcptools.py` (`action_tools`) |
| actions and views on the command line | `cli/quillrun.py` (`dispatch`, `_press`, `_view`) |
| views and actions in the web app | `server/web/kit_view.js` + `kit_view.css` (the primitives), `actions.js` + `actions.css` (forms, effects, the sheet's actions, the action bar), `kit.js` |
| views and actions in the terminal | `tui/panes/kit_view.py` + `tui/kit_view.tcss` (the primitives), `tui/quill_actions.py` (forms, effects, the ctrl+e palette), `tui/screens/record_sheet.py` |
| the template, and its skills | `quill_template/`, `quill_template/claude/skills/` |
