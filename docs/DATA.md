# The data concept

Cloudmorrow is the place your data lives. Apps come and go — from the
store, from a friend, from a conversation with an assistant — and the data
stays, yours, in shapes every app agrees on. This page is the concept for
that: what a piece of data is, how apps share it without owning it, how
one app's additions become something the next app can use, and how it is
all stored, guarded and carried out again.

Nothing here is in production, so nothing here is constrained by what is
stored today. The catalogue in `server/types.py` is the seed of it and
gets replaced by what this page says.

## Five rules

1. **Data belongs to a person, never to an app.** An app reads and writes
   records the person let it at. Deleting the app deletes nothing.
2. **Every record is of an element.** A contact is a contact whichever app
   made it. Elements are standard, published, versioned, and few.
3. **Apps extend, they do not fork.** An app that needs more on a contact
   adds fields under its own name. It never makes a second kind of contact.
4. **Every record is portable.** Each element says how it leaves — vCard,
   iCal, Markdown, `.env`, JSON at worst — and the export is complete.
5. **One gate.** Every read and write, by anyone, goes through the same
   check: this principal, this action, this element, this scope.

## The vocabulary

| word | meaning |
| --- | --- |
| **element** | A kind of data, standard across every app: `contact`, `task`, `event`. Published by the registry at cloudmorrow.com, versioned. |
| **record** | One piece of data of one element: this contact, that task. Has an id, an owner, a scope, a revision. |
| **standard field** | A field every record of the element has, defined by the element: a contact's `name`, a task's `lane`. |
| **extension field** | A field an app added to an element, under the app's name: `com.example.crm/deal_stage` on a contact. Any app may read it; the app that added it writes it. |
| **scope** | Who a record is for: `personal` (one owner), `shared` (named members), `public` (everybody on the server). |
| **link** | A typed reference from one record to another: this task's `assignee` is that contact. |
| **attachment** | A file kept with a record: the photo on a note, the receipt on an expense. |
| **revision** | Every write bumps it. Two clients writing the same record meet a 409, the way notes already do. |
| **change** | A row saying a record was created, changed or deleted, by whom, when. What automations and sync are built on. |
| **app** | Something that uses elements, extends them, or introduces new ones, with declared grants. Identified like an element: `com.cloudmorrow.notes`, `io.bramlabs.budget`. |

## Elements

**Identity.** An element is named in reverse-domain form and versioned by
an integer: `com.cloudmorrow.contact@1`. The registry at
`https://cloudmorrow.com/elements/contact` is where the definition lives;
a server holds a copy of every element it has records of, so a server
never depends on the registry to run. Anyone may publish an element under
their own domain — `io.bramlabs.plant@1` — and the store lists them beside
the standard ones. The standard ones are the ones under `com.cloudmorrow`.

**What an element defines.**

```toml
[element]
id = "com.cloudmorrow.contact"
version = 1
label = "Contact"
description = "A person or organisation you know: how to reach them, and how you know them."
scopes = ["personal", "shared"]       # never public: a contact list is not a phone book
export = "vcard"                      # how a record of it leaves

[fields]                              # the standard fields, in display order
name = { kind = "string", required = true, indexed = true }
kind = { kind = "enum", values = ["person", "organisation"], default = "person" }
emails = { kind = "list", of = "email" }
phones = { kind = "list", of = "phone" }
addresses = { kind = "list", of = "address" }
birthday = { kind = "date" }
organisation = { kind = "link", to = "com.cloudmorrow.contact" }
notes = { kind = "markdown" }
photo = { kind = "attachment" }

[sealed]                              # what is ciphertext at rest
fields = ["emails", "phones", "addresses", "birthday", "notes"]
```

**Field kinds.** Deliberately few, because every client must draw every
one and every export must carry every one: `string`, `text`, `markdown`,
`bool`, `int`, `decimal`, `money`, `date`, `datetime`, `duration`, `enum`,
`email`, `phone`, `url`, `address`, `geo`, `list` (of one kind), `link`
(to an element), `attachment`, `json` (the escape hatch, unindexable and
undrawn). A kind carries its own validation, its own widget in each client
and its own column in an export; adding a kind is adding all three.

**Indexed fields** are the ones kept plain for the server to filter and
sort by. Everything else is sealed. An element chooses; the default is
that only `name`-like fields and enums are indexed, so the plaintext on
disk stays a list of titles and states, which is what the code already
does for tasks and events.

**The starter catalogue.** Enough that the included apps run on it and a
person, a company or an institution finds what it expects, and no more:

| element | standard fields, in short | export |
| --- | --- | --- |
| `contact` | name, kind, emails, phones, addresses, birthday, organisation, notes, photo | vCard |
| `place` | name, address, geo, notes | vCard (as a location) |
| `note` | title, body (markdown), attachments | Markdown file |
| `task` | title, body, lane, due, assignee → contact, board → board | Markdown checklist |
| `board` | title | — |
| `event` | title, starts, ends, all_day, place → place, attendees → contact, notes, calendar → calendar | iCal |
| `calendar` | name, colour | iCal |
| `message` | body, author → user, thread → thread, sent | JSON |
| `thread` | name, kind, topic | JSON |
| `file` | path, size, mime, modified | the file |
| `secret` | vault, environment, key, value | `.env` |
| `user` | username, display_name, role | — |
| `machine` | name, hostname, platform, last_seen | — |
| `bookmark` | url, title, notes, tags | Netscape bookmarks |
| `item` | name, description, quantity, unit, where → place, photo | CSV |
| `expense` | amount (money), when, what, who → contact, category, receipt | CSV |

`item` and `expense` are there because a shopping list, an inventory and
a budget are the first three things people ask for, and each is a
list of one of these. Everything an app needs beyond this is an extension
or a new element, and the bar for a new *standard* element is that two
unrelated apps wanted it.

## The record envelope

Every record, of every element, carries the same envelope. Apps never see
a bare row; they see this:

```json
{
  "id": "rec_01J8ZK7Q3M9W",
  "element": "com.cloudmorrow.task@1",
  "scope": { "kind": "shared", "id": "house" },
  "owner": "alice",
  "rev": 7,
  "created_at": "2026-09-22T08:10:00Z",
  "updated_at": "2026-09-22T09:41:00Z",
  "written_by": "com.cloudmorrow.tasks",
  "tags": ["garden"],
  "fields": {
    "title": "Repot the fig",
    "lane": "doing",
    "due": "2026-09-27",
    "assignee": "rec_01J8ZG4T2KQ0"
  },
  "ext": {
    "io.bramlabs.plants": { "plant": "rec_01J8ZJ2H8C1R", "reminder": "weekly" }
  },
  "links": [
    { "role": "assignee", "to": "rec_01J8ZG4T2KQ0" },
    { "role": "io.bramlabs.plants/plant", "to": "rec_01J8ZJ2H8C1R" }
  ],
  "attachments": []
}
```

- `fields` are the element's standard fields. `ext` is every extension,
  keyed by the app that declared it. The two are drawn together on a
  screen and exported together; the split exists so nobody has to guess
  which is which.
- `written_by` is a fact for the audit line, not ownership. The record is
  Alice's whichever app wrote it.
- `tags` are universal: every element has them, every list can filter by
  them, and no app needs to invent a tagging scheme.
- `links` are derived from `link` fields, standard and extended, and kept
  in their own table, so "everything linked to this contact" is one query
  across every element.

## Extensions

An app that needs more on an element declares it:

```toml
[app]
id = "io.bramlabs.plants"

[[extends]]
element = "com.cloudmorrow.task"
[extends.fields]
plant = { kind = "link", to = "io.bramlabs.plant" }
reminder = { kind = "enum", values = ["daily", "weekly", "monthly"] }
```

The rules that make this safe to allow by default:

- **Namespaced by the app.** The fields live under `ext["io.bramlabs.plants"]`.
  Two apps adding `reminder` to a task never collide.
- **Readable by anyone who may read the record.** An extension is part of
  the record; an app with `read` on tasks sees the plant app's fields. This
  is the point: the plant app's data is the person's, and the calendar app
  may show the watering reminder if it likes.
- **Written by the app that declared it**, and by the person, in any
  client, because it is drawn like any other field. Another app that wants
  to write it asks for that in its grants, by name.
- **Never required.** An extension field cannot be `required`; a task made
  by the tasks app is a whole task without the plant app's opinion.
- **Promotion.** When a second app declares the same field on the same
  element, that is the signal to make it standard in the next version of
  the element. The registry sees both declarations; the standard field
  arrives with a migration that folds the extension into it.
- **Removal.** Uninstalling the app leaves its extension fields on the
  records, marked orphaned; the person is offered to drop them, and the
  export includes them until they do.

**New elements** are declared the same way, as `[[introduces]]`, with a
full definition. They are published to the server's own catalogue at
once, and to the registry when the app is published. From that moment
every other app may ask for them.

## Scopes and who is on the server

A server is one household, one company or one institution. Everybody on
it is a `user`, and the scopes are the three the chat and calendar already use:

- **personal** — one owner. Nobody else, not even an administrator, reads
  it through the API.
- **shared** — a named set of members: the house calendar, the sales team's
  contacts. The set is a record too (`com.cloudmorrow.circle`: name,
  members), so "the family" is defined once and used by every element.
- **public** — everybody on the server. The noticeboard, the office
  address book.

An element says which scopes it allows. Contacts cannot be public;
messages cannot be personal (a message to yourself is a note).

A company with departments is a server with circles. A company with
twenty offices is twenty servers, or a tenant each, and the registry is
what they share. Nothing here tries to be one database for a
conglomerate.

## Storage

One table for every record of every element, and the seal bound to what
must not change:

```
records(id, element, version, scope_kind, scope_id, owner, written_by,
        rev, created_at, updated_at, deleted_at,
        indexed  JSON   -- the indexed standard fields, plain
        body     SEALED -- fields + ext, everything else
        tags     TEXT   -- plain, space-separated, for LIKE and the tag list
)
links(from_id, role, to_id)                  -- derived from link fields on every write
members(scope_id, username)                  -- who is in a shared scope
changes(seq, id, element, op, by, at)        -- the feed
attachments(id, record_id, path, size, mime) -- files on disk, sealed like notes
```

The seal's associated data is `(element, scope_kind, scope_id)`: a
record moved to another person or another circle by editing the
database fails to open, which is the guarantee every sealed table gives
today. Notes stay files, because a folder of Markdown is the best
portable format there is; they are records with `body` on disk instead of
in the row, which the existing sealed-file machinery already does.

Search opens each record's body, in Python, per element — the way notes
search works — because, for now, nothing on a server is big enough for
an index. When it is, the indexed fields are already the columns, and
FTS over a plaintext shadow of chosen fields is one migration, not a
redesign.

Soft delete (`deleted_at`) with a thirty-day bin, because "the app I
uninstalled deleted my data" must never be a sentence anyone says.

## Revisions and the change feed

Every write takes the `rev` the writer last saw and refuses a stale one
with 409, carrying the current record — the conflict rule notes already
have, made universal. Every write appends to `changes`. That feed is:

- what a client polls to redraw (as the chat pane polls for messages);
- what an automation watches ("when a task's lane becomes done, post to
  the house thread");
- what a connector uses to push changes out (a CalDAV client that mirrors
  events);
- what the audit line on the Apps screen reads, filtered by `by`.

The feed keeps ninety days and is not a history: undo is the bin, not a
replay.

## Portability

Every element names an export format, and every app's data is included
in it because extensions are part of the record. `cm data export
contact` writes a vCard file with the plant app's fields as `X-` lines,
which is what vCard is for. `cm data export --all` writes a directory: one
folder per element, one file per record where the format is per-record,
one file per element where it is not, attachments beside them, and a
`manifest.json` naming every element and extension with its version. That
directory imports into another Cloudmorrow whole. This is the guarantee
under "you own your data", and it is checked by a test that exports a
seeded server, imports it into an empty one, and compares.

## The registry and the store

**cloudmorrow.com/elements** publishes element definitions: the standard
ones, and everyone else's under their own domain. A definition is a TOML
file and a page; the page shows the fields, which apps use it, and what
extensions exist on it in the wild. Versions are immutable.

**cloudmorrow.com/apps** publishes apps: a manifest, a page, a git URL,
and a donate link if the author wants one. The page says which elements
the app uses, extends and introduces, and what grants it asks for — the
same list the person sees on install. Reviews are records too, kept on
the store's own Cloudmorrow.

**Installing** is: fetch the manifest, show the grants, ask, and the app
is on every device. A server without internet installs from a file.

**Building** is the store in reverse. The builder — in the app, or an
assistant writing the manifest — starts from elements: drag `contact`
and `event` into an app, they arrive with their standard fields and
their screens, and the builder adds what is missing as extensions or a
new element. The standard fields are why a dragged-in contact list is a
working contact list before anything is typed, and why a contact made
in the new app is one every other app already understands. Publishing
is a git push and a form.

## The API and the assistant

Generic over elements, so a new element needs no new routes:

```
GET    /api/elements                       every element this server knows, with fields and who uses it
GET    /api/data/{element}?scope=&tag=&q=  list, filtered on indexed fields and tags, searched on the rest
POST   /api/data/{element}                 create
GET    /api/data/{element}/{id}            one record, envelope and all
PUT    /api/data/{element}/{id}            replace, with rev
PATCH  /api/data/{element}/{id}            change fields, with rev
DELETE /api/data/{element}/{id}            to the bin
GET    /api/data/{element}/{id}/links      everything linked to it, across elements
GET    /api/changes?since=                 the feed
```

The gate sits under every one of these. The included apps' routes today
(`/api/boards`, `/api/calendar/events`, …) become thin names for these
until the clients speak the generic ones, then go.

An assistant gets one tool per verb per element it may reach, generated
from the element's definition, with the fields as the schema. Secrets are
the element marked `assistant = false`, and stay so.

## From here to there

The catalogue in `server/types.py` is the first piece: the standard
elements and who uses them, as metadata. In order:

1. **Element definitions as data.** Replace the Python catalogue with
   TOML files under `elements/`, loaded at boot, with the `[element]`,
   `[fields]` and `[sealed]` sections above. `GET /api/elements` serves
   them. Add `contact`, `place`, `circle`, `item`, `expense`, `bookmark`.
2. **The record store.** The tables above, sealed, with revisions, links,
   tags, the bin and the change feed. The generic API on top. The gate,
   with today's rule — a person reaches their own records and their
   circles' — as its first policy.
3. **Tasks on records.** The first included app moved: its routes become
   names for the generic ones, its tests unchanged. Then calendar and
   chat, which bring shared and public scopes with them.
4. **Extensions and grants.** The manifest's `[[extends]]` and
   `[[grants]]`, the consent page, the Apps screen listing every app and
   assistant with its access, and the audit line from the feed.
5. **Export and import.** Per element, then `--all`, with the round-trip
   test.
6. **The registry and the store**, at cloudmorrow.com, as their own
   Cloudmorrow: elements and apps are records of `element` and `app`,
   which is the platform hosting its own catalogue and the best test it
   could have.
