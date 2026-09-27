# Three ways to get a Cloudmorrow

The same server, delivered three ways: installed on a machine you already
have, bought as a tenant on a service we run, or burnt onto an SD card and
plugged into the router. This page says what each one is, what is built,
what is not yet, and how the last two are meant to work, so the pieces
being built now fit the pieces that come after.

| shape | what you do | status |
| --- | --- | --- |
| **Your own machine** | run the installer, answer three questions | built |
| **A hosted tenant** | buy one, open the address, fill in the setup page | the server side is built; the shop and the control plane are not |
| **A Raspberry Pi image** | burn the card, plug it in, open `cloudmorrow.local` | the first-boot page and the ways to reach it are built; the image is not |

What all three share is now in the repository, and it is what makes the
other two possible without a terminal:

- **First boot in the browser.** A server with no accounts sends every
  front door — `/`, `/install`, `/app` — to `/setup`, one form that names
  the cloud and makes the administrator. The moment an account exists the
  page is gone: `/setup` redirects to the app and `/api/setup` answers 409.
  So a tenant or a Pi can be provisioned knowing nothing about its owner;
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
This is the shape everything else is measured against: whatever the other
two do for you, they must not need anything this one does not have.

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

## A Raspberry Pi image

**What is on the card.** Raspberry Pi OS Lite, 64-bit, with the installer
run at image-build time and told to ask nothing:

```bash
sudo sh install-server.sh --name Cloudmorrow --home-only --no-ssh-key
```

No `--user`, so no account is made. The hostname is set to `cloudmorrow`
and Avahi is left on, which Pi OS ships, so the box answers to
`cloudmorrow.local` on the LAN. The first person to open
`http://cloudmorrow.local:8787` on a phone gets the setup page, and it is
theirs. `pi-gen`, the tool the Pi OS images themselves are built with, is
the right way to make the card; the recipe is a stage that runs the
command above and sets the hostname. It is not written yet.

**What that gives you, and what it does not.** On the LAN, everything:
notes, tasks, calendar, chat, files, the terminal app, the assistant. What
it does not give is the phone app *as an app*: a service worker, and with
it push notifications and the badge, need HTTPS, and a phone away from
home cannot reach `cloudmorrow.local` at all. Both come from the same
thing: a public HTTPS address. That is the hard part of the image, and the
next section.

## Reaching your cloud

A cloud on a box behind a home router has no public address and no
certificate, and the person who owns it must never have to learn what
either is. There are three ways to reach one, and an owner can have any mix
of them. They are chosen at install (a question in the installer and on the
setup page) and changed later in **Administration → Access**.

| way | who reaches it | what the owner does | runs where |
| --- | --- | --- | --- |
| **Home network** | devices on the same network as the box | nothing: it is always on | the box |
| **Public** | anybody with the address; the sign-in page is the door | picks a name: `larsens.cloudmorrow.com` | the box, and the relay at cloudmorrow.com |
| **Private** | only devices you enrolled, from anywhere | enrolls each device once | the box, and the coordination server at cloudmorrow.com |

Everything at cloudmorrow.com lives in its own repository,
[`Cloudmorrow/relay`](https://github.com/Cloudmorrow/relay), and can be run
by anybody for themselves: the core only knows the address of a *control
server* (`access_control` in the server config, `https://relay.cloudmorrow.com`
by default).

### Home network

The box announces itself on the local network with multicast DNS, as
`<name>.local` (the cloud's name made into a hostname: `larsens.local`) and
as a service, `_cloudmorrow._tcp`, whose TXT record carries:

| key | value |
| --- | --- |
| `name` | what the cloud is called ("The Larsens") |
| `version` | the server's version |
| `url` | what to open on this network: `https://<name>.<zone>` with a public or private name, else `http://<name>.local:<port>` |
| `public` | `<name>.<zone>`, when public access is on |
| `private` | `<name>.<zone>`, when private access is on |

The service's port is 443 when the cloud has a public or private name
(Caddy answers there with the certificate for it), and the server's own
port (8787) when it has not. A box whose server listens only on the
loopback and has no name announces nothing: there is nothing a neighbour
could reach. `access_lan = false` turns it off.

- A fresh box with no accounts is set up from any browser on the network at
  `http://<name>.local:8787` (or `http://cloudmorrow.local:8787` before it has
  a name). The installer's "home network only" makes the server listen on
  every interface for this; the port stays 8787 because the service does not
  run as root.
- `cm login` with no server lists the clouds it finds on the network (the
  client installer, which comes from a server, already knows its server).
- When a cloud with a public or private name is found on the local network,
  `cm`, the TUI and the desktop app's own calls connect to it directly, at
  its local address (remembered as `local_address` at sign-in, tried with a
  quarter-second connect), sending the real name as SNI and `Host` and
  checking its certificate against it. The data does not go out to the
  internet and back to cross the living room. Not yet: the desktop app's web
  view and the rclone mounts, which still go by the public name (next: a
  loopback forwarder the web view and rclone are pointed at).

Plain `http` on the local network is used only for the first setup and for
finding the box: a phone's web app needs a real certificate for push and the
home screen, and that comes with a public or private name.

### Public: the relay

The relay moves bytes it cannot read. It never terminates a cloud's TLS and
never holds a certificate for one.

**Enrolment.** The box calls the control server once, with the name it wants
(`POST /v1/clouds`, below), and gets back a cloud id and a token. The token is
kept in the server's data directory, sealed; it is the cloud's only
credential there.

**The tunnel** (protocol `cmtunnel/1`). The box opens one long-lived, outbound
TLS connection to the relay — at the host and port of `access_control`,
the same place as the control API (443 unless the URL says otherwise; the
relay tells the two apart by what is said first) — outbound only, so no port
forwarding and no router settings — and keeps it open, reconnecting with
backoff. On it:

1. The box sends one line: `CMTUNNEL/1 <cloud_id> <token>\n`, and sends
   nothing more until it has read the answer: `OK <name>.<zone>\n`, or
   `NO <reason>\n` and the relay closes. The reasons, and what the box does:

   | reason | the box |
   | --- | --- |
   | `unknown cloud or wrong token` | stops, and says so on the Access screen, until something is changed there or the server restarts |
   | `public access is off for this cloud` | the same |
   | `too many failed attempts, wait a minute` | tries again in 60 seconds or more |
   | `not a cmtunnel/1 handshake`, `frames before OK` | a bug on one side: tries again in 5 minutes |
2. After `OK`, both sides speak frames: a 9-byte header — `type` (1 byte),
   `stream` (4 bytes, big-endian), `length` (4 bytes, big-endian) — then
   `length` bytes of payload. Types:

   | type | name | direction | payload |
   | --- | --- | --- | --- |
   | 1 | `OPEN` | relay → box | JSON `{"port": 443 or 80, "remote": "ip:port"}` (IPv6 bracketed: `[2001:db8::1]:443`) |
   | 2 | `DATA` | both | bytes, at most 64 KiB |
   | 3 | `CLOSE` | both | empty: this side will send no more `DATA` on the stream |
   | 4 | `WINDOW` | both | 4 bytes: more bytes the sender may now send on the stream |
   | 5 | `PING` | both | 8 bytes, echoed back in a `PONG` |
   | 6 | `PONG` | both | the 8 bytes of the `PING` |

   Each stream starts with a window of 256 KiB each way; a side sends `WINDOW`
   as it consumes data (the box: as it has written it into Caddy). A side
   never has more than its window outstanding, so a slow visitor slows its
   own stream and nobody else's. Streams are opened only by the relay. The box answers
   an `OPEN` by connecting to its local upstream for that port (`443` → the
   local TLS terminator, Caddy; `80` → the same, for the ACME challenge and
   the redirect to https) and splicing; if that fails it sends `CLOSE`.
   Either side sends a `PING` after 25 seconds of silence and drops the
   connection after 60 without a frame. Silence is nothing *received*;
   `PING` and `PONG` use stream 0, and the relay numbers streams from 1.
3. The details both sides keep to. `CLOSE` is a half-close. When the relay
   sends `CLOSE`, the box shuts the write side of its upstream connection and
   keeps sending what the upstream still says until it ends, then sends its
   own `CLOSE`. When the box sends `CLOSE`, the relay closes the visitor, and
   the stream is over for the box: it need not wait for anything back. When
   either side's connection to its end fails, it sends `CLOSE` if it has not. `DATA`, `CLOSE` and `WINDOW`
   for a stream that does not exist are ignored. A frame longer than 64 KiB
   is a protocol error and the connection is dropped. A frame of a type this
   list does not have is ignored, so a newer side can add one. An `OPEN`
   whose JSON cannot be read is taken as port 443. The box reconnects with
   jittered backoff from 1 second doubling to 60, back to 1 once a connection
   has held for 30 seconds; after a `NO`, as the table above says.

**Routing.** The relay listens on 443 and 80 for its whole zone. On 443 it
reads the SNI from the first TLS record without answering it: SNI equal to the
relay's own host is the relay's own business (the tunnel and the control API,
TLS terminated by the relay with its own certificate); SNI `<name>.<zone>`
with a live tunnel becomes an `OPEN` on port 443, and the bytes already read
are the first `DATA`. On 80 it reads the request's `Host` header the same
way. Anything else is closed. The relay adds nothing to the stream (the
client's address is in the `OPEN`'s `remote`, for the box's logs).

**The certificate.** Ports 80 and 443 reach the box unchanged, so Caddy on the
box gets and renews a Let's Encrypt certificate for `<name>.<zone>` by the
ordinary HTTP challenge. No DNS token on the box, no wildcard key on the relay.
The service, which is not root, keeps Caddy in step with the name: the
installer makes `/var/lib/cloudmorrow-caddy` (the service's, group `caddy`)
and puts `import /var/lib/cloudmorrow-caddy/*.caddy` in `/etc/caddy/Caddyfile`;
the service writes one site block for `<name>.<zone>` there and reloads Caddy
through its admin endpoint (`POST localhost:2019/load`, the Caddyfile as
`text/caddyfile`). The tunnel's upstreams are `access_upstream_443` and
`access_upstream_80`, Caddy on `127.0.0.1` by default.

**The address.** `public_url` becomes `https://<name>.<zone>`; `require_tls`
follows it, and phones have push, the badge and the home screen.

### Private: the mesh

The private way is the technology Tailscale is made of — WireGuard between
devices, direct where the networks allow it and through a relay (DERP) where
they do not — using [Headscale](https://github.com/juanfont/headscale), the
open-source coordination server, and Tailscale's own open-source apps on
every device (Headscale 0.26 or newer). Each cloud is one Headscale user,
`cloud-<cloud_id>`: its box and the devices its
people enroll can reach each other, and nobody else's.

**The box** joins at install or when private access is turned on: the core
asks the control server for a key (`POST /v1/clouds/me/mesh/keys`), installs
`tailscale` if it is not there (the installer asks first), and runs
`tailscale up --login-server <login_server> --authkey <key> --hostname cloud
--reset --operator=<service user>` (`--reset` so a box that was on another
tailnet is not refused; `--operator` so the service, which is not root, can
bring it down and up again afterwards — the first `up` is the installer's,
as root). Turning private access off runs `tailscale down` and reports an
empty address.
The control server records the box's mesh address and publishes
`<name>.<zone>` as it inside the mesh (a Headscale DNS extra record), so
enrolled devices go straight to the box.

**A computer** is enrolled by the client installer (`--private`) or later by
`cm access join`: signed in, it asks its cloud for a one-time key (`POST
/api/access/mesh/key`, `{device}`, answered `{key, login_server,
expires_at, hostname}`), installs `tailscale` with the person's consent
(`--yes` to not ask), and runs `sudo tailscale up --login-server … --authkey
… --hostname <computer>`. The desktop app shows whether this computer is
enrolled (Me → This computer) and offers to do it, through `pkexec`; it does
not install tailscale itself, it says how.

**A phone** uses the Tailscale app, pointed at the cloud's login server (a QR
code in **Me → Pair a device** carries it). The app shows a sign-in page from the
coordination server; that page asks for a six-character pairing code, which
the person gets from their cloud (**Me → Pair a device**, `POST
/api/access/mesh/pair`), and the control server registers the phone to that
cloud. A pairing code works once, for ten minutes.

**Certificates in private mode.** When public access is off, nothing on the
internet can reach the box for the HTTP challenge, so Caddy uses the DNS
challenge instead, through the control server's
[acme-dns](https://github.com/joohoi/acme-dns)-compatible endpoint (`POST
/v1/acme-dns/update`) and Caddy's `acmedns` DNS module. The control server
publishes the `_acme-challenge` TXT record for the cloud's name, and nothing
else; the certificate's private key never leaves the box.

**Both at once.** With public and private access on, `<name>.<zone>` points
at the relay for everybody and at the box's mesh address for enrolled
devices. One name, one certificate, the shortest path for each device.

### The control server's API (`/v1`)

Served by the relay host over HTTPS. The box authenticates with `Authorization:
Bearer <token>` from enrolment. JSON in and out; errors are `{"detail": "…"}`
with a plain sentence; a missing or revoked token is 401. Creates answer
201, deletes 204, a bad name or field 422 (FastAPI's list of `{msg}` is
accepted too; the core joins the sentences).

| call | what it does |
| --- | --- |
| `POST /v1/clouds` `{name, public?}` | Claim a name. `name` is 3–40 of `a-z 0-9 -`, not reserved (`www`, `relay`, `mesh`, `api`, `mail`, …). The relay makes every new name public; a private-only cloud sends `public: false` anyway, which is ignored, and then turns it off with `PATCH`. No token needed. 201 with `{cloud_id, token, name, zone, public_host, relay_host, login_server}` (`relay_host` is informational: the tunnel goes to `access_control`'s host and port). 409 if taken, 422 if not a name. |
| `GET /v1/clouds/me` | The cloud's record: `{cloud_id, name, zone, public_host, public, tunnel: {connected, connected_since}, bytes_in, bytes_out, mesh_address, login_server, devices}` (`devices` a list; `mesh_address` null when there is none). The core does not need it: the box knows its own tunnel. |
| `PATCH /v1/clouds/me` `{name?, public?}` | Rename, or turn public access on or off (off: the relay refuses the name, and DNS points it at the mesh address if there is one). Returns the record, as `GET`. 409 if the new name is taken. |
| `DELETE /v1/clouds/me` | Give the name back; revoke the token, the mesh user and its devices. 204. 502, with nothing deleted, when Headscale cannot be reached: the core then keeps the name and says why. |
| `POST /v1/clouds/me/mesh/keys` `{ephemeral?, expires_in?, for?, owner?}` | A one-time Headscale pre-auth key for this cloud's user. `for` is a label: `"the box"`, or `"<username>: <device>"` for a person's (`"jimmi: laptop"`); `owner` is that username. Both are kept with the device the key enrolls. `expires_in` is 60 seconds to 30 days, 3600 unless given (the core asks for 600). 201 with `{key, login_server, expires_at}`. |
| `POST /v1/clouds/me/mesh/pair` `{for, owner?}` | A six-character pairing code for a phone, valid ten minutes, once; `for` and `owner` as for a key. Returns `{code, expires_at, login_server}`. |
| `GET /v1/clouds/me/mesh/devices` / `DELETE …/devices/{id}` | The enrolled devices, a JSON list of `{id, name, for, owner, address, online, last_seen}` (`owner` may be absent: the core then reads it from `for`, before the `": "`), and removing one (204, 404 if not this cloud's). |
| `PUT /v1/clouds/me/mesh/address` `{address}` | The box reports its mesh address, for DNS: it must be in the mesh's prefixes and belong to one of this cloud's devices. `""` when it leaves the mesh (answered `{"address": null}`). |
| `POST /v1/acme-dns/register` | acme-dns compatible: credentials for this cloud's `_acme-challenge` record (Bearer-authenticated). 201 with `{username, password, fulldomain, subdomain, allowfrom, server_url}`. `fulldomain` is `_acme-challenge.<name>.<zone>` itself — no CNAME to set up — and `server_url` (`https://relay.<zone>/v1/acme-dns`) is what Caddy's `acmedns` module is given; the core falls back to `<access_control>/v1/acme-dns` without it. |
| `POST /v1/acme-dns/update` | acme-dns compatible (`X-Api-User`, `X-Api-Key`, `{subdomain, txt}`). Caddy's `acmedns` module posts here. |

The login server, `mesh.<zone>`, is TLS-terminated by the relay like the
control API: Tailscale's protocol paths go to Headscale, and `/register/<auth_id>`
to the relay's own pairing page, which asks for the code. A private cloud
with no mesh address yet answers its name with NOERROR and no records.

The DNS for the zone is answered by the relay repository's own small
authoritative server (it holds `<name>` → the relay or the mesh address,
`_acme-challenge.<name>` TXT, and the relay's and coordination server's own
names); the zone's parent delegates to it.

### What the relay knows, and what it cannot

It knows which names exist, which cloud each belongs to, whether its tunnel
is up, how many bytes went through, and which devices are enrolled in each
cloud's mesh. It cannot read anything any of them said: public traffic is TLS
end to end between the visitor and the box, and mesh traffic is WireGuard end
to end between devices. A cloud that wants none of it runs its own relay
repository and points `access_control` at it, or uses only the home network.

## What is in the repository, and what is not

| piece | where | status |
| --- | --- | --- |
| The guided installer | `deploy/install-server.sh` | built |
| First-boot setup page and `/api/setup` | `server/routes/setup.py`, `templates/setup.html` | built |
| The name, in the database, `GET`/`PATCH /api/server/settings` | `server/settings.py` | built |
| The container image, compose file, Caddyfile | `deploy/docker/` | built, not yet run in CI |
| The Pi image recipe | `deploy/pi/` | not started |
| Home network discovery, the tunnel client, private enrolment | `server/access_*.py`, `routes/access.py`, `client/discover.py` | built, tested against fakes of the relay |
| The relay, the control server, DNS, Headscale | [`Cloudmorrow/relay`](https://github.com/Cloudmorrow/relay) | being built |
| The shop and the tenant control plane | their own repositories | not started |
