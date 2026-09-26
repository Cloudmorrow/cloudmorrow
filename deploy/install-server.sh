#!/bin/sh
# Install (or re-install) the Cloudmorrow server on this machine.
#
# One command, four questions — what your cloud is called, the address
# people will reach it on, who its first account (the administrator) is,
# and which of the standard quills it has — and it is running:
#
#   curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/install-server.sh | sudo sh
#
# Or from a checkout: `sudo sh deploy/install-server.sh`. Every answer can be
# given as a flag instead, for a script or a re-run that should ask nothing:
#
#   sudo sh install-server.sh --name "The Larsens" \
#     --public-url https://cloud.example.com --user alice --quills all
#
# Idempotent: run it again to move the deployment to new settings. It never
# overwrites an existing /etc/cloudmorrow/server.toml, your notes, or the
# database, and it never asks a question it already has the answer to. For
# routine "I pushed a change" updates, use `cloudmorrow update server` from
# any machine, or the `cloudmorrow-update` command this script installs.
set -eu

DEFAULT_REPO="https://github.com/Cloudmorrow/cloudmorrow.git"
REPO=""
BRANCH="main"
PREFIX="/opt/cloudmorrow"
NOTES_DIR="/srv/cloudmorrow/notes"
DATA_DIR="/var/lib/cloudmorrow"
CLOUD_NAME=""
PUBLIC_URL=""
HOST="127.0.0.1"
PORT="8787"
SERVICE_USER="cloudmorrow"
SERVICE_NAME="cloudmorrow"
ADMIN_USER="${SUDO_USER:-}"
ACCOUNT=""
ACCOUNT_PASSWORD="${CLOUDMORROW_ADMIN_PASSWORD:-}"
SSH_KEY=""
NO_SSH_KEY=""
QUILLS=""
DRY_RUN=""

usage() {
	sed -n '2,20p' "$0"
	cat <<EOF

Options:
  --name TEXT         what your cloud is called         (asked if not given)
  --public-url URL    the address people reach it on    (asked if not given)
  --user NAME         the first account, an administrator (asked if not given;
                      its password is asked for, or read from
                      \$CLOUDMORROW_ADMIN_PASSWORD)
  --quills LIST       standard quills to have, comma-separated, or 'all'
                      (asked if not given; 'cloudmorrow-server quill standard' lists them)
  --repo URL          git URL to clone                  (default: this checkout's
                      origin, else $DEFAULT_REPO)
  --branch NAME       branch to deploy                  (default: $BRANCH)
  --prefix DIR        checkout + venv live here         (default: $PREFIX)
  --notes-dir DIR     where notes and files are stored  (default: $NOTES_DIR)
  --data-dir DIR      database and keys                 (default: $DATA_DIR)
  --host ADDR         bind address                      (default: $HOST)
  --port N            bind port                         (default: $PORT)
  --service-user NAME system user to run as             (default: $SERVICE_USER)
  --admin USER        unix user allowed to update and restart (default: \$SUDO_USER)
  --ssh-key PATH      deploy key for a private repo     (default: generate one)
  --no-ssh-key        the repo needs no key (it is public, or https)
  --dry-run           print what would happen, ask nothing, change nothing
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
	--name) CLOUD_NAME="$2"; shift 2 ;;
	--public-url) PUBLIC_URL="$2"; shift 2 ;;
	--user) ACCOUNT="$2"; shift 2 ;;
	--quills) QUILLS="$2"; shift 2 ;;
	--repo) REPO="$2"; shift 2 ;;
	--branch) BRANCH="$2"; shift 2 ;;
	--prefix) PREFIX="$2"; shift 2 ;;
	--notes-dir) NOTES_DIR="$2"; shift 2 ;;
	--data-dir) DATA_DIR="$2"; shift 2 ;;
	--host) HOST="$2"; shift 2 ;;
	--port) PORT="$2"; shift 2 ;;
	--service-user) SERVICE_USER="$2"; shift 2 ;;
	--service-name) SERVICE_NAME="$2"; shift 2 ;;
	--admin) ADMIN_USER="$2"; shift 2 ;;
	--ssh-key) SSH_KEY="$2"; shift 2 ;;
	--no-ssh-key) NO_SSH_KEY="1"; shift ;;
	--dry-run) DRY_RUN="1"; shift ;;
	-h | --help) usage; exit 0 ;;
	*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

say() { printf '\033[36m::\033[0m %s\n' "$*"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
run() {
	if [ -n "$DRY_RUN" ]; then
		printf '   \033[2mwould run:\033[0m %s\n' "$*"
	else
		"$@"
	fi
}
write_file() {
	# write_file <path> <mode>, contents on stdin
	if [ -n "$DRY_RUN" ]; then
		printf '   \033[2mwould write:\033[0m %s (mode %s)\n' "$1" "$2"
		cat >/dev/null
	else
		cat >"$1"
		chmod "$2" "$1"
	fi
}

SRC="$PREFIX/src"
VENV="$PREFIX/venv"
CONFIG_DIR="/etc/cloudmorrow"
CONFIG="$CONFIG_DIR/server.toml"
KEY_FILE="$CONFIG_DIR/cloudmorrow.key"

[ -n "$DRY_RUN" ] || [ "$(id -u)" = "0" ] || die "run this with sudo"
command -v git >/dev/null 2>&1 || die "git is required"

# --- the questions ---------------------------------------------------------
# Asked on the terminal, not stdin: the script itself may be what is on stdin
# when it arrives through `curl | sh`. Nothing is asked twice — an existing
# config keeps its name and address, an existing account is left alone — and
# nothing is asked at all without a terminal or with --dry-run, so a script
# that gives every answer as a flag runs straight through.
TTY=""
if [ -z "$DRY_RUN" ] && ( : </dev/tty ) 2>/dev/null; then
	TTY="1"
fi

ask() {
	# ask VAR "question" "default": sets VAR unless it already has a value.
	eval "current=\${$1}"
	[ -z "$current" ] || return 0
	[ -n "$TTY" ] || return 0
	if [ -n "$3" ]; then
		printf '\033[1m%s\033[0m [%s]: ' "$2" "$3" >/dev/tty
	else
		printf '\033[1m%s\033[0m: ' "$2" >/dev/tty
	fi
	read -r answer </dev/tty || answer=""
	[ -n "$answer" ] || answer="$3"
	eval "$1=\$answer"
}

read_secret() {
	# read_secret VAR "prompt": like ask, with the echo off.
	printf '\033[1m%s\033[0m: ' "$2" >/dev/tty
	stty -echo </dev/tty 2>/dev/null || true
	read -r answer </dev/tty || answer=""
	stty echo </dev/tty 2>/dev/null || true
	printf '\n' >/dev/tty
	eval "$1=\$answer"
}

ask_password() {
	# The server wants eight characters or more and a match, so the check is
	# made here, while it is still cheap to answer again.
	while :; do
		read_secret first "Password for $ACCOUNT"
		if [ "${#first}" -lt 8 ]; then
			printf 'At least eight characters, please.\n' >/dev/tty
			continue
		fi
		read_secret second "Repeat the password"
		if [ "$first" = "$second" ]; then
			ACCOUNT_PASSWORD="$first"
			return 0
		fi
		printf 'They differ; try again.\n' >/dev/tty
	done
}

if [ -f "$CONFIG" ]; then
	# A re-run: the config is kept as it is, so its name and address are the
	# answers, whatever the terminal might say.
	[ -n "$CLOUD_NAME" ] || CLOUD_NAME="$(sed -n 's/^name = "\(.*\)"$/\1/p' "$CONFIG" | head -n 1)"
	[ -n "$PUBLIC_URL" ] || PUBLIC_URL="$(sed -n 's/^public_url = "\(.*\)"$/\1/p' "$CONFIG" | head -n 1)"
fi

# Somebody on this server already means the first account exists: not asked.
EXISTING_USERS="0"
if [ -f "$CONFIG" ] && [ -x "$VENV/bin/cloudmorrow-server" ]; then
	EXISTING_USERS="$(CLOUDMORROW_SERVER_CONFIG="$CONFIG" "$VENV/bin/cloudmorrow-server" user list --count 2>/dev/null || echo 0)"
fi

if [ -n "$TTY" ]; then
	printf '\n  Four questions, and your cloud is running. Three now, and one once\n  the software is in: which of the standard quills it should have.\n\n' >/dev/tty
fi
ask CLOUD_NAME "What is your cloud called?" "Cloudmorrow"
ask PUBLIC_URL "What address will people use?" "https://$(hostname -f 2>/dev/null || hostname)"
if [ "$EXISTING_USERS" = "0" ]; then
	ask ACCOUNT "Username for the first account (the administrator)" "${SUDO_USER:-admin}"
	if [ -n "$ACCOUNT" ]; then
		# The same rule the server applies, so it is not learnt at the end.
		ACCOUNT="$(printf '%s' "$ACCOUNT" | tr 'A-Z' 'a-z')"
		printf '%s' "$ACCOUNT" | grep -Eq '^[a-z_][a-z0-9_-]{0,31}$' ||
			die "a username is 1-32 lowercase letters, digits, '_' or '-', starting with a letter or '_'"
		if [ -z "$ACCOUNT_PASSWORD" ] && [ -n "$TTY" ]; then
			ask_password
		fi
	fi
fi
if [ -n "$TTY" ]; then
	printf '\n' >/dev/tty
fi

CLOUD_NAME="${CLOUD_NAME:-Cloudmorrow}"
PUBLIC_URL="$(printf '%s' "$PUBLIC_URL" | sed 's|/*$||')"
if [ -z "$PUBLIC_URL" ]; then
	warn "no address given; the install page will guess from each request"
fi
case "$PUBLIC_URL" in
http://*)
	warn "$PUBLIC_URL is plain http: every client will have to allow that"
	warn "(cloudmorrow config set allow_insecure_http true). Put TLS in front when you can."
	;;
esac
if [ -n "$DRY_RUN" ]; then
	[ -n "$ACCOUNT" ] || [ "$EXISTING_USERS" != "0" ] || warn "would ask for the first account's username and password"
fi

# The default repo is wherever this checkout came from, so running the script
# straight out of a clone does the obvious thing; a copy on its own, or one
# that arrived through curl, installs the public code.
if [ -z "$REPO" ] && [ -f "$0" ]; then
	# Only a script that is really on disk has a checkout around it; through
	# a pipe, $0 is the shell, and whatever directory this runs from is not
	# ours to read a remote off.
	SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
	if [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/../.git" ]; then
		REPO="$(git -C "$SCRIPT_DIR/.." remote get-url origin 2>/dev/null || true)"
	fi
fi
[ -n "$REPO" ] || REPO="$DEFAULT_REPO"

# --- python ----------------------------------------------------------------
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
	if command -v "$candidate" >/dev/null 2>&1 &&
		"$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
		PYTHON="$candidate"
		break
	fi
done
[ -n "$PYTHON" ] || die "Python 3.11 or newer is required"
say "python: $($PYTHON -V 2>&1)"
say "cloud: $CLOUD_NAME${PUBLIC_URL:+ at $PUBLIC_URL}"

# --- service user ----------------------------------------------------------
if id "$SERVICE_USER" >/dev/null 2>&1; then
	say "service user $SERVICE_USER already exists"
else
	say "creating system user $SERVICE_USER"
	run useradd --system --home-dir "$DATA_DIR" --create-home \
		--shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- directories -----------------------------------------------------------
say "directories: $PREFIX, $NOTES_DIR, $DATA_DIR"
run mkdir -p "$PREFIX" "$NOTES_DIR" "$DATA_DIR" "$CONFIG_DIR"
run chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX" "$NOTES_DIR" "$DATA_DIR"

# --- deploy key, for a private repo over ssh -------------------------------
# GitHub deploy keys are the least-privilege way to let one machine pull one
# private repo: read-only, revocable, and no account token on disk.
SSH_DIR="$DATA_DIR/.ssh"
case "$REPO" in
git@* | ssh://*) NEEDS_KEY="1" ;;
*) NEEDS_KEY="" ;;
esac
if [ -n "$NO_SSH_KEY" ]; then
	NEEDS_KEY=""
fi

if [ -n "$NEEDS_KEY" ]; then
	[ -n "$SSH_KEY" ] || SSH_KEY="$SSH_DIR/id_ed25519"
	run mkdir -p "$SSH_DIR"
	run chown "$SERVICE_USER:$SERVICE_USER" "$SSH_DIR"
	run chmod 700 "$SSH_DIR"

	# Trust the forge's host key, or every non-interactive git call hangs.
	REPO_HOST="$(printf '%s' "$REPO" | sed -e 's|^ssh://||' -e 's|^[^@]*@||' -e 's|[:/].*$||')"
	if [ -n "$REPO_HOST" ] && [ ! -f "$SSH_DIR/known_hosts" ]; then
		say "recording the host key for $REPO_HOST"
		if [ -z "$DRY_RUN" ]; then
			ssh-keyscan -t rsa,ecdsa,ed25519 "$REPO_HOST" >"$SSH_DIR/known_hosts" 2>/dev/null
			chown "$SERVICE_USER:$SERVICE_USER" "$SSH_DIR/known_hosts"
			chmod 644 "$SSH_DIR/known_hosts"
		else
			printf '   \033[2mwould run:\033[0m ssh-keyscan %s > %s\n' "$REPO_HOST" "$SSH_DIR/known_hosts"
		fi
	fi

	GENERATED=""
	if [ ! -f "$SSH_KEY" ]; then
		say "generating a deploy key at $SSH_KEY"
		run sudo -u "$SERVICE_USER" ssh-keygen -q -t ed25519 -N "" \
			-C "cloudmorrow@$(hostname)" -f "$SSH_KEY"
		GENERATED="1"
	else
		say "using the existing key at $SSH_KEY"
	fi

	GIT_SSH="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$SSH_DIR/known_hosts"
	export GIT_SSH_COMMAND="$GIT_SSH"

	if [ -n "$GENERATED" ] && [ -z "$DRY_RUN" ]; then
		cat <<EOF

  This machine has no access to $REPO yet.

  Add its new public key to the repository as a read-only deploy key
  (GitHub: Settings -> Deploy keys -> Add deploy key), then run this
  script again — it will pick up where it left off.

EOF
		printf '  '
		cat "$SSH_KEY.pub"
		printf '\n'
		exit 0
	fi
fi

# --- checkout --------------------------------------------------------------
# sudo scrubs the environment, so the ssh command is passed through explicitly
# and then stored in the repo itself, where every later git call finds it —
# including `cloudmorrow-server update`, whoever ends up running it.
as_service() {
	if [ -n "${GIT_SSH:-}" ]; then
		run sudo -u "$SERVICE_USER" -H env GIT_SSH_COMMAND="$GIT_SSH" "$@"
	else
		run sudo -u "$SERVICE_USER" -H "$@"
	fi
}

if [ -d "$SRC/.git" ]; then
	say "updating existing checkout at $SRC"
	as_service git -C "$SRC" fetch --quiet origin "$BRANCH"
	as_service git -C "$SRC" checkout --quiet "$BRANCH"
	# reset, not merge: this checkout is a mirror of the branch, so it follows
	# the branch wherever it went — including back, or onto a rewritten history.
	as_service git -C "$SRC" reset --hard --quiet "origin/$BRANCH"
else
	say "cloning $REPO ($BRANCH) into $SRC"
	as_service git clone --quiet --branch "$BRANCH" "$REPO" "$SRC"
fi

if [ -n "${GIT_SSH:-}" ]; then
	run sudo -u "$SERVICE_USER" -H git -C "$SRC" config core.sshCommand "$GIT_SSH"
fi

# --- virtualenv ------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
	say "creating the virtualenv at $VENV"
	run sudo -u "$SERVICE_USER" "$PYTHON" -m venv "$VENV"
fi
# Both extras: the server runs an agent of its own, so it needs what an agent
# needs as well as what the API needs.
say "installing cloudmorrow[server,agent] (editable, so updates are a git pull)"
run sudo -u "$SERVICE_USER" "$VENV/bin/python" -m pip install --quiet --upgrade pip
run sudo -u "$SERVICE_USER" "$VENV/bin/python" -m pip install --quiet --editable "$SRC[server,agent]"

run ln -sf "$VENV/bin/cloudmorrow-server" /usr/local/bin/cloudmorrow-server


# --- configuration ---------------------------------------------------------
if [ -f "$CONFIG" ]; then
	say "keeping the existing $CONFIG"
else
	say "writing $CONFIG"
	write_file "$CONFIG" 0644 <<EOF
# Written by install-server.sh. Safe to edit; the installer never rewrites it.
[server]
# What this cloud is called: on the sign-in screen, the install page and
# the phone's home screen.
name = "$CLOUD_NAME"

notes_dir = "$NOTES_DIR"
data_dir = "$DATA_DIR"
per_user_dirs = true

host = "$HOST"
port = $PORT

# The key everything is sealed with at rest. Kept here, away from the data
# in $DATA_DIR, so a copy of that directory alone opens nothing. Back it up
# with the data, never instead of it: lose it and everything is gone.
key_file = "$KEY_FILE"

# The URL clients reach this server on, baked into the install page.
public_url = "$PUBLIC_URL"

token_ttl_hours = 720
cors_origins = []
EOF
	run chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG"
fi

# The sealing key. The service cannot write to /etc (ProtectSystem=strict),
# so it is made here, once, and never touched again by this script.
if [ -f "$KEY_FILE" ]; then
	say "keeping the existing key at $KEY_FILE"
else
	say "generating the sealing key at $KEY_FILE"
	if [ -z "$DRY_RUN" ]; then
		(umask 077 && head -c 32 /dev/urandom | base64 | tr '+/' '-_' >"$KEY_FILE")
	fi
	run chown "$SERVICE_USER:$SERVICE_USER" "$KEY_FILE"
	run chmod 600 "$KEY_FILE"
fi

# The client is not on PyPI, so this server is where
# machines get Cloudmorrow from. Build the wheel /install.sh will hand out.
say "publishing a client wheel for /install.sh"
run sudo -u "$SERVICE_USER" -H env CLOUDMORROW_SERVER_CONFIG="$CONFIG" \
	"$VENV/bin/cloudmorrow-server" publish --source "$SRC"

# --- systemd ---------------------------------------------------------------
UNIT="/etc/systemd/system/$SERVICE_NAME.service"
say "writing $UNIT"
write_file "$UNIT" 0644 <<EOF
[Unit]
Description=Cloudmorrow API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
Environment=CLOUDMORROW_SERVER_CONFIG=$CONFIG
Environment=HOME=$DATA_DIR
ExecStart=$VENV/bin/cloudmorrow-server serve
# always, not on-failure: an API deploy restarts the server by stopping it and
# letting systemd start it again on the new code. An explicit \`systemctl stop\`
# still stops it — systemd knows the difference.
Restart=always
RestartSec=3

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$NOTES_DIR $DATA_DIR $PREFIX

[Install]
WantedBy=multi-user.target
EOF

# --- the updater your user runs -------------------------------------------
say "installing /usr/local/bin/cloudmorrow-update"
write_file /usr/local/bin/cloudmorrow-update 0755 <<EOF
#!/bin/sh
# Pull the latest Cloudmorrow and restart the server. Installed by install-server.sh.
#
# The pull runs as $SERVICE_USER, which owns the checkout; only the restart
# needs root. Exit 3 from the update means there was nothing to pull, so the
# service is left alone.
set -eu
status=0
sudo -u $SERVICE_USER -H $VENV/bin/cloudmorrow-server update --no-restart --exit-status "\$@" \
	|| status=\$?
[ "\$status" = 0 ] || [ "\$status" = 3 ] || exit "\$status"
if [ "\$status" = 3 ]; then
	exit 0
fi
if [ -d /run/systemd/system ]; then
	sudo systemctl restart $SERVICE_NAME
	# No sudo: reading a unit's state needs no privilege, and the sudoers rule
	# matches arguments exactly — with the flags below it would not match, so
	# sudo would fall through to asking for a password and fail the whole run.
	systemctl --no-pager --lines=0 status $SERVICE_NAME
else
	printf "note: systemd is not running here; restart the server yourself\\n"
fi
EOF

# --- let the admin user update without a password --------------------------
if [ -n "$ADMIN_USER" ] && id "$ADMIN_USER" >/dev/null 2>&1; then
	SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"
	SUDOERS="/etc/sudoers.d/cloudmorrow"
	say "granting $ADMIN_USER the two commands cloudmorrow-update needs"
	write_file "$SUDOERS" 0440 <<EOF
# Installed by install-server.sh. Exactly what cloudmorrow-update needs, nothing more.
$ADMIN_USER ALL=($SERVICE_USER) NOPASSWD: $VENV/bin/cloudmorrow-server update *
$ADMIN_USER ALL=(root) NOPASSWD: $SYSTEMCTL restart $SERVICE_NAME, \\
	$SYSTEMCTL start $SERVICE_NAME, $SYSTEMCTL stop $SERVICE_NAME
EOF
	if [ -z "$DRY_RUN" ] && command -v visudo >/dev/null 2>&1; then
		visudo -cf "$SUDOERS" >/dev/null || die "the sudoers drop-in did not validate"
	fi
else
	warn "no --admin user, so nobody but root can run cloudmorrow-update"
fi

# --- the standard quills --------------------------------------------------
# Chosen before the service first starts, because a running server reads
# what is installed when it boots. Asked once: a re-run keeps the choice,
# and an administrator changes it from Administration afterwards. Quills
# from the catalog are downloaded from GitHub; one that cannot be reached is
# said, and the rest of the install goes on.
if [ -n "$DRY_RUN" ]; then
	if [ -n "$QUILLS" ]; then
		printf '   \033[2mwould choose:\033[0m the standard quills %s\n' "$QUILLS"
	else
		printf '   \033[2mwould ask:\033[0m which standard quills to have\n'
	fi
else
	CHOOSE="--once"
	if [ -n "$QUILLS" ]; then
		CHOOSE="$CHOOSE --only $QUILLS"
	elif [ -n "$TTY" ]; then
		CHOOSE="$CHOOSE --ask"
	fi
	# The options are ours, and split on purpose.
	# shellcheck disable=SC2086
	sudo -u "$SERVICE_USER" -H env CLOUDMORROW_SERVER_CONFIG="$CONFIG" \
		"$VENV/bin/cloudmorrow-server" quill choose $CHOOSE ||
		warn "the standard quills were not all installed; add them later from Administration, Quills"
fi

# --- start it --------------------------------------------------------------
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
	run systemctl daemon-reload
	run systemctl enable --quiet "$SERVICE_NAME"
	run systemctl restart "$SERVICE_NAME"
	say "$SERVICE_NAME is enabled and running"
else
	warn "systemd is not running here; start the server yourself:"
	printf '     %s serve\n' "$VENV/bin/cloudmorrow-server"
fi

# --- the first account -----------------------------------------------------
# Made straight against the database, as the service user, so it is sealed
# under the service's key. The first account on a server is its
# administrator; the password goes in on stdin, never on the command line.
ACCOUNT_MADE=""
if [ "$EXISTING_USERS" != "0" ]; then
	say "this server already has $EXISTING_USERS account(s); none made"
elif [ -z "$ACCOUNT" ]; then
	warn "no first account made — nobody was there to ask"
elif [ -z "$ACCOUNT_PASSWORD" ]; then
	warn "no password for $ACCOUNT — set CLOUDMORROW_ADMIN_PASSWORD or run this on a terminal"
elif [ -n "$DRY_RUN" ]; then
	printf '   \033[2mwould create:\033[0m the account %s, as administrator\n' "$ACCOUNT"
else
	say "creating the account $ACCOUNT (administrator)"
	printf '%s\n' "$ACCOUNT_PASSWORD" | sudo -u "$SERVICE_USER" -H \
		env CLOUDMORROW_SERVER_CONFIG="$CONFIG" \
		"$VENV/bin/cloudmorrow-server" user create "$ACCOUNT" --admin --password-stdin
	ACCOUNT_MADE="1"
fi
ACCOUNT_PASSWORD=""

# --- the server's own agent ------------------------------------------------
# Every other machine enrols by signing in, and nobody signs in here. It
# belongs to the first administrator, which is why it comes after the account.
AGENT_INSTALLED=""
if [ -z "$DRY_RUN" ] && "$VENV/bin/cloudmorrow-server" agent-install \
	--run-as "$SERVICE_USER" \
	--url "${PUBLIC_URL:-http://$HOST:$PORT}" >/tmp/cloudmorrow-agent-install.$$ 2>&1; then
	AGENT_INSTALLED="1"
	say "the server has an agent of its own (cloudmorrow-agent.service)"
	sed 's/^/   /' /tmp/cloudmorrow-agent-install.$$
elif [ -z "$DRY_RUN" ]; then
	warn "no agent on the server yet — it needs an account to belong to"
fi
rm -f /tmp/cloudmorrow-agent-install.$$

# --- what to do next -------------------------------------------------------
PUBLIC_HOST="$(printf '%s' "$PUBLIC_URL" | sed -e 's|^[a-z]*://||' -e 's|[:/].*$||')"

cat <<EOF

  $CLOUD_NAME is installed.

    address    ${PUBLIC_URL:-http://$HOST:$PORT}   (listening on $HOST:$PORT)
    config     $CONFIG
    notes      $NOTES_DIR
    checkout   $SRC   ($BRANCH)
EOF
if [ -n "$ACCOUNT_MADE" ]; then
	printf '    account    %s   (administrator)\n' "$ACCOUNT"
fi
printf '\n'

case "$PUBLIC_URL" in
https://*)
	cat <<EOF
  Put a reverse proxy in front of it for TLS. With Caddy, this is the whole file:

    $PUBLIC_HOST {
        reverse_proxy $HOST:$PORT
    }

EOF
	;;
esac

if [ "$EXISTING_USERS" = "0" ] && [ -z "$ACCOUNT_MADE" ] && [ -z "$DRY_RUN" ]; then
	cat <<EOF
  There is no account yet. The first one becomes the administrator:

    sudo -u $SERVICE_USER $VENV/bin/cloudmorrow-server user create alice

EOF
fi

ADDRESS="${PUBLIC_URL:-http://$HOST:$PORT}"
cat <<EOF
  Next:

    1. Open $ADDRESS in a browser and sign in${ACCOUNT_MADE:+ as $ACCOUNT}.
    2. On each computer, install the terminal app and the desktop app:

         curl -fsSL $ADDRESS/install.sh | sh

       The front page at $ADDRESS shows the same line, ready to copy.
    3. On a phone, open $ADDRESS/app and add it to the home screen.

  Later, after a change is pushed:  cloudmorrow update server   (from any machine)
                                    cloudmorrow-update          (here)

EOF

if [ -z "$AGENT_INSTALLED" ] && [ -z "$DRY_RUN" ]; then
	cat <<EOF
  Once an account exists, give the server an agent of its own — it is the
  machine that holds everything, so it should be in the list with the rest:

    sudo $VENV/bin/cloudmorrow-server agent-install --run-as $SERVICE_USER

EOF
fi
