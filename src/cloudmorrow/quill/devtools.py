"""What `cm quill preview` and `cm quill dev --local` run, in the Quill's own environment.

`cm` on a laptop has no server in it; a Quill's development environment
does (the template's pyproject.toml asks for `cloudmorrow[server]`), so
`cm` runs these there:

    python -m cloudmorrow.quill.devtools preview . garage [--as sam] [--sandbox]
    python -m cloudmorrow.quill.devtools serve . [--port 8799] [--no-sandbox]

`preview` draws one view as text, from a harness with nothing in it but
the Quill's datasets. `serve` is a throwaway server on this machine: a
temporary folder, the Quill installed from the folder and installed again
whenever a file in it changes, and two people to sign in as — you, an
administrator, and sam, who may read everything and change nothing — so
the Quill is seen as somebody in a smaller circle sees it too.
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

SKIP = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}


def _stamp(folder: Path) -> tuple:
    stamps = []
    for path in sorted(folder.rglob("*")):
        if SKIP & set(path.relative_to(folder).parts) or not path.is_file():
            continue
        stamps.append((str(path), path.stat().st_mtime_ns))
    return tuple(stamps)


def preview(folder: Path, screen: str, *, user: str, sandbox: bool) -> int:
    from cloudmorrow.quill.testing import Harness

    with Harness(folder, sandbox=sandbox) as q:
        if user != q.user:
            q = q.as_user(user)
        views = [s["id"] for s in q.manifest.screens if s["kit"] == "view"]
        if not screen:
            if not views:
                print(f"{q.manifest.name} has no views; its kit screens are previewed by `cm quill check`")
                return 1
            screen = views[0]
        if screen not in views:
            print(f"{screen} is not one of its views: {', '.join(views) or 'it has none'}")
            return 1
        print(q.view(screen).text(), end="")
    return 0


def _lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # nothing is sent: this only picks the route
            return probe.getsockname()[0]
    except OSError:
        return ""


def serve(folder: Path, *, port: int, sandbox: bool, host: str) -> int:
    import uvicorn

    from cloudmorrow.client.config import ClientConfig, StoredCredentials
    from cloudmorrow.quill.testing import datamodels_folder
    from cloudmorrow.server.app import create_app
    from cloudmorrow.server.config import ServerConfig
    from cloudmorrow.server.db import UserStore
    from cloudmorrow.server.quills import QuillError
    from cloudmorrow.server.quills import jobs as quilljobs
    from cloudmorrow.server.security import create_access_token, hash_password

    base = Path(tempfile.mkdtemp(prefix="quill-dev-"))
    config = ServerConfig(
        notes_dir=base / "notes",
        data_dir=base / "data",
        secret_key=secrets.token_urlsafe(48),
        host=host,
        port=port,
        quill_code="sandbox" if sandbox else "trusted",
        allow_api_update=False,
    )
    config.ensure_dirs()
    users = UserStore(config.database())
    you = os.environ.get("USER", "you").lower() or "you"
    password = secrets.token_urlsafe(9)
    users.create(you, hash_password(password), is_admin=True)
    users.create("sam", hash_password(password))
    # Only this Quill: none of the catalog's own, which a fresh server would fetch.
    for key in (
        quilljobs.SEEDED,
        quilljobs.SECRETS_QUILL,
        quilljobs.FILES_QUILL,
        quilljobs.LEGACY_TASKS,
        quilljobs.LEGACY_CALENDAR,
        quilljobs.LEGACY_CHAT,
        *(quilljobs.adopted_key(q) for q in quilljobs.MOVED_BUILTINS),
    ):
        quilljobs.write_meta(config.database(), key, "0")
    app = create_app(config)
    state = app.state.cloudmorrow
    if sandbox:
        from cloudmorrow import sandbox as _sandbox

        runtime = _sandbox.ensure_runtime(_sandbox.runtime_dir())
        (config.data_dir / "sandbox").symlink_to(runtime.parent, target_is_directory=True)
    visitors = state.circles.create("Visitors", rules={"*": "read"})
    for circle in state.circles.circles_of("sam"):
        if circle.id != visitors.id:
            state.circles.leave(circle.id, "sam")
    state.circles.join(visitors.id, "sam")
    models = datamodels_folder()

    def install() -> bool:
        try:
            plan = state.quills.install(folder, models, origin={"installed_by": you})
        except QuillError as exc:
            print(f"✗ {exc}", flush=True)
            return False
        print(f"✓ {plan['name']} {plan['version']} installed", flush=True)
        return True

    install()
    # `cm` in another terminal, signed in here and nowhere else.
    client_dir = base / "client"
    os.environ["CLOUDMORROW_CONFIG_DIR"] = str(client_dir)
    url = f"http://127.0.0.1:{port}"
    ClientConfig(api_url=url, allow_insecure_http=True).save()
    issued = create_access_token(you, config.secret_key, config.token_ttl_hours)
    StoredCredentials(api_url=url, username=you, access_token=issued.token).save()

    lan = _lan_address() if host == "0.0.0.0" else ""
    print(f"\n  web app   {url}" + (f"   (phone on this Wi-Fi: http://{lan}:{port})" if lan else ""))
    print(f"  sign in   {you} or sam, password {password}")
    print(f"  terminal  CLOUDMORROW_CONFIG_DIR={client_dir} cm")
    print(f"  code      {'in the sandbox, as a server runs it' if sandbox else 'in this Python, no sandbox'}")
    print("  Ctrl-C stops it and forgets everything\n", flush=True)

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    stamp = _stamp(folder)
    try:
        while thread.is_alive():
            time.sleep(1.0)
            now = _stamp(folder)
            if now != stamp:
                stamp = now
                install()
    except KeyboardInterrupt:
        server.should_exit = True
        thread.join(timeout=10)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cloudmorrow.quill.devtools")
    commands = parser.add_subparsers(dest="command", required=True)
    shown = commands.add_parser("preview")
    shown.add_argument("folder")
    shown.add_argument("screen", nargs="?", default="")
    shown.add_argument("--as", dest="user", default="alice")
    shown.add_argument("--sandbox", action="store_true")
    served = commands.add_parser("serve")
    served.add_argument("folder")
    served.add_argument("--port", type=int, default=8799)
    served.add_argument("--host", default="0.0.0.0")
    served.add_argument("--no-sandbox", action="store_true")
    args = parser.parse_args(argv)
    folder = Path(args.folder).resolve()
    if args.command == "preview":
        return preview(folder, args.screen, user=args.user, sandbox=args.sandbox)
    return serve(folder, port=args.port, sandbox=not args.no_sandbox, host=args.host)


if __name__ == "__main__":
    sys.exit(main())
