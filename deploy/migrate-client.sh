#!/bin/sh
# Move this machine's BramCloud client to Cloudmorrow.
#
#   sh migrate-client.sh https://cm.hl.bramlabs.io
#
# Keeps your sign-in and the directory -> project links by moving the config
# directory to its new name, installs the renamed client from the server
# (which enrols the agent again under its new name), and retires the old
# command, venv and user unit. Linux, as yourself — no sudo.
set -eu

URL="${1:-https://cm.hl.bramlabs.io}"
OLD_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/bramcloud"
NEW_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/cloudmorrow"
OLD_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/bramcloud"
BIN="$HOME/.local/bin"

say() { printf '\033[36m::\033[0m %s\n' "$*"; }

# --- the old agent, if it runs as a user service ---------------------------
if command -v systemctl >/dev/null 2>&1; then
	say "stopping the old bramcloud-agent user service"
	systemctl --user disable --now bramcloud-agent 2>/dev/null || true
	rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/bramcloud-agent.service"
	systemctl --user daemon-reload 2>/dev/null || true
fi

# --- the sign-in and the project links, under the new name ----------------
if [ -d "$OLD_CONFIG" ] && [ ! -d "$NEW_CONFIG" ]; then
	say "moving $OLD_CONFIG -> $NEW_CONFIG"
	mv "$OLD_CONFIG" "$NEW_CONFIG"
fi
if [ -f "$NEW_CONFIG/config.toml" ]; then
	say "pointing the client at $URL"
	sed -i -e "s#^api_url = .*#api_url = \"$URL\"#" "$NEW_CONFIG/config.toml"
fi

# --- the new client ---------------------------------------------------------
say "installing the cloudmorrow client from $URL"
curl -fsSL "$URL/install.sh" | sh

# --- the old one -------------------------------------------------------------
say "removing the old bramcloud client"
rm -rf "$OLD_DATA"
rm -f "$BIN/bramcloud" "$BIN/bc" "$BIN/bramcloud-agent"

cat <<EOF

  Done. \`cloudmorrow\` (or \`cm\`) is the command now. Sign in once more —

    cloudmorrow login

  — and the local agent is set up again under its new name as part of it.

EOF
