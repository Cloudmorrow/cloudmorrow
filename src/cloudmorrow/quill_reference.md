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
kit = "list"                       # list, board, detail, form, calendar, grid, editor, thread
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

Code, when declaring is not enough. The server runs it, as the administrator
who installed the Quill, and it reaches only what the Quill declared:

```toml
[[services]]                       # a program the core starts and keeps running
id = "sync"
command = ["python", "services/sync.py"]   # "python" is the server's own Python
always = true                      # started again if it exits (with backoff)

[[jobs]]                           # or: run a service now and then, never twice at once
id = "nightly"
action = "run"
service = "sync"                   # a service a job names is only started by the job
every = "1d"

[[webhooks]]                       # POST /hooks/<quill>/<path>, with the webhook's secret
id = "inbound"
path = "inbound"
model = "plants.plant"             # the JSON body becomes a record…
map = { name = "$.plant.name" }    # field = a path into the body: $.a.b[0].c
# forward = "sync"                 # …or the request goes to a service instead
# signature = "X-Hub-Signature-256"  # also accept a GitHub-style HMAC of the body

[[apis]]                           # /api/q/<quill>/… proxied to a service, for people signed in
id = "public"
service = "sync"
# prefix = "v1"                    # only paths under /api/q/<quill>/v1/
```

A service is started in the Quill's folder with only these in its
environment — nothing of the server's:

| variable | what |
| --- | --- |
| `CLOUDMORROW_URL` | the server, on loopback |
| `CLOUDMORROW_TOKEN` | the Quill's own token: the record API, its declared datamodels only |
| `CLOUDMORROW_QUILL`, `CLOUDMORROW_SERVICE` | its id, and which service this is |
| `PORT` | a free loopback port to serve on, for an API or a forwarded webhook |
| `HOME` | a folder of its own that survives updates |
| `PATH`, `LANG`, `PYTHONUNBUFFERED` | so programs are found and output is logged as it comes |

It uses the record API like any client: `GET/POST /api/records/<model>`,
`GET/PATCH/DELETE /api/records/<model>/<id>`, `POST …/<id>/move`. An API
request arrives at `/<path>` with `X-Cloudmorrow-User: <who is asking>` (never
their token); a forwarded webhook arrives as `POST /hooks/<path>` with
`X-Cloudmorrow-Webhook: <id>`, its secret already checked. What it prints goes
to its log (`cm quill logs <quill> <service>`). Only the standard library is
certain to be there. A whole service, `services/sync.py`:

```python
import json, os, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

URL, TOKEN = os.environ["CLOUDMORROW_URL"], os.environ["CLOUDMORROW_TOKEN"]

def records(method, path, body=None):
    request = urllib.request.Request(
        URL + "/api/records/" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.loads(answer.read() or b"null")

class Api(BaseHTTPRequestHandler):
    def do_GET(self):                           # GET /api/q/plants/count
        who = self.headers["X-Cloudmorrow-User"]
        body = json.dumps({"asked_by": who, "plants": len(records("GET", "plants.plant"))})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

print("up", flush=True)                         # into its log
ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Api).serve_forever()
```

The records it reads and writes are the installing administrator's; a service
per person is not there yet.

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
A datetime without a zone is the wall clock, kept as typed; a bare date is a
whole day. Filter a list with `?field=value`, or a range with `__lt`,
`__lte`, `__gt`, `__gte` on an indexed field.
`stamp` sets a datetime when another field takes a value and clears it when it
leaves. `secret = true` on a string or text field keeps it out of every listing
and has every surface draw it hidden until asked for.

## The kit

| kit | needs | draws |
| --- | --- | --- |
| list | model, title; optional subtitle, tick (bool), fields (the sheet's), group and subgroup (link, enum or indexed string) | rows, a circle per row if tick; chips (phone, web) or a list and buttons (terminal) to pick the group and subgroup |
| board | model, lane (enum, in ordered_within), title; optional group (link: chips), body (markdown), done (a lane value) | lanes; cards dragged between them |
| detail / form | model; optional fields = [...] | one record's fields, editable |
| calendar | model, starts, ends (indexed datetime/date), space (a link to a space datamodel); optional all_day (bool), colour (a field of the space), subtitle | every space's things at once: a month, a week, the day's list; the spaces and their people |
| editor | model, title, body (markdown); optional path (a string like folder/sub/title: the folders) | a tree of folders and records beside a page of Markdown; pictures where the backend keeps attachments |
| grid | a model with bytes beside its fields (the foundational `file`); group (link: the places, picked first), folder (string), kind (an enum with "folder"); optional size, modified, mime, group_subtitle and group_open (fields of the group's model) | the groups, then folders and tiles with pictures; put in, get, new folder, rename, move, delete |
| thread | model (in a space), space (its link to the space), body; optional about (a field of the space), made_as | the spaces with unread counts, then a conversation: newest at the bottom, grouped by author and day, a box to write in |

A thread's `made_as` says what fields a space gets for how it is made — by
scope, or `direct`: a shared space found-or-made between you and the person
you pick, named for them (its fields must be indexed):

```toml
[screens.made_as]
public = { kind = "public" }
shared = { kind = "private" }
direct = { kind = "direct" }
```

On the command line a thread is `cm <quill> list` (the spaces, with unread),
`show <space>` and `say <space> "text"`.

Every screen opens a record sheet when a row or card is chosen: every field,
with the widget for its kind, editable, with delete. An editor opens its page
instead. No other UI exists, on
purpose: what the kit cannot say, the kit grows to say, for every Quill at once.

## Rules

- Never ship UI code, HTML, or CSS. Use the kit.
- Never invent a second kind of something that is already a datamodel; extend it.
- Extension fields cannot be required.
- Everything you read or write that you did not introduce is in `[uses]`,
  `[[extends]]` or `[[grants]]`.
- Uninstalling a Quill never deletes records.
