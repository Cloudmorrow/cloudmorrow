"""The MCP server's JSON-RPC: one message in, one answer out, no HTTP in sight.

`/mcp` (routes/mcp.py) reads the body and says who is asking; this answers
what was asked — `initialize`, `ping`, the tools in `mcptools`, and the
empty lists of what this server does not offer — as that person.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cloudmorrow import __version__
from cloudmorrow.server import mcptools
from cloudmorrow.server.db import User

if TYPE_CHECKING:
    from cloudmorrow.server.deps import AppState

__all__ = ["PARSE_ERROR", "PROTOCOL_VERSIONS", "handle_message", "rpc_error", "rpc_result"]

# The protocol revisions this server speaks. A client names the one it
# wants; it gets that one back if it is here, and the newest otherwise.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

# JSON-RPC's own error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


def rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle_message(state: AppState, user: User, message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message in, one out — or nothing, for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return rpc_error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(method, str):
        # A response, or nothing we understand: there is no one to answer.
        return None if "result" in message or "error" in message else rpc_error(
            request_id, INVALID_REQUEST, "no method"
        )
    if request_id is None:
        # A notification. `notifications/initialized` and the like: noted.
        return None
    if not isinstance(params, dict):
        return rpc_error(request_id, INVALID_PARAMS, "params must be an object")
    if method == "initialize":
        wanted = params.get("protocolVersion")
        version = wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return rpc_result(
            request_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "cloudmorrow", "title": "Cloudmorrow", "version": __version__},
                "instructions": mcptools.INSTRUCTIONS,
            },
        )
    if method == "ping":
        return rpc_result(request_id, {})
    if method == "tools/list":
        return rpc_result(
            request_id, {"tools": [tool.to_dict() for tool in mcptools.available(state, user)]}
        )
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or mcptools.find(state, name, user) is None:
            return rpc_error(request_id, INVALID_PARAMS, f"unknown tool: {name!r}")
        return rpc_result(request_id, mcptools.call(state, user, name, params.get("arguments")))
    if method in {"resources/list", "resources/templates/list"}:
        key = "resourceTemplates" if method.endswith("templates/list") else "resources"
        return rpc_result(request_id, {key: []})
    if method == "prompts/list":
        return rpc_result(request_id, {"prompts": []})
    return rpc_error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")
