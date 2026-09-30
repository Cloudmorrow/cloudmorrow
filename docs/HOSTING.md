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
either is, or handle a key or a code to reach it. There are three ways in:

| way | who reaches it | what the owner does | runs where |
| --- | --- | --- | --- |
| **Home network** | devices on the same network as the box | nothing: it is always on | the box |
| **From anywhere** | any browser, and any client, at `<name>.cloudmorrow.tech` | links the box to a cloudmorrow.com account once, at install | the box, and the relay at `cloudmorrow.tech`, which passes the traffic through without reading it |
| **The mesh** | the cloud's own apps (desktop, `cm`, the TUI) once signed in | nothing: they join by themselves | the box, the devices, and the relay's coordination server |

Linking is a choice. A box that is not linked is reached on the home
network only, at `<name>.local` or its address, and never talks to anything
at cloudmorrow.com or cloudmorrow.tech. A linked box gets a name,
`<name>.cloudmorrow.tech`, and opening it anywhere shows the cloud's own
sign-in page. Signing in there is signing in to the cloud: the password is
checked by the box, over TLS that begins in the browser and ends on the box.

From the web app, **Me → Add a device** installs the rest: the desktop app,
the terminal clients, or the web app on a phone's home screen. A native
client signs in with the same name and password, and then puts its computer
on the cloud's mesh by itself, so from then on it goes straight to the box,
across the room or across the world, and the relay carries none of it. A
browser cannot join a mesh, so the web app always comes through the relay,
unless the device it runs on is on the mesh already.

The owner can take the cloud off the internet in **Administration →
Access** (*Reachable from anywhere*, on by default once linked). Then the
name reaches it only from the home network and from devices on its mesh.

### What leaves the box

This is the rule the rest of the section keeps to. A linked box sends the
relay:

- the WireGuard coordination Tailscale's own client sends to any
  coordination server (its public key, its endpoints, its mesh hostname,
  which the core sets to `cloud`);
- the `_acme-challenge` TXT value for its own name, when its certificate is
  renewed;
- `/v1` calls under its token: asking for a mesh key, reading its own
  record, and saying whether it is reachable from anywhere;
- the web traffic of people who open it from anywhere, still encrypted by
  TLS that the box ends: the relay moves the bytes and cannot read them.

That is all. It sends no account, user, file, note, label or name of a
person, and it never talks to cloudmorrow.com itself. What the website shows
about a cloud (online, uptime) the relay reads from Headscale, which knows it
already; what the offline page shows (a display name, a logo) the owner types
into the website.

Devices on the mesh are the same: the core asks the relay for keys without
saying whose device each is for, keeps its own labels ("jimmi: laptop"), and
enrols computers under an opaque hostname (`cm-<6 hex>`).

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
  a name). The setup page is never served from anywhere else (below).
- `cm login` with no server lists the clouds it finds on the network.
- A linked cloud stays reachable at home without the relay. `cm`, the TUI
  and the desktop app connect to its local address, sending the real name as
  SNI and `Host` and checking its certificate against it; a browser uses
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
   gets its certificate, opens its door for the relay, and `public_url`
   becomes `https://<name>.<zone>`. The installer ends by printing that
   address: *Open https://larsens.cloudmorrow.tech and sign in.*

**Unlinking** from the box (`DELETE /v1/clouds/me`) or from the website
gives the name back and revokes the token, the mesh and every device on it.
The box goes back to home network only.

**Renaming** is done on the website. The box reads its record
(`GET /v1/clouds/me`) every ten minutes and at start; when the name has
changed it rewrites its Caddy site, gets a certificate for the new name and
changes `public_url`. The old name stops resolving at once.

### From anywhere: the relay passes it through

`*.<zone>` resolves to the relay for everybody off the mesh. For a cloud's
name the relay does not end TLS. It reads the name the browser asks for
(the SNI in the TLS ClientHello, which is sent in the clear), and:

1. when that name is a linked cloud that is reachable from anywhere, it
   opens a TCP connection over the mesh, from its own mesh node, to port
   **8443** on the cloud's box, writes a
   [PROXY protocol v2](https://www.haproxy.org/download/2.8/doc/proxy-protocol.txt)
   header carrying the visitor's address, and then copies bytes both ways,
   starting with the ClientHello it read. It never holds a key for the
   cloud's name, and the box's certificate is the one the browser checks;
2. when the box cannot be reached (offline, or no answer within three
   seconds), or the owner turned *Reachable from anywhere* off, it ends TLS
   itself, with its own wildcard certificate for `*.<zone>`, and serves the
   **offline page** (below), and nothing else. A connection the relay ended
   is never forwarded to a box;
3. when the name is not linked to anything, the same with *There is no
   cloud here.*

The relay's node is on the mesh as `tag:relay`. The Headscale policy lets
`tag:relay` reach port 8443 of each cloud's box, and nothing else; no
device may reach the relay's node. Between the relay and the box the bytes
are inside WireGuard as well as TLS.

**On the box**, Caddy has a second site for `<name>.<zone>`, on port 8443,
with the same certificate. It accepts the PROXY protocol header only from
the relay's mesh addresses (`relay_addresses` in the box's record), refuses
the connection otherwise, and marks every request it passes on with
`Cloudmorrow-Way: public` and the visitor's address in `X-Forwarded-For`,
replacing whatever the request carried. The site on 443 (home network and
mesh) removes `Cloudmorrow-Way` from requests. The server believes the
header, and `X-Forwarded-For`, only from Caddy on the box's loopback. Turning
*Reachable from anywhere* off removes the 8443 site and tells the relay
(`PATCH /v1/clouds/me {public: false}`).

**What is different about a request from anywhere**, on the server:

- **The setup page is not there.** While a box has no accounts,
  `/setup` and `/api/setup` answer 404 to a public request, with a page
  that says to set the cloud up from the home network. Nobody on the
  internet can claim a cloud that was linked before it had an owner.
- **Sign-in is limited.** Failed sign-ins are counted per visitor address
  (10 in 15 minutes) and per account (20 in an hour); past either, sign-in
  answers 429 with `Retry-After`, for that address or that account, until
  the window has passed. The limits hold on every way in, not only the
  public one: the home network is where an unlocked guest laptop is.
- **Cookies are host-only** (no `Domain` attribute), so one cloud cannot
  set a cookie for another under the same zone.

**Traffic.** Everything a browser does from anywhere goes through the relay
both ways. That is the cost of a login page on the internet and it is
accepted; it is also why the native apps join the mesh.

### Adding a device

**Me → Add a device**, in the web app, is the one place for it. Nothing on
it is a code or a key to copy:

- **This computer, as an app**: the desktop app's download for the
  platform the browser says it is on, and the command that installs it,
  `curl -fsSL https://<name>.<zone>/install.sh | sh -s -- --desktop`;
- **The terminal**: `curl -fsSL https://<name>.<zone>/install.sh | sh`, for
  `cm` and the TUI;
- **A phone**: open `https://<name>.<zone>` in its browser and add it to the
  home screen (a QR code of the address).

The installer puts the client on the computer, sets the cloud's address,
and runs `cloudmorrow login`, which asks for the name and the password.

### Native clients on the mesh

A native client — `cm`, the TUI, the desktop app — that signs in to a cloud
whose `GET /api/access` says it is linked and its mesh is on, joins that
mesh without being asked to, right after signing in:

1. it asks the cloud, signed in, for a one-time key: `POST
   /api/access/mesh/key` → `{key, login_server, hostname, host}`;
2. when `tailscale` is not installed it asks once whether it may install it
   (from tailscale.com's installer on Linux; on a Mac it opens the App Store
   page, which it cannot do for anybody); a *no* is remembered;
3. it runs `tailscale up --login-server <login_server> --authkey <key>
   --hostname cm-<6 hex>`, which needs the computer's password (sudo in a
   terminal, a password dialog from the desktop app);
4. it tells the cloud the new address is this person's computer (`POST
   /api/access/mesh/mine`).

On the mesh the cloud's name resolves to the box (below), so the same
address now goes straight there. If joining fails or is declined, nothing
else does: the client keeps working through the relay, says so once, and
`cm access join` tries again. A computer already on this cloud's mesh skips
all of it. `cloudmorrow login --no-mesh`, or `mesh = false` in the client's
config, keeps a computer off.

### The mesh

The mesh is the technology Tailscale is made of — WireGuard between devices,
direct where the networks allow it (on the same network: over it) and
through a DERP relay where they do not — using
[Headscale](https://github.com/juanfont/headscale), the open-source
coordination server (0.28 or newer: the policy needs `autogroup:self` and tags of their own), and Tailscale's own open-source apps on
every device. Each cloud is one Headscale user, `cloud-<cloud_id>`, and the
policy is `autogroup:self`: a cloud's box and devices reach each other, and
nobody else's. The one exception is the rule above for `tag:relay` and port
8443 of each box.

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

**Certificates.** Nothing on the internet reaches the box directly, so Caddy
gets its Let's Encrypt certificate for `<name>.<zone>` by the DNS
challenge, through the relay's
[acme-dns](https://github.com/joohoi/acme-dns)-compatible endpoint and
Caddy's `acmedns` module. The relay publishes the `_acme-challenge` TXT
record for the cloud's name, and nothing else; the key never leaves the box.
The service keeps Caddy in step with the name through
`/var/lib/cloudmorrow-caddy/*.caddy` and Caddy's admin endpoint.

**Invite codes are retired.** They were how a device reached a cloud that
had no public door. The relay keeps `POST /v1/invites/redeem` and `cm access
join --invite` keeps working until clients older than this design are gone,
but nothing shows a code any more: not the web app, not the installer, not
My Clouds. A phone uses the web app from anywhere and does not need the
mesh.

### The offline page

When the relay cannot pass a visitor through, it serves one page, with its
own certificate, and forwards nothing:

- the cloud's display name and logo, if the owner turned them on in **My
  Clouds**; otherwise *A Cloudmorrow cloud*;
- *This cloud can't be reached right now*, or, when the owner turned
  *Reachable from anywhere* off, *This cloud opens at home and on its own
  devices*;
- the client downloads, linked to the core repository's GitHub Releases,
  so they cost the relay nothing.

### My Clouds (cloudmorrow.com)

A signed-in account sees its linked clouds, each with: the name as a link
to open it, online or not and since when, uptime over the last 30 days,
whether it is reachable from anywhere (the box decides; the website shows
it), and switches for showing the display name and the logo on the offline
page, the display name itself, the logo (PNG, SVG or JPEG, at most 256 KiB),
rename, and unlink. The website knows nothing else about a cloud: not its
devices, not its people, and it never signs in to one.

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
| `GET /v1/clouds/me` | `{cloud_id, name, zone, mesh_address, login_server, public, relay_addresses}`: `public` whether the relay passes visitors through, `relay_addresses` the relay's mesh addresses, the only ones the box accepts a PROXY header from. |
| `PATCH /v1/clouds/me` `{public}` | Reachable from anywhere, or not. The box sends it when the owner flips the switch and at start. |
| `DELETE /v1/clouds/me` | Unlink: give the name back, revoke the token, the mesh user and its devices. 204. |
| `POST /v1/clouds/me/mesh/keys` `{ephemeral?, expires_in?}` | A one-time Headscale pre-auth key for this cloud. 201 with `{key, login_server, expires_at, node_hint}`. |
| `POST /v1/clouds/me/mesh/invites` | Retired: an invite code, six characters, ten minutes, once. |
| `POST /v1/invites/redeem` `{name, code}` | Retired: trades an invite for a one-time key. No token, limited per address. |
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
| `GET /admin/v1/accounts/{account}/clouds` | `[{cloud_id, name, created, online, online_since, uptime_30d, public, show_name, show_logo, display_name, has_logo}]`: `online_since` is when the current state began, online or offline; `uptime_30d` a fraction, `0.998`. |
| `PATCH /admin/v1/clouds/{id}` `{account, name?, display_name?, show_name?, show_logo?}` | Rename, and the offline page's switches. The cloud must be the account's. |
| `GET` / `PUT` / `DELETE /admin/v1/clouds/{id}/logo?account=…` | The logo, as the body with its content type (404 when there is none). |
| `POST /admin/v1/clouds/{id}/invites` `{account}` | Retired, with the other invites. |
| `DELETE /admin/v1/clouds/{id}?account=…` | Unlink. |

### What the relay knows, and what it cannot

It knows which names exist and which account owns each, whether each box is
online, which devices are on each cloud's mesh (by key and address), and
what an owner chose to show on the offline page. For visitors from anywhere
it sees what any network in the middle sees: which cloud's name was asked
for, from which address, when, and how many bytes went each way.

It cannot read what visitors and the cloud say to each other: TLS ends on
the box, with a key the relay never has. It cannot read what devices on a
mesh say to each other either: that is WireGuard end to end, and the relay
carries it only when two devices cannot reach each other directly.

It *could* do one thing it does not: the wildcard certificate it keeps for
the offline page is valid for every cloud's name, so a relay that set out to
deceive could end a visitor's TLS itself and pretend to be the cloud. The
code does that only for the offline page and never forwards such a
connection. That is a promise, not a proof. The native apps on the mesh do
not depend on it (their traffic never touches the relay's certificate), and
a cloud that wants none of it runs the relay repository itself and points
`access_control` at it, or is never linked.

The website knows accounts, and for each the names of its clouds and what
the relay tells it above. It never talks to a box.

## What is in the repository, and what is not

| piece | where | status |
| --- | --- | --- |
| The guided installer | `deploy/install-server.sh` | built |
| First-boot setup page and `/api/setup` | `server/routes/setup.py`, `templates/setup.html` | built |
| The name, in the database, `GET`/`PATCH /api/server/settings` | `server/settings.py` | built |
| The container image, compose file, Caddyfile | `deploy/docker/` | built, not yet run in CI |
| Home network discovery, linking, the mesh | `server/access_*.py`, `routes/access.py`, `client/discover.py` | built |
| From anywhere on the box: the 8443 site, `Cloudmorrow-Way`, sign-in limits, setup only at home, *Reachable from anywhere* | `server/access_*.py`, `server/signin_limits.py` | being built |
| Add a device, native clients joining the mesh after sign-in | web app, `client/meshjoin.py`, `cli/access.py` | being built |
| The relay, its API and admin API, Headscale | [`Cloudmorrow/relay`](https://github.com/Cloudmorrow/relay) | running at cloudmorrow.tech; passing through, `tag:relay`, `public` and the offline page not started |
| `/link` and My Clouds | [`Cloudmorrow/cloudmorrow-web`](https://github.com/Cloudmorrow/cloudmorrow-web) | built; *reachable from anywhere*, the open link and dropping invites not started |
| The shop and the tenant control plane | their own repositories | not started |
