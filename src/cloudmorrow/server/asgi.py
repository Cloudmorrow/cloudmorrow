"""ASGI entry point: `uvicorn cloudmorrow.server.asgi:app`."""

from __future__ import annotations

from cloudmorrow.server.app import create_app

app = create_app()
