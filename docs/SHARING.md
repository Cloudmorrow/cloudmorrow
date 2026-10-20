# Quills of your own: made, shared, promoted, published

A Quill is software, and software should be something anybody on a server
can make, change and pass on — as long as the data stays where the circles
put it. This page is the contract for that: a Quill one person installs for
themselves, over their own data; shared with the people they choose, each
over theirs; made the server's by an administrator; and published to the
Quill Catalog for everybody. [QUILLS.md](QUILLS.md) is the contract for a
Quill; [CIRCLES.md](CIRCLES.md) for who may use which data. Nothing here
widens either.

## The words

| word | what it is |
| --- | --- |
| **shelf** | What one person has: the server's Quills that are for them, their own, and the ones shared with them. `GET /api/quills` is a person's shelf. |
| **server Quill** | A Quill an administrator installed, for everyone or for an **audience**: the circles and people named on its install sheet. What every Quill was until this page. |
| **personal Quill** | A Quill of somebody's own: installed by them, for them, under `<data_dir>/quills-personal/<owner>/<id>/`. Its **key** is `~owner.id` — `~alice.budget` — wherever one name must do for every Quill on the server: the feature switch, the logs, the sandbox, a webhook's address. |
| **owner** | Whose personal Quill it is. Its jobs, webhooks and APIs run as them; its datamodels are named after them. |
| **shared** | Offered by its owner to people, and accepted by each. Then it stands on their shelf too — over the Quill's data, as the owner's rules let them, run as *them*. |
| **holders** | Everybody a personal Quill stands with: its owner, unless they took it off their shelf, and whoever accepted it. The Quill stays as long as one of them has it. |
| **rules** | What a share lets a person do with each datamodel of the Quill's own: `write`, or `read`. Set by the owner, per person. Nothing named is write. |
| **promoted** | Made the server's by an administrator: the same folder installed as a server Quill, with every record of its datamodels moved under the server's name for them. |
| **adopted** | The other order: a server Quill of the same id arrives (from the catalog, say) and somebody's own folds into it, records and all. |
| **exported** | Written as a repository would hold it — the folder in the template's shape — to be tested, pushed, released and submitted. |
| **forked** | A copy of a Quill one has, as one's own, under a new id, to change. |
| **the policy** | Four settings an administrator sets: may people have Quills of their own (`on`, `ask`, `off`), may those run code, may they be shared, may people make their own rather than only take them from the catalog. Each for the server, and each again per person, in front of the server's. |

## The rules

1. **A Quill never gives anybody the server's data.** Over the server's
   datamodels — `contact`, `task` — a shared Quill runs as the person it is
   shared with, through the gate, narrowed by their own circles, over
   records that are theirs to see. A Quill over `contact` on the shelf of
   somebody whose circles do not give `contact` draws no contact screen,
   for them. Nothing on this page widens what anybody sees of the server's
   data; that is what circles and spaces are for.
2. **A personal Quill changes nothing other people see.** It adds no fields
   to datamodels everybody shares (a field on a record is seen by everyone
   who sees the record), and it runs no services (a service runs outside
   the sandbox, as the server). Its own datamodels are never spaces nor in
   one. Everything else a Quill may do, it may: screens, views, actions,
   hooks, jobs, webhooks, handler APIs, machine handlers, fetch, secrets
   from the owner's vault.
3. **Its own data is the Quill's, and carries its owner's name.** What the
   folder calls `budget.envelope` the server knows as `~alice.budget.envelope`,
   so two people's Budgets never meet in the record store, and the one
   store knows every shape there is. The code is given its own names
   (`Manifest.resolve`, `plain`): it reads and writes `budget.envelope` and
   never sees the prefix. The files are left as written, so they publish as
   they are. The records of such a datamodel are one pool, the Quill's —
   public within it (`scope = 'public'`), not each writer's alone — so
   everybody the Quill stands with works on the same envelopes. Isolated
   from everybody else, and tied to the Quill: see rule 8.
4. **Access to a Quill's own data is a rule on the datamodel, set by its
   owner.** `~alice.budget.*` is reachable by alice (write) and by whoever
   accepted her Budget, each as her share's rules say — `write`, or `read`,
   per datamodel, per person; nothing named is write. The circles are not
   asked: it is the Quill's data, not the server's, whatever `*` says. To
   anybody else it is absent: not listed, 404. The gate asks the shelf
   (`Shelf.access_for`, `Narrowed`), which is the one gate every read and
   write already passes ([CIRCLES.md](CIRCLES.md), rule 5). Rights are set
   on data, never on a Quill.
5. **Nothing installs without a yes, and it is the right person's.** An
   administrator says yes to a server Quill, for everyone or an audience.
   A person says yes to one of their own, and to one shared with them, on
   the same install sheet, which says: *yours alone; runs code in a sandbox,
   as you; its own data is yours and nobody else can reach it*.
6. **One id, one Quill, per shelf.** A server Quill stands in front of one
   shared with you, which stands in front of your own of the same id; what
   lost is listed as shadowed, not lost. A personal Quill may not take the
   id of a server Quill, and a person may not accept a share whose id they
   have already.
7. **Code is per person.** A personal Quill's views, actions and hooks run
   as the person using it, in a sandbox of that person's own, so code one
   person wrote shares no interpreter with the people it was shared with.
   Its jobs, webhooks and APIs run as its owner — or, once the owner took
   it off their shelf, as the first of the people who still have it. A hook
   runs once per change, as whoever made the change (as the Quill's own
   runner, for a change from outside the Quill's holders).
8. **A Quill stays as long as somebody has it, and its data with it.**
   Taking a personal Quill off your shelf — the owner's included — takes it
   off *your* shelf: while others still have it, it stays for them, data
   and all, and its owner is its owner in name (`owner_left`). The last to
   have it takes it off the server, and only then may a datamodel of its
   own go with it, records and all (`?drop=`), as an administrator may
   choose for a server Quill. Having it taken back, leaving it, switching
   it off: what you wrote stays the Quill's. Until the last holder says
   otherwise, nothing of a Quill's data is deleted.
9. **The administrator decides what the server allows, and what each person
   may,** and sees all of it: every personal Quill, whose it is, who has it,
   what it runs; every request; every switch. Each of the four settings is
   the server's, and may be said again for one person (`PUT /api/quills/
   policy/{username}`): no Quills of their own for the children, no sharing
   for the intern, the catalog only for somebody who should not be writing
   code here. Switching a personal Quill off (by its key, as any feature)
   takes it from everybody who has it until it is on again.

## The ladder

One package all the way up. What changes at each rung is the audience, who
says yes, and what is checked.

| rung | audience | who says yes | checks |
| --- | --- | --- | --- |
| personal | you | you | the personal rules (2), on the install sheet |
| shared | the people you pick | each of them | the same, on theirs |
| server | everyone, or circles and people | an administrator | the full install sheet; circles for its datamodels |
| catalog | every Cloudmorrow | a pull request on `quill-catalog` | `cm quill check`, `test --sandbox`, a human reading it |

### Personal

Three ways to have one, each the same install under `quills-personal/`:

- **From the catalog**, on the phone or in the browser under Me → Your
  Quills, or `cm quill add budget --mine`. The install sheet, then a yes.
- **From a folder**: `cm quill dev` as somebody who is not an administrator
  installs the folder as their own (an administrator's `cm quill dev` is the
  server's, as it always was).
- **With an assistant**: `quill_check` and `quill_dev_install` over MCP build
  one of the person's own for anybody who is not an administrator. The
  loop is the one in [QUILLCODE.md](QUILLCODE.md); the manifest and the
  Python are written against the Quill's own names.

What the policy says decides which are open: `on`, all three; `ask`, none
of them, and a **request** instead (below); `off`, none, and every personal
Quill there is goes dark until it is `on` again. `personal_quill_code = off`
refuses a personal Quill with `code`, and stops the code of those installed.
`personal_quill_create = off` keeps the second and third way shut — and a
fork, and an assistant's `quill_dev_install` — while the catalog stays
open: one takes a Quill, one does not make one. Each setting is answered
for the server, and again for a person an administrator said something
about in particular (`cm quill policy alice`, Administration → Users →
the account, *Quills of their own*); the person's answer stands in front.

### Shared

The owner offers it to people (`PUT /api/quills/mine/{id}/share`, Your
Quills → Share, `cm quill share budget bob carol`, or `quill_share` for an
assistant), or to everybody in a circle, which is the people in it today —
with **rules**: what each may do with the datamodels of the Quill's own,
`write` or `read`, per datamodel (`"rules": {"budget.envelope": "read"}`;
nothing named is write). Each is told, and says yes or no (`cm quill accept
alice/budget`); yes puts it on their shelf, and the Quill's data in their
reach, as the rules say. Offered again to somebody who has it, only their
rules change. The owner sees who has it and may take it back; a person may
leave. What anybody wrote stays the Quill's.

An update is the owner installing again: everybody who has it has the new
version at once. (A version that asks for more — a new host, a new secret —
waiting on each person's yes is *not yet*, below.)

**Taking it off a shelf.** The owner's Remove, and a holder's Leave, are
the same thing: the Quill comes off *that* shelf (`DELETE /api/quills/mine/
{id}`, `DELETE /api/quills/offers/{owner}/{id}`). While others still have
it, it stays for them — the data, the code, which runs as the first of them
now — and the owner may neither offer it nor take it off again; it is
theirs in name. The last to have it is asked what goes with it (`GET …/
brought`, then `?drop=`), and takes it off the server.

### Server

An administrator installs a Quill for everyone, as always, or for an
**audience**: circles and people ticked on the install sheet (`"audience":
{"circles": [...], "people": [...]}` on `POST /api/quills`; `cm quill add
fleet --for Parents --person carol`; `PUT /api/quills/{id}/audience` later).
A server Quill with an audience is on those shelves and no other. It is
about the software: the data under it is still the circles' business.

**Requests.** Anybody may ask an administrator for a Quill — from the
catalog or a source, or for one of their own to be promoted — with a word
on why (`POST /api/quills/requests`, Your Quills → Ask, `cm quill request`,
`quill_request`). Administrators are told; the request is on their Quills
screen with three answers: for everyone, for the one who asked, or decline
with a word back. The asker is told either way.

**Promotion.** An administrator takes somebody's own Quill and makes it the
server's (`POST /api/quills/promote`, Administration → Quills → Promote,
`cm quill promote alice/budget --for Members`): the same folder is installed
as a server Quill, for the audience given, with `promoted_from` in its
`.origin.json`; then every record of its datamodels — the owner's, and
those of every person it was shared with — moves from `~alice.budget.*` to
`budget.*`, sealed again under the new name (`RecordStore.rename_model`);
then the owner's copy and its shares go. Everybody it is for has it now,
their records with them.

**Adoption** is the same move the other way round. When a server Quill is
planned (`POST /api/quills/plan`) and somebody has a Quill of their own of
the same id introducing the same datamodels, the plan says so (`adopt`), the
install sheet offers to bring their records in, and `"adopt": ["alice"]` on
the install does it. That is how Alice's Budget, published and installed from
the catalog, finds her records waiting.

### Catalog

`GET /api/quills/mine/{id}/export`, Your Quills → Export, or `cm quill export
budget`: the folder as a repository would hold it. The Quill's own files as
they are (the prefix was only ever the server's reading of them), and what
the template has that the folder lacks: `tests/` on the harness, `CLAUDE.md`
with the skills, `pyproject.toml`, the workflows, `.gitignore`, a README. Of
the server, nothing: no records unless chosen, no secret, no name. Records of
its own datamodels may go along as datasets, by choice (`?datasets=budget.
envelope`, `--dataset`), as `per-owner` seeds with links and stamps left out.
From there it is [publishing](QUILLCODE.md#publishing): `uv sync`, `cm quill
test`, a push, a tag, a pull request on the catalog.

### Forked

Anybody takes a Quill on their shelf — the server's, shared with them, or
their own — into one of their own under a new id (`POST /api/quills/mine/
fork`, `cm quill fork budget spending`). It is a copy with the id renamed in
the manifest, the datamodels and the code: a textual rename, said so, and
`cm quill check` on the export says what it missed. A fork over foundational
datamodels works on the same records at once; one over the original's own
datamodels starts empty, under the forker's name.

## The install sheet, for a personal Quill

The same `describe()` as a server Quill's, with each datamodel of its own
carrying `plain` (what the files call it) beside `id` (what the server
does), and the clients saying, in words: *Yours alone. Uses your contacts,
as you may. Introduces budget.envelope, which nobody else can reach. Its
Python runs in a sandbox, as you, and reaches api.example.com; it reads
TRACKER_KEY from your vault.*

## The API

| call | what |
| --- | --- |
| `GET /api/quills` | your shelf: each Quill with `key`, `owner`, `personal`, `mine`, `shared_by`, and a server Quill's `audience` |
| `GET /api/quills/policy`, `PUT …` (admin) | the four settings, and `may`: what they mean for you |
| `GET /api/quills/policy/{username}`, `PUT …` (admin) | one person's: the server's, their `own`, the `effective`; a value per setting, or `inherit` |
| `GET /api/quills/mine` | your own Quills with `shared_with` and `webhook_urls`, what you were `offered`, your `requests`, the `shadowed` |
| `POST /api/quills/mine/plan`, `POST /api/quills/mine`, `POST /api/quills/mine/upload` | install one of your own: the sheet, from the catalog or a source, from a tarball (`cm quill dev`) |
| `GET /api/quills/mine/{id}`, `GET …/brought`, `DELETE …?drop=` | one of yours, with its `holders` and `owner_left`; what it brought and how many records; take it off your shelf — off the server, dropping, when you are the last to have it |
| `PUT /api/quills/mine/{id}/share`, `DELETE …/share/{username}` | offer it to `people` and `circles`, with `rules`; take it back |
| `GET /api/quills/mine/{id}/export?datasets=` | the tarball |
| `POST /api/quills/mine/fork` | `{id, new_id, name}` |
| `POST /api/quills/offers/{owner}/{id}/accept`, `…/decline`, `DELETE …?drop=`, `GET …/brought` | yes, no, leave — off the server, dropping, when you are the last to have it; what it brought |
| `GET /api/quills/requests?all=`, `POST …` | open requests (everybody's for an administrator); ask |
| `POST /api/quills/requests/{n}/approve`, `…/decline`, `DELETE …` | `{audience, give_to, note}`; a word back; withdraw |
| `GET /api/quills/all` (admin) | everything: server Quills with audiences, personal Quills with shares, requests, the policy, what is broken |
| `POST /api/quills/promote`, `POST /api/quills/adopt/{owner}/{id}` (admin) | `{owner, id, audience, give_to}`; fold one in |
| `PUT /api/quills/{id}/audience` (admin) | `{circles, people}` |
| `/hooks/~alice.budget/<path>`, `/api/q/~alice.budget/…` | a personal Quill's webhooks and APIs, by its key |

On the command line it is all under `cm quill`: `add --mine`, `add --for`,
`audience`, `mine`, `share`, `accept`, `decline`, `leave`, `request`,
`requests`, `approve`, `decline-request`, `promote`, `adopt`, `export`,
`fork`, `policy`. To an assistant: `quill_check` and `quill_dev_install`
(theirs for anybody but an administrator), `quill_mine`, `quill_share`,
`quill_request`.

## Storage

```
<data_dir>/quills/<id>/                       a server Quill; .origin.json: audience, promoted_from
<data_dir>/quills-personal/<owner>/<id>/      a personal Quill; .origin.json: owner, installed_by, forked_from
<data_dir>/logs/quills/~<owner>.<id>/         its code log
```

In the database, beside the features:

```
quill_shares(owner, quill, username, state, offered_by, offered_at, answered_at, rules)
    -- offered, accepted, declined; the owner's own row says 'left'; rules is {model: "read"}
quill_requests(id, username, kind, quill, source, ref, note, state, asked_at, answered_by, answered_at, answer)
settings: personal_quills, personal_quill_code, personal_quill_sharing, personal_quill_create,
          and quill_policy:<username> for what was said about one person (JSON)
```

A personal Quill's records are rows in the one `records` table like any
other's, under their prefixed datamodel id, with `scope = 'public'`: the
Quill's, for everybody it stands with. The seal on each is to its owner
and id, as ever. Schema step 6 marks the rows of older servers so.

## Not yet

- **Consent on update.** A new version that asks for more than the people
  who have it said yes to should wait for each of them; today an update
  reaches them at once, as the owner's own install does.
- **Fields a personal Quill adds to the server's datamodels.** Still
  refused (rule 2): a field on a record is seen by everybody who sees the
  record, so there is no keeping it to the Quill's holders. A Quill that
  wants to say more about a contact introduces a datamodel of its own with
  a link to the contact, which is the Quill's and isolated as rule 3 says.
- **Passing a Quill on.** Once its owner took it off their shelf, nobody
  offers it to anybody new, and nobody updates it; the people who have it
  keep it as it is until the last of them takes it off, or an administrator
  promotes it. A holder taking over as owner is next.
- **Maintainers.** After promotion the server Quill is updated by an
  administrator, like any other. A named maintainer whose new versions
  ship when they ask for nothing new is next.
- **Resource limits per person.** One sandbox per person per Quill, idle
  ones stopped after ten minutes, is what bounds it today; a cap on
  personal Quills per person and a CPU budget per minute are not written.
- **Fetch to the local network** from a personal Quill is refused by
  nothing but the host list the person said yes to.
- **An owner's account going.** Their personal Quills stay on disk, listed
  to an administrator as such, to promote or remove; their shares and
  requests go with the account.
- **The TUI** draws a person's shelf and an administrator's answers; a
  person's own management there — share, export, request — is `cm quill`.

## Where the code is

| part | where |
| --- | --- |
| a personal Quill as the server reads it: owner, key, the renaming | `server/quills/manifest.py` (`personalise`, `Manifest.resolve`, `plain`), `server/datamodels.py` (`OWNER_PREFIX`, `renamed`) |
| installing, listing and removing them; what one may not do; adoption's plan | `server/quills/registry.py` (`personal`, `install(owner=)`, `check_personal`, `by_key`, `all`) |
| the shelf, audiences, and the narrowed access the gate asks | `server/quills/shelf.py` |
| shares, requests, the policy | `server/quills/sharing.py` |
| promotion and adoption; moving records | `server/quills/promotion.py`, `RecordStore.rename_model` |
| export and fork | `server/quills/export.py` |
| the routes | `server/routes/quillshelf.py`; `audience` and `adopt` in `server/routes/quills.py` |
| code per person, as its owner, under its own names | `server/quills/code.py` (`_guest`, `installed`, `_runs_as`, `_hook_people`, `plain_record`) |
| a machine's shelf | `server/routes/agentquills.py` |
| the web app | `web/myquills.js` (Your Quills), `web/quillsadmin.js` (policy, requests, whose, audience, adopt) |
| the terminal app | `tui/panes/admin_quills.py` (the User Quills tab, `own_widgets`) |
| the command line, the client, the assistant | `cli/quill.py`, `client/api.py`, `server/mcptools.py` |
| the tests | `tests/test_quill_sharing.py`, with `tests/fixtures/quill-budget` |
