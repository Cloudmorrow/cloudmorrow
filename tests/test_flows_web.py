"""The roles side, Waiting for you and Flows are wired into the web app (docs/FLOWS.md)."""

from __future__ import annotations

from pathlib import Path

from cloudmorrow.server.routes.web import asset_version
from tests.conftest import js_code

WEB = Path(__file__).parent.parent / "src" / "cloudmorrow" / "server" / "web"
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")
NEW = ("rolesadmin", "approvals", "flows")


def test_the_three_screens_are_listed_and_served(client):
    version = asset_version()
    for name in NEW:
        assert f'import "./{name}.js";' in APP_JS, name
        assert f'@import "./{name}.css";' in APP_CSS, name
        for ext in ("js", "css"):
            assert client.get(f"/app/{version}/{name}.{ext}").status_code == 200, name


def test_roles_are_a_side_of_administration():
    admin = js_code((WEB / "admin.js").read_text(encoding="utf-8"))
    assert '["roles", "Roles"' in admin
    assert "drawRoles(panel)" in admin and 'roles: ["#/adminrole", "New role"]' in admin
    roles = js_code((WEB / "rolesadmin.js").read_text(encoding="utf-8"))
    assert 'registerScreen("adminrole"' in roles
    # Giving a role within a circle sends the circle along, as the API takes it.
    assert "?circle=" in roles and "/holders/" in roles


def test_me_leads_to_waiting_for_you_and_flows():
    me = js_code((WEB / "me.js").read_text(encoding="utf-8"))
    assert "approvalsRow(" in me and "flowsRow()" in me and "/api/approvals/count" in me


def test_the_screens_call_the_endpoints_that_exist(client, auth):
    approvals = js_code((WEB / "approvals.js").read_text(encoding="utf-8"))
    assert 'registerScreen("approvals"' in approvals
    assert '"/api/approvals"' in approvals and "/answer" in approvals
    flows = js_code((WEB / "flows.js").read_text(encoding="utf-8"))
    assert 'registerScreen("flows"' in flows and 'registerScreen("flow"' in flows
    assert '"/api/flows/check"' in flows and "/run" in flows
    # Every kind the editor offers is one the runner has.
    from cloudmorrow.server import flows as runner

    for kind in runner.STEP_KINDS:
        assert f'["{kind}",' in flows, kind
    assert client.get("/api/flows/kinds", headers=auth).status_code == 200
    assert client.get("/api/approvals/count", headers=auth).json() == {"waiting": 0}
