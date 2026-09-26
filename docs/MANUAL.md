# Cloudmorrow manual

The long-form reference: every feature, every command, every config key,
and the reasoning behind them. If you just want to get a server running,
start with the [README](../README.md); this is the page to come back to.

## What it does

- **Secrets.** Your keys and passwords, in **vaults** you name (`default`
  until you name one) and environments inside them (`local`, `production`,
  whatever you call them), encrypted at rest. `.env` files in and `.env`
  files out, `secret run` to hand them to a process without a file, and
  values never in a listing unless you ask. Part of the foundation: an app
  is *given* a secret when you say so, and never owns one.
- **Notes.** Markdown by title, yours. `note show`
  writes raw text to stdout, so redirection and pipes do what you expect.
- **Tasks.** Boards, picked from a dropdown that is also where you make one,
  and three lanes on each: ToDo, Doing, Done. Drag a card with the mouse to
  move it, or press `[` and `]` on the one you are on. A task is a title and a
  markdown body, so its detail and its `- [ ]` subtasks are the same thing the
  note editor already knows how to write and tick. **Done empties itself**: a
  task deleted a week after it got there, with every card saying how long it
  has left, so the lane stays what you finished recently rather than
  everything you ever finished.
- **Calendar.** Your own calendar, made for you the first time you look at
  it, plus the ones you share. A **shared** calendar works the way a private
  channel does — you put people in it and they are in it — and a **public**
  one is everybody's, in every list and open to write in. Every calendar you
  can see is drawn at once, each event in its calendar's colour, because a
  calendar you have to switch between is a calendar that lets you
  double-book yourself. Times are the times on the wall: what you typed is
  what every screen shows, in June and in December alike.
- **A TUI you can click.** Six tabs — notes, tasks, calendar, chat,
  secrets, files — because those are the kinds of thing there are. A vault
  is a row in a list, the same shape as a note, and its keys are beside it.
  Every row and button is a click target with a key beside it. The markdown
  editor is live: the line the cursor is on stays raw source, and every
  other line renders as you leave it.
- **Encrypted at rest.** Everything you write — chat, events, tasks, notes,
  pictures, secrets, synced dotfiles — is ciphertext on the server's disk,
  under one key the server holds. You never handle a key; you sign in with
  a password. See [Encryption at rest](#encryption-at-rest).
- **Notes are files.** Each note is a file under a directory you name in the
  server config, folders are folders, and a copy of the tree is a backup.
  The bytes inside are sealed, so it is the app that reads them, not `grep`.
- **A local agent** on each machine — registers itself when you sign in, runs
  as you, for backups and whatever comes next. The server has one too, so the
  box that holds everything is in the list with the rest of them.
- **Omarchy config sync.** Tick one box in Settings and this machine's
  `~/.config/hypr` is kept in step with every other machine that ticked it.
  Change a keybind on the laptop and the desktop has it within the minute,
  without either of them being told to. The first machine to tick the box
  claims the configuration; the rest adopt it.
- **My Files.** A drive of your own on the server, there because your
  account is: `cloudmorrow share mount my-files` and it is a folder on this
  machine; in the app it is the first thing under Files.
- **Fileshares.** A directory on the server with a name, served over WebDAV,
  mounted on whichever machine you are at: `cloudmorrow share mount media` and
  it is `~/Fileshares/media` here, or `/Volumes/media` on a Mac. Finder does
  the mounting on macOS with nothing installed; on Linux it is `rclone`.
  Made and mounted from the **Files** tab as well. Local backups have a tab
  beside them, with nothing in it yet.
- **Chat.** Channels and direct messages, between everyone on the server —
  a Quill, like Tasks, offered when you install. A **public** channel is
  everybody's, in everyone's list and open to write in; a **private** one is
  the people you pick, and they are *added* rather than invited — nobody
  accepts anything, they are simply in it and told so. A **direct** channel
  is two people, and it is never made from a form: pick somebody and it is
  there. Unread is when you last looked, per person per channel, so reading
  on the laptop is reading on the phone.
- **The count on the icon.** Chat is why the web app has push. An app on a
  home screen is not running most of the time, so nothing it could poll
  would keep its badge right — a real Web Push wakes a service worker,
  which shows the banner and sets the number. The badge is everything
  waiting: what is unread in your channels plus unread notifications. See
  [Push notifications](#push-notifications).
- **Users.** Password login, bearer tokens, per-user trees, and an admin API for
  creating more accounts. Every account has a **role** — Administrator, User,
  or DashboardDisplayer, which may only show dashboards on a shared screen —
  and a **type**, which is what is behind it rather than what it may do:
  Human, Agent, or SystemsUser for the machinery itself.
- **Administration.** An administrator has one more thing on the top bar of
  the TUI, left of Settings: Administration, which puts the whole workspace
  aside for the server's own panel — and the same panel is in the web app,
  behind a row in **Me** that only administrators are shown. **Users** is
  every account, added and edited there. **Features** is every area of the
  app — Notes, Tasks, Calendar, Chat, Projects, Files — with a tick box
  each: switch one off and its tab is gone from every client and its API
  answers 403, because off ought to mean off rather than hidden.
- **And a switch of your own.** The same list is in your own settings, in
  the terminal app and in **Me** on the phone, with your answer on each.
  Switching one off there takes its tab out of your clients, on every
  machine you sign in from — an account that never opens Projects can stop
  being offered them. Only what the server offers is listed: a feature an
  administrator has switched off is not something you are shown at all,
  because a tick box you cannot have an opinion about is worse than no tick
  box. Yours hides where theirs forbids; see [Two switches on every
  feature](#two-switches-on-every-feature).
- **One install command**, served by the server itself at `/`.
- **Claude can use it as you.** The server is an MCP server too, at `/mcp`,
  with OAuth in front of it: add the address to Claude Desktop, claude.ai or
  Claude Code, sign in on the page that opens, and from then on "put milk on
  my shopping list" or "what did I write about the greenhouse" is a tool call
  on your own notes, tasks and projects — and only yours. Nothing to
  configure, and every assistant you let in can be cut off again; see
  [An assistant working as you](#an-assistant-working-as-you).
- **Notes on the phone.** The same server serves a small web app at `/app`:
  sign in, and your notes are there to read and write, laid out the way a
  phone's notes app is — folders, a list, a note. Add it to the home screen and
  it opens like an app. The pixel B in its bar says which app you are in, and
  the photo button beside the note — or a paste, or a drop — puts a picture in
  it; see [Pictures](#pictures). It follows a deploy on its own: an app on the
  home screen is opened and hidden for weeks without ever being loaded, so the
  page asks which deploy the server is serving whenever it comes back to the
  front, and reloads itself when the answer has changed — with no force close,
  and never out from under a note you are writing.

## Layout

```
src/cloudmorrow/
  logo.py            the wordmark, shared by every entry point
  paths.py           path validation (nothing escapes the notes root)
  dotenv.py          the .env format, and the default vault and environment, shared by both ends
  slugs.py           ids for boards and shares, derived the same way on both ends
  palette.py         the colours, named once, for the TUI and the CLI alike
  bundles.py         what a config bundle's file names may be, checked at both ends
  cli/               the `cloudmorrow` command line, one module per resource
    dev.py           `--dev`: run the checkout you are standing in
    progress.py      the spinner, the bar, and the line saying what is happening
    secret.py        list, get, set, remove, import, export, run, vaults
    note.py          list, show, add, edit, remove
    share.py         list, show, add, remove, mount, unmount
  client/            talking to a server: config, credentials, HTTP
    mounts.py        which share is mounted where on this machine, and by what
  server/            FastAPI app, SQLite stores, notes-on-disk store
    types.py         the kinds of data there are, who provides each, and who reaches it
    settings.py      what the server was told about itself from the app: its name
    crypto.py        sealing secret values (AES-256-GCM)
    secrets.py       the secret store: vaults, environments, keys
    tasks.py         boards, lanes, and the week a finished task has left
    configsync.py    the one copy of the shared config, and its revisions
    notifications.py what the machines did, kept where all of them can leave it
    calendar.py      the calendars, who shares them, and what is on them
    webpush.py       VAPID, aes128gcm, and the devices to push
    shares.py        the fileshares: a name, a directory, whose directory it is
    dav.py           those directories over WebDAV, at /dav/<share>/
    templates/       the install page and install.sh
    web/             the app for the browser: one page, a core, and a file per feature
  agent/             the local agent: config, tasks, poll loop
    omarchy.py       what "my Omarchy config" means on disk, read and written
    sync.py          claim, adopt, push, pull — one pass per poll
  tui/               Textual client
    theme.py         the Textual theme, built from that palette
    screens/         splash, login, the workspace, and settings
    panes/           notes, tasks, calendar, chat, secrets (vaults + keys),
                     files (local backups + fileshares), and browse: what is
                     in a share, as a list or as thumbnails
    widgets/         the vault list, the note tree, the board, the toolbar,
                     the editor, and the picture beside it
deploy/              server installer, systemd unit, Caddy/nginx, example config
scripts/
  release.py         tag this commit as a release, and push it
```

Notes on disk, one tree per user:

```
<notes_dir>/<user>/notes/
```

Notes are the person's, not a project's, so there is one tree and no scoping
to think about. (Older layouts — notes loose in `<user>/`, or under
`<user>/projects/<slug>/notes/` from when a project had its own — are folded
into it the first time the server sees them; a project's notes become a folder
of that name.)

Secrets are the exception to files-not-a-database: they live in the SQLite
database, encrypted — see [Secrets](#secrets).

## The command line

Everything reads `cloudmorrow RESOURCE ACTION`, with singular resource names:

```
cloudmorrow secret  list | get | set | remove | import | export | run | vaults
cloudmorrow note    list | show | add | edit | remove | search
cloudmorrow agent   list | run | jobs | enroll-token
cloudmorrow share   list | show | add | remove | mount | unmount
cloudmorrow config  show | set
cloudmorrow update  [server | all]
```

`cm` is the same command in two letters — `cm note list`, or `cm` on its own
for the TUI — for the hundredth time in a day. An update never overwrites a
`cm` that is somebody else's program.

No invented syntax, no arrows. Data goes to stdout, status goes to stderr,
and `-v`/`-e` are overrides on commands that have a sensible default without
them. The old plural names (`cloudmorrow secrets list`) still
work, quietly, so old muscle memory and old scripts do not break.

## Server, on the home box

One script, run as root on the home box. It asks what the cloud is called,
what address people will use and who the first account is, then clones the
repo, builds a venv, writes the config and the systemd unit, generates the
sealing key, starts the service, creates that account as administrator and
gives the server an agent of its own.

```bash
curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/install-server.sh | sudo sh
```

The questions are asked on the terminal, not stdin, so the script can arrive
through a pipe. Every answer has a flag, and with all three given nothing is
asked, which is what a script or a re-run wants:

```bash
sudo sh deploy/install-server.sh \
  --name "The Larsens" \
  --public-url https://cloud.example.com \
  --user alice                    # password from $CLOUDMORROW_ADMIN_PASSWORD, or asked
```

Add `--dry-run` to read what it is about to do without doing any of it, or
asking anything. `--repo` deploys a fork; from a checkout it defaults to
that checkout's origin, and on its own to the public repository.

Installing from a private fork instead: give `--repo` an ssh URL and the script
does the deploy-key dance — the first run generates a read-only key and stops,
you add it under the repository's deploy keys, and the second run does the
install. (Cloning by hand first cannot work: that is the access the key is
about to grant.)

What it leaves behind:

| path | |
| --- | --- |
| `/opt/cloudmorrow/src` | the git checkout the service runs from |
| `/opt/cloudmorrow/venv` | its virtualenv, installed editable so updates are a pull |
| `/etc/cloudmorrow/server.toml` | the config — yours to edit, never rewritten |
| `/etc/systemd/system/cloudmorrow.service` | runs as the `cloudmorrow` system user |
| `/usr/local/bin/cloudmorrow-update` | the updater, below |
| `/etc/sudoers.d/cloudmorrow` | lets `--admin` run exactly those two commands |
| `/var/lib/cloudmorrow/.ssh/` | the deploy key the service pulls with, if the repo needed one |
| `/etc/cloudmorrow/cloudmorrow.key` | the key everything is sealed with at rest |

Re-running the script is safe: it puts the checkout on the remote branch,
reinstalls, and leaves your config, notes, database and accounts alone. It
reads the name and address back out of the existing config rather than
asking again, and asks for an account only while the server has none.

### The cloud's name

`name` in `/etc/cloudmorrow/server.toml` — what the installer's first
question wrote — is on the sign-in screen, the install page, the phone's
home screen (through the manifest and the Apple title), the page title, and
`/api/health`. It is text, never markup, and blank means "Cloudmorrow".
Change it by editing the config and `sudo systemctl restart cloudmorrow`; a
phone that already has the app on its home screen keeps the name it was
added under until it is added again.

### First boot in the browser

Skip the account question, or run the installer with no terminal, and the
server is set up on its first visit instead. While it has no accounts,
`/`, `/install` and `/app` all redirect to `/setup`: one form for the
cloud's name and the first account, posted to `/api/setup`, which makes
that account the administrator and sends the browser to the app. The
moment any account exists the page redirects to `/app` and the endpoint
answers 409, so there is nothing to find afterwards. `/api/health` says
`"setup": true` until then, for a client that wants to send somebody there.

The name set this way lives in the database, and wins over the one in the
config file: a running service cannot write `/etc`, and a hosted tenant
has no file to edit. An administrator changes it later with
`PATCH /api/server/settings` and `{"name": "…"}`; anybody signed in may
`GET` it. [HOSTING.md](HOSTING.md) is where this leads: a tenant somebody
bought, and a Pi image, are both "open it and fill in the setup page".

### As a container

`deploy/docker/` builds the server into one image, with `/data` and
`/keys` as its two volumes and every config key an environment variable.
`compose.yml` puts Caddy in front of it for the certificate, and the first
visit is the setup page above. Updating is replacing the image, so
`allow_api_update` is off inside it, and `FORWARDED_ALLOW_IPS=*` lets
uvicorn believe a proxy that is another container rather than the
loopback. The wheel the image was built from is copied into `/data/dist`
on every start, so `/install.sh` hands out the code that is running.

Accounts can also be made from the server at any time; the first one on a
server is its administrator whatever flags it is given:

```bash
sudo -u cloudmorrow /opt/cloudmorrow/venv/bin/cloudmorrow-server user create sam
```

`--password-stdin` reads the password from stdin instead of prompting, for
a script, and `user list --count` prints how many accounts there are, which
is how the installer knows whether to ask.

### Moving an install from BramCloud

Everything was renamed at once — the package, the commands, the paths, the
environment variables, the units — so an existing install carries on as
BramCloud until you move it. Do not run the old `bramcloud update server`
against the renamed code: it would pull it and then restart a unit whose
command no longer exists. Instead, on the server:

```bash
sudo sh deploy/migrate-from-bramcloud.sh --public-url https://cm.hl.bramlabs.io --admin jimmi
```

It stops the old units, moves `/etc`, `/var/lib`, `/opt` and the database to
their new names, renames the system user, rewrites the paths and `public_url`
in the config, fetches the renamed code and hands over to
`install-server.sh`, which writes the new unit, updater and sudoers file and
rebuilds the venv. The signing, secrets and VAPID keys move with the data
directory, so accounts, tokens, secrets and push subscriptions survive; notes
stay where `notes_dir` points.

Then, on each machine, `sh deploy/migrate-client.sh https://cm.hl.bramlabs.io`
installs the `cloudmorrow` client, keeps your sign-in and project links, and
retires the old `bramcloud` one. The phone app stores its token under a new
key, so it asks you to sign in once more.

### The URLs

Three places, and only the first two matter for a normal setup:

- **`public_url`** in `/etc/cloudmorrow/server.toml` — `https://cm.hl.bramlabs.io`.
  The install page bakes this into the command it hands out, so it must be the
  address other machines use, not the bind address.
- **your reverse proxy** — point it at whatever `--host`/`--port` the service
  listens on. On one box that is `127.0.0.1:8787`:

  ```
  cm.hl.bramlabs.io {
  	reverse_proxy 127.0.0.1:8787
  }
  ```

  With the proxy on a *different* machine, the default loopback bind is
  unreachable from it. Install with `--host <the app box's tailnet IP>` and
  point the proxy there:

  ```
  cm.hl.bramlabs.io {
  	reverse_proxy 100.71.157.19:8787
  }
  ```

- **each client** — `cloudmorrow config set api_url https://cm.hl.bramlabs.io`,
  which the install script does for you.

Change `public_url` later by editing the config and
`sudo systemctl restart cloudmorrow`.

### Answering only the proxy

On a machine that also serves other things, a host firewall can be more trouble
than it is worth. `allowed_client_ips` narrows the API instead:

```toml
allowed_client_ips = ["192.168.10.88"]   # just the reverse proxy
```

Addresses or CIDR ranges, matched against the real TCP peer — never
`X-Forwarded-For`, which the caller sets and could therefore forge. Everything
else gets a 403, including the install page and login. Empty (the default)
allows anyone who can reach the port.

It does not replace the login: whatever can reach the proxy can still reach the
API through it. It stops everything else on the LAN from talking to the port
directly.

### Updating after you push

Push, then deploy. From your laptop, if your account is an admin:

```bash
cloudmorrow update server
```

That goes through the API — no shell on the server, no ssh agent, nothing to
type but the command. The server puts its own checkout on whatever the remote
branch says, reinstalls in case dependencies moved, rebuilds the client wheel,
and restarts onto the new code; the command waits for it to come back and
prints the commit it came back on. With nothing new to pull it says so and
stops.

So a release is two things:

```bash
python scripts/release.py   # tag this commit, push the code and the tag
cloudmorrow update server     # the server runs it, and republishes the wheel
```

`cloudmorrow update all` does that second line and the `cloudmorrow update` that
usually follows it, in one go.

### Versions

The version is a git tag. Nothing writes it down — `pyproject.toml` reads it
back off the nearest `vX.Y.Z` behind `HEAD` — so there is no number in a file
to go stale and no way for it to disagree with the history it claims to
describe.

One bump per push: every push of new code is a release and takes the next
minor, which is what `scripts/release.py` does. A major is the only thing
anyone decides:

```bash
python scripts/release.py            # 0.6.0 → v0.7.0
python scripts/release.py --major    # 0.6.0 → v1.0.0
python scripts/release.py --dry-run  # say what it would do
```

It refuses on a dirty tree, and refuses to tag a commit that is already a
release — a push with nothing new in it is not one. The tag and the commits go
up together (`git push --follow-tags`), so the remote never holds code whose
release has not arrived.

Between releases the version says so: a commit past `v0.7.0` builds as
`0.8.0.dev3+g1c91c8b` — the release being worked towards, how far past, and
which commit. Anything with `.dev` in it is not a release, and the deploy
output names it by its commit rather than dressing it up as one.

The commit hash has not gone away, and should not: a version only changes when
a tag does, so it cannot prove a process restarted onto new code. That is what
`/api/health` still reports a commit for, and what `cloudmorrow update server`
compares when it waits for the server to come back. The version is what you
read; the commit is what is checked.

Nothing on the server watches git, by design — a push on its own deploys
nothing, and the deploy is a thing you do at a moment you choose.

**What restarts it, given the service has no privileges.** The service user
owns `/opt/cloudmorrow` and the deploy key, so the pull and the reinstall are
just it working on its own files. The restart it genuinely cannot do — so it
does not try: it stops itself, and systemd starts it again on the new code.
That is what `Restart=always` in the unit is for, and the server checks the
unit says so *before* it stops — otherwise a deploy would take the API down
until someone walked over to the box. `systemctl stop cloudmorrow` still stops
it for good; systemd knows the difference between that and an exit.

**What it trusts.** An admin token can change the code the server runs. That
is a real step up from what a token could do before, and worth deciding
deliberately rather than inheriting. What bounds it is git: the deploy is
`git reset --hard origin/<branch>`, so it can only run a commit that is
already pushed to the repository — not code of the caller's choosing. If that
is still more than you want a bearer token to do:

```toml
allow_api_update = false    # in /etc/cloudmorrow/server.toml
```

and the endpoint answers 403 for everyone.

**The way in when the API is the problem.** A bad deploy is exactly when you
cannot use the API to fix it, so the ssh path stays:

```bash
cloudmorrow update server --ssh
```

or, from your own account on the server, no sudo password and no root shell:

```bash
cloudmorrow-update
```

Those drive the same update over ssh instead, authorised by your ssh access
plus the sudoers rule the installer wrote rather than by a token. `--host`
takes any ssh target when the API hostname is not the one you ssh to (an ssh
alias, a tailnet name); make it permanent with
`cloudmorrow config set server_host <target>`.

Either way it refuses to run if the checkout has uncommitted changes or if
history has diverged, rather than merging on your behalf; `--force` overrides
the first of those, `--branch` deploys something other than the current branch,
and `--no-restart` leaves the new code on disk with the old code still serving.

Under the hood the ssh path is `cloudmorrow-server update`, which also takes
`--source` if you need it.

**Upgrading a server installed before any of this existed.** The endpoint and
the `Restart=always` unit both arrive *in* an update, so the first one still
goes over ssh:

```bash
cloudmorrow update server --ssh     # deploys the code that adds the endpoint
```

then re-run `deploy/install-server.sh` (it rewrites the unit and is safe to run
again) or edit `Restart=` in `/etc/systemd/system/cloudmorrow.service` by hand
and `sudo systemctl daemon-reload`. After that, `cloudmorrow update server` is
the API path. Until the unit is right the deploy still lands — the server just
reports that it did not restart itself, and says why.

### Where the client comes from

Cloudmorrow is not on PyPI, so the server is where machines get it: the installer
builds a wheel from the deployed checkout into `<data_dir>/dist`, serves it at
`/dist/…`, and `/install.sh` installs from there. Every `cloudmorrow-update`
rebuilds it, so a machine installing tomorrow gets today's code.

`cloudmorrow-server publish` rebuilds it by hand; pass a `.whl` to publish one
built elsewhere.

The wheel keeps the same version number between commits, so `/install.sh`
installs with `--force-reinstall` — otherwise pip would decide the old copy
already satisfied it.

## Notes on the phone

The install page is for machines. A phone gets the other thing on it: **Sign
in**, which opens `https://cm.hl.bramlabs.io/app`. Sign in with the same
username and password as `cloudmorrow login`, and the token stays in the browser
for as long as the server's `token_ttl_hours` says (thirty days by default),
so it is one sign-in, not one per visit.

It opens on **Today**: the time, the weather, a line worth a second thought,
and what the calendar has for the day, so the front page is a glance rather
than a tab. The clock is the phone's own. The quote is the day's — the same
one for everybody on the server, a different one tomorrow, from a list in
`server/today.py` that is there to be added to. The weather is Open-Meteo's,
which needs no key, for the place named by `weather_place` in the server
config (`"Copenhagen"`, or `"55.68,12.57"` when a name is ambiguous); leave
it out and the card says so instead of guessing. The events are the
calendar's, in its own rows, and the section is gone when that tab is
switched off.

**Me** — who you are signed in as, your switches, and the way out — is in
the top-right corner of every tab rather than a tab of its own, which is
where a phone keeps it. What a screen makes — a note, a task, an event, a
file — is the button beside its title.

Notes is three screens, the way a phone's notes app is: **Folders**, the
notes in one (newest first, with the first lines of each), and the note. The
pen beside the title starts a new note in the folder you are looking at; the
title is the file name, and the note saves itself as you type. Back out of a
note you never wrote anything in and it is thrown away. Search looks inside
the notes, not only at their names.

It writes the same files the TUI does. A new note starts with a `# Title`
heading matching its file name, as the TUI's do, and the app shows that heading
as the title rather than as a line of the body. Rename the title and the file
is renamed. Delete is the bin in the top corner, and asks first.

On iOS, share-sheet → **Add to Home Screen** makes it an app of its own: an
icon, no browser chrome, and it opens where you left it. Anything that can
reach the API can use it; there is nothing to configure on the server.

### The same app on a computer

Past 900 points wide — and 600 tall, because a phone held sideways is still a
phone — the tabs stand up into a **rail down the left**, with the wordmark at
the head of it and the name of the screen in the bar instead. The bar's
buttons come in to meet the column they act on rather than sitting out at the
window's edge, every row and tile says when the pointer is over it, and the
sheet that slides up from under a thumb is a dialog in the middle. The rail
stays put in an editor and in a thread, which on a phone drop the tab bar to
give the keyboard the room.

The keys are the ones already on the screen: `Esc` is the back button (or the
field you are in), `/` is the search box, `n` is the pen beside the title,
`j` and `k` — and the arrows, once the list has the keyboard — walk the rows,
and `Enter` opens the one you are on.

None of it changes the phone: `desktop.css` is one media query, and the two
rules outside it hide the parts that are only ever for the rail.
`tests/test_desktop_web.py` is that promise, kept by a test rather than by
hand.

### Administration, from the phone

The server's own panel is here too, so a new account does not mean walking
to the desk. It is a row at the bottom of **Me**, and only an administrator
is shown it — a row nobody else can use is a row nobody else should see.
Typing `#/admin` as anybody else lands you back on Me with a word about it,
which is a courtesy rather than the guard: every call under it is admin-only
at the server, and the screen would be empty without that.

Two sections under a switch, the same two the terminal app has:

- **Users.** Every account, with its type and, where it is worth pointing
  at, its role on a chip — an ordinary User has no chip, because that is the
  ordinary case, and an account that cannot sign in says so first and in
  red. Tapping one opens it: name, a new password (blank leaves it alone),
  role, type, and whether the password is still answered. The pencil beside
  the title makes a new one. Your own account is missing its Delete button,
  because the server refuses that anyway and a button that always fails is
  worse than no button.
- **Features.** Every area of the app with a tick box, what goes dark when
  it is off, and who last switched it. This is the server's switch, for
  everybody. Your own is further up the same screen, under **What your apps
  show you**.

One thing the terminal app does not have yet: **May sign in**. The API has
always taken it and the TUI's table has always shown it, with no way to
change it; the web form has the switch. Turning it off keeps the account and
its files and turns away the password.

## Two switches on every feature

A feature — Notes, Tasks, Calendar, Chat, Projects, Files — has two
switches, and they are not the same kind of thing.

**The server's** is an administrator's, in the Administration panel. Off
means off everywhere: the tab goes from every client, for everybody, and
the API answers 403 to anything that belongs to it. It is a statement about
what this server is.

**Yours** is in your own settings — the terminal app's Settings (`^g`), and
**Me** on the phone. Off means the tab goes from *your* clients, on every
machine you sign in from, because the answer is kept with your account
rather than on the machine. It is a preference, so it hides rather than
forbids: the API still answers you, and a link straight to a hidden screen
still works. A preference that closed the door would be a mistake with no
way back from the phone you made it on.

The two only ever narrow, and the narrower one wins. A feature the server
has switched off is **not in your settings at all** — not listed as off,
not listed — because it is not a thing you can have an opinion about. Your
own answer is remembered underneath it, so a feature switched off and back
on by an administrator comes back as you left it, not as they found it.

What is yours follows from that. The count on the home-screen icon stops
counting chat messages when you switch Chat off, because a number for a tab
you have not got is a count of something you cannot go and read. And with
every tab switched off the terminal app says so and points at Settings,
rather than leaving a pane up that nothing points at.

Two endpoints, and the difference between them is the whole of the story:
`/api/server/features` is the server's list, readable by anybody and
switchable by an administrator; `/api/me/features` is the same catalogue
narrowed to you, with your answer on each, and yours to switch. A client
that draws tabs asks the second one.

## Quills

Everything beyond the foundation is a **Quill**: Tasks today, and whatever
the [Quill Catalog](https://github.com/Cloudmorrow/quill-catalog) has next.
The contract is [QUILLS.md](QUILLS.md); this is how to use them.

**On a fresh server** the catalog's foundation Quills — Tasks, for now — are
installed at first boot, and boards and tasks from before Tasks was a Quill
move into the record store the first time the new version starts. Nothing
needs doing by hand. The server needs to reach GitHub for both; if it cannot,
it says so in the log and tries again at the next start.

**Adding one** is Administration → Quills on the phone or in the browser, the
Quills section of the TUI's Administration panel, or:

```sh
cm quill catalog          # what there is, by category
cm quill add tasks        # what it adds — datamodels, screens, jobs — then a yes
cm quill list
cm quill remove tasks     # its tabs and jobs go; your records stay
```

**Using one** is its tab, on every client, and the command line:

```sh
cm tasks list             # the board, lane by lane
cm tasks add "Repot the fig" due=2026-10-01
cm tasks done fig         # by the start of its id, or its title
cm tasks move 8f2c doing
cm tasks groups           # the boards
```

A Quill is a feature like the built-in ones: an administrator can switch it
off for the server, and each person can hide its tab (see *Two switches on
every feature*).

**Building one** needs no server to start:

```sh
cm quill new plants       # a folder with quill.toml, a datamodel, CLAUDE.md and a CI check
cd quill-plants
cm quill check            # against the foundational datamodels, with a preview of each screen
cm quill dev              # on your own server, on every device, now
```

`quill_catalog` in the server config says where the catalog is read from —
the GitHub URL by default, or a local folder.

## Chat

Everything else in Cloudmorrow is one person's. Chat is the exception, and it
is the reason the server knows how to talk to somebody who is not asking.

Chat is a Quill — [`Cloudmorrow/quill-chat`](https://github.com/Cloudmorrow/quill-chat),
in the catalog with Tasks and offered, ticked, when you install. It has no
code: a channel is a record of the foundational `channel` datamodel (a
*space*), a message one of `message` (in a channel, its author's), and its one
screen is the kit's `thread`. A server that had Chat before it was a Quill
gets the Quill at boot, switched on or off as the feature was, and its
channels, messages and read marks move into records once; the old tables stay
where they were.

There are three kinds of channel, and the kind *is* the access rule — there
is nothing else to check, and no permissions screen:

- **Public.** Everybody is in it. It is in everyone's list, anyone may write
  in it, and nobody can leave — leaving a room everybody is in is a mute, and
  a mute is not this. `#general` is one, made once for the whole server the
  first time anybody opens Chat.
- **Private.** The people in it. Anyone can make one and put people in it;
  there is no invitation to accept, because an invitation you have to accept
  is a second thing to build and a second thing to forget. You are added, you
  get a notification saying so, and you can leave. Its maker can take
  somebody out, and anybody in it can add somebody.
- **Direct.** Two people, and it is never made from a form. Pick `ada` and the
  conversation with her is there, whether or not it existed a moment ago;
  `ada` picking you finds the same one. It is called after the other person.

Everyone can write to everyone. There is no setting for that. A channel is
its maker's to rename, re-topic or delete (and an administrator's); a message
is its author's to change or take back.

**Unread** is when you last looked: everything somebody else wrote in a
channel after that is unread, and opening the channel — on any device — moves
it on. Writing in a channel reads it, since you cannot reply to what you have
not looked at. Somebody added to a channel counts from when they were added,
and a new account counts the public channels from when it was made: the
history is there to scroll back through, but a year of it is not a badge.

It is on every surface. On the phone it is the channels, then a conversation;
on a computer both side by side. In the terminal it is the **Chat** card
(`f4`), channels on the left and the conversation on the right, with `n` for a
new channel, `m` to write to one person, `a` to add somebody, `e` to rename or
delete one of yours and `l` to leave. On the command line:

```
cm chat list                     # the channels, with what is unread in each
cm chat show general             # the conversation, newest at the bottom
cm chat say ada "on my way"      # a channel by name, or the person
```

An assistant reaches it with the generic record tools.

Neither client holds a socket open. A conversation that is on screen asks for
what changed since the newest line it has, every few seconds, and a push wakes
it the moment something arrives — so the common case is instant, the fallback
is a small request that usually answers with nothing, and the server stays a
plain request-and-response thing that a phone on a train reconnects to
without noticing.

An administrator can switch it off in the Administration panel, like any
other Quill: the tab goes and the API answers 403. Removing the Quill takes
its tab and nothing else; the channels and messages are records, and stay.

## Calendar

The second thing here that is not one person's, and it borrows chat's shape
on purpose: the kind of a calendar *is* the access rule.

- **Personal.** Yours. Everybody has exactly one, made the first time they
  ask for their calendars and named after them. It cannot be shared, left or
  deleted — it is where your own things go, and a place that can vanish is
  not that. If you want one other people can see, make a shared one.
- **Shared.** The people in it. Anyone can make one and put people in it;
  as with a private channel there is nothing to accept, you are added, told
  so, and can leave again. Whoever made it can rename it, recolour it and
  delete it; everybody in it can write in it, because a shared calendar you
  cannot write in is one you are being *shown*.
- **Public.** Everybody's. In everyone's list, anyone may put something in
  it, and nobody can leave it.

**An event is a title and two moments**, plus where it is and anything else
worth writing down. Leave the end off and it is an hour long, or the whole
of the day it is on. Whoever wrote it may change it, and so may whoever owns
the calendar it is on — a shared calendar with somebody's stale event stuck
on it, and only that somebody able to fix it, is a worse rule than this one.
Moving an event keeps how long it is: an hour at ten, dragged to half
eleven, is an hour at half eleven.

**The times are the times on the wall.** A moment is stored as the local
time somebody typed — `2026-09-19T14:00` — and an all-day event as a bare
date. No zone, no conversion: this is one house on one clock, and "the
dentist at ten" is at ten on every screen in it, in October and in June
alike. It also makes "what is on this month" a pair of string comparisons,
because ISO sorts the way time does.

Being given a calendar leaves a notification and a push, the way being added
to a channel does. An event does not: a house calendar that pinged everybody
for every appointment is one nobody reads.

It is in both clients. In the terminal it is the **Calendar** tab (`f7`) —
the calendars on the left, the month beside them with a coloured dot per
event, and the day you are standing on written out underneath. `n` makes an
event on that day, `e` changes the one under the cursor, `del` removes it,
`c` makes a calendar, `s` shares it, `l` leaves it, `t` is today, and `[`
and `]` are the months. The list on the left is not a filter: what it picks
is which calendar a new event goes in. On the phone it is a month you tap a
day in, the day's events under it, and the little people icon beside the
month for the calendars themselves — where one is made, coloured, shared
and left.

An administrator can switch the whole thing off in the Administration panel,
like any other feature: the tab goes and the API answers 403.

## Push notifications

A web app on an iOS home screen is not a process most of the time — it is an
icon and a screenshot. Nothing it could poll would keep the count on that
icon right, so the count on the icon needs a real push: the browser vendor's
service wakes a service worker, and the worker shows the banner and sets the
badge. That is what `server/webpush.py` is.

Three specifications, implemented rather than installed, because the server's
dependencies already cover them (`pyjwt`, `cryptography`, and the standard
library):

- **RFC 8030** — a POST to the endpoint the browser gave us.
- **RFC 8292 (VAPID)** — an ES256 JWT saying which push service the message
  is for and when it expires, signed with a P-256 key in
  `<data_dir>/vapid.key`, generated on first use at mode 600. The public half
  is what the browser subscribes with, which is what ties the two together.
  Lose the file and no data goes with it, but every device has to be asked
  again — so back it up with the database.
- **RFC 8291 / 8188 (aes128gcm)** — the body, encrypted to the subscription's
  own key, so the push service carries something it cannot read.

The number on the icon is **everything waiting**: everything unread in the
spaces you are in — a channel's messages, or whatever another Quill declares
`unread` — plus unread notifications. It is worked out in one place
(`/api/push/badge`) so
the page, the service worker and the push payload cannot disagree about it.
Each push carries the recipient's own badge, which is why a message to four
people is four requests rather than one.

On iOS none of this exists until the app is on the home screen — in a Safari
tab there is no service worker to push and `setAppBadge` does nothing. So
**Me** says which of those situations you are in rather than offering a
button that cannot work: add it to the Home Screen, open it from there, and
**Turn on** appears. Once it is on, **Send a test** pushes you, because
everything between the server and the banner fails silently and otherwise the
only test is asking somebody to message you.

Set `push_subject` in the server config to the `mailto:` or `https:` URL a
push service should complain to. Left empty it is derived from `public_url`,
which is the truest answer the server has on its own.

Signing out does **not** unsubscribe the device: signing out of the phone app
and back in is routine, and asking iOS for permission again each time is the
quickest way to have it refused for good.

## An assistant working as you

The server speaks [MCP](https://modelcontextprotocol.io) at `/mcp`, so an
assistant that speaks it — Claude Desktop, claude.ai, Claude Code, or any
other client — can read and write your notes, tasks and projects for you,
as you. It signs in the way OAuth 2.1 says a client should, which means
there is nothing to configure and no token to paste:

1. Add the server's address to the assistant — in Claude Desktop and
   claude.ai that is **Settings → Connectors → Add custom connector**, with
   `https://cm.hl.bramlabs.io/mcp` as the URL; in Claude Code it is
   `claude mcp add --transport http cloudmorrow https://…/mcp`.
2. The assistant finds the sign-in page on its own and opens it in a
   browser: a page of this server's, which says who is asking and what it
   will be able to do. Sign in with your Cloudmorrow username and password
   and press **Allow**.
3. That is all. The assistant holds a token of its own from then on — good
   for `/mcp` and nothing else, and refreshed by itself for as long as it
   is used.

What it can do is what you can do in the app, one tool per thing: list,
read, search, create, write, append to, move and delete notes; list boards
and tasks, add a task, change it, move it between lanes; list, find, make
and change projects. Secrets are not on the list, on purpose. A feature an
administrator has switched off takes its tools off the list too.

Everything it does happens as you and lands where your other clients see
it, the moment it happens. To see which assistants you have let in, and to
cut one off:

```bash
curl -s $CLOUDMORROW/api/mcp/connections -H "Authorization: Bearer $TOKEN"
curl -s -X DELETE $CLOUDMORROW/api/mcp/connections/3 -H "Authorization: Bearer $TOKEN"
```

A cut-off assistant is back at step 2 the next time it tries.

Behind a reverse proxy, set `public_url` in the server config: the sign-in
flow tells the assistant where its pages are, and behind a proxy the server
cannot tell that address from the request it sees. Wiring a client up by
hand, without the sign-in page, works too — an ordinary access token from
`/api/auth/login` opens `/mcp` as well.

## Client, on your machine

Open `https://cm.hl.bramlabs.io/` and copy the one command it shows:

```bash
curl -fsSL https://cm.hl.bramlabs.io/install.sh | sh
cloudmorrow login -u bram
cloudmorrow                              # opens the TUI
```

It needs Python 3.11+ and nothing else: it makes a venv under
`~/.local/share/cloudmorrow`, links `cloudmorrow`, `cm` and `cloudmorrow-agent` into
`~/.local/bin`, and points the CLI at the server. As root it installs into
`/opt/cloudmorrow` and `/usr/local/bin` instead. `pipx install 'cloudmorrow[tui]'`
works too.

`cloudmorrow login` also registers the machine as an agent and starts it under
your account — see [the local agent](#the-local-agent). `--no-agent` skips
that if you would rather not.

Config lives in `~/.config/cloudmorrow/config.toml`, the token in
`credentials.json` beside it (mode 600).

### Keeping it up to date

```bash
cloudmorrow update
```

That is the install command without the copy and paste: it asks the server what
it is handing out, installs that wheel over this copy, and restarts the local
agent so it stops running the code it started with. `--check` shows what would
be installed and changes nothing; `--no-agent` leaves the service alone.

Update the server first — that is what publishes the wheel this pulls:

```bash
git push                    # the code exists
cloudmorrow update server     # the server pulls, reinstalls, restarts, republishes
cloudmorrow update            # then follow it on each machine
```

On the machine you deploy from, `cloudmorrow update all` is those last two in
one word: it deploys the server, waits for it to come back, and then installs
the wheel that deploy just published. It stops if the deploy does, so nothing
is installed here on top of a deploy that did not land. The flags of both
halves are there — `--branch`, `--ssh`, `--host`, `--wait`, `--no-agent`,
`--force`.

Every deploy is a tagged release, so the client can tell: when the server
publishes the version this copy already is, `cloudmorrow update` says it is up
to date and touches nothing — no reinstall, no agent restarted onto the code
it is already running. Otherwise it installs and says what it went from and
to. `--force` reinstalls anyway, for a redeploy of the same tag.

From a git checkout, `cloudmorrow update` refuses and tells you to `git pull`
instead, rather than pip-installing a wheel over your working copy.

### Removing it

```bash
cloudmorrow uninstall
```

The reverse of the install, in the reverse order: it strikes this machine's
agent off the server, stops and removes the agent service, deletes
`~/.config/cloudmorrow` (the config, the token and the project links), the
backups the agent made (`--keep-backups` leaves them), the `cloudmorrow`, `cm`
and `cloudmorrow-agent` links, and last the venv under
`~/.local/share/cloudmorrow`. It lists all of that and asks first; `--yes`
skips the question. Nothing on the server is deleted except the agent record
— your notes, projects and secrets are the server's. From a development
checkout it leaves the checkout and its venv alone.

## Secrets

Keys and passwords, yours. A secret lives in a **vault** and an
**environment**. The vault is `default` until you name one — `home`,
`work`, `verticore` — and the environment is `local` until you say
`production`. Both have a default, so the common case is bare:

```bash
cloudmorrow secret list                            # keys only; values stay hidden
cloudmorrow secret list -e production
cloudmorrow secret list --all                      # every environment at once
cloudmorrow secret list --reveal                   # values too, on purpose
cloudmorrow secret get OPENAI_API_KEY              # raw value, nothing else
cloudmorrow secret set OPENAI_API_KEY              # prompts, no echo
cloudmorrow secret remove OLD_KEY -e production
cloudmorrow secret vaults                          # what vaults hold something
cloudmorrow secret environments                    # what environments this vault has
```

`-v` names the vault, `-e` the environment, and the config remembers a
default for each:

```bash
cloudmorrow secret list -v verticore
cloudmorrow secret get OPENAI_API_KEY -v verticore -e production
cloudmorrow config set vault home                  # from now on, -v home is implied
```

`secret get` writes the value to stdout and nothing else, which is the whole
point:

```bash
cloudmorrow secret get OPENAI_API_KEY > key.txt
export OPENAI_API_KEY="$(cloudmorrow secret get OPENAI_API_KEY)"
```

`secret set` never takes the value as an argument — an argument shows up in
`ps` and lands in your shell history. At a terminal it prompts without echo;
handed something on stdin it takes that instead, minus one trailing newline:

```bash
cloudmorrow secret set DATABASE_URL -e production        # prompts
printf '%s' "$OPENAI_API_KEY" | cloudmorrow secret set OPENAI_API_KEY
cloudmorrow secret set OPENAI_API_KEY < secret.txt
```

Whole files, in and out:

```bash
cloudmorrow secret import -f .env.production -e production -v verticore
cloudmorrow secret export -e production -f .env    # write a .env, mode 600
cloudmorrow secret run -e production -- npm start  # no file at all
cloudmorrow secret purge -e staging                # the whole environment
cloudmorrow secret purge -v scratch --vault-and-all  # the whole vault
```

Importing merges by default: keys in the file are set, everything else is left
alone. Two flags change that, and `--dry-run` shows what either would do before
it does it:

| flag | |
| --- | --- |
| `--prune` | delete keys the file does not mention, so the environment matches it |
| `--no-overwrite` | keep values that are already there, fill in only what is missing |
| `--dry-run` | report what would change and write nothing |

`secret run` puts the values in a child process's environment and nowhere
else — no file to forget to delete. `secret export` writes mode 600, and
says so if it just wrote into a git repo that is not ignoring the file.

Environments are free-form: `local`, `development`, `staging`, `production`,
`test`, anything you type. Leave `-e` out and the configured default is used
(`local`, changed with `cloudmorrow config set environment <name>`). If the
environment you asked for is empty and others are not, the answer says which.
Vaults are the same shape, and a vault exists exactly as long as it holds
something: there is nothing to create and nothing to delete but the secrets.

In the TUI, `f3` opens **Secrets**: your vaults down the left, and for the
one picked, its environments across the top and that environment's keys
below. See [The TUI](#the-tui).

**What a vault used to be.** Secrets belonged to a *project* — a name, a
git URL, and a checkout `project add` read `.env` files out of and `project
clone` wrote them back into. That is gone: a secret is yours, not a
project's, and where it goes is a place you name. An older server's secrets
keep their place under a vault of the project's name, because the column
was renamed and the values, and their seals, kept.

### How they are stored

Values are sealed with AES-256-GCM under the server's key, each bound to the
row it belongs to — owner, vault, environment and key — so a sealed value
cannot be moved to another row, or another account, without the tamper check
failing. Key names, vaults, environments, lengths and a keyed fingerprint of
each value stay in the clear, which is what lets a listing be a listing
without opening anything. The fingerprint is an HMAC, not a plain hash: it
tells two values apart without being guessable. The key, and what else it
seals, is [Encryption at rest](#encryption-at-rest).

### Types: what kinds of data there are

Secrets are the first thing in the *foundation*: a kind of data the server
owns rather than any app. `GET /api/types` lists every kind there is —
users, secrets, files, shares, machines and notifications from the
foundation, then notes, boards and tasks, calendars and events, channels
and messages from the included apps — with its fields, which of them are
sealed, whether it may be shared, which apps use it and whether an
assistant let in over MCP may reach it. Secrets say no to that last one,
on purpose. Each app's row in `/api/server/features` names the types it
uses. Nothing enforces yet; this is the catalogue the guard will be
checked against, and the promise that a kind of data an app introduces is
yours, listed here, for any other app you allow.

## Encryption at rest

The long version, with the threat model and what every store seals, is
[ENCRYPTION.md](ENCRYPTION.md). The short one:

The server's disk holds ciphertext. Every piece of content — a chat message
and a channel's topic, an event's title, notes and place, a task and its
board's title, a notification, a synced dotfile, a project's description, an
agent job's payload and result, a phone's push keys, a secret's value, and
every note and picture in the notes tree — is sealed with AES-256-GCM before
it is written and opened when it is read. What stays plain is what the
server needs to find, sort and range by: usernames, slugs, timestamps, lanes,
positions, who is in a channel, and the names of notes, which are their file
names.

**One key, held by the server.** It is a file — `key_file` in the config,
`/etc/cloudmorrow/cloudmorrow.key` on an installed server, `<data_dir>/secrets.key`
when unset — generated on first boot at mode 600. The install script puts it
in `/etc`, away from `/var/lib`, so a copy of the data directory on its own
opens nothing. Three subkeys are derived from it, for the database, for the
notes tree and for secrets, so none of them is the key itself. Nobody who
uses Cloudmorrow ever sees any of this: you sign in with a password, and the
server does the rest. That is the point, and also the limit: this is
encryption at rest, not end to end. It protects the database file, the notes
directory, a backup of either, and a disk that leaves the machine. Whoever
has the key file and the data has everything.

**Back up the key with the data, and never instead of it.** Lose the key and
every note, message and secret is gone; there is no recovery. Keep a copy
somewhere that is not the server.

**Every seal is bound to its row.** A sealed value carries, in its tamper
check, the table and column it belongs to and what it is scoped by — the
channel a message is in, the owner of a task — so a row cannot be moved to
another channel or another account by editing the database.

**Older data is sealed on the first boot.** A database from before this
release is sealed in one transaction the first time the server opens it, and
every user's notes tree is swept at boot; a plain file left in a notes
directory is read as itself and sealed on the next start. After that every
read expects ciphertext, with no guessing: a message that happens to look
like one is still a message.

**Changing the key.** Stop the service, run `cloudmorrow-server rotate-key`,
start it again. Every row and file is opened under the key in place and
sealed under a new one, which replaces it; the old key stays beside it as
`cloudmorrow.key.old` until you delete it.

Not covered yet: the files in My Files and the fileshares, which are served
over WebDAV straight from disk, and the notes' file names.

### In transit

TLS ends at the reverse proxy — Caddy or nginx, see [The URLs](#the-urls) —
and the server listens on plain HTTP behind it, on this machine. Three
things make sure that is the only plain hop:

- **The server insists.** With `require_tls` on, which it is whenever
  `public_url` is https, a request that did not come over TLS is refused with
  426, and every TLS answer carries HSTS. What uvicorn reads from the proxy's
  `X-Forwarded-Proto` is what counts. A call from the box itself with no
  proxy header — `curl 127.0.0.1:8787` — is let through; it crosses no wire.
- **The clients refuse.** The TUI, the CLI and the agent will not talk to a
  plain `http://` address unless it is this machine, or the config says
  `allow_insecure_http = true`, which is a decision for a box you have
  reasons to reach in the clear, not a default.
- **What is not there yet.** A machine share is served by the agent on that
  machine over plain HTTP on your LAN, with Basic auth. It is the one place
  content still crosses a wire unencrypted; certificates issued by the server
  are the fix, and the next step.

## Notes

A note is a title and some markdown. Titles may contain slashes, which makes
them folders on the server.

```bash
cloudmorrow note list
cloudmorrow note show "Architecture"
cloudmorrow note add "Hetzner setup"        # opens $EDITOR
cloudmorrow note edit "Hetzner setup"
cloudmorrow note remove "Hetzner setup"
cloudmorrow note search postgres
cloudmorrow note rename old/plan new/plan
```

Text comes from stdin when there is any, and from `$EDITOR` when there is not.
`note show` writes the raw text to stdout, so redirection and pipes work:

```bash
cat architecture.md | cloudmorrow note add "Architecture"
cloudmorrow note show "Architecture" > architecture.md
cloudmorrow note show README | less
```

Notes are yours, not a project's: there is one set per account, and no `-p`
to think about. A title with slashes in it makes folders, which is how you
group them:

```bash
cloudmorrow note add "verticore/deployment"
cloudmorrow note list
```

In the TUI, `f1` opens notes: the list on the left, the live editor on the
right. `f6` imports a file into the selected folder and `f7` writes the open
note back out.

### Pictures

A note can carry pictures. On the phone, tap the photo button in the bar, or
paste one, or drop one on the note; in the TUI it is **Photo** (`ctrl+p`),
which asks for a file on this machine. Either way the picture is sent to the
server as it is, kept beside your notes, and a line is written where the
cursor was:

```markdown
![rack front](img/20260917-135026-8e642c-rack.png)
```

**Where they are.** `<notes root>/img/`, one flat folder. The name says when
the picture arrived, carries six random characters so two pastes in a second
cannot collide, and ends with what the file was called, so `ls img/` still
reads. The type is taken from the bytes, never from the name: PNG, JPEG, GIF
and WebP, up to 25 MB. The folder never shows in the note list — a picture
is something a note shows, not a thing to find — and a copy of the notes
tree takes the pictures with it, because they are files like everything else,
sealed like everything else.

**How they show.** The phone puts every picture the note mentions in a strip
under the text, in the order it mentions them; tap one to see it full size.
The TUI draws the picture the cursor is on — or the note's first, when the
cursor is elsewhere — in a panel beside the editor. Where the terminal speaks
Kitty's graphics protocol or Sixel (Kitty, Ghostty, WezTerm, foot, iTerm2)
that is the real picture; anywhere else it is coloured half-cells, which is
enough to tell the right photo from the wrong one. The editor itself still
shows the line as `🖼 rack front`: it draws one line per line of source, and
a picture is not a line.

Nothing deletes a picture yet: take the line out of the note and the file
stays in `img/` until something prunes it.

## Fileshares

A share is a directory with a name. The name is the last segment of its
URL — `…/dav/media/` — and the thing you mount. There are two kinds, told
apart by where the directory is:

- A **server share** is a folder in the Shares folder on the server, served
  by the server. Only an admin makes one: it puts files on the server.
- A **machine share** is a directory on the machine you are standing on,
  served by the agent running there. Anyone makes one — it is their own disk
  — and it is there for their other machines exactly as long as that agent
  is running. The Files tab and `share list` say which machine, and whether
  it is serving right now. It is always *this* machine: you share the
  directory in front of you, not a path on some other box typed from memory,
  so there is no machine to pick and nothing to get wrong. To share something
  on the desktop, make the share from the desktop.

```bash
cloudmorrow share add music --path ~/Music    # this machine
cloudmorrow share add media --server          # the server (admins)
cloudmorrow share mount music                 # ~/Fileshares/music, or /Volumes/music on a Mac
cloudmorrow share unmount music
cloudmorrow share remove music                # stops serving it; the files stay
cloudmorrow share remove media --files        # …and deletes its folder on the server
```

The same things are buttons on the **Files** tab, where a new share is on
this machine, or — for an admin — on the server. On a machine that has no
agent yet there is nothing to serve a share, and both say so.

**My Files.** Beside the shares, every account has a drive of its own on
the server, served as `my-files`: `…/dav/my-files/`, first in `share list`,
mounted with `share mount my-files`, and at the top of the **Files** tab in
both apps. Nobody makes it and nobody removes it — it is there because the
account is — and only its owner ever sees it. Its files are in that
account's own tree, `<notes_dir>/<username>/files/`, beside their notes.

In the web app, the **Files** tab lists My Files, then your shares. A server share opens as
its folders and files, the way a file manager shows them — sorted by name,
date, size or type, folders first — as a list, or as a grid of thumbnails
(the switch beside the sort; the choice is kept). A picture opens when
tapped, with its facts under it and a button that opens the phone's share
sheet. The plus in the bar puts a file in the folder you are in: one chosen
from the phone, or one its camera takes there and then. A machine share is
listed but not opened there: its files are on that machine, so it is
browsed from a mount.

The terminal app has the same: **Browse**, the third tab on Files, or
enter on a share in Fileshares. The same list, the same sort (`s` is the
next one, `S` turns it around), `v` for thumbnails, and the picture the
cursor is on drawn beside the listing — the real picture in Kitty or a
Sixel terminal, coloured half-cells anywhere else.

**Thumbnails.** The server makes them, once, with the long edge at one of
a few sizes, and keeps them under `<data_dir>/thumbs/`. The key includes
when the file changed, so a picture put back under the same name gets a
fresh one; the stale one is just never asked for again, and the folder is
safe to empty at any time. A JPEG, PNG, GIF, WebP, BMP or TIFF gets one;
a HEIC or an SVG shows as its icon, since Pillow reads neither without
help.

**Where a server share's files are.** In the Shares folder on the server,
and nowhere else: `<notes_dir>/Shares/` in the Cloudmorrow directory, or
`shares_dir` if the server config sets one. One folder for everyone's
shares, whichever admin made them. A share is the folder of its name in
there. `share add media --server` makes `Shares/media` if it is not there
— and if you have already
put a folder there (rsync'd a library in as `Pictures`, say), naming it
shares that folder as it is, whatever its case. The new-share dialog lists
the folders that are not shares yet. Keeping every share inside that one
directory is what lets the server be locked down to it: the systemd unit
makes the rest of the filesystem read-only, so a share anywhere else could
be read but never written to. `--files` on remove deletes the folder;
without it the share is only unlinked and the folder stays.

**How a machine share works.** The server keeps only the record: which
machine, which directory. The agent on that machine learns its shares on its
heartbeat, serves them over WebDAV itself — `http://<that machine>:8788/dav/<name>/`
— and reports the address back on the next heartbeat, which is what the
server hands out as the share's URL. When the heartbeats stop, the share is
offline and `share mount` says so. A mount signs in with your username and
token as ever; the agent has no passwords and no signing key, so it asks the
server whether they are good, and only the owner's are — a machine share is
one person's disk, for that person's other machines. The other machines
have to reach that one directly, so this is for machines on the same
network; the server share is the one that works from anywhere. In
`agent.toml`, `allow_shares = false` keeps a machine out of it, `share_port`
moves the port, and `share_host` names the address to advertise when the
one the agent works out for itself is not the one the others can reach.
WsgiDAV, which speaks the protocol, is not installed with the agent: the
first time a machine has a share to serve, its agent fetches it into its own
venv, so a machine that never shares never carries it.

**How it is served.** WebDAV, by [WsgiDAV](https://github.com/mar10/wsgidav),
mounted inside the API at `/dav`. Every machine already has a client for
that, which is the whole reason it is WebDAV rather than a FUSE driver of our
own: a driver would be more code on the end that is hardest to debug, for a
mount that behaves worse than the one the OS ships. The endpoint speaks HTTP
Basic and takes your password — or the access token `cloudmorrow login` stored,
in the password's place. That is what `share mount` sends, so a mount is
signed in exactly as long as the client that made it, and no second password
is written anywhere. Each account sees only its own shares; someone else's
does not exist as far as `/dav` is concerned. Point any WebDAV client at the
URL — a phone's file manager, a Windows drive letter — with the same
username and password.

**Mounting.** What differs per platform is who does the mounting:

- **macOS** — Finder, through one AppleScript line (`mount volume`), so
  nothing is installed. Finder picks the place, always `/Volumes/<name>`
  (or `/Volumes/<name>-1` when the name is taken), and `share mount` reads
  the real path back and reports it. Basic auth over plain `http://` is
  refused by macOS; the server is behind TLS, so this only matters against a
  dev server, and there `rclone` on a Mac works too.
- **Linux** — `rclone mount`, which puts a FUSE filesystem in front of the
  share at the path you chose. `rclone` is one binary in every
  distribution's repository (`pacman -S rclone`, `apt install rclone`); the
  message when it is missing says so. Writes go through rclone's cache
  (`--vfs-cache-mode writes`), which is what lets programs that seek and
  rewrite — editors, most of them — work on a share. rclone's log for a
  mount is `mount-<name>.log` beside the client config.

What was mounted, and where, is written to `mounts.json` beside the client
config — per machine, since the same share is at a different path on each —
which is how the Files tab says "mounted at …" and `share unmount` knows what
to undo. A mount does not survive a reboot; run `share mount` again.

## The local agent

Every machine you sign in from registers itself. `cloudmorrow login` enrols it,
writes its config and starts it under your own account — a launchd agent on
macOS, a systemd user unit on Linux. There is no token to copy and nothing to
run by hand. On Linux the account is set to *linger*, so the unit keeps
running when you log out and starts at boot; and `systemctl --user` is
reached over the session bus even from a shell that came in over ssh, which
would otherwise say only "Failed to connect to bus". If a machine has no
session for you at all, that message now says to `loginctl enable-linger`.

It runs **as you**, not as a service account, so it works on your files with
your permissions and needs root nowhere. It belongs to the Cloudmorrow user who
signed in: your agents are yours, and nobody else can see or drive them.

Signing in again from the same machine rotates its credential rather than
making a second agent. `cloudmorrow logout` stops it and forgets the credential.

To see your machines and what they have done:

```bash
cloudmorrow agent list
cloudmorrow agent run 1 backup --payload '{"paths":["/srv/data"],"name":"srv"}'
cloudmorrow agent jobs 1
```

The agent runs the code that was installed when it started, so an upgrade needs
a restart to take effect — `cloudmorrow update` does that for you.

What a job can be:

| type | what it does |
| --- | --- |
| `ping` | liveness, and which agent version answered |
| `sysinfo` | hostname, platform, CPUs, load, disk usage |
| `backup` | tar.gz some paths into the agent's backup dir, with retention |
| `shell` | run a command — **off unless that machine enables it** |

Config sync is not one of these. It is not queued work at all: the agent does
it on its own every poll, for whichever bundles the server says this machine
keeps — see [Omarchy config in sync](#omarchy-config-in-sync).

Everything a machine may do is declared in its own `~/.config/cloudmorrow/agent.toml`
rather than decided by the server: backups only read below `backup_roots`
(your home, by default), `shell` needs `allow_shell = true` there, and
`allow_shares = false` keeps the machine from serving [fileshares](#fileshares).
A job asking for anything else comes back failed, with the reason.

For a headless box you never sign in on — a NAS, say — mint a token with
`cloudmorrow agent enroll-token` and use the install command it prints.

### The server's own agent

The server is the one machine nobody signs in on, so it enrols itself —
straight against its own database, no token to carry — and runs as the service
account rather than as anybody:

```bash
sudo cloudmorrow-server agent-install --run-as cloudmorrow
```

`install-server.sh` does this for you, right after it has made the first
account for it to hang on; if it could not make one, it says so and prints
the command for after you have. It writes `/etc/cloudmorrow/agent.toml` and a system unit at
`/etc/systemd/system/cloudmorrow-agent.service` — the one place Cloudmorrow
installs anything outside a user's own home. Run it again to rotate the token;
nothing is duplicated.

Its backup roots are the server's own `data_dir` and `notes_dir`, so
`cloudmorrow agent run <id> backup` on it backs up the thing worth backing up.

The server's venv installs `cloudmorrow[server,agent]` for this — it runs an
agent, so it needs what an agent needs. A deployment from before that was true
has only `[server]`, and one `cloudmorrow update server --force` reinstalls it
with both.

The agent talks to the API like any other client, so it has to be able to
reach it. On a server that answers only its reverse proxy
(`allowed_client_ips`), that means adding the machine's own address to the
list and pointing the agent at the local port with `--url`.

## Omarchy config in sync

Every machine already runs an agent, and the agents already talk to the server
every half minute. That is most of a config sync — the rest is one tick box.

Open **Settings** (`ctrl+g`, or the button in the top bar next to your name).
It names the machine you are sitting at, says whether it is an Omarchy box,
and offers one thing:

```
  omarchy config
  ● online
  Omarchy — ~/.config/omarchy
  syncing ~/.config/hypr

  [X] Keep Omarchy config in sync

  revision 4 from desktop at 2026-09-11 13:03
  claimed by laptop · 6 files · kept by desktop, laptop
```

Tick it and this machine's agent hears about it on its next heartbeat. From
then on, changing something in `~/.config/hypr` on any of these machines puts
it on all of them — nothing to run, nothing to remember.

### Who wins

**The first machine to tick the box decides.** Its copy becomes revision 1,
and every machine that ticks the box afterwards adopts that instead of arguing
with it. This is the whole conflict story, and it is deliberately blunt: one
of the copies has to win, and "whoever asked first" is the only rule that
needs no adjudication.

After that, each change makes a new revision. A machine pushes when its own
files differ from the revision it holds, and pulls when the server has moved
past it. Two machines editing at the same time do not merge: the one that
pushes first wins the revision, and the other notices the higher number on its
next pass and takes it.

**Nothing is thrown away.** Before a file is overwritten, anything that is not
the copy Cloudmorrow itself put there — never seen before, or edited here since
— is copied to `<name>.cloudmorrow-backup` first, and those backups are never
synced anywhere. So adopting somebody else's config leaves yours next to it.

### What travels

`~/.config/hypr`, and nothing else yet. The rest of `~/.config` is full of
things that are about one machine — monitor layouts, caches an app decided to
keep next to its settings — and a sync that overwrites those is worse than no
sync at all. Growing the list is a line in `PATHS` in
`src/cloudmorrow/agent/omarchy.py`, once a directory has earned it.

Text files only, nothing over 512 KiB, no symlinks (a link into a dotfiles
repo is that machine's arrangement, not something to copy onto everybody
else), and none of the droppings — `.swp`, `~`, `.bak`.

### Switching it off

Untick the box. The machine keeps every file it has and stops following the
others; the bundle carries on without it. To make the *next* machine decide
again from scratch, throw the server's copy away — the machines keep theirs:

```bash
curl -X DELETE $CLOUDMORROW/api/config/omarchy -H "Authorization: Bearer $TOKEN"
```

A machine can also refuse outright, whatever the server says, with
`allow_config_sync = false` in its own `~/.config/cloudmorrow/agent.toml`. Same
principle as `allow_shell`: what a machine will do to itself is declared on
that machine.

### By hand

The agent does this every poll, but you do not have to wait for it:

```bash
cloudmorrow-agent sync           # do a pass now, and say what it did
cloudmorrow-agent sync --reset   # forget what this machine holds, adopt the server's
cloudmorrow-agent status         # which revision this machine is on
```

### Notifications

Every claim, every push and every machine that adopts a config leaves a note
on the server. The bell at the far right of the TUI's top bar carries the
count of the unread ones; ringing it (`f8`, or a click) opens the list, with
one button to say you have read them. They are facts, not messages — nothing
pushes them at you yet, which is what makes them the right thing to hang a
live channel off later.

```bash
curl -s $CLOUDMORROW/api/notifications -H "Authorization: Bearer $TOKEN"
```

## The TUI

`cloudmorrow` with no command opens the workspace on **Notes**, which is what
this is mostly open for. The tab strip has six, because there are six kinds
of thing here — and fewer when one of them is switched off, by the server
for everybody or by you in Settings, since a tab follows its feature.

```
┌──────────────────────────────────────────────────────────┐
│ Notes  Tasks  Calendar  Chat  Secrets  Files             │
├─────────────┬────────────────────────────────────────────┤
│ default   3 │ verticore                                  │
│ home      8 │ [New vault ^n] [Add a] [Reveal v] [Copy c] …│
│▎verticore 5 │ [local 3] [production 2] [＋]              │
│             │ ┌────────────────────────────────────────┐ │
│             │ │ key        value    len  updated       │ │
│             │ │ API_URL    ••••••   21   2026-09-10    │ │
└─────────────┴─┴────────────────────────────────────────┴─┘
```

A vault is not a frame the rest of the app hangs inside — it is an item in a
list, laid out like notes: the list on the left, what you picked on the right.
One vault to a line, its name dotted out if the column is too narrow for it,
and how many secrets it holds at the end of the row. A vault you have just
named is a row before it holds anything, so there is somewhere to stand while
you add the first key.

**Picking a vault names it on the secrets calls, and nowhere else.** There
is no selected vault in the top bar, nothing else changes with it, and the
CLI's own default vault is left alone.

**Notes are not.** They are yours, and they stay put whichever vault you are
looking at. **Machines** are not a tab: the agents enrol themselves at
sign-in and get on with it, `cloudmorrow agent` lists them and their jobs,
and what they have done is behind the bell.

**Files** has two tabs of its own: **Local backups**,
which is a placeholder until this machine's backups have something to list,
and **Fileshares** — the shares the server holds for you, which of them is
mounted on this machine and where, and the buttons that make, mount, unmount
and remove one. See [Fileshares](#fileshares).

It is meant to be used with a mouse: the tabs, the sub-tabs, the buttons above
each pane, the rows in every table, the vaults in the list and the notes in
the tree are all click targets, and every one of them has a key as well.
Sweeping the pointer across text selects it, and selecting *is* copying: the
moment the button comes up, what was swept is on the clipboard and a toast
says so. There is no copy step to find, because a terminal has no menu to
find it in. In the editor the copy is what is on screen — the line being
edited as source, every other line as it renders. Escape clears the highlight.
Tables, lists and the note tree are not sweepable; a row there is something
you pick, and the buttons beside it copy what a row has to copy.
Neither way is the real one, so the key is written on the thing it works —
`Notes  f1` in the strip, `⚙ Settings  ^g`, `🔔 f8` — and the bar along the
bottom carries a few of the rest: status on the left, at most five keys on
the right, the focused thing's first and quit last.

### Keys

Anywhere:

| key | action |
| --- | --- |
| `f1` … `f7` | notes, tasks (`f2`), secrets, files, calendar; the other Quills take `f4`, `f10`, `f11`, `f12` in turn — Chat is `f4` |
| `f8` | notifications: what the machines have been up to |
| `ctrl+g` | settings: this machine, and its config sync |
| `ctrl+r` | refresh |
| `ctrl+c` | quit — pressed twice; the first press asks in the bottom bar |

In secrets — the vault list:

| key | action |
| --- | --- |
| `n` / `ctrl+n` | new vault |

In secrets — the keys:

| key | action |
| --- | --- |
| `a` | add a secret, or replace one |
| `v` | reveal the selected value, or hide it again |
| `c` | copy it to the clipboard without showing it |
| `d` | delete it |
| `i` / `x` | import a `.env` / export one |
| `e` | work in another environment |

In files:

| key | action |
| --- | --- |
| `1` / `2` | its own tabs: local backups, fileshares |
| `ctrl+n` | new share |
| `m` / `u` | mount the selected share on this machine / unmount it |
| `c` | copy its WebDAV address |
| `d` | remove it (its files stay on the server) |

In notes — the list:

| key | action |
| --- | --- |
| `n` / `N` | new note / new folder (inside the selected folder) |
| `r` | rename or move |
| `d` | delete |
| `/` | search |

In notes — anywhere:

| key | action |
| --- | --- |
| `ctrl+s` | save now |
| `ctrl+n` / `ctrl+o` | new note / new folder |
| `ctrl+f` | search |
| `f6` / `f7` | import a file / export the open note |
| `ctrl+p` | put a picture from this machine in the note |

In the editor:

| key | action |
| --- | --- |
| `enter` | new line, continuing the list you are in |
| `ctrl+t` | make a task, or tick/untick it |
| `ctrl+k` / `ctrl+d` | cut line / duplicate line |
| `alt+↑` / `alt+↓` | move the line |
| `ctrl+z` / `ctrl+y` | undo / redo |
| `tab` / `shift+tab` | indent / dedent |

In any dialog:

| key | action |
| --- | --- |
| `←` `→` `↑` `↓` | move between the buttons |
| `enter` | press the one you are on |
| `escape` | leave without answering |

The arrows reach the dialog only when what has focus has no use for them, so
the cursor still moves in an input and the selection still moves in a list.

## API

All note paths are relative to the calling user's notes root.

| method | path | |
| --- | --- | --- |
| `POST` | `/api/auth/login` | `{username, password}` → bearer token |
| `GET` | `/api/auth/me` | the current user |
| `POST` | `/api/auth/password` | change your own password |
| `GET` | `/api/notes/tree` | the nested note list |
| `GET`/`PUT` | `/api/notes/file/{path}` | read / write a note |
| `POST` | `/api/notes/file`, `/api/notes/dir` | create |
| `POST` | `/api/notes/move` | rename or move |
| `DELETE` | `/api/notes/{path}` | delete (`?recursive=true` for folders) |
| `GET` | `/api/notes/search?q=` | full-text search |
| `POST` | `/api/notes/img` | keep a picture: the body is the image; `?filename=` names it |
| `GET` | `/api/notes/img/{name}` | the picture back, as it is |
| `GET` | `/api/secrets?env=` | the keys, without the values (`&reveal=true` for those) |
| `GET` | `/api/secrets/vaults` | the vaults that hold something, with counts |
| `GET` | `/api/secrets/environments` | environments that hold something, in this vault |
| `GET`/`PUT`/`DELETE` | `/api/secrets/item/{key}?env=` | one secret, value included |
| `POST` | `/api/secrets/import` | set many at once — what a `.env` becomes |
| `GET` | `/api/secrets/export?env=` | a `.env` file, or `&format=json` |
| `DELETE` | `/api/secrets/environment/{env}` | drop a whole environment |
| `DELETE` | `/api/secrets/vault/{vault}` | drop a whole vault |
| `GET` | `/api/types` | every kind of data there is: fields, scopes, what is sealed, who uses it |
| `GET` | `/api/quills` | the installed Quills, each with its screens and its datamodels in full |
| `GET` | `/api/quills/catalog` | the Quill Catalog, with what is installed |
| `POST` | `/api/quills/plan` | `{id}` or `{source, ref}` — what installing would add (administrators) |
| `POST`/`DELETE` | `/api/quills`, `/api/quills/{id}` | install, or remove; records are kept (administrators) |
| `POST` | `/api/quills/upload` | a `.tar.gz` of a Quill's folder, as a development Quill — `cm quill dev` |
| `GET` | `/api/datamodels` | every datamodel on the server, with its fields and the Quills that use it |
| `GET`/`POST` | `/api/records/{model}` | your records of a datamodel (`?field=value` filters on indexed fields); make one |
| `GET`/`PATCH`/`DELETE` | `/api/records/{model}/{id}` | one record; send `rev` with a change to get a 409 rather than overwrite |
| `POST` | `/api/records/{model}/{id}/move` | `{fields, index}` — another lane or group, and a place in it |
| `POST` | `/api/records/{model}` with `scope`, `members`, `unique` | a space — a channel, a calendar — made public or shared, with its people; `unique` finds the one with exactly those people instead of making another |
| `POST`/`DELETE` | `/api/records/{model}/{id}/members[/{username}]` | put somebody in a shared space; take them out, or with your own name, leave |
| `POST` | `/api/records/{model}/{id}/seen` | you have looked in a space: what is in it is not unread |
| `GET` | `/api/records/{model}?_last=50&_since=…` | the newest fifty, still in order; only what changed at or after a moment |
| `GET` | `/api/people` | everybody else on the server, to share a space with or write to |
| `GET`/`POST` | `/api/shares` | your fileshares; a share carries its `url` |
| `GET`/`DELETE` | `/api/shares/{name}` | one share; `?remove_files=true` deletes a directory the server made |
| `*` | `/dav/{name}/…` | the share itself, as WebDAV — Basic auth with your password or token |
| `GET`/`POST`/`DELETE` | `/api/agents…` | your machines |
| `POST` | `/api/agents/{id}/jobs` | queue work |
| `PATCH` | `/api/agents/{id}/sync` | `{sync_bundles}` — what that machine keeps in step |
| `GET` | `/api/config`, `/api/config/{bundle}` | the shared config: revision, origin, who keeps it |
| `DELETE` | `/api/config/{bundle}` | unclaim it, so the next machine to tick the box decides |
| `GET`/`POST` | `/api/notifications` | what the machines have been doing |
| `POST` | `/api/notifications/read` | mark them read; omit `ids` for all of them |
| `GET`/`POST` | `/api/calendar/calendars` | the calendars you can see; make one |
| `GET`/`PATCH`/`DELETE` | `/api/calendar/calendars/{slug}` | one calendar; rename or recolour it; delete it |
| `POST` | `/api/calendar/calendars/{slug}/members` | `{usernames}` — share it; they are told |
| `POST` | `/api/calendar/calendars/{slug}/leave` | leave a shared calendar |
| `GET` | `/api/calendar/people` | everybody a calendar could be shared with |
| `GET` | `/api/calendar/colours` | the colours a calendar may be |
| `GET` | `/api/calendar/events` | everything in `?from=`–`?to=`, across every calendar (`?calendar=` for one) |
| `GET` | `/api/calendar/upcoming` | the next few things (`?days=`, `?limit=`) |
| `POST` | `/api/calendar/calendars/{slug}/events` | put something in it |
| `GET`/`PATCH`/`DELETE` | `/api/calendar/events/{id}` | one event; change it, or `{calendar}` to move it |
| `GET` | `/api/push/key` | the VAPID public key, to subscribe a browser with |
| `POST` | `/api/push/subscribe` | a `PushSubscription`, as the browser gives it |
| `POST` | `/api/push/unsubscribe` | `{endpoint}` — forget this device |
| `GET` | `/api/push/devices` | the devices this account pushes to |
| `GET` | `/api/push/badge` | `{messages, notifications, badge}` — the number on the icon |
| `POST` | `/api/push/test` | push yourself, to find out whether this phone is wired up |
| `POST` | `/api/agent/enroll`, `/heartbeat`, `/jobs/claim` | the agent's own endpoints |
| `GET`/`POST` | `/api/agent/config/{bundle}` | the agent's side of config sync |
| `POST` | `/api/agent/notifications` | a machine saying what it just did |
| `GET` | `/api/server/features` | what this server offers |
| `PATCH` | `/api/server/features/{key}` | `{enabled}` — switch one for everybody, admin only |
| `GET` | `/api/me/features` | what you may switch, and your answer on each |
| `PATCH` | `/api/me/features/{key}` | `{enabled}` — switch one for yourself |
| `GET`/`POST`/`PATCH`/`DELETE` | `/api/users…` | admin only |
| `GET` | `/api/health` | no auth; carries the cloud's `name` and whether it still needs `setup` |
| `GET` | `/setup` | the first-boot page, while the server has no accounts; redirects to `/app` after |
| `POST` | `/api/setup` | `{name, username, password}` — name the cloud and make its administrator; 409 once anybody exists |
| `GET`/`PATCH` | `/api/server/settings` | `{name}` — what this cloud is called; `PATCH` is admin only |
| `GET` | `/api/client` | what `cloudmorrow update` should install, no auth |
| `POST` | `/api/server/update` | deploy from git and restart — admin only |
| `GET` | `/`, `/install.sh` | the install page and script, no auth |
| `POST` | `/mcp` | the MCP server, JSON-RPC over HTTP — an MCP token, or a user token |
| `GET` | `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server` | how an MCP client finds the sign-in flow, no auth |
| `POST` | `/oauth/register`, `/oauth/token` | an MCP client registering itself, and trading its code for tokens |
| `GET`/`POST` | `/oauth/authorize` | the page where you sign in and let an assistant in |
| `GET`/`DELETE` | `/api/mcp/connections…` | the assistants you have let in; delete one to cut it off |

Interactive docs at `/docs`.

Send `X-Cloudmorrow-Vault: <vault>` (or `?vault=<vault>`) to say which vault
a secrets call is about; without one it is the `default` vault. Nothing
else reads it — everything else belongs to the account outright.

Secret values are handed out one at a time, or all at once by `/export`; a
listing describes them instead. Those responses carry `Cache-Control: no-store`.

`PUT` takes the `rev` you last read; a stale `rev` gets a `409` carrying the
current revision and content, which is what drives the conflict dialog.

Agent tokens are a separate credential from user tokens: an agent token cannot
read notes, and a user token cannot claim jobs.
MCP tokens are a third: handed out by `/oauth/token` after somebody said yes
on the sign-in page, kept hashed, and good for `/mcp` alone.

A config push is conditional: it carries the revision the machine was working
from, and a push from an older one comes back `409` with the current revision
rather than overwriting. `base_revision: null` claims an unclaimed bundle,
which succeeds exactly once.

## Development

```bash
uv venv && uv pip install -e '.[tui,server,dev]'
pytest
ruff check src tests
```

### Running the checkout

The `cloudmorrow` on your PATH is the installed client, in its own venv: it does
not change when the source does, only when there is a release and an `update`.
To run what you are working on instead, stand in the checkout and say so:

```bash
cd ~/Projects/cloudmorrow
cloudmorrow --dev            # the TUI, from source
cloudmorrow --dev note list  # any other command, the same way
```

It is the directory that decides — anywhere inside the checkout will do, and
anywhere else the flag says it has nothing to point at. The command is handed
to the checkout's own venv if it has one, with `src` ahead of whatever is
installed; nothing is copied and nothing is installed, so the next run is
whatever the files say then. The TUI wears a `dev` badge beside its name while
it is the checkout you are looking at, and `cloudmorrow --dev version` says where
it is running from.

It is still the real server: `--dev` changes which code runs, not which API it
talks to, and it reads the same config and token as usual. For a TUI change
that is the point — no deploy to wait for. Point it somewhere else when you
need to:

```bash
CLOUDMORROW_API_URL=http://localhost:8787 cloudmorrow --dev
CLOUDMORROW_CONFIG_DIR=~/.config/cloudmorrow-dev cloudmorrow --dev   # its own login
```

### A server of your own

```bash
# a server against a scratch directory
CLOUDMORROW_NOTES_DIR=/tmp/notes CLOUDMORROW_DATA_DIR=/tmp/cloudmorrow-data \
  cloudmorrow-server user create dev
CLOUDMORROW_NOTES_DIR=/tmp/notes CLOUDMORROW_DATA_DIR=/tmp/cloudmorrow-data \
  cloudmorrow-server serve --port 8787 --reload
```

## Housekeeping

What is left over from the layout that kept notes inside projects — the
per-project note directories — is found by:

```bash
cloudmorrow-server prune          # on the server: says what nothing can reach
cloudmorrow-server prune --yes    # and deletes it
```

It never deletes a note: notes in an old per-project directory are moved into
the owner's tree first, as a folder of that project's name, and only empty
directories are removed. A directory holding anything else is reported and
left where it is.

## Known limits

- The editor takes a paste from the terminal and a mouse sweep copies out of
  it, but it has no keyboard selection: shift+arrows do nothing, and copy is
  the pointer's job. The clipboard is the terminal's (OSC 52), which most
  terminals honour and macOS Terminal.app does not.
- Long lines scroll horizontally instead of soft-wrapping.
- Search is a substring scan over the files. Fine for thousands of notes; it is
  not an index.
- Secrets belong to one user; there is no sharing between accounts yet, and
  no giving an app one — the types catalogue says who reaches what, and
  nothing enforces it yet.
- Content is encrypted at rest, not end to end: the server holds the key it
  seals everything with. See [Encryption at rest](#encryption-at-rest).
- Secret values are versioned nowhere: overwriting one loses the old value.
- Agents poll rather than hold a connection, so a job waits up to
  `poll_seconds` before it starts. There is no schedule yet — jobs are queued by
  hand or by whatever cron you point at `cloudmorrow agent run`.
- Config sync is whole-file and last-push-wins: it never merges two edits to
  one file. The loser's copy is kept as `.cloudmorrow-backup` rather than being
  reconciled, and putting the two back together is your job.
- It syncs `~/.config/hypr` and nothing else. Themes, waybar, everything else
  in `~/.config` stays where it is until a directory has earned a line in
  `PATHS`.
- A change is noticed by comparing hashes on a poll, not by watching the
  filesystem, so a config edit takes up to `poll_seconds` to leave the machine
  and another poll to arrive on the next one. Under a minute in practice, but
  it is not instant, and nothing pushes it.
- Nothing tells you a sync happened while you are looking at something else.
  The notifications are all on the server, waiting for a channel to carry
  them.
- Binary files and symlinks in a synced directory are skipped silently: they
  stay exactly as they are on each machine, and nothing says so.
- A fileshare mount is for the session: it does not come back after a
  reboot, and it stops working when the token it signed in with expires (30
  days by default), at which point `share mount` again. Nothing remounts it
  for you yet — that is a job for the agent, along with the Local backups
  tab, which is a placeholder.
- Fileshares belong to one account, like everything else. There is no
  read-only share and no sharing between accounts.
- A picture taken out of a note is not taken out of `img/`: nothing prunes
  the folder yet. The TUI shows one picture at a time, beside the text rather
  than in it, and a terminal without Kitty or Sixel graphics gets half-cells.

## License

Cloudmorrow is free software under the [GNU Affero General Public License,
version 3](../LICENSE), or any later version. Run it, change it, host it for other
people — and if what you host is a changed version, offer them its source the
way this repository offers you this one.
