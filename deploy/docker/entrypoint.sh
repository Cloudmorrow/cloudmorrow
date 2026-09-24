#!/bin/sh
# Container entrypoint: put the image's client wheel where the server hands
# it out from, then run whatever the command is (`cloudmorrow-server serve`).
set -eu

DATA_DIR="${CLOUDMORROW_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/dist"

# The server serves the newest wheel in <data_dir>/dist to /install.sh. The
# image carries the one it was built from; a new image brings a new wheel,
# and the old one goes so the newest is the only one.
for wheel in /opt/cloudmorrow/dist/*.whl; do
	[ -f "$wheel" ] || continue
	name="$(basename "$wheel")"
	if [ ! -f "$DATA_DIR/dist/$name" ]; then
		rm -f "$DATA_DIR/dist"/*.whl
		cp "$wheel" "$DATA_DIR/dist/$name"
	fi
done

exec "$@"
