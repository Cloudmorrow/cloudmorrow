#!/bin/sh
# Take the Cloudmorrow server off this machine: the reverse of install-server.sh.
#
#   curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/uninstall-server.sh | sudo sh
#
# It finds what the installer made — from the systemd unit and the config,
# so custom paths are found too — lists all of it, and asks before it
# touches anything. By default it takes the software away — the services,
# the code, the commands — and leaves the config and the sealing key, the
# database and every note and file, so a later install picks up where this
# one was. To delete all of that too, add --delete-data:
#
#   curl -fsSL …/uninstall-server.sh | sudo sh -s -- --delete-data
#
# Computers that used this cloud keep their own copy of Cloudmorrow; take it
# off each of them with `cm uninstall`.
set -eu

PREFIX=""
NOTES_DIR=""
DATA_DIR=""
SERVICE_USER=""
SERVICE_NAME="cloudmorrow"
AGENT_NAME="cloudmorrow-agent"
CONFIG_DIR="/etc/cloudmorrow"
DELETE_DATA=""
YES=""
DRY_RUN=""

usage() {
	sed -n '2,16p' "$0"
	cat <<EOF

Options:
  --delete-data       also delete the config, the key, the database and the
                      notes, and the service user that owns them
  --yes               do not ask first
  --dry-run           print what would be removed, change nothing
  --prefix DIR        where the checkout and venv are (default: from the unit)
  --notes-dir DIR     where the notes are               (default: from the config)
  --data-dir DIR      the database and keys             (default: from the config)
  --service-user NAME the system user it runs as        (default: from the unit)
  --service-name NAME the systemd service               (default: $SERVICE_NAME)
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
	--delete-data) DELETE_DATA="1"; shift ;;
	--keep-data) DELETE_DATA=""; shift ;; # the default now; still accepted
	--yes | -y) YES="1"; shift ;;
	--dry-run) DRY_RUN="1"; shift ;;
	--prefix) PREFIX="$2"; shift 2 ;;
	--notes-dir) NOTES_DIR="$2"; shift 2 ;;
	--data-dir) DATA_DIR="$2"; shift 2 ;;
	--service-user) SERVICE_USER="$2"; shift 2 ;;
	--service-name) SERVICE_NAME="$2"; shift 2 ;;
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

[ -n "$DRY_RUN" ] || [ "$(id -u)" = "0" ] || die "run this with sudo"

UNIT="/etc/systemd/system/$SERVICE_NAME.service"
AGENT_UNIT="/etc/systemd/system/$AGENT_NAME.service"
CONFIG="$CONFIG_DIR/server.toml"

# --- what the installer made ------------------------------------------------
# The unit says where the venv is and who it runs as; the config says where
# the data is. A flag wins over both, and the installer's defaults are last.
unit_value() { sed -n "s/^$1=//p" "$UNIT" 2>/dev/null | head -n 1; }
config_value() { sed -n "s/^$1 = \"\\(.*\\)\"\$/\\1/p" "$CONFIG" 2>/dev/null | head -n 1; }

if [ -z "$PREFIX" ]; then
	# ExecStart=/opt/cloudmorrow/venv/bin/cloudmorrow-server serve
	exec_start="$(unit_value ExecStart | cut -d' ' -f1)"
	case "$exec_start" in
	*/venv/bin/cloudmorrow-server) PREFIX="${exec_start%/venv/bin/cloudmorrow-server}" ;;
	*) PREFIX="/opt/cloudmorrow" ;;
	esac
fi
[ -n "$SERVICE_USER" ] || SERVICE_USER="$(unit_value User)"
[ -n "$SERVICE_USER" ] || SERVICE_USER="cloudmorrow"
[ -n "$NOTES_DIR" ] || NOTES_DIR="$(config_value notes_dir)"
[ -n "$NOTES_DIR" ] || NOTES_DIR="/srv/cloudmorrow/notes"
[ -n "$DATA_DIR" ] || DATA_DIR="$(config_value data_dir)"
[ -n "$DATA_DIR" ] || DATA_DIR="/var/lib/cloudmorrow"
CLOUD_NAME="$(config_value name)"

# Every directory this deletes wholesale is checked first: absolute, and not
# one of the system's own. A config edited by hand to say notes_dir = "/"
# must not be able to take the machine with it.
check_dir() {
	case "$1" in
	/*) ;;
	*) die "$1 is not an absolute path; give it with a flag" ;;
	esac
	case "$(printf '%s' "$1" | sed 's|/*$||')" in
	"" | /bin | /boot | /dev | /etc | /home | /lib | /lib64 | /media | /mnt | /opt | /proc | /root | \
		/run | /sbin | /srv | /sys | /tmp | /usr | /usr/local | /var | /var/lib | "$HOME")
		die "refusing to delete $1; give the right path with a flag"
		;;
	esac
}
check_dir "$PREFIX"
if [ -n "$DELETE_DATA" ]; then
	check_dir "$NOTES_DIR"
	check_dir "$DATA_DIR"
fi

# --- the list ---------------------------------------------------------------
REMOVE=""
add() { [ -e "$1" ] || [ -L "$1" ] && REMOVE="$REMOVE
$1" || true; }

add "$AGENT_UNIT"
add "$UNIT"
[ -L /usr/local/bin/cloudmorrow-server ] && add /usr/local/bin/cloudmorrow-server
grep -qs "install-server.sh" /usr/local/bin/cloudmorrow-update && add /usr/local/bin/cloudmorrow-update
grep -qs "install-server.sh" /etc/sudoers.d/cloudmorrow && add /etc/sudoers.d/cloudmorrow
add "$PREFIX"
if [ -n "$DELETE_DATA" ]; then
	add "$CONFIG_DIR"
	add "$DATA_DIR"
	add "$NOTES_DIR"
fi
USER_GOES=""
if [ -n "$DELETE_DATA" ] && id "$SERVICE_USER" >/dev/null 2>&1; then
	USER_GOES="1"
fi

if [ -z "$REMOVE" ] && [ -z "$USER_GOES" ]; then
	say "there is no Cloudmorrow server on this machine"
	exit 0
fi

printf '\n  This removes the Cloudmorrow server%s from this machine:\n\n' "${CLOUD_NAME:+ \"$CLOUD_NAME\"}"
printf '%s\n' "$REMOVE" | sed '/^$/d; s/^/    - /'
[ -z "$USER_GOES" ] || printf '    - the system user %s\n' "$SERVICE_USER"
if [ -z "$DELETE_DATA" ]; then
	printf '\n  and keeps %s, %s and %s,\n  so installing again picks up where it was.\n' "$CONFIG_DIR" "$DATA_DIR" "$NOTES_DIR"
	printf '  Add --delete-data to delete them too.\n'
else
	printf '\n  \033[1mEvery account, note, file and secret on it goes too.\033[0m\n'
	printf '  Leave out --delete-data to keep them.\n'
fi
printf '\n'

# --- ask ----------------------------------------------------------------------
# On the terminal, not stdin: through `curl | sh` the script itself is stdin.
if [ -n "$DRY_RUN" ]; then
	:
elif [ -z "$YES" ]; then
	( : </dev/tty ) 2>/dev/null || die "nobody to ask; run it again with --yes"
	if [ -z "$DELETE_DATA" ]; then
		printf '\033[1mGo ahead?\033[0m [y/N]: ' >/dev/tty
		read -r answer </dev/tty || answer=""
		case "$answer" in y | Y | yes) ;; *) die "nothing was removed" ;; esac
	else
		printf '\033[1mType "delete" to remove all of it\033[0m: ' >/dev/tty
		read -r answer </dev/tty || answer=""
		[ "$answer" = "delete" ] || die "nothing was removed"
	fi
fi

# --- the services -----------------------------------------------------------
# The agent first: it reports to the server, so it goes before the server does.
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
	for name in "$AGENT_NAME" "$SERVICE_NAME"; do
		if [ -f "/etc/systemd/system/$name.service" ]; then
			say "stopping $name"
			run systemctl disable --now --quiet "$name" || warn "$name did not stop cleanly"
		fi
	done
fi
for unit in "$AGENT_UNIT" "$UNIT"; do
	[ ! -f "$unit" ] || run rm -f "$unit"
done
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
	run systemctl daemon-reload
fi

# --- the commands and the rule that lets them run ----------------------------
say "removing the commands"
[ ! -L /usr/local/bin/cloudmorrow-server ] || run rm -f /usr/local/bin/cloudmorrow-server
if grep -qs "install-server.sh" /usr/local/bin/cloudmorrow-update; then
	run rm -f /usr/local/bin/cloudmorrow-update
fi
if grep -qs "install-server.sh" /etc/sudoers.d/cloudmorrow; then
	run rm -f /etc/sudoers.d/cloudmorrow
fi

# --- the code -----------------------------------------------------------------
if [ -e "$PREFIX" ]; then
	say "removing the code at $PREFIX"
	run rm -rf "$PREFIX"
fi

# --- the data -------------------------------------------------------------------
if [ -n "$DELETE_DATA" ]; then
	for dir in "$CONFIG_DIR" "$DATA_DIR" "$NOTES_DIR"; do
		if [ -e "$dir" ]; then
			say "removing $dir"
			run rm -rf "$dir"
		fi
	done
	# The installer made /srv/cloudmorrow to hold notes/; empty now, it goes too.
	parent="$(dirname "$NOTES_DIR")"
	if [ "$(basename "$parent")" = "cloudmorrow" ] && [ -d "$parent" ]; then
		run rmdir "$parent" 2>/dev/null || true
	fi
	if [ -n "$USER_GOES" ]; then
		say "removing the system user $SERVICE_USER"
		run userdel "$SERVICE_USER" || warn "the user $SERVICE_USER is still there; remove it with userdel"
	fi
fi

# --- what is left -----------------------------------------------------------------
if [ -n "$DRY_RUN" ]; then
	printf '\n  That was a dry run: nothing was removed.\n\n'
	exit 0
fi
cat <<EOF

  The Cloudmorrow server is gone from this machine.

  Left for you, because the installer never made them:

    - the reverse proxy's entry for this cloud (Caddy, nginx), if you added one
    - the deploy key on GitHub, if you gave the repository one
    - Cloudmorrow on each computer that used this cloud: run  cm uninstall  there

EOF
if [ -z "$DELETE_DATA" ]; then
	cat <<EOF
  Kept, for the next install: $CONFIG_DIR, $DATA_DIR, $NOTES_DIR
  and the system user $SERVICE_USER. To delete them, run this again with --delete-data.

EOF
fi
