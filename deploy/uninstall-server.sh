#!/bin/sh
# Take the Cloudmorrow server off this machine: the reverse of install-server.sh.
#
#   curl -fsSL https://raw.githubusercontent.com/Cloudmorrow/cloudmorrow/main/deploy/uninstall-server.sh | sudo sh
#
# It finds what the installer made — from the systemd unit and the config,
# so custom paths are found too — and shows it as a list of boxes to tick:
# the services, the code, the config and sealing key, the database, the
# notes, the system user. Only the services are ticked to begin with; tick
# what else should go, and it asks once more before it touches anything.
# Without a terminal, say it with a flag:
#
#   curl -fsSL …/uninstall-server.sh | sudo sh -s -- --remove services,code
#   curl -fsSL …/uninstall-server.sh | sudo sh -s -- --delete-data   (all of it)
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
CONFIG_DIR=""
REMOVE_FLAG=""
DELETE_DATA=""
YES=""
DRY_RUN=""

# Everything the installer makes, in the order it is removed. The user goes
# last: it owns the directories.
KINDS="services code config data notes shares user"

usage() {
	sed -n '2,17p' "$0"
	cat <<EOF

Options:
  --remove LIST       what goes, comma-separated, instead of asking:
                      services, code, config, data, notes, shares, user
  --delete-data       all of it: the software, the config, the key, the
                      database, the notes, and the service user
  --yes               do not ask; take what --remove says, or the services
  --dry-run           print what would be removed, change nothing
  --prefix DIR        where the checkout and venv are (default: from the unit)
  --notes-dir DIR     where the notes are               (default: from the config)
  --data-dir DIR      the database and keys             (default: from the config)
  --config-dir DIR    server.toml and the sealing key    (default: from the unit)
  --service-user NAME the system user it runs as        (default: from the unit)
  --service-name NAME the systemd service               (default: $SERVICE_NAME)
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
	--remove) REMOVE_FLAG="$2"; shift 2 ;;
	--delete-data | --all) DELETE_DATA="1"; shift ;;
	--keep-data) DELETE_DATA=""; shift ;; # once the default; still accepted
	--yes | -y) YES="1"; shift ;;
	--dry-run) DRY_RUN="1"; shift ;;
	--prefix) PREFIX="$2"; shift 2 ;;
	--notes-dir) NOTES_DIR="$2"; shift 2 ;;
	--data-dir) DATA_DIR="$2"; shift 2 ;;
	--config-dir) CONFIG_DIR="$2"; shift 2 ;;
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

# --- what the installer made ------------------------------------------------
# The unit says where the venv and the config are and who it runs as; the
# config says where the data is. A flag wins over both, and the installer's
# defaults are last.
unit_value() { sed -n "s/^$1=//p" "$UNIT" 2>/dev/null | head -n 1; }
if [ -z "$CONFIG_DIR" ]; then
	# Environment=CLOUDMORROW_SERVER_CONFIG=/etc/cloudmorrow/server.toml
	config_now="$(unit_value Environment=CLOUDMORROW_SERVER_CONFIG)"
	case "$config_now" in
	/*/server.toml) CONFIG_DIR="$(dirname "$config_now")" ;;
	*) CONFIG_DIR="/etc/cloudmorrow" ;;
	esac
fi
CONFIG="$CONFIG_DIR/server.toml"
KEY_FILE="$CONFIG_DIR/cloudmorrow.key"
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
# The Shares folder is inside the notes directory unless the config moved it
# out; only then is it a thing of its own to remove.
SHARES_DIR="$(config_value shares_dir)"
case "$SHARES_DIR" in
"" | "$NOTES_DIR" | "$NOTES_DIR"/*) SHARES_DIR="" ;;
esac
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

# --- the list ---------------------------------------------------------------
# One row per kind of thing, only for the kinds that are there. A row is
# "kind|label|detail"; the detail says what and where, so the list is the
# answer to "what is on this machine?" even for somebody removing nothing.
FOUND=""
found() { FOUND="$FOUND$1
"; }
is_found() { case "$FOUND" in *"$1|"*) return 0 ;; *) return 1 ;; esac; }

services_detail=""
[ -f "$UNIT" ] && services_detail="$SERVICE_NAME"
[ -f "$AGENT_UNIT" ] && services_detail="${services_detail:+$services_detail, }$AGENT_NAME"
commands=""
[ -L /usr/local/bin/cloudmorrow-server ] && commands="cloudmorrow-server"
grep -qs "install-server.sh" /usr/local/bin/cloudmorrow-update && commands="${commands:+$commands, }cloudmorrow-update"
grep -qs "install-server.sh" /etc/sudoers.d/cloudmorrow && commands="${commands:+$commands, }the sudo rule"
if [ -n "$services_detail" ] || [ -n "$commands" ]; then
	found "services|Services|${services_detail:+the units $services_detail}${services_detail:+${commands:+; }}${commands:+the commands $commands}"
fi
[ ! -e "$PREFIX" ] || found "code|Code|$PREFIX: the checkout and the virtualenv"
if [ -e "$CONFIG_DIR" ]; then
	key_note=""
	[ ! -f "$KEY_FILE" ] || key_note=" and the sealing key"
	found "config|Config|$CONFIG_DIR: server.toml$key_note"
fi
[ ! -e "$DATA_DIR" ] || found "data|Data|$DATA_DIR: the database, keys and quills"
[ ! -e "$NOTES_DIR" ] || found "notes|Notes|$NOTES_DIR: every note and file"
[ -z "$SHARES_DIR" ] || [ ! -e "$SHARES_DIR" ] || found "shares|Shares|$SHARES_DIR: every fileshare"
! id "$SERVICE_USER" >/dev/null 2>&1 || found "user|User|the system user $SERVICE_USER"

if [ -z "$FOUND" ]; then
	say "there is no Cloudmorrow server on this machine"
	exit 0
fi

row_label() { printf '%s\n' "$FOUND" | sed -n "s/^$1|\\([^|]*\\)|.*/\\1/p"; }
row_detail() { printf '%s\n' "$FOUND" | sed -n "s/^$1|[^|]*|//p"; }
kinds_found() {
	for kind in $KINDS; do
		! is_found "$kind" || printf '%s\n' "$kind"
	done
}

# --- the choice --------------------------------------------------------------
# CHOSEN is the kinds that go, space-separated. A flag decides it outright;
# otherwise the list is asked on the terminal, with the services ticked.
CHOSEN=""
chose() { case " $CHOSEN " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

if [ -n "$DELETE_DATA" ]; then
	CHOSEN="$(kinds_found | tr '\n' ' ')"
elif [ -n "$REMOVE_FLAG" ]; then
	for kind in $(printf '%s' "$REMOVE_FLAG" | tr ',' ' '); do
		case " $KINDS " in
		*" $kind "*) ;;
		*) die "--remove does not know \"$kind\"; it takes: $(echo $KINDS | sed 's/ /, /g')" ;;
		esac
		! is_found "$kind" || CHOSEN="$CHOSEN $kind"
	done
else
	CHOSEN="services"
fi

# The list of boxes to tick is the one the installer asks with
# (cloudmorrow.checklist), run from the checkout when it is still there.
# Without it, or without a terminal that can draw, a numbered list does.
checklist_python() {
	if [ -x "$PREFIX/venv/bin/python" ] && "$PREFIX/venv/bin/python" -c "import cloudmorrow.checklist" 2>/dev/null; then
		echo "$PREFIX/venv/bin/python"
	elif [ -d "$PREFIX/src" ] && PYTHONPATH="$PREFIX/src" python3 -c "import cloudmorrow.checklist" 2>/dev/null; then
		echo "env PYTHONPATH=$PREFIX/src python3"
	fi
}

ask_with_checklist() {
	python="$1"
	set -- --title "What should go from this machine?"
	for kind in $(kinds_found); do
		set -- "$@" --item "$kind" "$(row_label "$kind")" "$(row_detail "$kind")"
	done
	for kind in $CHOSEN; do
		set -- "$@" --on "$kind"
	done
	status=0
	chosen="$($python -m cloudmorrow.checklist "$@")" || status=$?
	case "$status" in
	0) CHOSEN="$(printf '%s\n' "$chosen" | tr '\n' ' ')" ;;
	130) die "stopped; nothing was removed" ;;
	*) return 1 ;;
	esac
}

ask_with_numbers() {
	printf '\n  \033[1mWhat should go from this machine?\033[0m\n\n' >/dev/tty
	n=0
	for kind in $(kinds_found); do
		n=$((n + 1))
		if chose "$kind"; then box="x"; else box=" "; fi
		printf '    %d  [%s] %-9s %s\n' "$n" "$box" "$(row_label "$kind")" "$(row_detail "$kind")" >/dev/tty
	done
	ticked="$(n=0; for kind in $(kinds_found); do n=$((n + 1)); ! chose "$kind" || printf '%s ' "$n"; done)"
	printf '\n  Type the numbers to remove, separated by spaces; nothing removes nothing.\n' >/dev/tty
	printf '  Numbers [%s]: ' "$(echo $ticked)" >/dev/tty
	read -r answer </dev/tty || answer=""
	[ -n "$answer" ] || answer="$ticked"
	CHOSEN=""
	for number in $answer; do
		kind="$(kinds_found | sed -n "${number}p" 2>/dev/null)" || kind=""
		[ -n "$kind" ] || die "there is no $number in the list; nothing was removed"
		CHOSEN="$CHOSEN $kind"
	done
}

if [ -n "$DRY_RUN" ] || [ -n "$YES" ] || [ -n "$DELETE_DATA" ] || [ -n "$REMOVE_FLAG" ]; then
	:
else
	# On the terminal, not stdin: through `curl | sh` the script itself is stdin.
	( : </dev/tty ) 2>/dev/null || die "nobody to ask; say what goes with --remove, or --yes for the services"
	python="$(checklist_python)"
	if [ -z "$python" ] || ! ask_with_checklist "$python"; then
		ask_with_numbers
	fi
fi

# Only what is there can go: "services" ticked on a machine without the
# units is nothing to do.
CHOSEN="$(for kind in $CHOSEN; do ! is_found "$kind" || printf '%s ' "$kind"; done)"

# A dry run with no choice shows the whole list, so it reads as an inventory.
if [ -n "$DRY_RUN" ] && [ -z "$REMOVE_FLAG" ] && [ -z "$DELETE_DATA" ]; then
	printf '\n  On this machine%s:\n\n' "${CLOUD_NAME:+, the Cloudmorrow server \"$CLOUD_NAME\"}"
	for kind in $(kinds_found); do
		if chose "$kind"; then box="x"; else box=" "; fi
		printf '    [%s] %-9s %s\n' "$box" "$(row_label "$kind")" "$(row_detail "$kind")"
	done
	printf '\n  Ticked is what goes without --remove.\n'
fi

if [ -z "$(echo $CHOSEN)" ]; then
	printf '\n  Nothing ticked: nothing was removed.\n\n'
	exit 0
fi

# Data is anything a later install would pick up again, and the user that
# owns it. Removing it is a different question from removing software.
DATA_GOES=""
for kind in config data notes shares user; do
	! chose "$kind" || DATA_GOES="1"
done

! chose code || check_dir "$PREFIX"
! chose data || check_dir "$DATA_DIR"
! chose notes || check_dir "$NOTES_DIR"
! chose shares || check_dir "$SHARES_DIR"

printf '\n  %sThis removes from this machine:\n\n' "${CLOUD_NAME:+The Cloudmorrow server \"$CLOUD_NAME\". }"
for kind in $(kinds_found); do
	! chose "$kind" || printf '    - %-9s %s\n' "$(row_label "$kind")" "$(row_detail "$kind")"
done
kept=""
for kind in $(kinds_found); do
	chose "$kind" || kept="${kept:+$kept, }$(row_label "$kind" | tr 'A-Z' 'a-z')"
done
if [ -n "$kept" ]; then
	printf '\n  and keeps the %s, so installing again picks up where it was.\n' "$kept"
fi
if [ -n "$DATA_GOES" ]; then
	printf '\n  \033[1mWhat is removed cannot be brought back: accounts, notes, files, secrets.\033[0m\n'
fi
printf '\n'

# --- ask once more --------------------------------------------------------------
if [ -n "$DRY_RUN" ]; then
	:
elif [ -z "$YES" ]; then
	( : </dev/tty ) 2>/dev/null || die "nobody to ask; run it again with --yes"
	if [ -z "$DATA_GOES" ]; then
		printf '\033[1mGo ahead?\033[0m [y/N]: ' >/dev/tty
		read -r answer </dev/tty || answer=""
		case "$answer" in y | Y | yes) ;; *) die "nothing was removed" ;; esac
	else
		printf '\033[1mType "delete" to remove it\033[0m: ' >/dev/tty
		read -r answer </dev/tty || answer=""
		[ "$answer" = "delete" ] || die "nothing was removed"
	fi
fi

# --- the services -----------------------------------------------------------
# The agent first: it reports to the server, so it goes before the server does.
if chose services; then
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

	# The commands, and the rule that lets them run.
	say "removing the commands"
	[ ! -L /usr/local/bin/cloudmorrow-server ] || run rm -f /usr/local/bin/cloudmorrow-server
	if grep -qs "install-server.sh" /usr/local/bin/cloudmorrow-update; then
		run rm -f /usr/local/bin/cloudmorrow-update
	fi
	if grep -qs "install-server.sh" /etc/sudoers.d/cloudmorrow; then
		run rm -f /etc/sudoers.d/cloudmorrow
	fi
fi

# --- the code -----------------------------------------------------------------
if chose code && [ -e "$PREFIX" ]; then
	say "removing the code at $PREFIX"
	run rm -rf "$PREFIX"
fi

# --- the data -------------------------------------------------------------------
remove_dir() {
	if [ -e "$1" ]; then
		say "removing $1"
		run rm -rf "$1"
	fi
}
! chose config || remove_dir "$CONFIG_DIR"
! chose data || remove_dir "$DATA_DIR"
if chose notes; then
	remove_dir "$NOTES_DIR"
	# The installer made /srv/cloudmorrow to hold notes/; empty now, it goes too.
	parent="$(dirname "$NOTES_DIR")"
	if [ "$(basename "$parent")" = "cloudmorrow" ] && [ -d "$parent" ]; then
		run rmdir "$parent" 2>/dev/null || true
	fi
fi
! chose shares || remove_dir "$SHARES_DIR"
if chose user; then
	say "removing the system user $SERVICE_USER"
	run userdel "$SERVICE_USER" || warn "the user $SERVICE_USER is still there; remove it with userdel"
fi

# --- what is left -----------------------------------------------------------------
if [ -n "$DRY_RUN" ]; then
	printf '\n  That was a dry run: nothing was removed.\n\n'
	exit 0
fi
printf '\n  Done.\n'
if chose services; then
	cat <<EOF

  Left for you, because the installer never made them:

    - the reverse proxy's entry for this cloud (Caddy, nginx), if you added one
    - the deploy key on GitHub, if you gave the repository one
    - Cloudmorrow on each computer that used this cloud: run  cm uninstall  there
EOF
fi
if [ -n "$kept" ]; then
	printf '\n  Kept: the %s.\n  Run this again to remove them, or install again to pick up where it was.\n' "$kept"
fi
printf '\n'
