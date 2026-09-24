#!/bin/sh
# Move a BramCloud install to Cloudmorrow, in place, on the server.
#
#   sudo sh migrate-from-bramcloud.sh --public-url https://cm.hl.bramlabs.io --admin jimmi
#
# Everything was renamed at once — the package, the commands, the paths, the
# environment variables, the units — so an old install carries on as BramCloud
# until it is moved. This stops the old units, moves the config, data and
# checkout to their new names, renames the system user, rewrites the paths in
# the config, fetches the renamed code, and hands over to install-server.sh,
# which writes the new unit, updater and sudoers file and rebuilds the venv.
#
# The database and the signing, secrets and VAPID keys move with the data
# directory: accounts, tokens, secrets and push subscriptions all survive.
# Notes stay where notes_dir points. Run it once; a second run finds nothing
# left to move and just reinstalls.
set -eu

OLD="bramcloud"
NEW="cloudmorrow"
OLD_PREFIX="/opt/$OLD"
NEW_PREFIX="/opt/$NEW"
OLD_DATA="/var/lib/$OLD"
NEW_DATA="/var/lib/$NEW"
OLD_CONFIG_DIR="/etc/$OLD"
NEW_CONFIG_DIR="/etc/$NEW"
BRANCH="main"
PUBLIC_URL=""
ADMIN_USER="${SUDO_USER:-}"
OLD_URL="https://bramcloud.hl.bramlabs.io"

while [ $# -gt 0 ]; do
	case "$1" in
	--public-url) PUBLIC_URL="$2"; shift 2 ;;
	--old-url) OLD_URL="$2"; shift 2 ;;
	--admin) ADMIN_USER="$2"; shift 2 ;;
	--branch) BRANCH="$2"; shift 2 ;;
	-h | --help) sed -n '2,15p' "$0"; exit 0 ;;
	*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

say() { printf '\033[36m::\033[0m %s\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "run this with sudo"
[ -n "$PUBLIC_URL" ] || die "say where the server lives: --public-url https://cm.hl.bramlabs.io"

# --- stop the old units ----------------------------------------------------
for unit in $OLD-agent $OLD; do
	if systemctl list-unit-files "$unit.service" >/dev/null 2>&1; then
		say "stopping $unit"
		systemctl disable --now "$unit" 2>/dev/null || true
	fi
done

# --- move things to their new names ---------------------------------------
move() {
	if [ -e "$1" ] && [ ! -e "$2" ]; then
		say "moving $1 -> $2"
		mv "$1" "$2"
	fi
}
move "$OLD_CONFIG_DIR" "$NEW_CONFIG_DIR"
move "$OLD_DATA" "$NEW_DATA"
move "$NEW_DATA/$OLD.db" "$NEW_DATA/$NEW.db"
move "$OLD_PREFIX" "$NEW_PREFIX"

if id "$OLD" >/dev/null 2>&1; then
	say "renaming the system user $OLD -> $NEW"
	usermod --login "$NEW" --home "$NEW_DATA" "$OLD"
	groupmod --new-name "$NEW" "$OLD" 2>/dev/null || true
fi

# --- the config, with its paths and its address rewritten -------------------
for toml in "$NEW_CONFIG_DIR"/server.toml "$NEW_CONFIG_DIR"/agent.toml; do
	[ -f "$toml" ] || continue
	say "rewriting the paths in $toml"
	sed -i \
		-e "s#$OLD_CONFIG_DIR#$NEW_CONFIG_DIR#g" \
		-e "s#$OLD_DATA#$NEW_DATA#g" \
		-e "s#$OLD_PREFIX#$NEW_PREFIX#g" \
		-e "s#$OLD\.db#$NEW.db#g" \
		-e "s#$OLD_URL#$PUBLIC_URL#g" \
		"$toml"
done
CONFIG="$NEW_CONFIG_DIR/server.toml"
[ -f "$CONFIG" ] || die "no $CONFIG — was BramCloud installed here?"
NOTES_DIR="$(sed -n 's/^notes_dir *= *"\(.*\)"/\1/p' "$CONFIG" | head -1)"
[ -n "$NOTES_DIR" ] || die "no notes_dir in $CONFIG"

# --- the old venv, unit, updater and sudoers ------------------------------
# The venv's scripts carry the old path in their shebangs and the old package
# name in their metadata; install-server.sh makes a fresh one.
if [ -d "$NEW_PREFIX/venv" ]; then
	say "removing the old virtualenv (rebuilt below)"
	rm -rf "$NEW_PREFIX/venv"
fi
say "removing the old unit files, updater and sudoers rule"
rm -f "/etc/systemd/system/$OLD.service" "/etc/systemd/system/$OLD-agent.service" \
	"/usr/local/bin/$OLD-update" "/usr/local/bin/$OLD-server" "/etc/sudoers.d/$OLD"
rm -rf "/etc/systemd/system/$OLD.service.d"
systemctl daemon-reload

# --- the renamed code ------------------------------------------------------
# The checkout is still the old code, whose installer would write the old
# names back. Fetch the branch first, with the deploy key that moved with the
# data directory, then run the installer that came with it.
SRC="$NEW_PREFIX/src"
[ -d "$SRC/.git" ] || die "no checkout at $SRC"
KEY="$NEW_DATA/.ssh/id_ed25519"
GIT_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$NEW_DATA/.ssh/known_hosts"
say "fetching $BRANCH into $SRC"
sudo -u "$NEW" -H env GIT_SSH_COMMAND="$GIT_SSH" git -C "$SRC" fetch --quiet origin "$BRANCH"
sudo -u "$NEW" -H git -C "$SRC" checkout --quiet "$BRANCH"
sudo -u "$NEW" -H git -C "$SRC" reset --hard --quiet "origin/$BRANCH"
[ -f "$SRC/deploy/install-server.sh" ] || die "the fetched code has no deploy/install-server.sh"
grep -q "$NEW" "$SRC/deploy/install-server.sh" || die "the fetched code is not yet Cloudmorrow"

say "handing over to install-server.sh"
exec sh "$SRC/deploy/install-server.sh" \
	--repo "$(sudo -u "$NEW" -H git -C "$SRC" remote get-url origin)" \
	--branch "$BRANCH" \
	--prefix "$NEW_PREFIX" \
	--data-dir "$NEW_DATA" \
	--notes-dir "$NOTES_DIR" \
	--public-url "$PUBLIC_URL" \
	--ssh-key "$KEY" \
	${ADMIN_USER:+--admin "$ADMIN_USER"}
