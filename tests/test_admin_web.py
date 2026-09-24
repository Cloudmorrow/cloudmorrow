"""Administration in the browser: that it is wired in, and that it has not drifted.

The screens themselves are driven in a browser, not from here. What a test
can hold on to is the part that goes wrong silently: `admin.js` spells out
the roles, the types and the shortest password it will send, and the server
decides all three. Nothing makes the two agree, so a role added to `db.py`
would quietly be a role the web app never offers — the same kind of gap the
brand page has against the tab icons, and caught the same way.
"""

from __future__ import annotations

import re

from cloudmorrow.server.db import ROLES, USER_TYPES
from cloudmorrow.server.routes.web import WEB
from cloudmorrow.server.schemas import UserCreate
from tests.conftest import GUEST, token_for

ADMIN_JS = (WEB / "admin.js").read_text(encoding="utf-8")


def _keys(block: str) -> list[str]:
    """The first string of each row in a `const X = [[...], ...]` table."""
    listed = ADMIN_JS.split(f"const {block} = [", 1)[1].split("\n];", 1)[0]
    return re.findall(r'^\s*\["([a-z_]+)"', listed, re.MULTILINE)


def test_the_roles_it_offers_are_the_roles_the_server_takes():
    assert _keys("ROLES") == list(ROLES)


def test_the_types_it_offers_are_the_types_the_server_takes():
    assert _keys("TYPES") == list(USER_TYPES)


def test_it_asks_for_as_long_a_password_as_the_server_does():
    """Saying so in the browser beats a 422 from the API; saying the wrong
    number is worse than not saying one."""
    wanted = UserCreate.model_fields["password"].metadata[0].min_length
    found = int(re.search(r"const MIN_PASSWORD = (\d+);", ADMIN_JS).group(1))
    assert found == wanted


def test_the_panel_is_listed_with_the_other_features():
    assert 'import "./admin.js";' in (WEB / "app.js").read_text(encoding="utf-8")
    assert '@import "./admin.css";' in (WEB / "app.css").read_text(encoding="utf-8")


def test_both_of_its_screens_are_registered():
    for screen in ("admin", "adminuser"):
        assert f'registerScreen("{screen}"' in ADMIN_JS, screen


def test_the_way_in_is_drawn_only_for_an_administrator():
    """Me asks; it does not decide for itself."""
    me = (WEB / "me.js").read_text(encoding="utf-8")
    assert "isAdmin(me) ? adminRow() : \"\"" in me
    assert "is_admin" in ADMIN_JS, "and isAdmin reads the server's own answer"


def test_it_calls_the_endpoints_that_exist(client, auth):
    """Every path the panel asks for answers an administrator."""
    for path in ("/api/users", "/api/server/features"):
        assert path in ADMIN_JS, path
        assert client.get(path, headers=auth).status_code == 200, path


def test_those_endpoints_turn_an_ordinary_account_away(client):
    """The redirect in the browser is a courtesy; this is the guard."""
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/users", headers=guest).status_code == 403
    assert client.patch(
        "/api/server/features/notes", json={"enabled": False}, headers=guest
    ).status_code == 403
