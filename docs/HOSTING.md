# Two ways to get a Cloudmorrow

The same server, delivered two ways: installed on a machine you already
have, or bought as a tenant on a service we run. This page says what each
one is, what is built, what is not yet, and how the tenant is meant to
work, so the pieces being built now fit the pieces that come after.

| shape | what you do | status |
| --- | --- | --- |
| **Your own machine** | run the installer, answer five questions | built |
| **A hosted tenant** | buy one, open the address, fill in the setup page | the server side is built; the shop and the control plane are not |

What both share is in the repository, and it is what makes the tenant
possible without a terminal:

- **First boot in the browser.** A server with no accounts sends every
  front door — `/`, `/install`, `/app` — to `/setup`, one form that names
  the cloud and makes the administrator. The moment an account exists the
  page is gone: `/setup` redirects to the app and `/api/setup` answers 409.
  So a tenant can be provisioned knowing nothing about its owner;
  whoever opens it first, owns it.
- **A name that lives in the database.** The installer writes `name` into
  `server.toml`; the setup page and `PATCH /api/server/settings` write it
  into the database, which wins. A service cannot write `/etc`, and a
  tenant has no `/etc` to speak of.
- **A container.** `deploy/docker/` builds the server into one image with
  two volumes, the data and the key that seals it. It is what a tenant is,
  and it runs on your own hardware too.

## Your own machine

[The README](../README.md#install-a-server). One command, five questions.
This is the shape everything else is measured against: whatever the tenant
does for you, it must not need anything this one does not have.

## A hosted tenant

**One container per customer.** Not one big multi-tenant server with a
`tenant_id` on every row. The reasons:

- The server seals everything under one key. One key per tenant means a
  tenant's key can be handed to them, rotated, or destroyed with their
  data, and a leak of one opens one.
- A tenant's backup is two directories, and a tenant leaving takes two
  directories with them. Restoring one customer never touches another.
- An idle server is around 100 MB of memory and no CPU. A modest VPS runs
  dozens; the price of a tenant is the price of that slice plus storage,
  which is what "pretty cheap" needs.
- There is no multi-tenant code to write, test, or get wrong. Isolation is
  the kernel's, not ours.

**What the platform does**, per tenant, and none of it is in this
repository yet:

1. Takes a name and payment, picks a subdomain — `larsens.cloudmorrow.com`.
2. Starts the image with `CLOUDMORROW_PUBLIC_URL=https://larsens.cloudmorrow.com`
   and two fresh volumes. Nothing else: the name and the administrator
   come from the first visit.
3. Routes the subdomain to that container at the edge proxy, under a
   wildcard certificate for `*.cloudmorrow.com`.
4. Backs up `/data` and `/keys` on separate schedules to separate places,
   because one without the other is useless to a thief and to us alike.
5. Updates by rolling the image. `allow_api_update` is off in the
   container: there is no git checkout to pull.
6. Meters storage by the size of `/data`, which is where notes, files and
   shares are.

Everything a tenant's owner needs after that is the app: their accounts,
their switches, their name. The service never signs in as them.

**Trust.** TLS ends at our edge, so the platform can read traffic in
flight, and the platform holds the key volume, so it can read data at
rest. That is the same trust every hosted service asks for; the honest
description is "encrypted against a lost disk and against other tenants,
not against the operator". Nothing in the design stops a tenant from
taking their two volumes and running the same image on their own hardware, which is
the guarantee that matters.

## Reaching your cloud

A cloud is reached at its server's address, and that is all Cloudmorrow
does about the network. It ships no relay, no VPN and no name service, and
a cloud never talks to cloudmorrow.com.

- **At home**, the box announces itself with multicast DNS as
  `<name>.local` (the cloud's name made into a hostname: `larsens.local`)
  and as a service, `_cloudmorrow._tcp`, whose TXT record carries `name`,
  `version` and `url`: the address to open, which is `public_url` when the
  config has one and `http://<name>.local:<port>` otherwise. `cm login`
  with no server lists the clouds it finds. `access_lan = false` turns the
  announcement off.
- **From outside**, it is the owner's own setup: a domain and a reverse
  proxy in front, with `public_url` saying what the address is, or a VPN
  such as Tailscale, where the cloud is simply the box's address on it.
- **A hosted tenant** is reached at the subdomain the platform gives it
  (above).

What the server does for whichever way is chosen:

- **TLS is required** once `public_url` is https; a plain request is
  answered only straight to the port from the box itself, the local
  network or a VPN's addresses ([ENCRYPTION.md](ENCRYPTION.md)).
- **Sign-in is limited.** Failed sign-ins are counted per visitor address
  (10 in 15 minutes) and per account (20 in an hour); past either, sign-in
  answers 429 with `Retry-After` until the window has passed.
- **No cookies.** A sign-in is a bearer token the page keeps in its own
  origin's storage.

**Me → Add a device**, in the web app and the terminal, is the one place
for putting the cloud on another device, at the address the person is
signed in to: `curl -fsSL <address>/install.sh | sh` for a computer (the
desktop app, `cm` and the TUI), `<address>/app` and a QR code of it for a
phone, `<address>/mcp` for an assistant. Every one signs in with the
person's own name and password.

## How far one cloud goes

A cloud is one process, by design (quills/services.py says why), and the
way to more people is more clouds: a tenant each, not one big one. What
one process does is measured rather than guessed, with
`scripts/loadtest.py`: it starts a server of its own on a directory it
takes away again, makes the accounts, fills every board, and times the
four requests an open screen makes, as so many people at once. Run it on
the machine a cloud will run on; these are a desktop's numbers, Python
3.12, and what a Raspberry Pi does is a fraction of them.

Fifty accounts, two hundred tasks each and a channel with a thousand lines
in it — 11,051 records — served 400 requests of each kind at 10, 50 and 100
at once, without an error, and the server stayed at 159 MB:

| request | at once | req/s | p50 | p95 | max | errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| list | 10 | 29 | 330 ms | 574 ms | 641 ms | 0 |
| create | 10 | 148 | 61 ms | 89 ms | 120 ms | 0 |
| search | 10 | 26 | 397 ms | 687 ms | 754 ms | 0 |
| thread | 10 | 286 | 31 ms | 45 ms | 59 ms | 0 |
| list | 50 | 30 | 1268 ms | 2730 ms | 3910 ms | 0 |
| create | 50 | 109 | 365 ms | 449 ms | 552 ms | 0 |
| search | 50 | 21 | 2047 ms | 3375 ms | 3652 ms | 0 |
| thread | 50 | 217 | 141 ms | 171 ms | 189 ms | 0 |
| list | 100 | 21 | 4150 ms | 5650 ms | 6073 ms | 0 |
| create | 100 | 91 | 713 ms | 917 ms | 987 ms | 0 |
| search | 100 | 20 | 4347 ms | 6000 ms | 6642 ms | 0 |
| thread | 100 | 151 | 311 ms | 588 ms | 654 ms | 0 |

`list` is a board of two hundred tasks opening, `create` a task being made,
`search` a `?q=` over the person's tasks, `thread` an open conversation
asking for what it has not got. Seeding ran at 113 writes a second with
sixteen writing at once.

What the numbers say. Writes and small reads go at a hundred to three
hundred a second whatever the crowd. A listing of two hundred records
costs the process some fifteen milliseconds of Python — each row is
unsealed and decoded, the query itself is answered from an index — so one
process hands out twenty to thirty such listings a second, and past that
people queue: ten opening boards at once wait a third of a second, a
hundred wait four. A household never gets there; a company of fifty on
one cloud will feel it on the heaviest screens at the busiest moment, and
the answer is for screens to ask for less (`_last`, a filter) before it is
for the server to grow.

What was changed to make these numbers true, and to hold them:

- The database is in write-ahead mode with a busy wait, so a write no
  longer blocks every read, and the clock folds the log back into the file
  (`db.connect`, `db.checkpoint`).
- A connection closes when its `with` block ends. Python 3.12's own
  connection frees its native memory only when the cyclic collector gets
  round to it, and under load hundreds sat open, each with its cache: the
  server grew by the gigabyte. That is why the server now stays at 159 MB.
- A listing is at most a thousand records and a search two hundred
  matches, and the fields a screen narrows by have indexes
  ([DATAMODELS.md](DATAMODELS.md), *Records*).
- The change feed keeps ninety days; the sweep takes the rest.
- An open screen listens to `/api/changes` instead of asking every five
  seconds — one idle connection per screen instead of a request per screen
  per five seconds, which at fifty open screens is ten requests a second
  for nothing.
- A notice to the people in a space goes through one thread, and the badge
  — every space they can see, counted — is worked out only for somebody
  with a device to carry it.

## What is in the repository, and what is not

| piece | where | status |
| --- | --- | --- |
| The guided installer | `deploy/install-server.sh` | built |
| First-boot setup page and `/api/setup` | `server/routes/setup.py`, `templates/setup.html` | built |
| The name, in the database, `GET`/`PATCH /api/server/settings` | `server/settings.py` | built |
| The container image, compose file, Caddyfile | `deploy/docker/` | built, not yet run in CI |
| Home network discovery | `server/access_lan.py`, `client/discover.py` | built |
| Sign-in limits | `server/signin_limits.py` | built |
| The change feed, `GET /api/changes` | `server/changefeed.py`, `web/changes.js` | built |
| The load measurement | `scripts/loadtest.py` | built; numbers above |
| Add a device | web app, `tui/screens/adddevice.py` | built |
| The shop and the tenant control plane | their own repositories | not started |
