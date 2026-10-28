# Installing, updating and backing up

The long form of what [cloudmorrow.com/install](https://cloudmorrow.com/install)
says in short: the server, the computers, the people, the updates and the
backups. Every feature, command, config key and route is in
[MANUAL.md](MANUAL.md).

## Two ways to get one

- **Your own machine.** The installer below: one command, five questions.
- **A hosted tenant.** The same server as a container, one per customer, on
  a service we run at a low monthly price. The server side is built; the
  shop is not yet.

[HOSTING.md](HOSTING.md) has the plan for the hosted tenant, and
how a cloud is reached.

## Install a server

You need a Linux machine with systemd and Python 3.11 or newer. The
installer adds `git`, `sudo` and Python's venv module if they are missing,
or says the command that would. One command:

```bash
curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/install-server.sh | sudo sh
```

It asks six questions: what your cloud is called, a username and password
for the first account, which becomes the administrator, where on the
machine it goes (the code, the settings and the data, each on a row with
its usual place filled in; Enter takes them all, or change the ones you
want elsewhere; everything people keep goes under the data directory, in
`files/`), which of the machine's addresses it answers on
(every one unless you tick others, or type your own), which database it
keeps its records in (the built-in one, a file in the data directory,
which is right for most; or PostgreSQL, in a container it runs beside the
server or on a server you already have), and which of the
standard quills it should have (every one Cloudmorrow makes, with Files,
Calendar, Notes and Tasks ticked to begin with; the rest can be added from
Administration later). Then it creates a service
user, clones the code into `/opt/cloudmorrow` (or where you said), builds a
virtualenv, writes the config and the systemd unit, generates the
encryption key, starts the service and makes your account. The terminal
app is on the server too: `cm` at the box signs in to the server beside
it, whichever addresses it answers on, and an administrator has
Administration there as anywhere. Run it again any time: if the server is running and answering, it
asks whether to update it, and Enter says yes; if not, it updates and
reinstalls it and checks again (`--update` does that without asking, and
without a terminal a server that is well is left alone). It keeps your
config, notes, database and accounts, and never asks a question it already
has the answer to.

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

An nginx example is in [deploy/nginx.conf.example](../deploy/nginx.conf.example).

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
username and password, tick the standard quills you want, and it is yours. That page is how a hosted tenant is set up too.

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
[deploy/server.example.toml](../deploy/server.example.toml).

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
cloudmorrow secret  list | get | set | import | export | run | vaults | remove
cloudmorrow share   list | add | with | unshare | mount | unmount | remove
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

