# Datamodels: the shape of your data

> **Now:** this page is the contract for data: what a datamodel is, how it
> is versioned, extended, shared and guarded. [QUILLS.md](QUILLS.md) is the
> contract for what sits on top — screens, jobs and code — and
> [DATA.md](DATA.md) is the reasoning behind both. *What is next* at the
> end is the plan, agreed on 8 October 2026; everything before it is built.

Cloudmorrow's claim is that you own your data and pick who may change it.
A datamodel is the unit of that claim: the shape every Quill agrees on, the
thing a circle gives access to, the thing a space shares. A contact is a
contact whichever Quill made it, so one Quill's data is the next one's, and
a Quill that goes leaves every record behind.

## Two kinds

**Foundational datamodels** are the ones Cloudmorrow decides are
foundational: the shapes in [`Cloudmorrow/datamodels`](https://github.com/Cloudmorrow/datamodels),
grouped in **domains** — Tasks, Customers, Fleet, Calendars, Messaging,
Notes, Secrets, Files — and chosen by domain when you install, with or
without a Quill that uses them. They grow by our hand, by pull request to
that repository, when we judge a shape is one every Quill should agree on.
A datamodel is foundational because we said so, not because enough Quills
happened to want it.

**Extended datamodels** are what Quills add on top: fields of their own on
a foundational datamodel (`fleet.odometer` on a `vehicle`), or whole new
datamodels under their own name (`fleet.service_visit`). Any later Quill may
use either. They are declared in the Quill's repository, arrive with it,
and the records written in them stay when it goes.

## A datamodel

A datamodel is a TOML file: in [`Cloudmorrow/datamodels`](https://github.com/Cloudmorrow/datamodels)
for the foundational ones, in a Quill's `datamodels/` for the ones it
introduces.

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

Extension fields are namespaced by the Quill's id and are never `required`.
They are the person's, like every field: readable by anybody who may read
the record, drawn on every sheet, and written by anybody who may write the
record. A Quill's *token* writes only the datamodels it declared or was
granted ([QUILLS.md](QUILLS.md), *Grants*).

**Introducing** a datamodel is a file in the Quill's `datamodels/`, with an
id under the Quill's name: `fleet.service_visit`. From the moment the Quill is
installed, every other Quill may ask for it.

## Versions

A datamodel's `version` is an integer, and a released version never
changes. A foundational datamodel grows by its version: when a Quill that
needs it is installed with a newer one than the server has, the newer one
replaces it. A new version may add fields, and may keep its records in a
space (`contact` v2 is in a `book`). It never takes a field away and never
changes a field's kind: the records written before keep opening — one in
no space is still its owner's own — and a shape that needs a field gone is
a new datamodel. The Quill Catalog pins one release of the datamodels
repository, so every server installing from it agrees on the same
versions, and a server never holds two versions of one datamodel.

## Records

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
| `GET /api/changes` | a server-sent events stream: each record you may see being made, changed or deleted, by datamodel, id and space — never its fields. `?since=<seq>` to catch up after a drop; see *Keeping a screen current* |
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

A plain listing answers with at most a thousand records, the first thousand
in order, and says so with the header `X-Records-Capped: 1000` when it
stopped there; a search answers with at most two hundred matches. Filters,
`_last` and `_since` are how a screen asks for the part it shows. Since a
record's text is sealed, a search reads and opens every row it looks at,
and stops at the last match wanted; filters on indexed fields are answered
from an index, so a screen narrows with those first and searches second.

**Keeping a screen current.** `GET /api/changes` is a server-sent events
stream (`text/event-stream`). It opens with `event: hello` and the feed's
position, then sends `event: change` with `{"seq", "model", "id",
"space", "owner", "action", "at"}` for each record the caller may see
being `created`, `changed` or `deleted`, and `: ping` while nothing
happens. It never carries a field: the screen asks the record API for
what it has not got, so nothing reaches anybody that the gate would not
hand them. A client that drops comes back with `?since=<seq>` and gets the
changes it missed of the last few thousand; `?limit=N` closes the stream
after N, for a script. The web app's thread screen listens this way and
falls back to asking every few seconds while the stream is down
(`web/changes.js`).

Scopes are `personal`, `shared` and `public`, as chat and calendar have them.
Records of a datamodel that is not a space, and not in one, are personal:
their owner's alone. So is a record of a datamodel that lives in spaces when
its space link is left empty — a contact in no book is your own address
book's. See *Spaces* for everything shared.

## Spaces: what more than one person shares

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
for everyone's own calendar). A dataset of a datamodel *in* a space can be
seeded once in every space that has none of it (`seed = "per-space"`): the
CRM's pipeline stages, in every book, the first time a book's stages are
read — so a book made later gets them too, and there is never a book
without a pipeline.

A space link is `on_delete = "cascade"`: what is in a space goes with it.
`clear` is refused, because a record sealed to a space it no longer names
could not be opened.

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

## Backends: data that lives somewhere else

Most datamodels live in the record store. Three foundational ones live where
they always have, because other things reach them there, and are served
through the same record API by a **backend**:

| datamodel | backend | lives in | also reached by |
| --- | --- | --- | --- |
| `note` | `notes` | Markdown files in the `Notes` folder of each person's drive | WebDAV, the Files Quill, the notes MCP tools, `cm note` |
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

## Access: who may see it, who may change it

The whole of it, in five lines. The screens are in [CIRCLES.md](CIRCLES.md).

- Access is **none, read or write**, on a datamodel, given to a circle.
  Nothing finer: there is no rule on a field. A person's access is the most
  any of their circles gives.
- **No access, no Quill.** A Quill over data you may not reach is not on
  your phone. Read only, and the Quill is the same screen looked at: no
  new, no edit, no dragging, no composer. Write, and it is yours to change.
- **A new Quill's data is everyone's, read and write, by default.** A fresh
  server's one circle has `* = write`, so a datamodel that arrives with a
  Quill is open to all; the install sheet is where an administrator narrows
  it before saying yes, and the circles screen is where it is narrowed later.
- **A space is what some people share**: personal, shared with named
  members, or public. Seeing a space is writing in it; who may change a
  particular line in it is the datamodel's `authored`.
- **One gate.** Every read and write, by a person, a Quill's code or an
  assistant, passes the same check of principal, action, datamodel and
  scope, and an assistant never reaches `secret`.

Next, under *What is next*: the same three words given to one person
without a circle, and a log on every record of who changed it.

## What is next

Agreed on 8 October 2026, after setting an outside proposal for a
"foundational datamodel specification" against what is built. Most of
what it asked for exists in a smaller shape — the registry, versions,
domains, the envelope, scopes, extensions, datasets, the change feed — and
the gaps are in the claim itself: who may change a record is only half
said, reference data is free text, and the foundation is narrow. Each
phase ends with something a person can use.

### Phase 1 — Who may change it, said in full

The part of the claim people feel first, and the smallest set of controls
that keeps it both delightful and safe.

1. **Access for a person, not only a circle.** Beside circle rules, a rule
   for one account: `PUT /api/access/{username}/{model}` with `none`,
   `read` or `write`; shown on the accounts screen and in `cm access`. The
   gate reads both and takes the most. No new vocabulary.
2. **The install sheet says the default.** A Quill bringing data new to the
   server shows *Everyone can read and write: vehicle, service visit* with
   the circles to narrow it to, before the yes. The same words on the
   catalog page at cloudmorrow.com.
3. **A record's log.** Every write keeps the names of the fields it touched
   beside who and when, in `record_changes`, kept for the life of the
   record instead of ninety days. `GET /api/records/{model}/{id}/history`
   serves it, newest first; the record sheet shows it under the fields on
   every surface; `cm <quill> history <id>` on the command line. Never a
   value: the log says *bram changed phone and notes on Tuesday*, and the
   record says what they are now. People act under responsibility, and
   responsibility is visible.
4. **Not in this, and said so:** hiding one field from some people; a
   guardian reading a child's personal records; access by time.

*Done when:* one person is given read on the budget without a circle made
for them, a Quill's install sheet shows who gets its data before it is
installed, and a contact's sheet shows who changed what and when.

### Phase 2 — Lists and kinds

Reference lists in the datamodels repository, `lists/<id>.toml`: a list of
`{ value, label }` with an optional `deprecated` flag, versioned with the
repository. An `enum` field may say `values = "@currencies"` instead of
listing its own. `book.currency` and `deal.currency` move to it in their
next versions; `country` arrives on `contact` and `organisation` the same
way. A list is a picker on every surface, which enums already are, so no
new widget. Start with currencies and countries; units and languages when a
Quill asks.

A `money` kind (amount and currency together) is the one value type worth
its widget on five surfaces. Decide it after the lists land, when `deal`
shows what a decimal and a separate string cost in screens.

*Done when:* a deal's currency is picked, not typed, and a list changes by
pull request without a datamodel version.

### Phase 3 — Broaden the foundation

New domains in the datamodels repository, decided and written by us, each
with a Quill of ours that uses it so the shapes are proven on a screen
before release. In order:

| domain | datamodels | reuses |
| --- | --- | --- |
| Home | `item` (name, quantity, unit, where, photo), `expense` (amount, when, who, category, receipt) | `contact` |
| Projects | `project` (a space), `time_entry`; `task` v2 gains `project` | `task`, `contact` |
| Invoicing | `quote`, `invoice`, `line` — an issued document keeps its lines as written, whatever changes later | `organisation`, `contact`, `book` |
| Membership | `association` (a space), `membership` (from, to, kind), `donation` | `contact` |

Workforce, inventory, purchasing and accounting wait until somebody who
runs one asks. A Quill that needs a shape outside the foundation introduces
it as an extended datamodel, and that is where it stays unless we take it
in. Home goes first because the catalog's Home shelf holds only Chat.

### Kept out, on purpose

- **Party, PartyRole, ContactPoint, PartyAddress** and the rest of the
  normalised identity model. A person who is a customer and a volunteer is
  one `contact` in two books, or one contact with two Quills' extension
  fields on it. A typed link says what a Party reference would, with one
  table fewer.
- **Semantic versions, lockfiles, side-by-side majors.** Integers, pinned
  by the catalog, additive only.
- **Dataset provenance with checksums and licence review.** The lists we
  need are short, are facts, and are typed into a TOML file reviewed by
  pull request like any field.
- **Permissions per field, retention policies, legal holds, governance
  packs.** Access that is a spreadsheet is not delightful, and nobody on
  one box asks for it. The control that keeps data safe is three words on
  a datamodel and a log of who did what.
- **Export and import.** Not needed until there is somewhere to take the
  data. The sealed database and its key are the backup, and the record API
  hands out every record as JSON today. When a hosted tenant exists,
  leaving it must be easy on that day, and that is when a whole-server
  export arrives, with each datamodel naming its format (vCard for a
  contact, iCal for an event, CSV for anything flat).
- **Installation profiles** as a fourth kind of thing. If wanted, a named
  tick-set in the catalog, not a layer.
- **Reviewed merges of duplicate contacts.** A real wish, later, as a Quill
  action.
