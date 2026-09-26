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
   and it runs outside the server (see *Services*).
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
| `POST /api/records/{model}` | create, from `{"fields": {...}}` |
| `GET /api/records/{model}/{id}` | one record |
| `PATCH /api/records/{model}/{id}` | change fields; send `rev` to get a 409 instead of overwriting |
| `POST /api/records/{model}/{id}/move` | `{"fields": {"lane": "done"}, "index": 0}`: change group fields and position together |
| `DELETE /api/records/{model}/{id}` | delete, cascading along `on_delete = "cascade"` links |
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

A space's scope is set when it is made. Members are added with
`POST /api/records/{model}/{id}/members` and removed with `DELETE
…/members/{username}`; being added leaves a notification. A record in a
space is sealed to the space, so moving a message to another channel by
editing the database opens as nothing.

A dataset can seed a space once per server (`seed = "once"`, for the
public calendar and `#general`) or once per person (`seed = "per-owner"`,
for everyone's own calendar).

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
| `file` | `shares` | the fileshares and each person's drive | WebDAV, the desktop app's mounts, `cm share` |
| `secret` | `vaults` | the secrets store, sealed under its own key | `cm secret run`, and never an assistant |

A backend answers the same list, get, create, change and delete, with the
same envelope, so a Quill, `cm <quill>` and an assistant cannot tell the
difference. The Notes, Files and Secrets Quills carry only their screens.

### Screens

Each screen names a kit element and binds it to fields. The kit, and what
each element needs:

| kit | binds | on the phone | on the full web app | in the terminal | on the command line |
| --- | --- | --- | --- | --- | --- |
| `list` | `model`, `title`, optional `subtitle`, `tick` (a bool field), `fields` (the sheet's), `group` and `subgroup` (a link, an enum or an indexed string: picked through) | chips for the group and subgroup, a list with a circle per row | the same, wider | the groups down the left, the subgroup as buttons, a table | `cm <quill> list [-g group/subgroup]`, `add`, `done` |
| `board` | `model`, `lane` (enum), `title`, optional `group` (link), `body`, `done` | lanes stacked | lanes as columns, drag and drop | lanes as columns, drag and keys | `cm <quill> list`, `add`, `move` |
| `detail` / `form` | `model`, `fields` | a sheet | a panel | a modal | `cm <quill> show`, `set` |
| `calendar` | `model`, `starts`, `ends`, optional `all_day`, `space` (the calendars) | a day list and a month | a week and a month | a month and the day's list | `cm <quill> list --from --to`, `add` |
| `thread` | `model`, `body`, `space` (the channels) | channels, then a conversation | both side by side | both side by side | `cm <quill> list`, `say` |
| `editor` | `model` with a `markdown` field, optional folders from the title | a tree, then a page | both side by side | both side by side | `cm <quill> show`, `add`, `edit` |
| `grid` | `model` of kind file | folders and tiles | the same, wider | a table | `cm <quill> list`, `get`, `put` |

Every screen gets a record sheet for free: opening a card or a row shows the
record's fields with the widget for each kind, editable, with delete.

A Quill's screens become a tab, in the order of `[[screens]]`, on every
surface. An administrator switches a Quill off for the server; a person
switches its tab off for themselves — the same two switches the included
features have always had.

### Jobs

Declared work the core runs on a schedule, as the Quill:

| action | does |
| --- | --- |
| `expire` | delete records of `model` whose `field` is older than `after` |
| `run` | start the Quill's service command once (see *Services*) |

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

[[webhooks]]
id = "stripe"
path = "stripe"            # POST /hooks/<quill>/stripe
model = "payment"          # declarative: the JSON body becomes a record…
map = { amount = "$.data.object.amount", customer = "$.data.object.customer" }
# …or forward = "imap-sync" hands the request to a service instead

[[apis]]
id = "public"
service = "imap-sync"      # GET/POST /api/q/<quill>/... proxied to the service
```

A service is any program. The core starts it with `CLOUDMORROW_URL` and a
`CLOUDMORROW_TOKEN` of the Quill's own, and it talks to the record API exactly
as the clients do, through the gate, bound by the Quill's grants. The first
release validates these tables and shows them on the install sheet; running
them is the next step after the kit, and until then the sheet says so.

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
| jobs | `server/quilljobs.py` |
| the kit on the web (phone and full) | `server/web/kit.js`, `kit.css`, `quills.js`; a grouped list and hidden fields in `kit_grouped.js`/`.css`; the catalog and install sheet in `quillsadmin.js` |
| the kit in the terminal | `tui/panes/kit.py` (list), `tui/panes/kit_grouped.py` (a grouped list, hidden fields) with `tui/widgets/group_list.py`, `tui/panes/kit_board.py`, `tui/widgets/kit.py`, `tui/screens/record_sheet.py`; the catalog in `tui/panes/admin_quills.py` |
| backends (notes, secrets) | `server/backends.py` |
| the kit on the command line | `cli/quillrun.py` (`cm <quill> …`) |
| building one | `cli/quill.py` (`cm quill new/check/dev/add`), `quill_reference.md`, `quill_template/` |
| the kit to an assistant | `server/mcptools.py` (generic record tools) |

## The order from here

1. Tasks is the first Quill, and the proof: no task code left in the core.
2. Services, webhooks and APIs run, with Quill tokens and the gate on them.
3. `calendar` and `thread` in the kit; Calendar and Chat become Quills.
4. `grid` and `editor`; Files and Notes become Quills. Secrets is a Quill
   already — a grouped `list` of the `secret` datamodel — while its store stays
   foundation, and it is the one datamodel no assistant may ever reach.
5. Shared and public scopes in the record store; named datasets.
6. The catalog page at cloudmorrow.com, and the first Quill we did not write.
