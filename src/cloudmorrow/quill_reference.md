# Writing a Quill

A Quill is a Cloudmorrow software package: one folder (one repository) with a
`quill.toml` at its root. It declares data and screens; the core does the rest.
The same Quill is drawn on the phone, the full web app and the terminal, is a
`cm <quill>` command, and is tools for an assistant. You never write UI code.

## The loop

1. `cm quill check` — validate the manifest against the datamodels, and see a
   text preview of each screen. Fix what it says; it says it plainly.
2. `cm quill dev` — install this folder on your own server as a development
   Quill. Every surface has it at once. Run it again after a change.
3. Tag a release (`v1.0.0`) and open a pull request on
   `Cloudmorrow/quill-catalog` adding the Quill to `catalog.toml`.

Over MCP an administrator's assistant has the same loop: `quill_schema`,
`quill_check`, `quill_dev_install`.

## quill.toml

```toml
[quill]
id = "plants"                      # lowercase, 2-32 of a-z 0-9 _
name = "Plants"
version = "1.0.0"                  # major.minor.patch
summary = "Your plants, and when you last watered each."
category = "home"                  # home, personal, business, developer, …
icon = "plants"
publisher = "you"
license = "MIT"
features = ["One line per thing it does, for the catalog"]

[uses]
datamodels = ["task"]              # foundational datamodels, by id

[[extends]]                        # your own fields on a foundational datamodel
model = "task"
[extends.fields]
room = { kind = "string", indexed = true }      # stored as "plants.room"

[[grants]]                         # anything else you read or write, with a reason
model = "contact"
access = "read"                    # read or write
why = "to show who looks after each plant"

[[screens]]                        # one tab per screen, on every surface
id = "plants"
kit = "list"                       # list, board, detail, form, grid (calendar, thread, editor: next)
label = "Plants"
model = "plants.plant"
title = "name"
subtitle = "last_watered"
tick = "healthy"                   # a bool field: a circle on each row

[[jobs]]                           # work the core does for you
id = "forget-dead"
action = "expire"                  # delete records whose `field` is older than `after`
model = "plants.plant"
field = "died_at"
after = "30d"
every = "1d"

[[datasets]]                       # records that come with the Quill
id = "first-plant"
model = "plants.plant"
seed = "per-owner"                 # once for each person who has none
records = [{ name = "{owner}'s first plant" }]
# or: file = "datasets/plants.csv"  (CSV with a header row, or TOML [[records]])
```

Code, when declaring is not enough (validated and listed today; run by the
core in the next release):

```toml
[[services]]                       # a program the core keeps running
id = "sync"
command = ["python", "services/sync.py"]
always = true

[[webhooks]]                       # POST /hooks/<quill>/<path>
id = "inbound"
path = "inbound"
model = "plants.plant"             # the JSON body becomes a record…
# forward = "sync"                 # …or goes to a service

[[apis]]                           # /api/q/<quill>/… proxied to a service
id = "public"
service = "sync"
```

A service gets `CLOUDMORROW_URL` and `CLOUDMORROW_TOKEN` and uses the record
API like any client: `GET/POST /api/records/<model>`,
`GET/PATCH/DELETE /api/records/<model>/<id>`, `POST …/<id>/move`.

## Datamodels you introduce

One TOML file each, in `datamodels/`, with an id under your Quill's:

```toml
[datamodel]
id = "plants.plant"
version = 1
label = "Plant"
description = "A plant you look after."
scopes = ["personal"]              # personal only, for now
title = "name"                     # what a record is called in a list
# ordered_within = ["room"]        # keep a position inside each group (boards need it)

[fields]
name = { kind = "string", required = true }
room = { kind = "enum", values = ["kitchen", "bedroom"], labels = ["Kitchen", "Bedroom"], indexed = true }
healthy = { kind = "bool", default = true, indexed = true }
last_watered = { kind = "date", indexed = true }
died_at = { kind = "datetime", indexed = true, stamp = { field = "healthy", value = "false" } }
notes = { kind = "markdown" }
owner = { kind = "link", to = "contact", on_delete = "clear" }
```

Field kinds: string, text, markdown, bool, int, decimal, date, datetime, enum,
email, phone, url, link, json. `indexed` fields are plain on disk so the server
can filter and sort by them; everything else is encrypted at rest. Links are
record ids and are always indexed. `on_delete` is `cascade` or `clear`.
`stamp` sets a datetime when another field takes a value and clears it when it
leaves.

## The kit

| kit | needs | draws |
| --- | --- | --- |
| list | model, title; optional subtitle, tick (bool) | rows, a circle per row if tick |
| board | model, lane (enum, in ordered_within), title; optional group (link: chips), body (markdown), done (a lane value) | lanes; cards dragged between them |
| detail / form | model; optional fields = [...] | one record's fields, editable |
| grid | a model with bytes beside its fields (the foundational `file`); group (link: the places, picked first), folder (string), kind (an enum with "folder"); optional size, modified, mime, group_subtitle and group_open (fields of the group's model) | the groups, then folders and tiles with pictures; put in, get, new folder, rename, move, delete |

Every screen opens a record sheet when a row or card is chosen: every field,
with the widget for its kind, editable, with delete. No other UI exists, on
purpose: what the kit cannot say, the kit grows to say, for every Quill at once.

## Rules

- Never ship UI code, HTML, or CSS. Use the kit.
- Never invent a second kind of something that is already a datamodel; extend it.
- Extension fields cannot be required.
- Everything you read or write that you did not introduce is in `[uses]`,
  `[[extends]]` or `[[grants]]`.
- Uninstalling a Quill never deletes records.
