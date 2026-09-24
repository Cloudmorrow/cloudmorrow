"""An assistant signing in over OAuth and working in Cloudmorrow over MCP.

The walk a client like Claude takes, end to end: find the server's
metadata, register, send the person to the sign-in page, trade the code
for tokens, and call tools as that person. Then the person's side of it —
seeing the connection and cutting it off — and what a switched-off
feature does to the tools.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest

from cloudmorrow.server.mcp import Client
from tests.conftest import ADMIN, GUEST, token_for

CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def register(client, name: str = "Claude", **extra) -> dict:
    response = client.post(
        "/oauth/register",
        json={
            "client_name": name,
            "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorize(client, registered: dict, who=ADMIN, *, challenge: str, decision: str = "allow"):
    """Sign in on the consent page. Returns the redirect the browser would follow."""
    return client.post(
        "/oauth/authorize",
        data={
            "client_id": registered["client_id"],
            "redirect_uri": CALLBACK,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "response_type": "code",
            "scope": "cloudmorrow",
            "username": who[0],
            "password": who[1],
            "decision": decision,
        },
        follow_redirects=False,
    )


def redirected_query(response) -> dict[str, str]:
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    assert location.startswith(CALLBACK + "?")
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


def connect(client, who=ADMIN) -> dict:
    """The whole dance, for the tests that only want a token at the end."""
    registered = register(client)
    verifier, challenge = pkce()
    code = redirected_query(authorize(client, registered, who, challenge=challenge))["code"]
    exchanged = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "client_id": registered["client_id"],
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return {**exchanged.json(), "client_id": registered["client_id"]}


def rpc(client, token: str, method: str, params: dict | None = None, *, id: int = 1):
    message: dict = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        message["params"] = params
    return client.post("/mcp", json=message, headers={"Authorization": f"Bearer {token}"})


def call(client, token: str, tool: str, **arguments) -> dict:
    response = rpc(client, token, "tools/call", {"name": tool, "arguments": arguments})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]


# -- discovery -------------------------------------------------------------------
def test_an_unauthenticated_call_points_at_the_metadata(client):
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'resource_metadata="http://testserver/.well-known/oauth-protected-resource"' in challenge


def test_the_metadata_names_this_server_as_its_own_authorization_server(client):
    resource = client.get("/.well-known/oauth-protected-resource").json()
    assert resource["resource"] == "http://testserver/mcp"
    assert resource["authorization_servers"] == ["http://testserver"]
    # The path-suffixed form too, which is what the 2025-06-18 clients ask for.
    assert client.get("/.well-known/oauth-protected-resource/mcp").json() == resource
    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == "http://testserver"
    assert server["authorization_endpoint"] == "http://testserver/oauth/authorize"
    assert server["token_endpoint"] == "http://testserver/oauth/token"
    assert server["registration_endpoint"] == "http://testserver/oauth/register"
    assert "S256" in server["code_challenge_methods_supported"]
    assert "none" in server["token_endpoint_auth_methods_supported"]


def test_public_url_wins_over_the_request_host(config, users):
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app

    config.public_url = "https://cloudmorrow.example.net/"
    with TestClient(create_app(config)) as proxied:
        server = proxied.get("/.well-known/oauth-authorization-server").json()
        assert server["issuer"] == "https://cloudmorrow.example.net"
        resource = proxied.get("/.well-known/oauth-protected-resource").json()
        assert resource["resource"] == "https://cloudmorrow.example.net/mcp"


# -- registration ----------------------------------------------------------------
def test_a_public_client_registers_and_gets_no_secret(client):
    registered = register(client)
    assert registered["client_id"]
    assert "client_secret" not in registered
    assert registered["redirect_uris"] == [CALLBACK]
    assert registered["token_endpoint_auth_method"] == "none"


def test_a_confidential_client_gets_a_secret_it_must_present(client):
    registered = register(client, token_endpoint_auth_method="client_secret_post")
    assert registered["client_secret"]
    verifier, challenge = pkce()
    code = redirected_query(authorize(client, registered, challenge=challenge))["code"]
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CALLBACK,
        "client_id": registered["client_id"],
        "code_verifier": verifier,
    }
    without = client.post("/oauth/token", data=body)
    assert without.status_code == 401
    assert without.json()["error"] == "invalid_client"


def test_a_code_may_only_be_sent_somewhere_safe(client):
    refused = client.post(
        "/oauth/register",
        json={"client_name": "Sneaky", "redirect_uris": ["http://evil.example/cb"]},
    )
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_redirect_uri"
    loopback = client.post(
        "/oauth/register",
        json={"client_name": "Claude Code", "redirect_uris": ["http://localhost:3000/callback"]},
    )
    assert loopback.status_code == 201


def test_a_loopback_redirect_matches_on_any_port():
    registered = Client("id", "x", ("http://127.0.0.1:3000/callback",), False, "")
    assert registered.allows_redirect("http://127.0.0.1:51234/callback")
    assert not registered.allows_redirect("http://127.0.0.1:51234/other")
    assert not registered.allows_redirect("http://example.com:3000/callback")
    exact = Client("id", "x", (CALLBACK,), False, "")
    assert exact.allows_redirect(CALLBACK)
    assert not exact.allows_redirect(CALLBACK + "x")


# -- the sign-in page --------------------------------------------------------------
def test_the_consent_page_says_who_is_asking(client):
    registered = register(client, "Claude Desktop")
    _, challenge = pkce()
    page = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered["client_id"],
            "redirect_uri": CALLBACK,
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert page.status_code == 200
    assert "Claude Desktop" in page.text
    assert "wants to use Cloudmorrow as you" in page.text
    # The request travels through the form, so a POST can check it again.
    assert f'name="code_challenge" value="{challenge}"' in page.text


def test_an_unknown_client_or_redirect_gets_a_page_not_a_redirect(client):
    registered = register(client)
    _, challenge = pkce()
    unknown = client.get(
        "/oauth/authorize",
        params={"client_id": "nope", "redirect_uri": CALLBACK, "code_challenge": challenge},
    )
    assert unknown.status_code == 400
    assert "Unknown client" in unknown.text
    elsewhere = client.get(
        "/oauth/authorize",
        params={
            "client_id": registered["client_id"],
            "redirect_uri": "https://evil.example/cb",
            "code_challenge": challenge,
        },
    )
    assert elsewhere.status_code == 400
    assert "did not register" in elsewhere.text


def test_pkce_is_required(client):
    registered = register(client)
    response = client.get(
        "/oauth/authorize",
        params={"client_id": registered["client_id"], "redirect_uri": CALLBACK, "state": "s"},
        follow_redirects=False,
    )
    query = redirected_query(response)
    assert query["error"] == "invalid_request"
    assert query["state"] == "s"


def test_a_wrong_password_stays_on_the_page(client):
    registered = register(client)
    _, challenge = pkce()
    response = authorize(client, registered, ("bram", "wrong-password"), challenge=challenge)
    assert response.status_code == 401
    assert "Wrong username or password" in response.text
    assert 'value="bram"' in response.text


def test_cancel_sends_the_client_away_with_no_code(client):
    registered = register(client)
    _, challenge = pkce()
    query = redirected_query(authorize(client, registered, challenge=challenge, decision="deny"))
    assert query == {"error": "access_denied", "state": "xyz"}


# -- the token endpoint ----------------------------------------------------------------
def test_the_code_is_traded_once_and_only_with_the_verifier(client):
    registered = register(client)
    verifier, challenge = pkce()
    query = redirected_query(authorize(client, registered, challenge=challenge))
    assert query["state"] == "xyz"
    body = {
        "grant_type": "authorization_code",
        "code": query["code"],
        "redirect_uri": CALLBACK,
        "client_id": registered["client_id"],
    }
    wrong = client.post("/oauth/token", data={**body, "code_verifier": "not-the-one"})
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"
    # And that attempt spent the code: the right verifier is too late now.
    right = client.post("/oauth/token", data={**body, "code_verifier": verifier})
    assert right.status_code == 400


def test_tokens_come_back_and_refresh_rotates_them(client):
    tokens = connect(client)
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"].startswith("bcm_")
    assert tokens["refresh_token"].startswith("bcr_")
    assert tokens["expires_in"] > 0
    refreshed = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    fresh = refreshed.json()
    assert fresh["access_token"] != tokens["access_token"]
    # The old pair is gone; the new one works.
    again = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )
    assert again.status_code == 400
    assert rpc(client, tokens["access_token"], "ping").status_code == 401
    assert rpc(client, fresh["access_token"], "ping").status_code == 200


def test_a_json_token_request_works_too(client):
    registered = register(client)
    verifier, challenge = pkce()
    code = redirected_query(authorize(client, registered, challenge=challenge))["code"]
    exchanged = client.post(
        "/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": CALLBACK,
            "client_id": registered["client_id"],
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text


# -- MCP ---------------------------------------------------------------------------------
def test_initialize_answers_with_the_version_asked_for(client):
    token = connect(client)["access_token"]
    response = rpc(
        client, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}
    )
    result = response.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "cloudmorrow"
    assert "tools" in result["capabilities"]
    assert "notes" in result["instructions"]
    # An unknown one gets the newest we speak, not an error.
    result = rpc(client, token, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
    assert result["protocolVersion"] == "2025-11-25"


def test_a_notification_is_accepted_and_not_answered(client):
    token = connect(client)["access_token"]
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 202
    assert response.content == b""


def test_the_tools_are_listed_with_schemas(client):
    token = connect(client)["access_token"]
    tools = rpc(client, token, "tools/list").json()["result"]["tools"]
    by_name = {tool["name"]: tool for tool in tools}
    assert {"create_note", "read_note", "create_task", "move_task"} <= set(by_name)
    assert by_name["create_note"]["inputSchema"]["required"] == ["path"]
    assert by_name["create_note"]["description"]


def test_an_assistant_writes_a_note_as_the_person(client, auth):
    token = connect(client)["access_token"]
    result = call(
        client, token, "create_note", path="ideas/garden", content="# Garden\n\n- beans\n"
    )
    assert "isError" not in result
    assert result["structuredContent"]["path"] == "ideas/garden.md"
    # It is a real note, where the person's own client sees it.
    note = client.get("/api/notes/file/ideas/garden.md", headers=auth)
    assert note.status_code == 200
    assert note.json()["content"] == "# Garden\n\n- beans\n"
    call(client, token, "append_to_note", path="ideas/garden", text="- peas")
    assert client.get("/api/notes/file/ideas/garden.md", headers=auth).json()["content"] == (
        "# Garden\n\n- beans\n- peas\n"
    )
    listed = call(client, token, "list_notes", previews=True)["structuredContent"]
    assert [e["path"] for e in listed["entries"]] == ["ideas", "ideas/garden.md"]
    found = call(client, token, "search_notes", query="peas")["structuredContent"]
    assert found["results"][0]["path"] == "ideas/garden.md"


def test_writing_over_a_changed_note_is_refused(client, auth):
    token = connect(client)["access_token"]
    call(client, token, "create_note", path="log", content="one\n")
    read = call(client, token, "read_note", path="log")["structuredContent"]
    client.put("/api/notes/file/log.md", headers=auth, json={"content": "two\n"})
    stale = call(client, token, "write_note", path="log", content="three\n", rev=read["rev"])
    assert stale["isError"] is True
    assert "changed since it was read" in stale["content"][0]["text"]


def test_an_assistant_adds_a_task_to_the_only_board(client, auth):
    token = connect(client)["access_token"]
    created = call(client, token, "create_task", title="Water the beans")["structuredContent"]
    assert created["lane"] == "todo"
    boards = client.get("/api/boards", headers=auth).json()
    assert len(boards) == 1
    listed = client.get(f"/api/boards/{boards[0]['slug']}/tasks", headers=auth).json()
    assert [task["title"] for task in listed] == ["Water the beans"]
    moved = call(client, token, "move_task", id=created["id"], lane="done")["structuredContent"]
    assert moved["lane"] == "done"
    everything = call(client, token, "list_tasks")["structuredContent"]
    assert everything["boards"][0]["tasks"][0]["lane"] == "done"


def test_with_two_boards_the_assistant_has_to_say_which(client):
    token = connect(client)["access_token"]
    call(client, token, "list_boards")
    call(client, token, "create_board", title="Garden")
    refused = call(client, token, "create_task", title="Dig")
    assert refused["isError"] is True
    assert "say which board" in refused["content"][0]["text"]
    assert "garden" in refused["content"][0]["text"]
    fine = call(client, token, "create_task", title="Dig", board="garden")
    assert fine["structuredContent"]["board"] == "garden"


def test_a_tool_that_cannot_do_it_says_so_without_a_protocol_error(client):
    token = connect(client)["access_token"]
    missing = call(client, token, "read_note", path="nowhere")
    assert missing["isError"] is True
    unknown = rpc(client, token, "tools/call", {"name": "launch_rockets", "arguments": {}})
    assert unknown.json()["error"]["code"] == -32602
    nonsense = rpc(client, token, "what/ever")
    assert nonsense.json()["error"]["code"] == -32601
    bad = client.post("/mcp", content=b"{not json", headers={"Authorization": f"Bearer {token}"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == -32700


def test_no_stream_and_no_sessions(client):
    token = connect(client)["access_token"]
    assert client.get("/mcp", headers={"Authorization": f"Bearer {token}"}).status_code == 405
    assert client.delete("/mcp", headers={"Authorization": f"Bearer {token}"}).status_code == 405


def test_an_ordinary_access_token_opens_mcp_too(client, auth):
    """For wiring a client up by hand, without the OAuth dance."""
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=auth
    )
    assert response.status_code == 200
    assert response.json()["result"] == {}


def test_an_mcp_token_opens_nothing_but_mcp(client):
    token = connect(client)["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/notes/tree", headers=headers).status_code == 401
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_each_person_gets_their_own_data(client):
    bram = connect(client, ADMIN)["access_token"]
    guest = connect(client, GUEST)["access_token"]
    call(client, bram, "create_note", path="private", content="mine\n")
    assert call(client, guest, "read_note", path="private")["isError"] is True
    assert call(client, guest, "list_notes")["structuredContent"]["entries"] == []


# -- the person's side ------------------------------------------------------------------
def test_connections_are_listed_and_can_be_cut_off(client, auth):
    tokens = connect(client)
    listed = client.get("/api/mcp/connections", headers=auth).json()
    assert len(listed) == 1
    assert listed[0]["client_name"] == "Claude"
    assert listed[0]["created_at"]
    # Somebody else's list does not have it.
    guest_auth = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/mcp/connections", headers=guest_auth).json() == []
    assert (
        client.delete(f"/api/mcp/connections/{listed[0]['id']}", headers=guest_auth).status_code
        == 404
    )
    assert client.delete(f"/api/mcp/connections/{listed[0]['id']}", headers=auth).status_code == 204
    assert rpc(client, tokens["access_token"], "ping").status_code == 401
    refreshed = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )
    assert refreshed.status_code == 400
    assert client.get("/api/mcp/connections", headers=auth).json() == []


def test_using_a_connection_is_noted(client, auth):
    token = connect(client)["access_token"]
    assert client.get("/api/mcp/connections", headers=auth).json()[0]["last_used_at"] == ""
    rpc(client, token, "ping")
    assert client.get("/api/mcp/connections", headers=auth).json()[0]["last_used_at"] != ""


# -- features ------------------------------------------------------------------------------
def test_a_feature_switched_off_takes_its_tools_away(client, auth):
    pytest.importorskip("cloudmorrow.server.features")
    token = connect(client)["access_token"]
    off = client.patch("/api/server/features/notes", headers=auth, json={"enabled": False})
    assert off.status_code == 200, off.text
    names = {t["name"] for t in rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert "create_note" not in names
    assert "create_task" in names
    refused = call(client, token, "create_note", path="x", content="")
    assert refused["isError"] is True
    assert "switched off" in refused["content"][0]["text"]
    client.patch("/api/server/features/notes", headers=auth, json={"enabled": True})
    assert call(client, token, "create_note", path="x", content="")["structuredContent"]["created"]
