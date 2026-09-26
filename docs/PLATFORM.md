# Cloudmorrow as a platform: your data, your apps

> **Now:** apps are **Quills** and elements are **datamodels** —
> foundational or extended — and each Quill lives in its own repository and
> is found in the Quill Catalog. The contract, and what is built, is
> [QUILLS.md](QUILLS.md). This page is the reasoning behind it.

The angle: Cloudmorrow is where your data lives — files and a database, on
hardware you own or a tenant you rent, whether you are a person, a company
or an institution — and the apps are things that sit around that data with
clearly drawn access to it. Notes, tasks, chat and calendar happen to come
in the box. A shopping list, a reading log, a budget, an inventory, a
place for a project's mail, you fetch from the store or add yourself: from
a phone, in plain words, with an assistant that builds it, and it turns up
in every client you have. The platform makes that possible by giving every
app the same four things for free: storage, guarded access, standard
screens on every device, and tools an assistant can use.

This page is the plan for getting there from what the code is today. It
is written against the actual repository, so each layer says what it grows
out of.

## What it is, in four layers

| layer | what it is | what it grows out of |
| --- | --- | --- |
| **Data** | Files, and a database of records of catalogued types, sealed at rest, searchable | the notes tree, My Files and shares; the per-feature SQLite tables and the `SEALED` scope binding |
| **Guard** | Who may touch which type or folder, declared, approved, listed, revocable | the feature switches, the three access kinds in chat and calendar, MCP connections you can cut off, agent tokens |
| **Kit** | A small vocabulary of screens — list, detail, form, board, calendar, thread, grid, editor — each rendered by every client | the web app's one-file-per-feature screens and `registerTab`, the TUI panes, `cm RESOURCE ACTION` |
| **Apps** | A manifest naming the types it uses, the grants it asks for and its screens; the included apps are just the first manifests | Notes, Tasks, Calendar, Chat, Secrets, Files as they are |

And two things across all four:

- **Every device.** A manifest is rendered by the phone app, the desktop
  browser, the terminal app, and the command line, and is exposed as MCP
  tools. Five surfaces, one description, nothing per-surface to write.
- **An assistant, in and above.** In: every app's records are tools an
  assistant can use, as you. Above: an assistant can write a manifest, so
  building an app is a conversation. On the hosted tenant the assistant is
  included; on your own server you connect your own.

## The data layer

The full concept — elements, standard and extension fields, the record
envelope, scopes, storage, revisions, the change feed, export, and the
registry and store — is [DATA.md](DATA.md). This section is the short
form, and where the two differ, DATA.md wins.

**Types, not collections.** The first version of this page had each app
declaring collections of its own. That is the wrong unit: it makes a
contact the contacts app's, and the whole point is that a contact is
*yours*. So the platform catalogues **types** — `contact`, `note`, `task`,
`message`, `secret`, `user` — and an app *uses* types, *augments* one with
fields of its own (namespaced, so two apps' additions never collide), or
*introduces* a new one, which joins the catalogue for every other app the
person allows. The catalogue exists today: `GET /api/types` lists every
kind of data on the server with its fields, its scopes, what is sealed,
which apps use it and whether an assistant may reach it. It is metadata
until the record store arrives; then it is the schema.

**Records of a type.** The platform stores them in SQLite in one table:

```
records(type, id, scope_kind, scope_id, owner, written_by,
        indexed JSON, body SEALED, created_at, updated_at)
```

`body` is the record, sealed exactly the way a chat message is today, with
the seal bound to `(type, scope)` so a record cannot be moved between
types or people by editing the database. `written_by` says which app put
it there, for the audit line, and nothing else: it confers no ownership.
`indexed` holds the few fields the type marks as filterable or sortable —
a due date, a lane, a status — plain, the way lanes and timestamps are
plain now. This is the same split the code already makes: content sealed,
what the server must find by in the clear.

**Three scopes, borrowed whole.** A record is *personal* (one owner),
*shared* (a named set of members), or *public* (everybody on the server).
Chat channels and calendars already work exactly this way and the rule has
held up; it becomes the platform rule so every app gets sharing without
designing it.

**Files.** Each app gets a folder in each person's tree,
`<user>/apps/<app>/`, and may ask for others by grant. Notes stays a
files app: a note is a file, and that is a feature, not a legacy.

**Search.** The notes search opens each file and scans it; records search
the same way, per type, in Python, because nothing on a home server
is big enough to need an index yet. When one is, it is one place to add.

**Secrets are in, as the first foundation type.** Vaults of keys and
passwords are the person's, stored by the server, and listed in the
catalogue with `assistant: false`. An app is *given* a secret by name when
the person says so — the grant names the key, never the vault — and an
assistant is never given one. Projects, which used to own them, are gone.

## The guard

**Principals.** A person, an app, an assistant (an MCP connection), a
machine (an agent). The last three already have credentials of their own;
apps get one in the same shape.

**Resources and actions.** A type, or one secret by key, or a folder; `read`, `write`,
`admin`. Nothing finer for the first version: a permission model people
can hold in their head is worth more than one that can express everything.

**Grants are declared and approved.** A manifest says which types the app
uses — what it introduced is granted implicitly — and what else it asks
for:

```toml
[[grants]]
type = "event"
access = "read"
why = "to show what is on the day beside the list"

[[grants]]
type = "secret"
key = "OPENWEATHER_API_KEY"
access = "read"
why = "to fetch the forecast"
```

The catalogue already says which types each included app uses
(`/api/server/features` lists them), which is the declared half of this
with nothing yet enforcing it.

Installing the app shows that list on a page, the same page an assistant
gets when it signs in over OAuth today, and the person says yes. The
Administration panel gains one screen, **Apps**, that lists every app and
every assistant with what each may see, and a switch to cut any of it.
That screen is the product: the reason to run this rather than five
services that each hold everything.

**One gate.** Every read and write of a record or a file goes through one
function that takes `(principal, action, type, scope)`, and the existing
feature routers move behind it one at a time. A permission system is only
as good as the number of doors it does not cover, and the way to have one
door is to build it and then walk everything through it.

**An audit line.** Every access by an app or assistant leaves a row:
who, what, when. Nothing pushes it at you; it is there to read on the Apps
screen, the way notifications already are.

## The kit

**The vocabulary.** Eight elements, because that is how many kinds of
screen the six included apps turned out to need:

| element | binds to | already exists as |
| --- | --- | --- |
| `list` | a type, with a sort and a filter | the notes list, the vault list |
| `detail` | one record, with its fields and its actions | a secret's row, revealed |
| `form` | one record, to make or change | every new-thing sheet |
| `board` | a type with a lane field | Tasks |
| `calendar` | a type with start and end fields | Calendar |
| `thread` | a type ordered by time, appended to | Chat |
| `grid` | a folder | Files |
| `editor` | a file, markdown, with pictures | Notes |

Plus `today` cards, which any app may contribute one of, and the settings
switch every app gets for free.

**A screen is an element bound to data.** A manifest's screens are these
elements pointed at its types, with a few options each. The renderer
for `board` in the web app is the Tasks screen with the type name
made a parameter; the renderer in the TUI is the tasks pane the same way.
This is the whole trick: not building a UI framework, but taking the six
screens that exist and letting a manifest choose which of them to draw and
on what.

**Escapes.** An app that needs a screen the vocabulary cannot express gets
one on the web only, as a custom element that talks to the data API, and
the terminal app shows what it can — the list and the detail. Better a
gap named than a vocabulary that grows until nothing renders it.

**Three renderers, one contract.** Web (phone and desktop are already one
codebase), terminal, and the command line, which needs no rendering at
all: `cm shopping list`, `cm shopping add "milk"` fall straight out of the
manifest, in the `RESOURCE ACTION` shape the CLI already has.

## Apps

**A manifest** is one file. The first one to write, and the one to test
the kit against, is something that is not in the box:

```toml
[app]
id = "shopping"
name = "Shopping"
icon = "cart"

[[types]]                              # a type this app introduces: now everybody's
key = "shopping_item"
label = "Shopping item"
scope = "shared"                       # the household's list, not one person's
indexed = ["done", "shop"]
[types.fields]
text = "string"
shop = "string"
done = "bool"

[[screens]]
element = "list"
type = "shopping_item"
sort = "done, created_at"
tick = "done"                          # a list with a box on each row

[[today]]
text = "{{ count(shopping_item, done=false) }} things to buy"
```

That is an app. It has a tab in the phone app and the terminal, a `cm
shopping` command, four MCP tools, a card on Today, a new row in
`/api/types` that any other app may now ask for, and a row on the Apps
screen saying it introduced one type and asks for nothing else.

**The included apps become manifests**, in this order, each proving a
piece of the kit: Tasks (`board`, personal scope), then Calendar and Chat
(`calendar`, `thread`, shared and public scope, members), then Secrets
(`list` + `detail`, with the vault list as the first `list` of a foundation
type), then Files and Notes, which are file-backed and keep their own code longest. When the
last one is a manifest, the kit is real; until then it is a promise.

**Logic.** Most apps need none: the elements carry create, change, move,
tick, delete. For the rest, in two steps:

1. *Automations*, declared: "when a record in `tasks.items` gets
   `lane = done`, post to `chat.house`". A small set of triggers and
   actions, all through the gate as the app's principal, so an automation
   cannot reach what its app cannot.
2. *Out-of-process apps*, later: an app that is its own program talks to
   the API with an app token, exactly as a machine's agent does today, and
   is bound by the same grants. Connectors — email over IMAP, a CalDAV feed
   — are these. They are how "your email lives here too" happens without
   the mail client living inside the server.

**Where apps come from.** A folder of manifests on the server, installed
by pasting a git URL or by an assistant writing one. A directory of them
is a repository on GitHub, nothing more.

## The assistant

**Every app is tools.** Today `mcptools.py` hand-writes one tool per
action per feature. The record store makes that generic: every type in
the catalogue marked `assistant`, that the signed-in person may reach,
becomes `list`, `search`, `create`, `update`, `delete` tools with the
type's fields as the schema. The hand-written tools go as each app becomes a manifest.
Grants apply to the assistant as to anyone: an assistant the person let in
sees what the person sees, minus what the person switched off for it.

**Building is a tool call.** `create_app(manifest)` and
`update_app(id, manifest)`, admin only, validated and rendered on the spot.
"Make me a place to track the plants and when I watered them" is one call
that writes eight lines of TOML, and the app is on the phone before the
sentence is finished. Iterating is the same call again.

**Two ways to have one.**

- *On your own server:* connect the assistant you already have, as now — the MCP
  address and the sign-in page. Nothing to pay us for.
- *On the tenant:* the assistant is in the app, on every device, with the
  tenant's MCP tools as its tools and its usage in the price. Server-side,
  that is one endpoint that calls the Anthropic API with the tenant's own
  tool list, through the official SDK, as the signed-in person. Self-hosters
  get the same endpoint with their own API key in the config.

## Phases

Each phase ends with something a person can use, and the next one does
not start on a promise.

**Phase 1 — The data layer and the gate.** The records table, sealed and
scoped. The gate, and the Tasks routes moved behind it as the first
tenant. Generic MCP tools over any type. The Apps screen listing
the six built-in apps and every assistant, with what each may see.
*Done when:* Tasks runs on records with no feature-specific table, and an
assistant reaches tasks through the generic tools only.

**Phase 2 — The manifest and the kit, web first.** The manifest format
and its loader. `list`, `detail`, `form` and `board` as web elements. The
shopping app above, from a manifest, on the phone. `create_app` as an MCP
tool. *Done when:* an assistant makes a new app in a conversation and it
is on the phone without a deploy.

**Phase 3 — Every device.** The same four elements in the terminal app,
and the generic CLI. Then `calendar`, `thread`, `grid` in both. Calendar
and Chat become manifests. *Done when:* the shopping app is in the
terminal and on the command line, and Calendar and Chat have no code of
their own beyond their manifests.

**Phase 4 — Grants and automations.** Cross-app grants with the consent
page, the audit line, declared automations. Secrets become grantable by
key, to apps and never to assistants. *Done when:* an app that asks for another app's
data has to be allowed, and the Apps screen shows every such allowance.

**Phase 5 — Apps from outside.** Install from a git URL. App tokens for
out-of-process apps. The first connector: a read-only mail archive over
IMAP into a `mail_message` type, rendered with `thread` and `detail`. *Done when:*
somebody's mail is in their Cloudmorrow and only the mail app can see it.

**Phase 6 — The assistant included.** The in-app assistant on the tenant,
metered; bring-your-own-key on your own server. This is where the two earlier plans
meet: [HOSTING.md](HOSTING.md) puts the tenant and the Pi in people's
hands, and this puts the builder in the app.

Files and Notes stay as they are throughout; they are the files half of
"files and a database", and they are already what the platform says
everything should be.

## What this costs, honestly

- **Six apps rebuilt.** The kit is only true when the included apps are
  manifests. That is the bulk of the work and there is no way to skip it
  that leaves the story standing. The order above puts the easy proof
  first and the file-backed apps last.
- **A vocabulary is a ceiling.** Eight elements cover a shopping list, a
  budget, contacts, a reading log, a habit tracker, an inventory — most of
  what a person, a company or an institution would ask for. They do not cover a
  map, a chart, a game. The web-only escape hatch is the answer, and it is
  a worse experience than the vocabulary on purpose, so the vocabulary
  gets the pressure.
- **Three renderers per element.** Every element is written three times.
  The mitigation is that two of them already exist for every element, as
  the six apps; the work is parametrising, not inventing.
- **One gate or none.** The guard is a story until the last feature
  router is behind it. Phase 1 puts one there; phases 3 and 4 finish the
  walk. Until then the Apps screen must say which apps are not yet under
  it, rather than imply they are.
- **A document store on SQLite.** Right for one household, one company or
  one institution; every design above keeps the content sealed and the lookups
  plain so that swapping the store later is a storage change, not a
  product change.
- **Email is a product.** A read-only archive is a connector; a mail
  client is a year. Phase 5 does the first and says so.

## Where to start, this week

1. `server/records.py`: the table, sealed under a new `SEALED` version,
   with the three scopes and the gate function, keyed by the types in
   `server/types.py`, which now exists.
2. `server/tasks.py` rewritten on it, its routes unchanged to the outside,
   its tests unchanged and passing. This is the proof that the store is
   enough.
3. `mcptools.py` gains generic tools over the catalogue's types; the task tools are
   deleted the day the generic ones pass the same tests.
4. The Apps screen, listing what exists, so the guard has a face before it
   has teeth.

Then the shopping manifest, and the first app nobody wrote.
