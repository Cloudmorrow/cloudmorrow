# Cloudmorrow

**A local cloud anyone can install, on hardware they own.** A person, a
company, a school, a club: your data lives on your own machine, in
standard shapes, and you choose which apps sit around it and what each
may touch. Notes, tasks, a calendar, chat, files and secrets come in the
box; everything else is an app from the store at cloudmorrow.com, or one
you build yourself. No subscription, no account with anyone, and nothing
you write ever touches a disk unencrypted.

```
  ██████╗██╗      ██████╗ ██╗   ██╗██████╗ ███╗   ███╗ ██████╗ ██████╗ ██████╗  ██████╗ ██╗    ██╗
 ██╔════╝██║     ██╔═══██╗██║   ██║██╔══██╗████╗ ████║██╔═══██╗██╔══██╗██╔══██╗██╔═══██╗██║    ██║
 ██║     ██║     ██║   ██║██║   ██║██║  ██║██╔████╔██║██║   ██║██████╔╝██████╔╝██║   ██║██║ █╗ ██║
 ██║     ██║     ██║   ██║██║   ██║██║  ██║██║╚██╔╝██║██║   ██║██╔══██╗██╔══██╗██║   ██║██║███╗██║
 ╚██████╗███████╗╚██████╔╝╚██████╔╝██████╔╝██║ ╚═╝ ██║╚██████╔╝██║  ██║██║  ██║╚██████╔╝╚███╔███╔╝
  ╚═════╝╚══════╝ ╚═════╝  ╚═════╝ ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝ 
                               own your data, choose your apps
```

Cloudmorrow is one Python service that runs on whatever you have: a
Raspberry Pi, an old laptop, a NAS, a small VPS, a box in the server room. It
installs with one command, serves a phone app from its own address, and hands
every other machine on the network a one-line install command. Everyone gets an account; everything they
write is encrypted before it touches the disk.

It is free software under the [GNU AGPL v3](LICENSE).

## What you get

- **Notes.** Markdown files in folders, with pictures. Written on the phone,
  in the terminal, or by piping a file in. Each note is a real file on the
  server, so a copy of the folder is a backup.
- **Tasks.** Boards with three lanes: ToDo, Doing, Done. Drag a card, tick a
  subtask. Done cleans itself out after a week. Tasks is the first
  [Quill](docs/QUILLS.md), [in a repository of its own](https://github.com/Cloudmorrow/quill-tasks).
- **Quills.** Everything beyond the foundation is a Quill: a package from the
  [Quill Catalog](https://github.com/Cloudmorrow/quill-catalog), shelved by
  category, that shows you what data it uses, extends and introduces before
  you say yes. A Quill has no UI code: its screens come from one kit, so each
  one is on the phone, in the browser, in the terminal, on the command line
  (`cm tasks list`) and to your assistant at once. Build your own with
  `cm quill new`, or ask your assistant to.
- **Calendar.** One of your own, plus the ones you share with the people on
  your server. Every calendar you can see is drawn at once, so nobody
  double-books the meeting room or the car.
- **Chat.** Channels and direct messages between the people on your server,
  with real push notifications and an unread count on the phone's icon.
- **Files.** A private drive per account and named shares for what a team
  or a household keeps together, served over WebDAV so Finder, a Windows
  drive letter, a phone's file manager or `rclone` can mount them.
- **Secrets.** Keys and passwords in vaults you name, encrypted, never
  printed unless you ask. `.env` files in and out, or `secret run` to hand
  them to a program with no file at all. Part of the foundation: an app is
  given a secret when you say so and never owns one.
- **Three ways in.** A web app made for the phone (add it to the home
  screen), the same app grown up for a laptop browser, and a terminal app you
  can use with a mouse.
- **A desktop app that mounts your shares.** The same web app in a window of
  its own (`cloudmorrow app`, or the icon in your applications menu), with
  the client behind it: **Mount on this computer** beside each share, the
  folder it landed in a click away, and one sign-in shared with the terminal
  app. Linux today; macOS and Windows are next.
- **An assistant, if you want one.** The server speaks MCP, so Claude or any
  other MCP client can read and write your notes and every Quill's records as
  you, after you sign in and say yes — and, for an administrator, write,
  check and install a new Quill in the conversation. Secrets are never on
  that list.
- **Encrypted at rest.** Notes, messages, events, tasks, secrets and pictures
  are ciphertext on disk, under one key the server holds. You sign in with a
  password and never handle a key. See [docs/ENCRYPTION.md](docs/ENCRYPTION.md).
- **Switches, not settings.** An administrator can turn any whole area off
  for the server. Each person can hide any area from their own screens. That,
  and the list of accounts, is the whole administration panel.

## Where this is going

Cloudmorrow is becoming your personal platform for everything, for a
person, a household, a company or an institution: the place your data
lives, in standard shapes
every app agrees on, with apps around it that each have clearly drawn
access. Notes, tasks, chat and calendar come in the box. A shopping list,
a reading log or the budget you fetch from the store at cloudmorrow.com,
tweak, or build yourself by dragging in the data elements it needs and
describing the rest to an assistant, and it turns up on the phone, in the
browser, in the terminal and as tools an assistant can use. The concept
is [Concept.md](Concept.md); how software is packaged, found and built is
[docs/QUILLS.md](docs/QUILLS.md); the data model is [docs/DATA.md](docs/DATA.md);
the plan for the rest is [docs/PLATFORM.md](docs/PLATFORM.md).

## Three ways to get one

- **Your own machine.** The installer below: one command, three questions.
- **A hosted tenant.** The same server as a container, one per customer, on
  a service we run at a low monthly price. The server side is built; the
  shop is not yet.
- **A Raspberry Pi image.** Burn a card, plug the Pi into the router, open
  `cloudmorrow.local` on a phone and set it up from the browser. The
  first-boot page is built; the image and the public tunnel are not yet.

[docs/HOSTING.md](docs/HOSTING.md) has the plan for the last two, and for
certificates and public access that just work.

## Install a server

You need a Linux machine with systemd, `git` and Python 3.11 or newer, and a
name it can be reached by, such as `cloud.example.com`. One command:

```bash
curl -fsSL https://raw.githubusercontent.com/bramlabs-io/cloudmorrow/main/deploy/install-server.sh | sudo sh
```

It asks three questions: what your cloud is called, the address people will
use, and a username and password for the first account, which becomes the
administrator. Then it creates a service user, clones the code into
`/opt/cloudmorrow`, builds a virtualenv, writes the config and the systemd
unit, generates the encryption key, starts the service and makes your
account. Run it again any time: it keeps your config, notes, database and
accounts, and never asks a question it already has the answer to.

Every answer can be a flag instead, for a script or a machine with no
terminal, and `--dry-run` says what it would do without doing any of it:

```bash
sudo sh install-server.sh --name "The Larsens" --public-url https://cloud.example.com --user alice
```

The server listens on the loopback and expects a reverse proxy in front of
it for TLS. Caddy is the easy choice: it fetches and renews the certificate
itself, and the whole config is what the installer prints at the end.

```
cloud.example.com {
	reverse_proxy 127.0.0.1:8787
}
```

An nginx example is in [deploy/nginx.conf.example](deploy/nginx.conf.example).

Then open `https://cloud.example.com/app` on a phone and sign in. Use
**Add to Home Screen** and it opens like any other app, with your cloud's
name under the icon. `https://cloud.example.com` on a computer is the
install page, with the one command that puts the client on it.

No terminal at hand? Skip the account question. A server with no accounts
shows a setup page on its first visit instead: name the cloud, choose a
username and password, and it is yours. That page is how a hosted tenant
and a Pi image are set up too.

Rather run it as a container? `deploy/docker/` has the image, a compose
file and a Caddyfile:

```bash
cd deploy/docker && CLOUDMORROW_DOMAIN=cloud.example.com docker compose up -d
```

The server keeps its config in `/etc/cloudmorrow/server.toml`, notes and
files under `/srv/cloudmorrow/notes`, the database under `/var/lib/cloudmorrow`
and the encryption key in `/etc/cloudmorrow/cloudmorrow.key`. Every key in the
config, the cloud's name included, is explained in
[deploy/server.example.toml](deploy/server.example.toml).

### No domain name yet?

Answer the address question with a plain `http://` address and the server
stops insisting on TLS. Each client then has to opt in with
`cloudmorrow config set allow_insecure_http true`, because talking to a
server in the clear should be a decision rather than a default. A private
network with its own certificates, such as Tailscale, is the better answer.

## Install on your computers

Open the server's address in a browser and copy the one command it shows:

```bash
curl -fsSL https://cloud.example.com/install.sh | sh
cloudmorrow login
cloudmorrow                  # the terminal app; `cm` is the same thing in two letters
```

It needs Python 3.11 or newer and nothing else. It installs into your home
directory, points the command line at your server, and registers the machine
as one of yours so it can serve shares and run backups. On a Linux computer
with a desktop it adds the desktop app and puts it in the applications menu
(`--no-desktop` skips that; a machine reached over ssh gets the terminal app
alone). Every `cloudmorrow` command reads `RESOURCE ACTION`:

```
cloudmorrow note    list | show | add | edit | search | remove
cloudmorrow secret  list | get | set | import | export | run | vaults | remove
cloudmorrow share   list | add | mount | unmount | remove
cloudmorrow agent   list | run | jobs
cloudmorrow update  [server | all]
cloudmorrow app
cloudmorrow uninstall
```

## Adding people

Each person gets their own account and their own notes, files, boards and
calendar. Shared calendars, channels and shares are how you meet in the
middle. An administrator adds accounts from the **Administration** screen in
the app or the terminal, or from the server:

```bash
sudo -u cloudmorrow /opt/cloudmorrow/venv/bin/cloudmorrow-server user create sam
```

## Keeping it up to date

There is no package registry in the loop. The server pulls its own code from
git, and every other machine installs from the server.

```bash
cloudmorrow update server    # the server pulls, reinstalls and restarts itself
cloudmorrow update           # then this machine installs what the server now serves
cloudmorrow update all       # both, in that order
```

The first one goes through the API, so an administrator can do it from a
laptop without a shell on the server. Set `allow_api_update = false` in the
config if you would rather it always went over ssh.

## Backing it up

Three things, and the third is the one people forget:

| what | where |
| --- | --- |
| notes, pictures, files and shares | `/srv/cloudmorrow/notes` |
| accounts, tasks, chat, calendar, secrets | `/var/lib/cloudmorrow` |
| the encryption key | `/etc/cloudmorrow/cloudmorrow.key` |

Notes, tasks, chat, calendar and secrets are ciphertext without the third.
Back the key up with the data and keep the copy somewhere that is not the
server. Lose it and there is no recovery, by design. Files in the drives and
shares are stored as they are, so they need no key, and are not yet encrypted.

## How it is built

One FastAPI service with SQLite and a folder of files, a Textual terminal
app, a plain HTML web app, and a small agent that runs on each machine. No
containers, no build step, no JavaScript framework. The layout, the API and
every command are described in [docs/MANUAL.md](docs/MANUAL.md).

```bash
uv venv && uv pip install -e '.[tui,server,dev]'
pytest
ruff check src tests
```

`cloudmorrow --dev` runs the checkout you are standing in against your real
server, so a change to the terminal app needs no deploy to try.

## Documentation

- [docs/MANUAL.md](docs/MANUAL.md): every feature, command, config key and
  API route, with the reasoning behind them.
- [docs/ENCRYPTION.md](docs/ENCRYPTION.md): what is encrypted, how, what it
  protects against and what it does not.
- [Concept.md](Concept.md): what Cloudmorrow is, in one page.
- [docs/DATA.md](docs/DATA.md): the data concept: elements with standard
  fields, extensions apps add, scopes, storage, the change feed, export,
  and the registry and store at cloudmorrow.com.
- [docs/PLATFORM.md](docs/PLATFORM.md): the plan for Cloudmorrow as a
  platform: your data, guarded access, one kit of screens on every device,
  and apps you build by talking to an assistant.
- [docs/HOSTING.md](docs/HOSTING.md): a hosted tenant, a Raspberry Pi
  image, and how certificates and public access are meant to just work.
- [deploy/](deploy): the installer, the container, the systemd unit, and
  Caddy, nginx, server and agent examples.

## Contributing

Issues and pull requests are welcome at
[github.com/bramlabs-io/cloudmorrow](https://github.com/bramlabs-io/cloudmorrow).
Run `pytest` and `ruff check src tests` before you push. If you add something
that stores what a person wrote, seal it; the last section of
[docs/ENCRYPTION.md](docs/ENCRYPTION.md) says how.

## License

Cloudmorrow is free software under the [GNU Affero General Public License,
version 3](LICENSE), or any later version. Run it, change it, host it for other
people. If what you host is a changed version, offer them its source the way
this repository offers you this one.
