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
| **A Raspberry Pi image** | burn the card, plug it in, open `cloudmorrow.local` | the first-boot page is built; the image and the tunnel are not |

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
sudo sh install-server.sh --name Cloudmorrow --public-url http://cloudmorrow.local:8787 --no-ssh-key
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

## Certificates and public access

A box behind a home router has no public address and no certificate, and
the person who bought it must never have to learn what either is. Three
ways to get there, two of which work today with a little setup and one of
which is the one to build.

| way | works today | who terminates TLS | what the owner does |
| --- | --- | --- | --- |
| Cloudflare Tunnel | yes | Cloudflare | owns a domain on Cloudflare, runs `cloudflared` on the box |
| Tailscale Serve / Funnel | yes | the box, with a Tailscale-issued certificate | installs Tailscale on the box and the phones |
| A cloudmorrow.com tunnel | not yet | the box, with a Let's Encrypt certificate | nothing: it is on by default on the image |

(Wayland is a display protocol; the thing you meant is WireGuard, and it is
what the third way runs on.)

**The cloudmorrow.com tunnel, as it should be built.** The relay is
deliberately dumb: it moves bytes it cannot read.

1. **DNS.** `*.cloudmorrow.com` points at the relay.
2. **Enrolment.** The box generates a WireGuard key pair on first boot.
   From the setup page — a fourth field, "Reach it from anywhere as
   `___.cloudmorrow.com`" — it posts its public key and the name it wants.
   The relay answers with a tunnel address and its own endpoint. That is
   the only API call in the design.
3. **The tunnel.** The box brings up WireGuard to the relay. Outbound only,
   so no port forwarding and no router settings. WireGuard reconnects on
   its own and costs nothing while idle.
4. **Routing.** The relay listens on 443 and 80 for the whole wildcard.
   On 443 it reads the SNI of each TLS handshake and forwards the raw
   connection down the tunnel to the box whose name that is, without
   terminating it. On 80 it does the same by `Host`. It never holds a
   certificate for anyone.
5. **The certificate.** Because ports 80 and 443 reach the box unchanged,
   the box runs Caddy exactly as an installed server does, and Caddy gets
   and renews a Let's Encrypt certificate for `larsens.cloudmorrow.com` by
   the ordinary HTTP challenge. No DNS API token on the device, no
   wildcard key to protect on the relay, nothing to rotate on our side.
6. **`public_url`** becomes `https://larsens.cloudmorrow.com`, `require_tls`
   follows it, and the phone app has push, the badge and the home screen.

What the relay knows: which names exist and which tunnel each one is on,
and how many bytes went through. What it cannot know: what any of them
said. The server on the box is unchanged by all of this; it is a reverse
proxy in front of it, like every other deployment, and a `deploy/tunnel/`
that does steps 2 and 3 is the piece of this repository that does not
exist yet. The relay is its own service, in its own repository.

Cloudflare's tunnel is the same shape with Cloudflare as the relay and
Cloudflare holding the certificate. It is the right stopgap for anyone who
already has a domain there, and it is what to run on the first few Pis
while the relay is being written.

## What is in the repository, and what is not

| piece | where | status |
| --- | --- | --- |
| The guided installer | `deploy/install-server.sh` | built |
| First-boot setup page and `/api/setup` | `server/routes/setup.py`, `templates/setup.html` | built |
| The name, in the database, `GET`/`PATCH /api/server/settings` | `server/settings.py` | built |
| The container image, compose file, Caddyfile | `deploy/docker/` | built, not yet run in CI |
| The Pi image recipe | `deploy/pi/` | not started |
| The tunnel client on the box | `deploy/tunnel/` | not started |
| The relay, the shop, the control plane | their own repositories | not started |
