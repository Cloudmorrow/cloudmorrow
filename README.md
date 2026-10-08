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
  server, so a copy of the folder is a backup. Notes is a
  [Quill](docs/QUILLS.md) too, [in a repository of its own](https://github.com/Cloudmorrow/quill-notes).
- **Tasks.** Boards with three lanes: ToDo, Doing, Done. Drag a card, tick a
  subtask. Done cleans itself out after a week. A
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

## Two ways to get one

- **Your own machine.** The installer below: one command, five questions.
- **A hosted tenant.** The same server as a container, one per customer, on
  a service we run at a low monthly price. The server side is built; the
  shop is not yet.

[docs/HOSTING.md](docs/HOSTING.md) has the plan for the hosted tenant, and
how a cloud is reached.

## Install a server

You need a Linux machine with systemd and Python 3.11 or newer. The
installer adds `git`, `sudo` and Python's venv module if they are missing,
or says the command that would. One command:

```bash
curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/install-server.sh | sudo sh
```

It asks five questions: what your cloud is called, a username and password
for the first account, which becomes the administrator, where on the
machine it goes (the code, the settings and the data, each on a row with
its usual place filled in; Enter takes them all, or change the ones you
want elsewhere; everything people keep goes under the data directory, in
`files/`), which of the machine's addresses it answers on
(every one unless you tick others, or type your own), and which of the
standard quills it should have (Notes, Tasks, Calendar, Chat, Files,
Secrets; all of them unless you untick some). Then it creates a service
user, clones the code into `/opt/cloudmorrow` (or where you said), builds a
virtualenv, writes the config and the systemd unit, generates the
encryption key, starts the service and makes your account. Run it again any time: if the server is running and answering, it
says so and changes nothing; if not, it updates and reinstalls it and checks
again (`--update` does that either way). It keeps your config, notes,
database and accounts, and never asks a question it already has the answer to.

Every answer can be a flag instead, for a script or a machine with no
terminal, and `--dry-run` says what it would do without doing any of it:

```bash
sudo sh install-server.sh --name "The Larsens" --user alice --quills all
```

**How it is reached** is this machine's address. On a home network the
box also announces itself as `<name>.local`, and `cm login` finds it there.
Reaching it from outside is your own setup, and Cloudmorrow needs none of
it: a domain and a reverse proxy, or a VPN such as Tailscale if you use one.

Have a domain and a reverse proxy of your own? Give
`--public-url https://cloud.example.com`. Caddy is the easy choice: it
fetches and renews the certificate itself, and the whole config is what the
installer prints at the end.

```
cloud.example.com {
	reverse_proxy 127.0.0.1:8787
}
```

An nginx example is in [deploy/nginx.conf.example](deploy/nginx.conf.example).

Then, with `cloud.example.com` standing for your cloud's address
(or `http://<name>.local:8787` at home):

1. Open it in a browser and sign in.
2. On each computer, install the terminal app (`cm`) and the desktop app,
   which also mounts your fileshares, with the line **Me → Add a device**
   shows: `curl -fsSL https://cloud.example.com/install.sh | sh`. It
   signs you in.
3. On a phone, open `https://cloud.example.com/app`, sign in, and use
   **Add to Home Screen**: it opens like any other app, with your cloud's
   name under the icon.

No terminal at hand? Skip the account question. A server with no accounts
shows a setup page on its first visit instead: name the cloud, choose a
username and password, tick the standard quills, and it is yours. That page is how a hosted tenant is set up too.

Rather run it as a container? `deploy/docker/` has the image, a compose
file and a Caddyfile:

```bash
cd deploy/docker && CLOUDMORROW_DOMAIN=cloud.example.com docker compose up -d
```

The server keeps its config in `/etc/cloudmorrow/server.toml`, the database
under `/var/lib/cloudmorrow`, everyone's files beside it in
`/var/lib/cloudmorrow/files` (a folder per person, and the Shares folder) and
the encryption key in `/etc/cloudmorrow/cloudmorrow.key` — unless you put them
elsewhere when the installer asked, or with `--prefix`, `--config-dir`,
`--data-dir`, `--files-dir` and `--shares-dir`; a re-run finds them where they
are. Every key in the
config, the cloud's name included, is explained in
[deploy/server.example.toml](deploy/server.example.toml).

### Only at home?

Without an address of its own, the cloud is plain
`http://<name>.local:8787` on your network. Picking it from the list `cm
login` shows is saying that is how it is meant to be; a client given the
address by hand opts in with `cloudmorrow config set allow_insecure_http
true`, because talking to a server in the clear should be a decision rather
than a default.

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
| everyone's files and shares | `/var/lib/cloudmorrow/files` |
| accounts, tasks, chat, calendar, secrets | `/var/lib/cloudmorrow` |
| the encryption key | `/etc/cloudmorrow/cloudmorrow.key` |

Tasks, chat, calendar and secrets are ciphertext without the third.
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
- [docs/HOSTING.md](docs/HOSTING.md): a hosted tenant, and how a cloud is
  reached.
- [deploy/](deploy): the installer, the container, the systemd unit, and
  Caddy, nginx, server and agent examples.

## Contributing

Issues and pull requests are welcome at
[github.com/Cloudmorrow/cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow).
Run `pytest` and `ruff check src tests` before you push. If you add something
that stores what a person wrote, seal it; the last section of
[docs/ENCRYPTION.md](docs/ENCRYPTION.md) says how.

## Releasing and deploying

`make deploy` shows what is released and live — the core's version, and
the commits live on cloudmorrow.com and the mail Worker — and
offers to release or deploy whatever is behind. A release is a git tag on
main (`vX.Y.Z`), and the only version number there is:
`make deploy WHAT=explain` says how the pieces fit together, and the top
of [scripts/deploy.py](scripts/deploy.py) lists every step.

## License

Cloudmorrow is free software under the [GNU Affero General Public License,
version 3](LICENSE), or any later version. Run it, change it, host it for other
people. If what you host is a changed version, offer them its source the way
this repository offers you this one.
