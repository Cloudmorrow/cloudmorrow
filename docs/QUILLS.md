# Quills: software for your Cloudmorrow

Cloudmorrow is a foundation. Everything a person uses on top of it — a task
board, a CRM, a fleet log, the family calendar — is a **Quill**: a package in
its own repository, found in the **Quill Catalog**, chosen when you install
and added whenever you like after. The ones we write are Quills like anybody
else's; they are simply the first in the catalog.

This page is the contract. It supersedes the "app" and "element" wording in
[PLATFORM.md](PLATFORM.md) and [DATA.md](DATA.md); where they differ, this
page wins, and those pages remain the reasoning behind it.

## The words

| word | what it is |
| --- | --- |
| **Core** | This repository. Accounts, sealing, the record store, the gate, the Quill runtime, the kit renderers for every surface, the CLI, the MCP server. Nothing a person would call an app. |
| **Quill** | A software package: one repository with a `quill.toml` at its root. It declares the data it uses, the screens it shows, and the jobs, webhooks, APIs and services it runs. |
| **Quill Catalog** | [`Cloudmorrow/quill-catalog`](https://github.com/Cloudmorrow/quill-catalog): one `catalog.toml` naming every published Quill, its repository, a pinned release and a category. Your server reads it; a pull request adds to it. |
| **Category** | Where a Quill is shelved in the catalog: Home, Personal, Business, Developer, … Chosen from at install. |
| **Datamodel** | A kind of data with standard fields: `task`, `contact`, `vehicle`. Records belong to the person, never to a Quill. |
| **Foundational datamodel** | One of the standard datamodels in [`Cloudmorrow/datamodels`](https://github.com/Cloudmorrow/datamodels). Grouped into **domains** — Tasks, Customers (CRM), Fleet, Messaging, Calendars — which you can choose at install on their own, with or without a Quill that uses them. |
| **Extended datamodel** | What a Quill adds: fields of its own on a foundational datamodel (`fleet.odometer` on a `vehicle`), or a new datamodel under its own name (`fleet.service_visit`). Anybody's next Quill may use either. |
| **Dataset** | Records that come with a Quill — reference data (car makes, country codes) or a starting record (your first board) — and, later, a named collection of records a person makes and shares ("Fleet 2026"). |
| **Kit** | The fixed vocabulary of screens every surface can draw: `list`, `board`, `detail`, `form`, `calendar`, `thread`, `grid`, `editor`. |

## The rules

1. **A Quill never ships its own UI.** Screens are built from the kit, so
   every Quill is on the phone, the full web app and the terminal
   automatically — and on the command line and to an assistant as tools.
   There is no escape hatch. When the kit cannot say something, the kit
   grows, and every surface grows with it.
2. **Data is the person's.** Uninstalling a Quill removes its screens and
   its jobs, never a record. Its extension fields stay on the records, read-
   only, until something else writes them or the person clears them.
3. **What a Quill adds is visible before it is added.** The catalog page and
   the install sheet list its datamodels (used, extended, introduced), its
   datasets, its screens, its jobs, webhooks, APIs and services, and every
   grant it asks for. Nothing installs without a yes.
4. **Declarative first.** A Quill with no code is the normal case: the
   datamodels carry create, change, move, tick and delete; the kit carries the
   screens; the core runs declared jobs. Code is for what cannot be declared,
   and it runs outside the server (see *Webhooks, APIs and services*).
5. **One gate.** Every read and write — by a person, a Quill's service, or an
   assistant — goes through the same check of principal, action, datamodel and
   scope.
6. **Every Quill is its own repository.** Ours live in the Cloudmorrow
   organisation as `quill-<id>`; anybody else's live wherever they like and
   join the catalog by pull request.

## A Quill

```
quill-tasks/
  quill.toml          the manifest: everything below is declared here
  README.md           what it is, for the catalog page
  CLAUDE.md           how to work on it with an assistant (from the template)
  datasets/           optional: records to load, as TOML or CSV
  datamodels/         optional: datamodels this Quill introduces
  services/           optional: code for the services it runs
```

### The manifest

The whole of Tasks:

```toml
[quill]
id = "tasks"                              # lowercase, unique in the catalog
name = "Tasks"
version = "1.0.0"
summary = "Boards with three lanes: To Do, Doing, Done."
category = "personal"
icon = "tasks"                            # a kit icon name
publisher = "Cloudmorrow"
license = "AGPL-3.0-or-later"
features = [                              # what it does, for the catalog and the install sheet
  "Boards with three lanes: To Do, Doing, Done",
  "Subtasks as - [ ] lines in a task's Markdown",
  "Done empties itself a week after a task is finished",
]

[uses]
datamodels = ["board", "task"]            # foundational; installed with the Quill

[[screens]]
id = "board"
kit = "board"
label = "Tasks"
model = "task"
group = "board"                           # a link field: the chips across the top
lane = "lane"                             # an enum field: the columns
title = "title"
body = "body"
done = "done"                             # the lane the circle on a card moves to

[[jobs]]
id = "sweep-done"
action = "expire"                         # a core action, no code
model = "task"
field = "done_at"
after = "7d"
every = "1h"

[[datasets]]
id = "first-board"
model = "board"
seed = "per-owner"                        # once for each person who has none
records = [{ title = "{owner}'s tasks" }]
```

### Datamodels

A datamodel is a TOML file: in `Cloudmorrow/datamodels` for the foundational
ones, in a Quill's `datamodels/` for the ones it introduces.

```toml
[datamodel]
id = "task"
version = 1
label = "Task"
description = "One thing to do, on a board, in a lane."
domain = "tasks"
scopes = ["personal"]
title = "title"                           # what a record is called in a list
ordered_within = ["board", "lane"]        # records keep a position inside each group

[fields]
board   = { kind = "link", to = "board", required = true, indexed = true, on_delete = "cascade" }
title   = { kind = "string", required = true }
body    = { kind = "markdown" }
lane    = { kind = "enum", values = ["todo", "doing", "done"], labels = ["To Do", "Doing", "Done"], default = "todo", indexed = true }
done_at = { kind = "datetime", indexed = true, stamp = { field = "lane", value = "done" } }
```

**Field kinds:** `string`, `text`, `markdown`, `bool`, `int`, `decimal`,
`date`, `datetime`, `enum`, `email`, `phone`, `url`, `link`, `json`. Each kind
has a widget on every surface; adding a kind means adding all of them.

**`datetime`** keeps what it was given. With a zone it is a moment, kept
with its zone; without one it is the time on the wall — `2026-10-01T10:00`,
"the dentist at ten" — kept as typed, to the minute, and never converted; a
bare date (`2026-10-01`) is a whole day and stays one. Every client sends
what a person typed without a zone, so a calendar is on one clock. A stamp
the server sets is a moment, in UTC.

**`secret = true`** on a string or text field keeps it out of every
listing — the record store and every backend send it as null there — and
every surface draws it hidden until asked: dots and an eye on a row, a
password box on the sheet, `--reveal` on the command line. Reading the one
record is how its value is fetched. A secret field is never indexed.

**Indexed** fields are kept plain so the server can filter and sort by them.
Everything else is sealed at rest under the server's key, bound to the
datamodel, the owner and the record, so nothing can be moved by editing the
database.

**`stamp`** sets a datetime when another field takes a value, and clears it
when the field leaves it — how a task knows when it was finished.

**Extending** a datamodel is a `[[extends]]` table in the Quill's manifest:

```toml
[[extends]]
model = "vehicle"
[extends.fields]
odometer = { kind = "int", indexed = true }   # stored as "fleet.odometer"
```

Extension fields are namespaced by the Quill's id, are never `required`, and
are readable by anybody who may read the record.

**Introducing** a datamodel is a file in the Quill's `datamodels/`, with an
id under the Quill's name: `fleet.service_visit`. From the moment the Quill is
installed, every other Quill may ask for it.

### Records

Every record, of every datamodel, has the same envelope:

```json
{
  "id": "r_8f2c1d0a9b",
  "model": "task",
  "owner": "alice",
  "scope": "personal",
  "rev": 3,
  "position": 0,
  "created_at": "2026-09-26T08:10:00+00:00",
  "updated_at": "2026-09-26T09:41:00+00:00",
  "written_by": "tasks",
  "fields": { "board": "r_1a2b3c4d5e", "title": "Repot the fig", "lane": "doing", "body": "" },
  "expires_at": null
}
```

The core serves every installed datamodel at the same API:

| call | what it does |
| --- | --- |
| `GET /api/records/{model}?field=value` | list, filtered on indexed fields, in order |
| `GET /api/records/{model}?field__gte=…&field__lt=…` | a range on an indexed field: `__lt`, `__lte`, `__gt`, `__gte`; a record without the field never matches |
| `GET /api/records/{model}?q=text` | the records whose text holds it; each found one's `preview` is the line that matched |
| `GET /api/records/{model}?previews=true` | the list, with a line of each record's text as `preview` |
| `GET /api/records/{model}?_last=50&_since=<time>` | the newest fifty, still in order; only what changed at or after a moment — a conversation's page, and what an open one has not got |
| `POST /api/records/{model}` | create, from `{"fields": {...}}`; a space also takes `scope`, `members` and `unique` (see *Spaces*) |
| `GET /api/records/{model}/{id}` | one record |
| `PATCH /api/records/{model}/{id}` | change fields; send `rev` to get a 409 instead of overwriting |
| `POST /api/records/{model}/{id}/move` | `{"fields": {"lane": "done"}, "index": 0}`: change group fields and position together |
| `DELETE /api/records/{model}/{id}` | delete, cascading along `on_delete = "cascade"` links |
| `POST /api/records/{model}/{id}/members` | `{"username": …}`: put somebody in a shared space (see *Spaces*) |
| `DELETE /api/records/{model}/{id}/members/{username}` | take them out; with your own name, leave |
| `GET /api/people` | everybody on the server a space could be shared with |
| `GET /api/datamodels` | every datamodel on the server, with its fields and who uses it |
| `GET /api/quills` | every installed Quill, with its manifest |
| `GET /api/quills/catalog` | the catalog, with what is installed |
| `POST /api/quills` | install, from the catalog or a source (admin) |

Scopes are `personal`, `shared` and `public`, as chat and calendar have them.
Records of a datamodel that is not a space, and not in one, are personal:
their owner's alone. See *Spaces* for everything shared.

### Spaces: what more than one person shares

A calendar the household shares and a channel the team talks in are the
same shape: a container some people are in, and things inside it that
everybody in it may see. The record store has that shape once, for every
Quill, as **spaces**.

```toml
[datamodel]
id = "calendar"
space = true                      # a record of it is a space
scopes = ["personal", "shared", "public"]

[datamodel]
id = "event"
in_space = "calendar"             # a link field: whoever may see the calendar sees the event
```

| scope | who sees it and writes in it | who manages it | leaving |
| --- | --- | --- | --- |
| `personal` | its owner | its owner | cannot |
| `shared` | its owner and its members | its owner, and administrators | a member may |
| `public` | everybody on the server | its owner, and administrators | nobody can |

A space's scope is set when it is made, and a shared one may be made with
its people in it (`"members": [...]`). Members are added with
`POST /api/records/{model}/{id}/members` and removed with `DELETE
…/members/{username}`; being added leaves a notification. `"unique": true`
finds the space of that datamodel with exactly you and `members` in it, and
the same indexed fields, before making one (200 rather than 201) — the one
conversation between two people, from either side; its people are not told
they were added, because the first thing written in it tells them.
`GET /api/people` is everybody else there is to share with. A record in a
space is sealed to the space, so moving a message to another channel by
editing the database opens as nothing.

A dataset can seed a space once per server (`seed = "once"`, for the
public calendar and `#general`) or once per person (`seed = "per-owner"`,
for everyone's own calendar).

Being able to see a space is being able to write in it. Who may change
or delete what is written there is the datamodel's `authored`:

| `authored` | who changes and deletes a record | for |
| --- | --- | --- |
| `false` (the default) | anybody who may see it | a shared list |
| `true` | only whoever wrote it | a message |
| `"or-manager"` | whoever wrote it, or whoever manages its space | an event: the calendar's maker can clear somebody's stale one |

A space may declare what happens when something is written in it:

```toml
[[notify]]                        # on the datamodel of what is written
when = "created"
to = "members"                    # everybody in the space but the writer
push = true                       # and a push to their phones
unread = true                     # counted until they open the space
```

### Backends: data that lives somewhere else

Most datamodels live in the record store. Three foundational ones live where
they always have, because other things reach them there, and are served
through the same record API by a **backend**:

| datamodel | backend | lives in | also reached by |
| --- | --- | --- | --- |
| `note` | `notes` | Markdown files in each person's notes folder, sealed | WebDAV, the notes MCP tools, `cm note` |
| `share`, `file` | `shares` | the fileshares and each person's drive | WebDAV, the desktop app's mounts, `cm share`, `/api/shares` |
| `secret` | `vaults` | the secrets store, sealed under its own key | `cm secret run`, and never an assistant |

A backend answers the same list, get, create, change and delete, with the
same envelope, so a Quill, `cm <quill>` and an assistant cannot tell the
difference. The Notes, Files and Secrets Quills carry only their screens.

`q` and `previews` are not filters, and every listing takes them: the record
store searches the text fields it unseals, and a backend searches its own
way (notes read their files, names and every line). A backend may do two
things more, and a datamodel says which in `can` beside it in
`GET /api/quills` — `["search", "folders", "attachments"]` for a note:

| capability | calls | what it is |
| --- | --- | --- |
| `folders` | `GET`, `POST {path}`, `PATCH {path, to}`, `DELETE ?path=` on `/api/records/{model}/_folders` | folders a record's path is in, which exist before anything is put in them and take everything in them when they go |
| `attachments` | `POST` (the body is the file) and `GET …/{name}` on `/api/records/{model}/_attachments` | files kept beside the records; the answer's `path` is what Markdown writes (`![alt](img/<name>)`) |

A folder is not a record: it has no fields, no rev and nothing to seal, and
a listing of notes with folders in it would be a listing of two things. So
it is a capability a backend declares by having the methods, and any other
backend with folders — the fileshares — answers the same calls.
A backend may also keep **content**: bytes beside a record's fields. The
`shares` backend does — a file's — and the record API has three more calls
for any datamodel whose backend keeps some:

| call | what it does |
| --- | --- |
| `GET /api/records/{model}/{id}/content` | the bytes, as themselves |
| `GET /api/records/{model}/{id}/thumb?size=256` | a small JPEG of a picture; 415 when it is not one the server can scale |
| `POST /api/records/{model}/upload?field=value…` | a new record from the body's bytes, the query saying where and what it is called |

A share's id is its name (`my-files` for the person's own drive); a file's
is the share and the path in it, encoded, and it is listed a folder at a
time: `GET /api/records/file?share=my-files&folder=Photos`. Making a `file`
record with `kind = "folder"` makes a folder; changing its `name`, `folder`
or `path` renames or moves it inside its share.

### Screens

Each screen names a kit element and binds it to fields. The kit, and what
each element needs:

| kit | binds | on the phone | on the full web app | in the terminal | on the command line |
| --- | --- | --- | --- | --- | --- |
| `list` | `model`, `title`, optional `subtitle`, `tick` (a bool field), `fields` (the sheet's), `group` and `subgroup` (a link, an enum or an indexed string: picked through) | chips for the group and subgroup, a list with a circle per row | the same, wider | the groups down the left, the subgroup as buttons, a table | `cm <quill> list [-g group/subgroup]`, `add`, `done` |
| `board` | `model`, `lane` (enum), `title`, optional `group` (link), `body`, `done` | lanes stacked | lanes as columns, drag and drop | lanes as columns, drag and keys | `cm <quill> list`, `add`, `move` |
| `detail` / `form` | `model`, `fields` | a sheet | a panel | a modal | `cm <quill> show`, `set` |
| `calendar` | `model`, `starts`, `ends` (indexed datetime or date fields), `space` (a link to a space: the calendars), optional `all_day` (bool), `colour` (a field of the space: cyan, violet, green, amber, rose), `title`, `subtitle` | a month with a dot per thing, and the day's list | a week of hours or a month written in | the spaces, a month, and the day's list | `cm <quill> list --from --to`, `add "<title>" starts=… ends=…` |
| `thread` | `model` (in a space), `space` (its link to the space), `body`; optional `about` (a field of the space), `made_as` | the spaces with unread, then a conversation | both side by side | both side by side | `cm <quill> list`, `show`, `say` |
| `editor` | `model`, `title`, `body` (markdown), optional `path` (a string, `folder/sub/title`: the folders) | a tree, then a list, then the page | the list and the page side by side | the tree and the live editor side by side | `cm <quill> list`, `show`, `add`, `edit`, `search` |
| `grid` | `model` with content (`file`), `group` (a link: the places, picked first), `folder`, `kind` (an enum with `folder`), optional `size`, `modified`, `mime`, `group_subtitle`, `group_open` | the groups, then folders and tiles | the same, wider; drag and drop in | the groups in a table, then the folder, with the picture beside | `cm <quill> list [group] [folder]`, `get`, `put`, `add` |

Every screen gets a record sheet for free: opening a card or a row shows the
record's fields with the widget for each kind, editable, with delete. An
editor opens its own page instead, and takes pictures when its datamodel has
`attachments`.

A screen whose things are in spaces (`space` on a `calendar`) also gets the
spaces: a list of them — yours, shared, everybody's — the way to make one
(its name, who can see it, who is in it), and on a space's own sheet who is
in it, adding somebody, taking somebody out and leaving. That is the kit's,
not the calendar's: every surface has it once (web `kit_space.js`, terminal
`widgets/kit_space.py`), for any element that draws things in spaces.

A `thread` is the kit's conversation: things written (`body`) in spaces. Its
`made_as` says what fields a space gets for how it is made — by its scope, or
`direct`, a shared space found-or-made between you and the person you pick
and named for them — and the kit draws around it what every space has: making
one, the people in it, adding and taking out, leaving. Chat is:

```toml
[[screens]]
id = "chat"
kit = "thread"
model = "message"
space = "channel"
body = "body"
about = "topic"
[screens.made_as]
public = { kind = "public" }
shared = { kind = "private" }
direct = { kind = "direct" }
```

A conversation opens on its newest page (`?_last=100`), asks what changed
since (`?_since=`) every few seconds and when a push arrives, and marks the
space seen (`POST …/seen`) as it is read. The unread counts come on the
spaces themselves (`unread`, and `last`: the newest line), and the number on
the phone's icon adds them up across every space whose Quill is on for you.

A Quill's screens become a tab, in the order of `[[screens]]`, on every
surface; Quills from the catalog stand in the catalog's order (Notes, then
Tasks), and the rest follow, oldest first. The clients open on the first tab
there is. An administrator switches a Quill off for the server; a person
switches its tab off for themselves — the same two switches the included
features have always had.

### Jobs

Declared work the core runs on a schedule, as the Quill:

| action | does |
| --- | --- |
| `expire` | delete records of `model` whose `field` is older than `after` |
| `run` | start the command of the Quill's `service` once, every `every`, never twice at once (see *Webhooks, APIs and services*) |

`every` is `15m`, `1h`, `1d`. An `expire` job also runs when its datamodel is
listed, so the rule holds on a server that was asleep, and every record it
would take carries its `expires_at`.

### Webhooks, APIs and services

These are the parts of a Quill that are code, and they run outside the server
so the gate means something and a Raspberry Pi stays a Raspberry Pi.

```toml
[[services]]
id = "imap-sync"
command = ["python", "services/imap_sync.py"]   # started and kept running by the core
always = true

[[jobs]]
id = "nightly"
action = "run"             # start a service's command once, every `every`
service = "imap-sync"
every = "1d"

[[webhooks]]
id = "stripe"
path = "stripe"            # POST /hooks/<quill>/stripe; the id when left out
model = "payment"          # declarative: the JSON body becomes a record…
map = { amount = "$.data.object.amount", customer = "$.data.object.customer" }
# …or forward = "imap-sync" hands the request to a service instead
# signature = "X-Hub-Signature-256"   # also take a GitHub-style HMAC of the body

[[apis]]
id = "public"
service = "imap-sync"      # GET/POST/… /api/q/<quill>/... proxied to the service
# prefix = "v1"            # only /api/q/<quill>/v1/…, when a Quill has several
```

A service is any program. The core starts it and it talks to the record API
exactly as the clients do, over loopback HTTP, through the gate, bound by the
Quill's grants. The server never imports a Quill's code.

**How it runs** (`server/quillservices.py`). Every service of every installed
Quill that is switched on for the server is a process of its own, started in
the Quill's folder (`<data_dir>/quills/<id>/`) with an environment built from
nothing:

| variable | what |
| --- | --- |
| `CLOUDMORROW_URL` | the server on loopback, `http://127.0.0.1:<port>` |
| `CLOUDMORROW_TOKEN` | the Quill's token |
| `CLOUDMORROW_QUILL`, `CLOUDMORROW_SERVICE` | which Quill, which service |
| `PORT` | a free loopback port the core picked, for a service that serves an API or a forwarded webhook |
| `HOME` | `<data_dir>/quill-homes/<id>`, kept across updates |
| `PATH`, `LANG`, `PYTHONUNBUFFERED` | the server's own PATH and LANG, and unbuffered output |

`python` as the first word of `command` is the server's own interpreter, so
a script needs nothing installed; the standard library is what it can count
on. A service with `always = true` is started again when it exits, after a
pause that doubles with each quick failure (1 s … 60 s); one without runs
once per start of the Quill. A service a `run` job names is started only by
the job, on its `every`, never twice at once, and the time it last ran is
kept so a restart of the server does not run a daily job again. Output goes
to `<data_dir>/logs/quills/<id>/<service>.log`, one megabyte and one older
file. Switching the Quill off, removing it and stopping the server stop its
processes: SIGTERM to the process group, SIGKILL five seconds later.
Reinstalling restarts them on the new code.

**APIs** (`/api/q/<quill>/<path>`) are for anybody signed in. The request goes
to the service's `PORT` at `/<path>` without the caller's `Authorization` or
cookies, with `X-Cloudmorrow-User: <username>` added (or
`X-Cloudmorrow-Quill` when the Quill calls its own API); no `Set-Cookie`
comes back.

**Webhooks** (`POST /hooks/<quill>/<path>`) are for the outside world, so not
an account but a secret: each webhook has one the core made, which an
administrator copies from Administration → Quills as part of its address and
can replace. It comes back as `?token=`, as `X-Cloudmorrow-Webhook-Token`,
or — when the webhook names a `signature` header — as an HMAC-SHA256 of the
body under the secret, the way GitHub signs (`sha256=<hex>`). A body is at
most a megabyte, and a webhook answers 120 calls a minute. With `model` and
`map`, each field is a path into the JSON body — `$`, `.name`, `[n]` and
`["odd name"]`, nothing more, because the body is somebody else's input —
and the record is made as the Quill; a path that finds nothing leaves the
field out. With `forward`, the request goes to the service as
`POST /hooks/<path>` with `X-Cloudmorrow-Webhook: <id>`, the secret taken off.

**The security model.**

- *Who it acts for.* A Quill's code acts for one account: in this first
  version, the administrator who installed it, recorded in its
  `.origin.json` (`installed_by`). One installed with nobody signed in — at
  first boot, or from `cloudmorrow-server quill add` — acts for the oldest
  active administrator. If the installer's account is gone, or no longer an
  administrator, the code acts for nobody and does not run until the Quill
  is installed again. The install sheet says it: *Runs code on this server:
  … It runs as bram, and can read and write only: …*
- *What its token opens.* A Quill's token (`cmq_…`, `server/quilltokens.py`)
  is kept only as a hash. It is `Principal("quill", <that account>,
  quill=<id>, models=<used, introduced, extended, granted>)`, and the gate
  refuses it every datamodel it did not declare. It opens the record API
  (`get_principal`) and the Quill's own APIs; every other route asks for a
  person's signed token, which it is not — notes, secrets, accounts,
  shares, the MCP server all answer 401. It stops working the moment the
  Quill is switched off or removed. Because only the hash is stored, the
  working token lives in the server's memory and the processes'
  environment: each start of the server issues a new one, and an
  administrator's *new token* issues one and restarts the services.
- *What it is given.* None of the server's environment, config path or
  keys; a port only on loopback; its own home.
- *What runs.* Only a Quill an administrator installed, from the copy the
  install made. `allowed_client_ips` lets its loopback calls through
  (from 127.0.0.1, not through the proxy, with a Quill token).
- *What it is not.* A sandbox. The process runs as the server's own system
  user and can do whatever that user can on the machine; the token bounds
  what it can do *through Cloudmorrow*. Installing a Quill with code is
  trusting its author, and the sheet says so.

**Next.** A service per person, each acting for its own account and started
when the person switches the Quill on (a mail sync for everyone, not only
the admin); a separate system user or container per Quill, so the
filesystem is bounded too; Stripe's signature scheme beside GitHub's; logs
and state pushed to the admin screen instead of fetched; and a worker model
if the server ever runs more than one process (the supervisor lives in the
one uvicorn process today, and two would each start every service).

### Grants

A Quill may read and write what it declared in `[uses]`, what it introduced,
and its own extension fields. Anything else is a grant, with a reason the
person reads before saying yes:

```toml
[[grants]]
model = "contact"
access = "read"
why = "to show who a vehicle is assigned to"
```

## The catalog

```toml
# Cloudmorrow/quill-catalog/catalog.toml
[datamodels]
repo = "https://github.com/Cloudmorrow/datamodels"
ref = "v1.0.0"

[[categories]]
id = "personal"
label = "Personal"
description = "Your own lists, notes and plans."

[[quills]]
id = "tasks"
repo = "https://github.com/Cloudmorrow/quill-tasks"
ref = "v1.0.0"
category = "personal"
foundation = true          # offered, ticked, on the first-boot page
```

The server reads the catalog from `quill_catalog` in its config (the URL
above by default), fetches a Quill as the tarball of its pinned `ref` — no git
needed on the server — and keeps it under `<data_dir>/quills/<id>/`. A source
can also be a local directory, which is how you develop one.

## Building one, with an assistant

The loop is meant to be a conversation, and every step of it has a command
and an MCP tool, so an assistant can drive it as well as you can.

1. **Start** from [`Cloudmorrow/quill-template`](https://github.com/Cloudmorrow/quill-template)
   (a GitHub template), or `cm quill new fleet`. The template's `CLAUDE.md`
   teaches an assistant this page, the datamodels there are, and the loop below.
2. **Check** with `cm quill check`: the manifest against the schema, every
   screen against its datamodel, and a text preview of what each surface will
   draw. Nothing to deploy to find out it is wrong.
3. **Try** with `cm quill dev .`: installs the folder on your own server as a
   development Quill, and reinstalls it when a file changes. It is on your
   phone and in your terminal at once.
4. **Publish** with a release tag in your repository and a pull request adding
   three lines to the catalog.

Over MCP, an administrator's assistant has `quill_schema`, `quill_check` and
`quill_dev_install`: "make me a place to track the car's services" is a
manifest written, checked and installed in one conversation.

## Where the code is

| part | where |
| --- | --- |
| datamodel definitions, validation | `server/datamodels.py` |
| records, sealing, positions, stamps, the gate | `server/records.py` |
| manifests, sources, install, catalog | `server/quills.py`, `server/routes/quills.py` |
| the record API | `server/routes/records.py` |
| jobs, and the boot work (foundation Quills, built-ins that became Quills, old tables into records: `move_legacy_tasks`, `move_legacy_calendar`, `move_legacy_chat`) | `server/quilljobs.py` |
| spaces: who is told what, the badge, the people there are | `server/spacenotify.py`, `server/routes/push.py` (`badge_for`), `GET /api/people` in `server/routes/records.py` |
| backends: notes (their folders and pictures), shares and files, secrets | `server/backends.py`; a share's files in `server/fileops.py` |
| the kit on the web (phone and full) | `server/web/kit.js`, `kit.css`, `quills.js`; the grid in `kit_grid.js`, `kit_grid.css` (with `registerGridHook`, which the desktop app's mount lines come in by); the editor in `kit_editor.js`, `kit_editor.css` and `pictures.js`; the calendar in `kit_calendar.js`, `kit_calendar.css`; the thread in `kit_thread.js`, `kit_thread.css`; spaces (their list, making one, writing to somebody, their people) in `kit_space.js`, `kit_space.css`, shared by calendar and thread; a grouped list and hidden fields in `kit_grouped.js`, `kit_grouped.css`; the catalog and install sheet in `quillsadmin.js` |
| the kit in the terminal | `tui/panes/kit.py` (list), `tui/panes/kit_grouped.py` + `kit_grouped.tcss` (a grouped list, hidden fields) with `tui/widgets/group_list.py`, `tui/panes/kit_board.py`, `tui/panes/kit_editor.py` + `kit_editor.tcss` (with `widgets/editor.py`, `note_tree.py`, `picture.py`), `tui/panes/kit_grid.py` (with `register_group_extension`; the mount column and buttons for shares are `tui/sharemounts.py`), `tui/panes/kit_calendar.py` + `kit_calendar.tcss`, `tui/panes/kit_thread.py`, `tui/widgets/kit_space.py` + `kit_space.tcss` (spaces: `NewSpaceModal`, `SpaceModal`, `PickPersonModal`), `tui/widgets/kit.py`, `tui/screens/record_sheet.py`; the catalog in `tui/panes/admin_quills.py` |
| the kit on the command line | `cli/quillrun.py` (`cm <quill> …`) |
| building one | `cli/quill.py` (`cm quill new/check/dev/add`), `quill_reference.md`, `quill_template/` |
| the kit to an assistant | `server/mcptools.py` (generic record tools) |
| a Quill's code: running it | `server/quillservices.py` (the supervisor, run jobs, logs), started with the app; `run` jobs asked for by the Clock in `server/quilljobs.py` |
| a Quill's token and webhook secrets, who it runs as | `server/quilltokens.py`; `get_principal` in `server/deps.py` |
| APIs, webhooks, and their administration | `server/routes/quillcode.py`, with `server/quillproxy.py` (to a service's port) and `server/quillhooks.py` (map paths, signatures, the rate) |
| watching it run | web `quillservices.js`, `quillservices.css`; terminal `tui/panes/admin_quill_services.py`; `cm quill services`, `cm quill logs` |

## The order from here

1. Tasks is the first Quill, and the proof: no task code left in the core.
2. Services, webhooks and APIs run, with Quill tokens and the gate on them.
   (They run, as the installing administrator; a service per person is next.)
3. `calendar` and `thread` in the kit; Calendar and Chat become Quills.
   (Both are Quills: `calendar` and `thread` are drawn on every surface.)
4. `grid` and `editor`; Files and Notes become Quills. (Both are drawn,
   and both are Quills.) Secrets is a Quill too, a grouped `list` of the
   `secret` datamodel, while its store stays foundation, and it is the one
   datamodel no assistant may ever reach.
5. Shared and public scopes in the record store; named datasets.
6. The catalog page at cloudmorrow.com, and the first Quill we did not write.
