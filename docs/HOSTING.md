# Two ways to get a Cloudmorrow

The same server, delivered two ways: installed on a machine you already
have, or bought as a tenant on a service we run. This page says what each
one is, what is built, what is not yet, and how the tenant is meant to
work, so the pieces being built now fit the pieces that come after.

| shape | what you do | status |
| --- | --- | --- |
| **Your own machine** | run the installer, answer three questions | built |
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

[The README](../README.md#install-a-server). One command, three questions.
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

A cloud on a box behind a home router has no public address and no
certificate, and the person who owns it must never have to learn what
either is. There are two ways to reach one:

| way | who reaches it | what the owner does | runs where |
| --- | --- | --- | --- |
| **Home network** | devices on the same network as the box | nothing: it is always on | the box |
| **The mesh** | devices that joined the cloud's mesh, from anywhere | links the box to a cloudmorrow.com account once, at install; invites each device once | the box, and the relay at `cloudmorrow.tech` |

Linking is a choice. A box that is not linked is reached on the home
network only, at `<name>.local` or its address, and never talks to anything
at cloudmorrow.com or cloudmorrow.tech. A linked box gets a name,
`<name>.cloudmorrow.tech`, that works from anywhere for devices on its mesh.
Nothing reaches a cloud's web app from the open internet: someone who opens
the name without being on the mesh gets a landing page with the client
downloads, served by the relay, not by the box.

### What leaves the box

This is the rule the rest of the section keeps to. A linked box sends the
relay:

- the WireGuard coordination Tailscale's own client sends to any
  coordination server (its public key, its endpoints, its mesh hostname,
  which the core sets to `cloud`);
- the `_acme-challenge` TXT value for its own name, when its certificate is
  renewed;
- `/v1` calls under its token: asking for a mesh key or an invite code, and
  reading its own record.

That is all. It sends no account, user, file, note, label or name of a
person, and it never talks to cloudmorrow.com itself. What the website shows
about a cloud (online, uptime) the relay reads from Headscale, which knows it
already; what the landing page shows (a display name, a logo) the owner types
into the website.

Devices on the mesh are the same: the core asks the relay for keys and codes
without saying whose device it is for, keeps its own labels ("jimmi:
laptop"), and enrols computers under an opaque hostname (`cm-<6 hex>`). A
phone joins with the Tailscale app, which sends the phone's own device name
to Headscale; the relay does not store it or pass it on.

### Home network

The box announces itself on the local network with multicast DNS, as
`<name>.local` (the cloud's name made into a hostname: `larsens.local`) and
as a service, `_cloudmorrow._tcp`, whose TXT record carries:

| key | value |
| --- | --- |
| `name` | what the cloud is called ("The Larsens") |
| `version` | the server's version |
| `url` | what to open on this network: `https://<name>.<zone>` when the box is linked, else `http://<name>.local:<port>` |
| `mesh` | `<name>.<zone>`, when the box is linked |

The service's port is 443 when the box is linked (Caddy answers there with
the certificate for its name), and the server's own port (8787) when it is
not. `access_lan = false` turns it off.

- A fresh box with no accounts is set up from any browser on the network at
  `http://<name>.local:8787` (or `http://cloudmorrow.local:8787` before it has
  a name).
- `cm login` with no server lists the clouds it finds on the network.
- A linked cloud stays reachable at home without the mesh. `cm`, the TUI and
  the desktop app connect to its local address, sending the real name as SNI
  and `Host` and checking its certificate against it; a browser uses
  `http://<name>.local:8787`. The data does not go out to the internet and
  back to cross the living room.

### Linking the box

At install (the installer's question, or the setup page), or later in
**Administration → Access**, the box asks the relay for a link code, the
way a television signs in:

1. `POST /v1/links` (no token, nothing in the body) answers `{code, poll,
   url, expires_at, interval}`: `code` is eight characters shown as
   `KXRT-4829`, `url` is `https://cloudmorrow.com/link`, both valid fifteen
   minutes.
2. The box shows: *Open cloudmorrow.com/link and enter KXRT-4829.* (The
   setup page and Access screen show the link with the code filled in, and a
   QR code of it.)
3. On cloudmorrow.com the person signs in or makes an account, enters the
   code, and picks a free name: 5–40 of `a-z 0-9 -`, not starting or ending
   with `-`, not reserved. The website asks the relay to approve the code
   with that name and the account (the admin API, below).
4. The box polls `POST /v1/links/poll` `{poll}` every `interval` seconds.
   Until approval it gets 202; after, once, 200 with `{cloud_id, token, name,
   zone, login_server, acme_dns}`. Expired or refused: 410.
5. The box seals the token in its data directory, joins the mesh (below),
   gets its certificate, and `public_url` becomes `https://<name>.<zone>`.

**Unlinking** from the box (`DELETE /v1/clouds/me`) or from the website
gives the name back and revokes the token, the mesh and every device on it.
The box goes back to home network only.

**Renaming** is done on the website. The box reads its record
(`GET /v1/clouds/me`) every ten minutes and at start; when the name has
changed it rewrites its Caddy site, gets a certificate for the new name and
changes `public_url`. The old name stops resolving at once.

### The mesh

The mesh is the technology Tailscale is made of — WireGuard between devices,
direct where the networks allow it (on the same network: over it) and
through a DERP relay where they do not — using
[Headscale](https://github.com/juanfont/headscale), the open-source
coordination server (0.26 or newer), and Tailscale's own open-source apps on
every device. Each cloud is one Headscale user, `cloud-<cloud_id>`, and the
policy is `autogroup:self`: a cloud's box and devices reach each other, and
nobody else's.

**The box** joins right after linking: the core asks the relay for a key
(`POST /v1/clouds/me/mesh/keys`), installs `tailscale` if it is not there
(the installer asks first), and runs `tailscale up --login-server
<login_server> --authkey <key> --hostname cloud --reset
--operator=<service user>`.

**The name inside the mesh.** The relay keeps a Headscale extra-records file
(`dns.extra_records_path`) with `<name>.<zone>` → the box's mesh address for
every linked cloud whose box has one, read from Headscale. Devices on the
mesh resolve the name to the box and go straight to it. Everywhere else the
name resolves to the relay.

**Certificates.** Nothing on the internet reaches the box, so Caddy gets its
Let's Encrypt certificate for `<name>.<zone>` by the DNS challenge, through
the relay's [acme-dns](https://github.com/joohoi/acme-dns)-compatible
endpoint and Caddy's `acmedns` module. The relay publishes the
`_acme-challenge` TXT record for the cloud's name, and nothing else; the key
never leaves the box. The service keeps Caddy in step with the name through
`/var/lib/cloudmorrow-caddy/*.caddy` and Caddy's admin endpoint.

**Inviting a device.** Someone already on the cloud — on the mesh or at
home — makes an invite in **Me → Invite a device** (`POST
/api/access/mesh/invite`, which calls `POST /v1/clouds/me/mesh/invites`).
The first device has nothing on the mesh to make one from, so there are two
more ways: the installer prints one when it has linked the box
(`cloudmorrow-server access invite`, from the box's shell at any time), and
the owner makes one in **My Clouds** on cloudmorrow.com (`POST
/admin/v1/clouds/{id}/invites`). An invite is a six-character code, valid
ten minutes, once, and only puts a device on the mesh: it still signs in to
the cloud itself. It works two ways:

- **A computer:** the client installer from the landing page asks for it
  (`--invite <code>`), trades it at the relay for a one-time key (`POST
  /v1/invites/redeem` `{name, code}` → `{key, login_server, expires_at}`,
  no token, limited per address), installs `tailscale` with the person's
  consent, joins as `cm-<6 hex>`, and then signs in to the cloud as usual.
- **A phone:** the Tailscale app, pointed at the login server (the landing
  page and the invite show a QR code of it), shows the relay's pairing page,
  which asks for the code.

A signed-in computer on the home network can also join without an invite:
`cm access join` asks its cloud for a key (`POST /api/access/mesh/key`).

### The landing page

`<name>.<zone>` resolves to the relay for anybody not on the mesh. The relay
terminates TLS for it with its own wildcard certificate for `*.<zone>` and
serves one page, and nothing is forwarded to the box:

- the cloud's display name and logo, if the owner turned them on in **My
  Clouds**; otherwise *A Cloudmorrow cloud*;
- the client downloads, linked to the core repository's GitHub Releases,
  so they cost the relay nothing;
- `curl -fsSL https://<name>.<zone>/install.sh | sh`, a few lines that fetch
  the released client installer and run it with `--server
  https://<name>.<zone> --invite`;
- the QR code for a phone's Tailscale app;
- one line: *This cloud's web app opens on its devices. Ask someone on it
  for an invite.*

A name that is not linked to anything answers *There is no cloud here.*

### My Clouds (cloudmorrow.com)

A signed-in account sees its linked clouds, each with: the name, online or
not and since when, uptime over the last 30 days, and switches for showing
the display name and the logo on the landing page, the display name itself,
the logo (PNG, SVG or JPEG, at most 256 KiB), rename, and unlink. The website
knows nothing else about a cloud: not its devices, not its people.

The relay counts uptime from Headscale: once a minute it reads whether each
cloud's box (the node named `cloud`) is online, and keeps the changes.

### The relay's API (`/v1`)

Served at `relay.<zone>` over HTTPS; the box's `access_control` points there
(`https://relay.cloudmorrow.tech` by default). The box authenticates with
`Authorization: Bearer <token>`. JSON in and out; errors are `{"detail": "…"}`
with a plain sentence; a missing or revoked token is 401.

| call | what it does |
| --- | --- |
| `POST /v1/links` | Start linking. No token. 201 with `{code, poll, url, expires_at, interval}`. Limited per address. |
| `POST /v1/links/poll` `{poll}` | 202 until the code is approved; then once 200 with `{cloud_id, token, name, zone, login_server, acme_dns}`; 410 when expired or refused. |
| `GET /v1/clouds/me` | `{cloud_id, name, zone, mesh_address, login_server}`. |
| `DELETE /v1/clouds/me` | Unlink: give the name back, revoke the token, the mesh user and its devices. 204. |
| `POST /v1/clouds/me/mesh/keys` `{ephemeral?, expires_in?}` | A one-time Headscale pre-auth key for this cloud. 201 with `{key, login_server, expires_at, node_hint}`. |
| `POST /v1/clouds/me/mesh/invites` | An invite code, six characters, ten minutes, once. 201 with `{code, expires_at, login_server}`. |
| `POST /v1/invites/redeem` `{name, code}` | No token. Trades an invite for a one-time key. 201 with `{key, login_server, expires_at}`; 404 for a wrong or used code. Limited per address. |
| `GET /v1/clouds/me/mesh/devices` / `DELETE …/devices/{id}` | The devices on the mesh, `{id, address, online, last_seen}`, and removing one. The box joins them to its own labels by `id`. |
| `POST /v1/acme-dns/update` | acme-dns compatible (`X-Api-User`, `X-Api-Key`, `{subdomain, txt}`); the credentials come in the link's `acme_dns`. |

The login server, `mesh.<zone>`, is TLS-terminated by the relay like the
API: Tailscale's protocol paths go to Headscale, `/register/<auth_id>` to
the relay's pairing page.

### The admin API (the website → the relay)

Served at `relay.<zone>/admin/v1`, only to the website, which authenticates
with `Authorization: Bearer <admin secret>` from the relay's secrets file.
Accounts are opaque to the relay: the website's account id, nothing else.

| call | what it does |
| --- | --- |
| `GET /admin/v1/names/{name}` | `{available, problem}`: whether a name can be taken. |
| `GET /admin/v1/links/{code}` | Whether a link code is waiting: `{waiting, expires_at}`; 404 unknown, 410 expired or used. Codes are read without regard to case, dashes or spaces. |
| `POST /admin/v1/links/{code}/approve` `{account, name}` | Makes the cloud, owned by `account`, and hands its token to the waiting box. 409 if the name is taken, 410 if the code is gone. |
| `POST /admin/v1/links/{code}/refuse` | The person said no. |
| `GET /admin/v1/accounts/{account}/clouds` | `[{cloud_id, name, created, online, online_since, uptime_30d, show_name, show_logo, display_name, has_logo}]`: `online_since` is when the current state began, online or offline; `uptime_30d` a fraction, `0.998`. |
| `PATCH /admin/v1/clouds/{id}` `{account, name?, display_name?, show_name?, show_logo?}` | Rename, and the landing page's switches. The cloud must be the account's. |
| `GET` / `PUT` / `DELETE /admin/v1/clouds/{id}/logo?account=…` | The logo, as the body with its content type (404 when there is none). |
| `POST /admin/v1/clouds/{id}/invites` `{account}` | An invite code for a device, as the box makes: `{code, expires_at, login_server}`. It counts against the cloud's invites per hour (429). |
| `DELETE /admin/v1/clouds/{id}?account=…` | Unlink. |

### What the relay knows, and what it cannot

It knows which names exist and which account owns each, whether each box is
online, which devices are on each cloud's mesh (by key, address and the
device name a phone's Tailscale app reports), and what an owner chose to show
on the landing page. It cannot read anything the devices say to each other:
mesh traffic is WireGuard end to end, and the relay carries it only when two
devices cannot reach each other directly. A cloud that wants none of it runs
the relay repository itself and points `access_control` at it, or is never
linked.

The website knows accounts, and for each the names of its clouds and what
the relay tells it above. It never talks to a box.

## What is in the repository, and what is not

| piece | where | status |
| --- | --- | --- |
| The guided installer | `deploy/install-server.sh` | built |
| First-boot setup page and `/api/setup` | `server/routes/setup.py`, `templates/setup.html` | built |
| The name, in the database, `GET`/`PATCH /api/server/settings` | `server/settings.py` | built |
| The container image, compose file, Caddyfile | `deploy/docker/` | built, not yet run in CI |
| Home network discovery, linking, the mesh, invites | `server/access_*.py`, `routes/access.py`, `client/discover.py` | being built (from the `access-core` branch, without its tunnel) |
| The relay, its API and admin API, the landing page, Headscale | [`Cloudmorrow/relay`](https://github.com/Cloudmorrow/relay) | running at cloudmorrow.tech with the tunnel; linking and the landing page being built |
| `/link` and My Clouds | [`Cloudmorrow/cloudmorrow-web`](https://github.com/Cloudmorrow/cloudmorrow-web) | not started |
| The shop and the tenant control plane | their own repositories | not started |
