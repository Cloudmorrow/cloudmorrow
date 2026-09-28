# Quill code: everything a Quill does, in the Quill

> **Proposal.** Nothing on this page is built yet. Where it and
> [QUILLS.md](QUILLS.md) differ, QUILLS.md is what runs today and this page
> is where it is going.

A Quill today is a manifest. Its screens are drawn by kit code in the core
(`web/kit*.js`, `tui/panes/kit*.py`), what a click does is whatever the kit
does, and the only code a Quill can carry is a `[[services]]` process that
cannot touch a screen and is not sandboxed. So a Quill can say what data it
has and which kit screen shows it, but not what happens when somebody presses
a button.

This page puts the rest in the Quill: its screens, its buttons and what they
do, what happens when a record changes, its jobs, webhooks and APIs. It is
written in **Python and TOML**, it runs inside the server in a sandbox, and
it is still one description for the phone, the web app, the terminal, the
command line and an assistant.

## The words

| word | what it is |
| --- | --- |
| **Quill code** | `quill.py` (or a `quill/` package): Python functions the manifest names. |
| **SDK** | `cloudmorrow.quill`, in the `cloudmorrow` package: the decorators, `ui`, the effects, and the test harness. Quill code imports nothing else from Cloudmorrow. |
| **Handler** | A function the core calls: a view, an action, a hook, a job, a webhook, an API. |
| **View** | A handler that returns a screen, as a tree of primitives. |
| **Action** | Something a person can do to a record or on a screen, with a form of its own, that runs a handler. |
| **Primitive** | One of the fixed building blocks a view is made of — `stack`, `table`, `button` — drawn by every surface. |
| **Effect** | What a handler asks the surface to do after it ran: a toast, open a record, go to a screen, redraw. |
| **Sandbox** | The Python interpreter, compiled to WebAssembly, that Quill code runs in. Authors never see it. |

## The rules, as they change

Rules 1 and 4 of [QUILLS.md](QUILLS.md) change; the rest stand.

1. **A Quill never ships per-surface UI.** Its views return primitives, and
   every surface draws the same tree its own way. There is still no HTML, no
   JavaScript and no Textual in a Quill. When the primitives cannot say
   something, the primitives grow, and every surface grows with them.
4. **Declarative first, then Python.** A Quill with no code is still the
   normal case, and a `kit = "board"` screen is still a line of TOML. Code is
   for what cannot be declared, and it runs in the sandbox, inside the gate.

And one more:

7. **The manifest says everything the code may do.** Every action, view,
   hook, job, webhook and API is declared in `quill.toml` with the handler
   that implements it. The install sheet, `cm quill check` and the catalog
   read the manifest and never run the code to find out what a Quill is.

## A Quill with code

```
quill-fleet/
  quill.toml          what it is, what it uses, what it shows and does
  quill.py            the handlers; a quill/ package when it grows
  datamodels/         datamodels it introduces
  datasets/           records it comes with
  tests/              pytest, against the harness
  pyproject.toml      for development only: cloudmorrow (the SDK) and pytest
  README.md           the catalog page
  CLAUDE.md           how an assistant works on it
  .github/workflows/  check and test on every push; a release on a tag
```

The manifest names the handlers:

```toml
[quill]
id = "fleet"
name = "Fleet"
version = "0.3.0"
sdk = "1"                             # the SDK's major version it is written for
code = "quill.py"                     # or "quill" for a package

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
on = "vehicle"                        # on every vehicle, wherever one is drawn
handler = "log_service"
[actions.fields]
date = { kind = "date", required = true }
km   = { kind = "int", required = true }

[[hooks]]
on = "vehicle"
when = "changed"                      # created, changed, deleted
fields = ["fleet.odometer"]           # only when one of these changed
handler = "service_due"

[[jobs]]
id = "reminders"
action = "call"                       # call a handler, every `every`
handler = "remind"
every = "1d"

[[webhooks]]
id = "tracker"
handler = "tracker_ping"

[[fetch]]
host = "api.example-tracker.com"      # the only host its code may reach
why = "to read each van's odometer from the tracker"
```

And the code implements them:

```python
from cloudmorrow.quill import action, hook, job, view, webhook, ui, toast


@view("garage")
def garage(ctx):
    vans = ctx.records.list("vehicle")
    return ui.stack(
        ui.stat("Vehicles", len(vans)),
        ui.table(vans, columns=["name", "fleet.odometer"], open=True),
        ui.button("Log a service", action="log-service"),
    )


@action("log_service")
def log_service(ctx, vehicle, date, km):
    ctx.records.create("fleet.service_visit", vehicle=vehicle.id, date=date, km=km)
    ctx.records.patch("vehicle", vehicle.id, {"fleet.odometer": km})
    return toast(f"Logged at {km} km")


@hook("service_due")
def service_due(ctx, change):
    ...


@job("remind")
def remind(ctx):
    ...


@webhook("tracker_ping")
def tracker_ping(ctx, request):
    ...
```

A decorator only registers a function under a name. What it is — its label,
its form, what it is on — is in the manifest, so `check` can compare the
two without running anything: a handler the manifest names that the code
does not have, or the other way round, fails the check.

### What a handler gets: `ctx`

| | what |
| --- | --- |
| `ctx.user` | who it is running for: `username`, `name`, `circles` |
| `ctx.records` | `list`, `get`, `create`, `patch`, `move`, `delete`, the same calls and envelope as the record API, through the gate |
| `ctx.fetch(url, …)` | an HTTP request, to a host in `[[fetch]]` only |
| `ctx.secret(key)` | a secret the person granted this Quill by key |
| `ctx.params` | a view's parameters: `ctx.params.record` when it was opened on one |
| `ctx.now()`, `ctx.log(…)` | the time on the server; a line in the Quill's log |

Nothing else reaches out of the sandbox: no files, no sockets, no processes.
`import` finds the standard library (without what the sandbox has no use
for), the SDK, and the Quill's own modules.

### Who it acts as

| handler | acts as | reaches |
| --- | --- | --- |
| view, action | the person looking at it or pressing it | what their circles let them, and only the datamodels the Quill declared |
| hook | whoever made the change | the same |
| job, webhook, API | the administrator who installed it, as services do now | what the Quill declared |

A view or action runs as the person, so a child pressing a button in a
family Quill can do no more than the child could do by hand. That is the
gate as [CIRCLES.md](CIRCLES.md) has it, with nothing added.

### Actions, on every surface

An action is the smallest piece of Quill code and the most useful: one
declaration, and the core draws it everywhere.

| surface | an action is |
| --- | --- |
| phone and web app | a button on the record's sheet and in its row menu; its form as a sheet |
| terminal | the same, in the record modal, and in the command palette |
| command line | `cm fleet log-service <vehicle> --date 2026-09-28 --km 1200` |
| assistant | an MCP tool, `fleet_log_service`, with the form as its schema |

The form is drawn by the core from `[actions.fields]`, with the widget for
each field kind, before the handler runs. `on` may name another Quill's
datamodel if this Quill uses it or was granted it: how one Quill adds a
button to another's records.

### Views and primitives

A view returns a tree. Every surface draws every primitive; that is the
whole contract between a Quill and a screen.

| primitive | what it is |
| --- | --- |
| `stack`, `row`, `columns`, `tabs` | layout |
| `text`, `markdown`, `image`, `badge`, `stat`, `empty` | content |
| `field` | one field of a record, with its kind's widget, read-only or editable |
| `form` | fields and a submit that runs an action |
| `button`, `menu` | run an action, or open something |
| `table`, `cards` | records, a row or a card each; opening one shows its sheet |
| `lanes` | records in columns by an enum, dragged between them |
| `month` | records on a calendar by a date field |

A view is drawn again after every action it ran and whenever a record it
listed changes. `lanes` moves a card at once and the server agrees or puts
it back, so dragging does not wait for a round trip.

The kit's screens (`kit = "board"` and the rest) stay as they are. Once the
primitives can draw them, each may become a view written in Python with
them — and move out of the core into the Quill that uses it. Tasks' board is
the one to try first.

### Effects

A handler returns nothing (redraw), or one of:

| effect | does |
| --- | --- |
| `toast("…")` | a line that goes away |
| `open(record)` | the record's sheet |
| `go(screen, **params)` | another screen of this Quill |
| `confirm("…", then=…)` | ask first, then run another action |
| `error("…")` | the form stays open with the message |

## The sandbox

The server runs Quill code in CPython compiled to WebAssembly (CPython's own
WASI build), under [wasmtime](https://wasmtime.dev), which is one wheel
from PyPI and runs on a Raspberry Pi. Each Quill gets one interpreter,
started when it is first called and dropped when it is idle, with a memory
limit and a time limit per call. The host and the interpreter speak JSON
lines over its standard input and output: the core sends a call, the
interpreter runs the handler, and every `ctx.records`, `ctx.fetch` and
`ctx.secret` is a request back to the core, which answers it through the
gate.

That is the whole of it, and none of it is visible to somebody writing a
Quill: they write Python, test it with Python, and publish Python. Another
language later is another interpreter behind the same JSON lines.

What the sandbox cannot do that a service can: hold a connection open, run
all the time, use a package with C in it. `[[services]]` stays for those, as
it is, outside the sandbox and trusted like it is now.

## Testing a Quill locally

Three steps, from fastest to most real. None needs an account anywhere.

**1. Tests, with the harness.** `cloudmorrow.quill.testing.Harness` loads the
Quill from its folder and runs it in plain Python, in-process, against the
real record store and the real gate on a temporary database. Errors are
Python tracebacks, and a debugger works.

```python
from cloudmorrow.quill.testing import Harness


def test_logging_a_service_moves_the_odometer():
    q = Harness(".")
    van = q.seed("vehicle", name="Van", **{"fleet.odometer": 1000})
    done = q.act("log-service", van, date="2026-09-28", km=1200)
    assert done.toast == "Logged at 1200 km"
    assert q.get("vehicle", van.id)["fleet.odometer"] == 1200


def test_a_kid_cannot_log_a_service():
    q = Harness(".", circles={"Kids": {"vehicle": "read"}})
    van = q.seed("vehicle", name="Van")
    done = q.as_user("sam", circles=["Kids"]).act("log-service", van, date="2026-09-28", km=1)
    assert done.refused


def test_the_garage_lists_the_vans():
    q = Harness(".")
    q.seed("vehicle", name="Van")
    assert "Van" in q.view("garage").text()
```

`q.fetch` is a fake with the declared hosts only; `q.clock` moves time for
jobs and expiry; `q.hook_calls` lists what the hooks were called with.

**2. `cm quill test`.** `check`, then pytest. `cm quill test --sandbox` runs
the same tests with every handler inside the WebAssembly interpreter, the
way the server will — the step that catches an import the sandbox does not
have. The interpreter is downloaded once and cached.

**3. `cm quill dev --local`.** A throwaway server on this machine: a
temporary data folder, the foundational datamodels, the Quill installed from
the folder and reinstalled when a file changes, its datasets seeded, and two
people to sign in as (an administrator and somebody in a smaller circle).
It prints the address for the browser and the phone on the same Wi-Fi, and
`cm` in another terminal is signed in to it. Without `--local`, `cm quill
dev` installs on your own server as it does now.

And, between them, `cm quill preview garage [--as sam]`: a view drawn in the
terminal, for reading what a screen will be without starting anything.

## Publishing

1. **Start** from `Cloudmorrow/quill-template` with GitHub's *Use this
   template* (not a fork: a fork stays tied to the template, cannot be
   private, and sends pull requests to us), or `cm quill new fleet`.
2. **Build** it, with `cm quill test` passing.
3. **Release** with a tag. The template's workflow runs `check`, `test` and
   `test --sandbox`, and attaches the tarball to the release.
4. **Submit** the repository's address at cloudmorrow.com/publish. The site
   reads the latest release, runs the check, and opens the pull request to
   `quill-catalog` for you: `repo`, `ref`, `category`, and the tarball's
   `sha256`, so what is installed is exactly what was reviewed.

Ours go the same way. Every Quill we write is a `quill-*` repository made
from the same template and added by the same kind of pull request; the only
thing ours have that nobody else's do is `foundation = true` in the catalog.
If the path is awkward for us it is awkward for everybody, and we will be
the first to notice.

A repository made from a template does not get the template's later
changes, so the template holds as little as it can: the SDK is a dependency
(`cloudmorrow` in `pyproject.toml`, and `sdk = "1"` in the manifest), and an
update to a Quill is a version bump, not a merge.

## Building one with an assistant

The template's `CLAUDE.md` changes from *never write code* to *declare
first, then Python*: the reference to the manifest and the SDK, the
primitives, and the loop — change `quill.toml` and `quill.py`, write a test,
`cm quill test` until it passes, `cm quill preview` to read the screens,
`cm quill dev --local` for the person to look. An assistant writes the
Python and the tests; nothing it has to touch is WebAssembly.

## What it costs, honestly

- **A round trip per click.** On loopback and a home network that is
  nothing; over the relay it is noticeable, which is why `lanes` moves first
  and asks after. Nothing a view draws works offline.
- **An interpreter per busy Quill.** CPython in WebAssembly takes tens of
  megabytes; on a Pi with many Quills, idle ones have to be dropped and
  started again, which costs a moment on the first click.
- **Pure Python only,** and at first the standard library only: see below.
- **The primitives are a ceiling,** as the kit was, and each new one is
  drawn on every surface. It is the same pressure, one level lower.

## Open

- **Packages.** Pure-Python dependencies from PyPI, listed in the manifest
  and vendored into the release tarball by the template's workflow, so the
  server never runs pip. Not in the first version.
- **Per-person code.** A hook runs as whoever made the change; a job still
  runs as the installer. A job per person is the same *next* as services.
- **Services in the sandbox.** A `run(ctx)` handler that is allowed to
  loop, with `ctx.fetch` as its only way out, would take most services
  inside the gate. Later.
- **Other languages.** A JavaScript template, on QuickJS, behind the same
  JSON lines. Later, and only after Python is right.

## The order

1. **The SDK and the harness**, in plain Python: `@action`, `ctx.records`,
   the effects, `Harness`, and `cm quill test`. A Quill can be written and
   tested before the server runs any of it.
2. **The sandbox** and `[[actions]]` on every surface: the first code a
   person can press. `cm quill test --sandbox`, and `cm quill dev --local`.
3. **Views and the primitives**, web and terminal, and `cm quill preview`.
4. **Hooks, `call` jobs, webhooks and APIs** as handlers.
5. **The template** made Python and TOML, `/publish` opening the catalog
   pull request, and one of our Quills — Fleet, or an action on Tasks —
   published that way first.
6. **Tasks' board as a view**, out of the core, if the primitives hold.
