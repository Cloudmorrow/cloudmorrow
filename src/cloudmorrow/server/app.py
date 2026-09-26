"""FastAPI application factory."""

from __future__ import annotations

from functools import partial

from a2wsgi import WSGIMiddleware
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse

from cloudmorrow import __version__
from cloudmorrow.server.access import is_allowed, parse_rules
from cloudmorrow.server.agents import AgentStore, JobStore
from cloudmorrow.server.chat import ChatStore
from cloudmorrow.server.config import ServerConfig, load_config
from cloudmorrow.server.configsync import ConfigStore
from cloudmorrow.server.dav import MOUNT_PATH, CredentialCheck, build_dav_app
from cloudmorrow.server.db import UserStore
from cloudmorrow.server.deps import AppState
from cloudmorrow.server.drive import user_drive
from cloudmorrow.server.features import Feature, FeatureStore
from cloudmorrow.server.mcp import MCPStore
from cloudmorrow.server.notifications import NotificationStore
from cloudmorrow.server.quilljobs import Clock
from cloudmorrow.server.quills import QuillRegistry
from cloudmorrow.server.records import RecordStore
from cloudmorrow.server import spacenotify
from cloudmorrow.server.backends import NotesBackend
from cloudmorrow.server.routes import (
    agents,
    auth,
    chat,
    configsync,
    features,
    install,
    mcp,
    notes,
    notifications,
    push,
    quills,
    records,
    secrets,
    setup,
    sharefiles,
    shares,
    today,
    users,
    web,
)
from cloudmorrow.server.routes import (
    server as server_routes,
)
from cloudmorrow.server.sealed import seal_tree, use_key
from cloudmorrow.server.secrets import SecretStore
from cloudmorrow.server.settings import SettingsStore
from cloudmorrow.server.shares import ShareStore
from cloudmorrow.server.today import Weather
from cloudmorrow.server.transport import install as require_tls
from cloudmorrow.server.update import deployed_commit
from cloudmorrow.server.webpush import PushStore, default_subject


def create_app(config: ServerConfig | None = None) -> FastAPI:
    config = config or load_config()
    config.ensure_dirs()
    config.ensure_secret_key()

    app = FastAPI(
        title="Cloudmorrow",
        version=__version__,
        summary="Cloudmorrow API — your data, the apps around it, and the machines.",
    )
    # The key, before the first connection: every store seals through it.
    sealer = use_key(config.db_path, config.secrets_key_path)
    user_store = UserStore(config.db_path)
    # Notes written before they were sealed. Idempotent, and quick once done.
    for user in user_store.list():
        seal_tree(config.notes_root(user.username), sealer)
    share_store = ShareStore(config.db_path, config.shares_root)
    # Shares made when each account had its own shares folder come into the
    # one Shares folder, so there is one place to look.
    share_store.relocate()
    credential_check = CredentialCheck(user_store, config.ensure_secret_key())
    # What is installed, and the one table every Quill's records live in.
    quill_registry = QuillRegistry(config.quills_dir, config.datamodels_dir, config.quill_catalog)
    record_store = RecordStore(config.db_path, quill_registry.models, quill_registry.expiries)
    app.state.cloudmorrow = AppState(
        config=config,
        users=user_store,
        agents=AgentStore(config.db_path),
        jobs=JobStore(config.db_path),
        secrets=SecretStore(config.db_path, sealer.master),
        config_sync=ConfigStore(config.db_path),
        notifications=NotificationStore(config.db_path),
        # Each installed Quill is one more thing to switch, at both levels.
        features=FeatureStore(
            config.db_path,
            lambda: (
                Feature(q.id, q.name, q.summary, tuple(sorted(q.models)))
                for q in quill_registry.quills.values()
            ),
        ),
        chat=ChatStore(config.db_path),
        push=PushStore(
            config.db_path,
            config.vapid_key_path,
            subject=config.push_subject or default_subject(config.public_url),
        ),
        shares=share_store,
        mcp=MCPStore(config.db_path),
        weather=Weather(config.weather_place),
        credential_check=credential_check,
        sealer=sealer,
        settings=SettingsStore(config.db_path),
        quills=quill_registry,
        records=record_store,
    )
    # The foundation Quills on a fresh server, old tasks into records, and
    # the sweeps: on a thread, once the server is up, so none of it can
    # keep it from starting.
    # What happens in shared spaces reaches the people in them.
    spacenotify.install(app.state.cloudmorrow)
    # Datamodels that live where they always have, served as records.
    record_store.backends["notes"] = NotesBackend(
        lambda username: app.state.cloudmorrow.note_store(user_store.require(username))
    )
    clock = Clock(config.db_path, quill_registry, record_store)
    app.router.on_startup.append(clock.start)
    app.router.on_shutdown.append(clock.stop)

    require_tls(app, config)
    allowed_clients = parse_rules(config.allowed_client_ips)
    if allowed_clients:

        @app.middleware("http")
        async def restrict_clients(request: Request, call_next):
            """Answer only the hosts named in allowed_client_ips."""
            client = request.client.host if request.client else None
            if not is_allowed(client, allowed_clients):
                return PlainTextResponse("forbidden", status_code=403)
            return await call_next(request)

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # A feature that is switched off answers 403 everywhere it lives, so the
    # guard goes on the routers rather than inside each of their endpoints.
    # Both share routers are the Files tab.
    in_files = [Depends(features.require_feature("files"))]

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(today.router)
    app.include_router(features.router)
    app.include_router(features.mine_router)
    app.include_router(features.types_router)
    app.include_router(notes.router, dependencies=[Depends(features.require_feature("notes"))])
    app.include_router(
        secrets.router, dependencies=[Depends(features.require_feature("secrets"))]
    )
    app.include_router(records.router)
    app.include_router(records.models_router)
    app.include_router(records.people_router)
    app.include_router(quills.router)
    app.include_router(shares.router, dependencies=in_files)
    app.include_router(sharefiles.router, dependencies=in_files)
    app.include_router(agents.router)
    app.include_router(agents.agent_router)
    app.include_router(configsync.router)
    app.include_router(configsync.agent_router)
    app.include_router(notifications.router)
    app.include_router(notifications.agent_router)
    app.include_router(chat.router, dependencies=[Depends(features.require_feature("chat"))])
    app.include_router(push.router)
    # Assistants: the OAuth pages and the MCP endpoint.
    app.include_router(mcp.router)
    # Before the web router: its /app/{filename} would otherwise match
    # /app/sw.js and serve the service worker with a year of caching.
    app.include_router(push.worker_router)
    app.include_router(setup.router)
    app.include_router(install.router)
    app.include_router(web.router)
    app.include_router(server_routes.router)

    # The fileshares, spoken WebDAV. A WSGI app, because that is what WsgiDAV
    # is; a2wsgi streams bodies through rather than buffering a whole upload.
    @app.get(MOUNT_PATH, include_in_schema=False)
    def dav_root() -> RedirectResponse:
        return RedirectResponse(MOUNT_PATH + "/", status_code=307)

    app.mount(
        MOUNT_PATH,
        WSGIMiddleware(
            build_dav_app(share_store, credential_check, partial(user_drive, config))
        ),
        name="dav",
    )

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        state: AppState = app.state.cloudmorrow
        return {
            "status": "ok",
            "service": "cloudmorrow",
            "name": state.cloud_name(),
            # True until the first account exists: a client that lands on a
            # fresh server can send the person to /setup instead of a login.
            "setup": state.users.count() == 0,
            "version": __version__,
            # The version does not move between commits, so this is the only
            # honest answer to "is my deploy live yet".
            "commit": deployed_commit(),
            "users": state.users.count(),
        }

    return app
