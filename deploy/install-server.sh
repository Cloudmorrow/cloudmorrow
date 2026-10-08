#!/bin/sh
# Install (or re-install) the Cloudmorrow server on this machine.
#
# One command, five questions — what your cloud is called, who its first
# account (the administrator) is, where on this machine it goes (Enter
# takes the usual places), which of its addresses it answers on, and which
# of the standard quills it has — and it is running:
#
#   curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/install-server.sh | sudo sh
#
# Or from a checkout: `sudo sh deploy/install-server.sh`. Every answer can be
# given as a flag instead, for a script or a re-run that should ask nothing:
#
#   sudo sh install-server.sh --name "The Larsens" --user alice --quills all
#
# The cloud is reached at this machine's address, and on a home network at
# <name>.local. Reaching it from outside is your own setup: a domain and a
# reverse proxy of your own (--public-url), or a VPN such as Tailscale.
#
# Run it again on a machine that already has Cloudmorrow and it checks the
# server first: running and answering, it says so and changes nothing;
# otherwise it updates and reinstalls it, and checks again. --update does
# that whatever the check says. It never overwrites an existing
# /etc/cloudmorrow/server.toml, everyone's files, or the database, and it never
# asks a question it already has the answer to. For routine "I pushed a
# change" updates, use `cloudmorrow update server` from any machine, or the
# `cloudmorrow-update` command this script installs.
set -eu

DEFAULT_REPO="https://github.com/Cloudmorrow/cloudmorrow.git"
REPO=""
BRANCH="main"
DEFAULT_PREFIX="/opt/cloudmorrow"
DEFAULT_CONFIG_DIR="/etc/cloudmorrow"
DEFAULT_DATA_DIR="/var/lib/cloudmorrow"
PREFIX=""
CONFIG_DIR=""
DATA_DIR=""
FILES_DIR=""
SHARES_DIR=""
CLOUD_NAME=""
PUBLIC_URL=""
HOST="0.0.0.0"
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
UPDATE=""
HOST_GIVEN=""

usage() {
	sed -n '2,18p' "$0"
	cat <<EOF

Options:
  --name TEXT         what your cloud is called         (asked if not given)
  --public-url URL    an address of your own, behind a reverse proxy of your
                      own
  --user NAME         the first account, an administrator (asked if not given;
                      its password is asked for, or read from
                      \$CLOUDMORROW_ADMIN_PASSWORD)
  --quills LIST       standard quills to have, comma-separated, or 'all'
                      (asked if not given; 'cloudmorrow-server quill standard' lists them)
  --repo URL          git URL to clone                  (default: this checkout's
                      origin, else $DEFAULT_REPO)
  --branch NAME       branch to deploy                  (default: $BRANCH)
  --prefix DIR        the checkout and the virtualenv   (default: $DEFAULT_PREFIX)
  --config-dir DIR    server.toml and the sealing key   (default: $DEFAULT_CONFIG_DIR)
  --data-dir DIR      everyone's files, the database, keys and quills
                                                        (default: $DEFAULT_DATA_DIR)
                      (where things go is asked when none of the three is
                      given; a re-run finds them where they are)
  --files-dir DIR     everyone's files — a folder per person, and the
                      Shares folder — when they are not to be under the
                      data directory                    (default: <data>/files)
  --shares-dir DIR    the Shares folder, when it is not to be with the
                      files                             (default: <files>/Shares)
  --host ADDR         address(es) to answer on, comma-separated
                      (asked if not given; default: $HOST, every address)
  --port N            bind port                         (default: $PORT)
  --service-user NAME system user to run as             (default: $SERVICE_USER)
  --admin USER        unix user allowed to update and restart (default: \$SUDO_USER)
  --ssh-key PATH      deploy key for a private repo     (default: generate one)
  --no-ssh-key        the repo needs no key (it is public, or https)
  --update            update and reinstall an existing server even when it
                      is running well
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
	--config-dir) CONFIG_DIR="$2"; shift 2 ;;
	--files-dir | --notes-dir) FILES_DIR="$2"; shift 2 ;;
	--shares-dir) SHARES_DIR="$2"; shift 2 ;;
	--data-dir) DATA_DIR="$2"; shift 2 ;;
	--host) HOST="$2"; HOST_GIVEN="1"; shift 2 ;;
	--port) PORT="$2"; shift 2 ;;
	--service-user) SERVICE_USER="$2"; shift 2 ;;
	--service-name) SERVICE_NAME="$2"; shift 2 ;;
	--admin) ADMIN_USER="$2"; shift 2 ;;
	--ssh-key) SSH_KEY="$2"; shift 2 ;;
	--no-ssh-key) NO_SSH_KEY="1"; shift ;;
	--update) UPDATE="1"; shift ;;
	--dry-run) DRY_RUN="1"; shift ;;
	-h | --help) usage; exit 0 ;;
	*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
done

say() { printf '\033[36m::\033[0m %s\n' "$*"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# The finished page's colours: the brand's sky for headings, its muted grey
# for the words beside them. None when nobody is looking, or NO_COLOR says so.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
	HEAD='\033[1;38;2;90;166;224m'
	SOFT='\033[38;2;153;161;179m'
	GOOD='\033[1;38;2;92;232;155m'
	OFF='\033[0m'
else
	HEAD='' SOFT='' GOOD='' OFF=''
fi
heading() { printf "\n  ${HEAD}%s${OFF}\n" "$*"; }
# line TEXT: one line under a heading. item LABEL TEXT: the same, after a
# short grey label; labels are a word, so they line up at any width.
line() { printf '    %s\n' "$1"; }
item() { printf "    ${SOFT}%-9s${OFF} %s\n" "$1" "$2"; }

term_width() {
	width="$(stty size </dev/tty 2>/dev/null | awk '{print $2}')"
	echo "${width:-${COLUMNS:-80}}"
}

# --- the wordmark (scripts/installer_banner.py draws this) ---------------
wordmark() {
	if [ "$1" -ge 67 ]; then
		printf '  \033[1;38;2;18;86;145m▄▀▀▀▄ \033[1;38;2;21;93;154m█     \033[1;38;2;24;101;163m▄▀▀▀▄ \033[1;38;2;27;108;172m█   █ \033[1;38;2;33;116;181m█▀▀▄  \033[1;38;2;42;124;188m█▄ ▄█ \033[1;38;2;52;133;195m▄▀▀▀▄ \033[1;38;2;61;141;202m█▀▀▀▄ \033[1;38;2;71;149;210m█▀▀▀▄ \033[1;38;2;80;158;217m▄▀▀▀▄ \033[1;38;2;90;166;224m█   █\033[0m\n'
		printf '  \033[1;38;2;18;86;145m█     \033[1;38;2;21;93;154m█     \033[1;38;2;24;101;163m█   █ \033[1;38;2;27;108;172m█   █ \033[1;38;2;33;116;181m█   █ \033[1;38;2;42;124;188m█ █ █ \033[1;38;2;52;133;195m█   █ \033[1;38;2;61;141;202m█▄▄▄▀ \033[1;38;2;71;149;210m█▄▄▄▀ \033[1;38;2;80;158;217m█   █ \033[1;38;2;90;166;224m█ ▄ █\033[0m\n'
		printf '  \033[1;38;2;18;86;145m█   ▄ \033[1;38;2;21;93;154m█     \033[1;38;2;24;101;163m█   █ \033[1;38;2;27;108;172m█   █ \033[1;38;2;33;116;181m█  ▄▀ \033[1;38;2;42;124;188m█   █ \033[1;38;2;52;133;195m█   █ \033[1;38;2;61;141;202m█ ▀▄  \033[1;38;2;71;149;210m█ ▀▄  \033[1;38;2;80;158;217m█   █ \033[1;38;2;90;166;224m█▄▀▄█\033[0m\n'
		printf '  \033[1;38;2;18;86;145m ▀▀▀  \033[1;38;2;21;93;154m▀▀▀▀▀ \033[1;38;2;24;101;163m ▀▀▀  \033[1;38;2;27;108;172m ▀▀▀  \033[1;38;2;33;116;181m▀▀▀   \033[1;38;2;42;124;188m▀   ▀ \033[1;38;2;52;133;195m ▀▀▀  \033[1;38;2;61;141;202m▀   ▀ \033[1;38;2;71;149;210m▀   ▀ \033[1;38;2;80;158;217m ▀▀▀  \033[1;38;2;90;166;224m▀   ▀\033[0m\n'
	else
		printf '  \033[1;38;2;18;86;145mC \033[1;38;2;21;93;154mL \033[1;38;2;24;101;163mO \033[1;38;2;27;108;172mU \033[1;38;2;33;116;181mD \033[1;38;2;42;124;188mM \033[1;38;2;52;133;195mO \033[1;38;2;61;141;202mR \033[1;38;2;71;149;210mR \033[1;38;2;80;158;217mO \033[1;38;2;90;166;224mW\033[0m\n'
	fi
	printf '  \033[38;2;153;161;179mown your data, choose your apps\033[0m\n\n'
}
# --- end of the wordmark -------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
	printf '\n'
	wordmark "$(term_width)"
fi
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

# --- where things are, or go ----------------------------------------------
# A flag says. Else, on a machine that has the server, the unit says where
# the venv and the config are and the config says where the data and the
# files are, so a re-run needs no flags to find a custom layout. On a fresh
# machine the usual places are offered on the terminal (ask_places, below),
# to change or to take with Enter. Everything people keep — a folder per
# person, and the Shares folder — is under the data directory, in files/,
# unless a flag or the config says otherwise.
UNIT="/etc/systemd/system/$SERVICE_NAME.service"
unit_value() { sed -n "s/^$1=//p" "$UNIT" 2>/dev/null | head -n 1; }
ASK_PLACES=""
if [ -z "$PREFIX$CONFIG_DIR$DATA_DIR$FILES_DIR$SHARES_DIR" ] && [ ! -f "$UNIT" ] && [ ! -f "$DEFAULT_CONFIG_DIR/server.toml" ]; then
	ASK_PLACES="1"
fi
if [ -z "$PREFIX" ]; then
	# ExecStart=/opt/cloudmorrow/venv/bin/cloudmorrow-server serve
	exec_start="$(unit_value ExecStart | cut -d' ' -f1)"
	case "$exec_start" in
	*/venv/bin/cloudmorrow-server) PREFIX="${exec_start%/venv/bin/cloudmorrow-server}" ;;
	*) PREFIX="$DEFAULT_PREFIX" ;;
	esac
fi
if [ -z "$CONFIG_DIR" ]; then
	# Environment=CLOUDMORROW_SERVER_CONFIG=/etc/cloudmorrow/server.toml
	config_now="$(unit_value Environment=CLOUDMORROW_SERVER_CONFIG)"
	case "$config_now" in
	/*/server.toml) CONFIG_DIR="$(dirname "$config_now")" ;;
	*) CONFIG_DIR="$DEFAULT_CONFIG_DIR" ;;
	esac
fi
CONFIG="$CONFIG_DIR/server.toml"
config_value() { sed -n "s/^$1 = \"\{0,1\}\([^\"]*\)\"\{0,1\}\$/\1/p" "$CONFIG" 2>/dev/null | head -n 1; }
[ -n "$DATA_DIR" ] || DATA_DIR="$(config_value data_dir)"
[ -n "$DATA_DIR" ] || DATA_DIR="$DEFAULT_DATA_DIR"
# The config's key for the files is notes_dir, from when notes were all it
# held; the flag and the installer's words say files.
FILES_GIVEN="$FILES_DIR"
[ -n "$FILES_GIVEN" ] || FILES_GIVEN="$(config_value notes_dir)"
[ -n "$SHARES_DIR" ] || SHARES_DIR="$(config_value shares_dir)"
# places: what follows from the answers; called again once they are asked.
places() {
	SRC="$PREFIX/src"
	VENV="$PREFIX/venv"
	CONFIG="$CONFIG_DIR/server.toml"
	KEY_FILE="$CONFIG_DIR/cloudmorrow.key"
	FILES_DIR="${FILES_GIVEN:-$DATA_DIR/files}"
}
places
# shares_outside: the Shares folder when it is a directory of its own —
# outside the files, the data and the code — to make, and to let the
# service write to (ReadWritePaths in the unit). Moved by hand later, a
# run with --update rewrites the unit to match.
shares_outside() {
	case "$SHARES_DIR" in
	"" | "$FILES_DIR" | "$FILES_DIR"/* | "$DATA_DIR" | "$DATA_DIR"/* | "$PREFIX" | "$PREFIX"/*) ;;
	*) printf '%s' "$SHARES_DIR" ;;
	esac
}
# place_flags: the flags that name every place that is not the usual one,
# for a message that says how to run this again.
place_flags() {
	[ "$PREFIX" = "$DEFAULT_PREFIX" ] || printf ' --prefix %s' "$PREFIX"
	[ "$CONFIG_DIR" = "$DEFAULT_CONFIG_DIR" ] || printf ' --config-dir %s' "$CONFIG_DIR"
	[ "$DATA_DIR" = "$DEFAULT_DATA_DIR" ] || printf ' --data-dir %s' "$DATA_DIR"
	[ "$FILES_DIR" = "$DATA_DIR/files" ] || printf ' --files-dir %s' "$FILES_DIR"
	[ -z "$SHARES_DIR" ] || printf ' --shares-dir %s' "$SHARES_DIR"
}

[ -n "$DRY_RUN" ] || [ "$(id -u)" = "0" ] || die "run this with sudo"
# --- what it needs ----------------------------------------------------------
# Checked before anything is asked or changed, so a missing package shows up
# in the first second, not after the user and the checkout are made. This
# runs as root, so it installs what is missing with the machine's own
# package manager; where it cannot, it says the exact command and stops.
PKG=""
for candidate in apt-get dnf yum zypper pacman apk; do
	if command -v "$candidate" >/dev/null 2>&1; then
		PKG="$candidate"
		break
	fi
done

pkg_command() {
	case "$PKG" in
	apt-get) echo "apt-get install -y $*" ;;
	dnf | yum) echo "$PKG install -y $*" ;;
	zypper) echo "zypper --non-interactive install $*" ;;
	pacman) echo "pacman -S --noconfirm --needed $*" ;;
	apk) echo "apk add $*" ;;
	*) echo "" ;;
	esac
}

# The package that brings a command, by package manager.
pkg_for() {
	case "$1:$PKG" in
	git:* | sudo:*) echo "$1" ;;
	python:pacman) echo python ;;
	python:zypper) echo python311 ;;
	python:*) echo python3 ;;
	useradd:apt-get) echo passwd ;;
	useradd:dnf | useradd:yum) echo shadow-utils ;;
	useradd:*) echo shadow ;;
	ssh:apt-get) echo openssh-client ;;
	ssh:dnf | ssh:yum | ssh:zypper) echo openssh-clients ;;
	ssh:*) echo openssh ;;
	esac
}

# install_packages "what for" pkg...: installs them, or explains and stops.
install_packages() {
	what="$1"
	shift
	command="$(pkg_command "$@")"
	if [ -z "$command" ]; then
		die "this machine needs $what, and no package manager here is one this script knows. Install it and run this again."
	fi
	if [ -n "$DRY_RUN" ]; then
		printf '   \033[2mwould run:\033[0m %s   (for %s)\n' "$command" "$what"
		return 0
	fi
	say "installing $what: $command"
	if [ "$PKG" = "apt-get" ]; then
		DEBIAN_FRONTEND=noninteractive apt-get -qq update >/dev/null 2>&1 || true
	fi
	# The command is ours, and split on purpose.
	# shellcheck disable=SC2086
	DEBIAN_FRONTEND=noninteractive $command >/dev/null ||
		die "that did not work. Install it yourself with: sudo $command"
}

find_python() {
	PYTHON=""
	for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
		if command -v "$candidate" >/dev/null 2>&1 &&
			"$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
			PYTHON="$candidate"
			return 0
		fi
	done
	return 1
}

MISSING=""
NEEDED=""
need() {
	# need <command> <what>: notes the package when the command is missing.
	if ! command -v "$1" >/dev/null 2>&1; then
		MISSING="$MISSING $(pkg_for "$2")"
		NEEDED="$NEEDED${NEEDED:+, }$1"
	fi
}
need git git
need sudo sudo
need useradd useradd
find_python || { MISSING="$MISSING $(pkg_for python)"; NEEDED="$NEEDED${NEEDED:+, }python3"; }
if [ -n "$MISSING" ]; then
	# shellcheck disable=SC2086
	install_packages "$NEEDED" $MISSING
fi

if ! find_python && [ -z "$DRY_RUN" ]; then
	newest="$(python3 -V 2>/dev/null || echo "no Python at all")"
	die "Python 3.11 or newer is required, and this machine has $newest. Install a newer one (your distribution's python3.11 or later) and run this again."
fi

# Debian and Ubuntu ship venv's pip bootstrap in a package of its own
# (python3.12-venv), so "import venv" works and making one does not, or
# makes one without pip. Only making one, and asking its pip, says for sure.
if [ -n "$PYTHON" ]; then
	VENV_TEST="$(mktemp -d)"
	if ! "$PYTHON" -m venv "$VENV_TEST/venv" >/dev/null 2>&1 ||
		! "$VENV_TEST/venv/bin/python" -m pip --version >/dev/null 2>&1; then
		version="$("$PYTHON" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
		case "$PKG" in
		apt-get) install_packages "Python's venv module and pip" "python$version-venv" ;;
		*) die "$PYTHON cannot make a virtualenv with pip in it here. Install the venv module and pip for Python $version, then run this again." ;;
		esac
		if [ -z "$DRY_RUN" ]; then
			rm -rf "$VENV_TEST/venv"
			{ "$PYTHON" -m venv "$VENV_TEST/venv" >/dev/null 2>&1 &&
				"$VENV_TEST/venv/bin/python" -m pip --version >/dev/null 2>&1; } ||
				die "$PYTHON still cannot make a virtualenv with pip in it. Install python$version-venv and run this again."
		fi
	fi
	rm -rf "$VENV_TEST"
fi

# The default repo is wherever this checkout came from, so running the script
# straight out of a clone does the obvious thing; a copy on its own, or one
# that arrived through curl, installs the public code.
# Only a script that is really on disk has a checkout around it; through a
# pipe, $0 is the shell, and whatever directory this runs from is not ours
# to read a remote off.
SCRIPT_DIR=""
if [ -f "$0" ]; then
	SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
fi
if [ -z "$REPO" ] && [ -n "$SCRIPT_DIR" ] && [ -d "$SCRIPT_DIR/../.git" ]; then
	REPO="$(git -C "$SCRIPT_DIR/.." remote get-url origin 2>/dev/null || true)"
fi
[ -n "$REPO" ] || REPO="$DEFAULT_REPO"

# A repository over ssh needs a deploy key, and the tools to make one.
case "$REPO" in
git@* | ssh://*)
	if [ -z "$NO_SSH_KEY" ] && ! command -v ssh-keygen >/dev/null 2>&1; then
		install_packages "ssh-keygen" "$(pkg_for ssh)"
	fi
	;;
esac

# --- already here? ------------------------------------------------------------
# A server that is installed, running and answering is left as it is. One
# that is not gets the whole install again over it: the checkout reset to
# the branch, the packages reinstalled, the unit rewritten, the service
# restarted. That mends almost everything short of lost data.
# listening_on "HOST, HOST": sets HEALTH_HOST, how this machine reaches the
# server (loopback when it listens there or everywhere, else the first
# address), and LAN_HOST, how the network does (the machine's own IP when
# it listens everywhere, else the first address that is not loopback).
listening_on() {
	loop="" first="" lan=""
	for h in $(printf '%s' "$1" | tr ',' ' '); do
		case "$h" in
		0.0.0.0 | ::) loop="127.0.0.1"; lan="${lan:-$(hostname -I 2>/dev/null | awk '{print $1}')}" ;;
		127.* | localhost) loop="${loop:-$h}" ;;
		::1) loop="${loop:-[::1]}" ;;
		*:*) first="${first:-[$h]}"; lan="${lan:-[$h]}" ;;
		*) first="${first:-$h}"; lan="${lan:-$h}" ;;
		esac
	done
	HEALTH_HOST="${loop:-${first:-127.0.0.1}}"
	LAN_HOST="${lan:-$HEALTH_HOST}"
}
HEALTH_PORT="$PORT"
if [ -f "$CONFIG" ]; then
	listening_on "$(config_value host)"
	HEALTH_PORT="$(config_value port)"
else
	listening_on "$HOST"
fi
HEALTH_URL="http://$HEALTH_HOST:${HEALTH_PORT:-8787}/api/health"
HAS_SYSTEMD=""
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
	HAS_SYSTEMD="1"
fi

# health: prints what is wrong and fails, or prints nothing when all is well.
health() {
	if [ -n "$HAS_SYSTEMD" ]; then
		if ! systemctl is-active --quiet "$SERVICE_NAME"; then
			echo "the $SERVICE_NAME service is not running"
			return 1
		fi
		if [ -f /etc/systemd/system/cloudmorrow-agent.service ] && ! systemctl is-active --quiet cloudmorrow-agent; then
			echo "the server's agent (cloudmorrow-agent) is not running"
			return 1
		fi
	fi
	if [ ! -x "$VENV/bin/python" ]; then
		echo "$VENV is missing"
		return 1
	fi
	"$VENV/bin/python" - "$HEALTH_URL" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as r:
        status = json.load(r).get("status")
except Exception as exc:
    print(f"it does not answer on {sys.argv[1]} ({exc})")
    sys.exit(1)
if status != "ok":
    print(f"{sys.argv[1]} says {status!r}")
    sys.exit(1)
PY
}

# wait_healthy: a freshly restarted server takes a few seconds to answer.
wait_healthy() {
	tries=0
	while ! problem="$(health)"; do
		tries=$((tries + 1))
		if [ "$tries" -ge 20 ]; then
			printf '%s' "$problem"
			return 1
		fi
		sleep 1
	done
}

if [ -z "$UPDATE" ] && [ -z "$DRY_RUN" ] && [ -f "$CONFIG" ] && [ -x "$VENV/bin/cloudmorrow-server" ]; then
	if problem="$(health)"; then
		NAME_NOW="$(config_value name)"
		URL_NOW="$(config_value public_url)"
		LOCAL_NOW="${HEALTH_URL%/api/health}"
		printf "\n  ${GOOD}✓${OFF} %s is already here, running and answering.\n" "${NAME_NOW:-Cloudmorrow}"
		heading "Open it"
		line "${URL_NOW:-$LOCAL_NOW}/app"
		heading "Nothing to do. To update it anyway"
		item "here" "cloudmorrow-update"
		item "anywhere" "cloudmorrow update server"
		item "all again" "... | sudo sh -s -- --update"
		printf '\n'
		exit 0
	fi
	warn "Cloudmorrow is installed here, but $problem"
	say "updating and reinstalling it, then checking again"
fi

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
	printf '  A few questions, and your cloud is running.\n\n' >/dev/tty
fi
ask CLOUD_NAME "What is your cloud called?" "Cloudmorrow"
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

# --- where it goes ---------------------------------------------------------
# The usual places, each on a row to change or to leave: Enter takes them
# all. The form (cloudmorrow.form) is in the checkout when this runs from
# one; through curl | sh nothing is installed yet, so the three files it is
# made of are fetched from the repository on their own. Failing both, each
# place is asked on a line.
PLACES_PYTHON=""
PLACES_DIR=""
places_python() {
	if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../src/cloudmorrow/form.py" ]; then
		PLACES_PYTHON="env PYTHONPATH=$SCRIPT_DIR/../src $PYTHON"
		return 0
	fi
	if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import cloudmorrow.form" 2>/dev/null; then
		PLACES_PYTHON="$VENV/bin/python"
		return 0
	fi
	case "$REPO" in
	https://github.com/*) raw="https://raw.githubusercontent.com/${REPO#https://github.com/}" ;;
	git@github.com:*) raw="https://raw.githubusercontent.com/${REPO#git@github.com:}" ;;
	*) return 1 ;;
	esac
	raw="${raw%.git}/$BRANCH/src/cloudmorrow"
	if command -v curl >/dev/null 2>&1; then
		fetch="curl -fsSL -o"
	elif command -v wget >/dev/null 2>&1; then
		fetch="wget -qO"
	else
		return 1
	fi
	PLACES_DIR="$(mktemp -d)"
	mkdir -p "$PLACES_DIR/cloudmorrow"
	: >"$PLACES_DIR/cloudmorrow/__init__.py"
	for file in form.py checklist.py palette.py; do
		$fetch "$PLACES_DIR/cloudmorrow/$file" "$raw/$file" 2>/dev/null || return 1
	done
	PLACES_PYTHON="env PYTHONPATH=$PLACES_DIR $PYTHON"
}

ask_places() {
	status=0
	answer="$($PLACES_PYTHON -m cloudmorrow.form \
		--title "Where should it go? Enter takes the usual places. Everything people keep — a folder per person, and the Shares folder — goes under Data, in files/." \
		--field prefix "Code" "$DEFAULT_PREFIX" "the checkout and the virtualenv" \
		--field config "Settings" "$DEFAULT_CONFIG_DIR" "server.toml and the sealing key" \
		--field data "Data" "$DEFAULT_DATA_DIR" "files/, the database, keys and quills" \
		--pattern '/\S*' --problem "an absolute path, please")" || status=$?
	case "$status" in
	0)
		PREFIX="$(printf '%s\n' "$answer" | sed -n 's/^prefix=//p')"
		CONFIG_DIR="$(printf '%s\n' "$answer" | sed -n 's/^config=//p')"
		DATA_DIR="$(printf '%s\n' "$answer" | sed -n 's/^data=//p')"
		;;
	130) die "stopped. Run this again to carry on where it left off." ;;
	*) return 1 ;;
	esac
}

ask_places_on_lines() {
	printf '  Where should it go? Enter takes the usual place. Everything people keep\n' >/dev/tty
	printf '  — a folder per person, and the Shares folder — goes under Data, in files/.\n' >/dev/tty
	PREFIX="" CONFIG_DIR="" DATA_DIR=""
	ask PREFIX "Code, the checkout and the virtualenv" "$DEFAULT_PREFIX"
	ask CONFIG_DIR "Settings, server.toml and the sealing key" "$DEFAULT_CONFIG_DIR"
	ask DATA_DIR "Data, everyone's files, the database, keys and quills" "$DEFAULT_DATA_DIR"
	for place in "$PREFIX" "$CONFIG_DIR" "$DATA_DIR"; do
		case "$place" in
		/*) ;;
		*) die "$place is not an absolute path" ;;
		esac
	done
	printf '\n' >/dev/tty
}

if [ -n "$ASK_PLACES" ]; then
	if [ -n "$DRY_RUN" ]; then
		printf '   \033[2mwould ask:\033[0m where things go (the usual places unless changed)\n'
	elif [ -n "$TTY" ]; then
		if places_python && ask_places; then
			:
		else
			ask_places_on_lines
		fi
		[ -z "$PLACES_DIR" ] || rm -rf "$PLACES_DIR"
		places
	fi
fi

CLOUD_NAME="${CLOUD_NAME:-Cloudmorrow}"
PUBLIC_URL="$(printf '%s' "$PUBLIC_URL" | sed 's|/*$||')"
# The name it announces on the home network: "The Larsens" -> the-larsens.local.
LABEL="$(printf '%s' "$CLOUD_NAME" | tr 'A-Z' 'a-z' |
	sed -e 's/[^a-z0-9-]\{1,\}/-/g' -e 's/-\{2,\}/-/g' -e 's/^-*//' -e 's/-*$//' | cut -c1-63)"
[ -n "$LABEL" ] || LABEL="cloudmorrow"
case "$PUBLIC_URL" in
http://*)
	warn "$PUBLIC_URL is plain http: every client will have to allow that"
	warn "(cloudmorrow config set allow_insecure_http true). Put TLS in front when you can."
	;;
esac
if [ -n "$DRY_RUN" ]; then
	[ -n "$ACCOUNT" ] || [ "$EXISTING_USERS" != "0" ] || warn "would ask for the first account's username and password"
fi

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
SHARES_OUTSIDE="$(shares_outside)"
say "directories: $PREFIX, $CONFIG_DIR, $DATA_DIR, $FILES_DIR${SHARES_OUTSIDE:+, $SHARES_OUTSIDE}"
run mkdir -p "$PREFIX" "$DATA_DIR" "$FILES_DIR" "$CONFIG_DIR" ${SHARES_OUTSIDE:+"$SHARES_OUTSIDE"}
run chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX" "$DATA_DIR" "$FILES_DIR" ${SHARES_OUTSIDE:+"$SHARES_OUTSIDE"}

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
		PLACE_FLAGS="$(place_flags)"
		cat <<EOF

  This machine has no access to $REPO yet.

  Add its new public key to the repository as a read-only deploy key
  (GitHub: Settings -> Deploy keys -> Add deploy key), then run this
  script again — it will pick up where it left off.
${PLACE_FLAGS:+
  Give it the same places:$PLACE_FLAGS
}
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
# A venv without pip is what a run that stopped halfway leaves behind (the
# venv module could make the directory but not bootstrap pip). It holds
# nothing but installed packages, so it is made again.
if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
	say "the virtualenv at $VENV has no pip; making it again"
	run rm -rf "$VENV"
fi
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


# --- where it answers -----------------------------------------------------
# Asked once the software is in, because the question is a list of boxes to
# tick that the checkout brings (cloudmorrow.checklist). A config that
# exists already has its answer, and so does --host.

# interfaces: "name=address" for each IPv4 address on this machine but
# loopback, which the list offers on a line of its own.
interfaces() {
	if command -v ip >/dev/null 2>&1; then
		ip -o -4 addr show 2>/dev/null | awk '$2 != "lo" { sub("/.*", "", $4); print $2 "=" $4 }'
	else
		for address in $(hostname -I 2>/dev/null); do
			case "$address" in *:*) ;; *) echo "=$address" ;; esac
		done
	fi
}

ask_addresses() {
	set -- --title "Which addresses should it answer on?" --need-one \
		--item 0.0.0.0 "Every address" "all networks, now and later" --on 0.0.0.0 --alone 0.0.0.0 \
		--item 127.0.0.1 "This machine only" "for a proxy on this box"
	for pair in $(interfaces); do
		set -- "$@" --item "${pair#*=}" "${pair#*=}" "${pair%%=*}"
	done
	set -- "$@" --other "Other" --other-hint "type an address or a host name" \
		--other-pattern '[A-Za-z0-9._:-]+'
	status=0
	chosen="$("$VENV/bin/python" -m cloudmorrow.checklist "$@")" || status=$?
	case "$status" in
	0) HOST="$(printf '%s\n' "$chosen" | paste -sd, - | sed 's/,/, /g')" ;;
	130) die "stopped. Run this again to carry on where it left off." ;;
	*) warn "could not ask, so it answers on every address (--host chooses)" ;;
	esac
}

if [ -z "$HOST_GIVEN" ] && [ ! -f "$CONFIG" ]; then
	if [ -n "$DRY_RUN" ]; then
		printf '   \033[2mwould ask:\033[0m which addresses to answer on\n'
	elif [ -n "$TTY" ]; then
		ask_addresses
	fi
fi
if [ ! -f "$CONFIG" ]; then
	listening_on "$HOST"
	HEALTH_URL="http://$HEALTH_HOST:$PORT/api/health"
fi

# --- configuration ---------------------------------------------------------
if [ -f "$CONFIG" ]; then
	say "keeping the existing $CONFIG"
else
	say "writing $CONFIG"
	if [ -n "$SHARES_DIR" ]; then
		SHARES_LINE="shares_dir = \"$SHARES_DIR\""
	else
		SHARES_LINE="# shares_dir = \"/srv/shares\""
	fi
	write_file "$CONFIG" 0644 <<EOF
# Written by install-server.sh. Safe to edit; the installer never rewrites it.
[server]
# What this cloud is called: on the sign-in screen, the install page and
# the phone's home screen.
name = "$CLOUD_NAME"

# Everyone's files: a folder per person, and the Shares folder. (The key
# is called notes_dir from when notes were all that was kept in it.)
notes_dir = "$FILES_DIR"
# The database, the keys and the quills.
data_dir = "$DATA_DIR"
per_user_dirs = true

# The Shares folder, for files shared with every machine: Shares among
# the files, unless this says otherwise. A folder outside the directories
# above has to be in the service's ReadWritePaths as well: after moving
# it, run the installer again with --update.
$SHARES_LINE

host = "$HOST"
port = $PORT

# The key everything is sealed with at rest. Kept here, away from the data
# in $DATA_DIR, so a copy of that directory alone opens nothing. Back it up
# with the data, never instead of it: lose it and everything is gone.
key_file = "$KEY_FILE"

# The URL clients reach this server on, baked into the install page: your
# own domain, behind your own reverse proxy. Empty, the page uses the
# address it was opened at.
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
ReadWritePaths=$FILES_DIR $DATA_DIR $PREFIX${SHARES_OUTSIDE:+ $SHARES_OUTSIDE}

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
	if [ -n "$DRY_RUN" ]; then
		:
	elif problem="$(wait_healthy)"; then
		say "$SERVICE_NAME is enabled, running and answering"
	else
		warn "$SERVICE_NAME was started, but $problem"
		warn "to see why:  journalctl -u $SERVICE_NAME -n 50"
	fi
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
	--config "$CONFIG" --run-as "$SERVICE_USER" \
	--url "${PUBLIC_URL:-http://$HEALTH_HOST:$PORT}" >/tmp/cloudmorrow-agent-install.$$ 2>&1; then
	AGENT_INSTALLED="1"
	say "the server has an agent of its own (cloudmorrow-agent.service)"
	sed 's/^/   /' /tmp/cloudmorrow-agent-install.$$
elif [ -z "$DRY_RUN" ]; then
	warn "no agent on the server yet — it needs an account to belong to"
fi
rm -f /tmp/cloudmorrow-agent-install.$$

# --- what to do next -------------------------------------------------------
# Headings with short lines under them, never columns: a narrow terminal
# wraps a long line wherever it likes, and columns lined up past its edge
# read as noise.
PUBLIC_HOST="$(printf '%s' "$PUBLIC_URL" | sed -e 's|^[a-z]*://||' -e 's|[:/].*$||')"
ADDRESS="${PUBLIC_URL:-http://$LAN_HOST:$PORT}"
LISTENING="$HOST"
if [ -f "$CONFIG" ] && [ -z "$DRY_RUN" ]; then
	LISTENING="$(config_value host)"
fi

if [ -n "$DRY_RUN" ]; then
	printf '\n  %s would be installed.\n' "$CLOUD_NAME"
else
	printf "\n  ${GOOD}✓${OFF} %s is installed.\n" "$CLOUD_NAME"
fi

case "$PUBLIC_URL" in
https://*)
	heading "First, a proxy in front, for TLS"
	line "With Caddy, this is the whole file:"
	printf '\n      %s {\n          reverse_proxy %s:%s\n      }\n' "$PUBLIC_HOST" "$HEALTH_HOST" "$PORT"
	;;
esac

heading "Open it in a browser"
line "$ADDRESS"
if [ -z "$PUBLIC_URL" ]; then
	line "or http://$LABEL.local:$PORT, at home"
fi
if [ -n "$ACCOUNT_MADE" ]; then
	line "and sign in as $ACCOUNT"
fi

if [ -z "$PUBLIC_URL" ]; then
	heading "From outside your network"
	line "That is yours to set up: a"
	line "domain and a reverse proxy"
	line "(public_url in the settings),"
	line "or a VPN such as Tailscale."
fi

if [ "$EXISTING_USERS" = "0" ] && [ -z "$ACCOUNT_MADE" ] && [ -z "$DRY_RUN" ]; then
	heading "Make the first account, the administrator"
	line "sudo -u $SERVICE_USER \\"
	line "  $VENV/bin/cloudmorrow-server \\"
	line "  user create alice"
fi

heading "Put it on your computers"
line "curl -fsSL $ADDRESS/install.sh | sh"

heading "Put it on your phone"
line "Open $ADDRESS/app"
line "and add it to the home screen."

heading "It answers on"
for h in $(printf '%s' "$LISTENING" | tr ',' ' '); do
	case "$h" in
	0.0.0.0 | ::) line "every address, port $PORT" ;;
	*) line "$h, port $PORT" ;;
	esac
done

heading "Where things are"
item "settings" "$CONFIG"
item "data" "$DATA_DIR"
item "files" "$FILES_DIR"
item "shares" "${SHARES_DIR:-$FILES_DIR/Shares}"
item "code" "$SRC ($BRANCH)"

heading "To update it later"
item "anywhere" "cloudmorrow update server"
item "here" "cloudmorrow-update"

if [ -z "$AGENT_INSTALLED" ] && [ -z "$DRY_RUN" ]; then
	heading "Once there is an account, give the server an agent"
	line "sudo $VENV/bin/cloudmorrow-server \\"
	line "  agent-install --run-as $SERVICE_USER"
fi
printf '\n'
