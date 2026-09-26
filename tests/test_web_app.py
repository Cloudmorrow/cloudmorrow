"""The web app at /app: the page, its files, and the previews it lists notes by."""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB, asset_version


def test_app_page_needs_no_auth_and_carries_no_placeholders(client):
    response = client.get("/app")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="app"' in response.text
    assert "__VERSION__" not in response.text
    assert "__ASSET_VERSION__" not in response.text


def test_app_page_is_installable_on_a_phone(client):
    body = client.get("/app").text
    assert 'rel="manifest"' in body
    assert 'rel="apple-touch-icon"' in body
    assert 'name="apple-mobile-web-app-capable" content="yes"' in body
    manifest = client.get("/app/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/app"
    # It is Cloudmorrow on the home screen, not a second app called Notes.
    assert manifest.json()["name"] == "Cloudmorrow"
    assert manifest.json()["short_name"] == "Cloudmorrow"
    assert 'name="apple-mobile-web-app-title" content="Cloudmorrow"' in body
    for name in ("icon-180.png", "icon-192.png", "icon-512.png"):
        icon = client.get(f"/app/{name}")
        assert icon.status_code == 200
        assert icon.headers["content-type"] == "image/png"
        assert icon.content.startswith(b"\x89PNG")


def test_app_assets_are_served_under_the_deploy_and_nothing_else_is(client):
    page = client.get("/app").text
    version = asset_version()
    assert f'href="/app/{version}/app.css"' in page
    assert f'<script type="module" src="/app/{version}/app.js"' in page
    css = client.get(f"/app/{version}/app.css")
    assert css.headers["content-type"].startswith("text/css")
    assert "immutable" in css.headers["cache-control"]
    script = client.get(f"/app/{version}/app.js")
    assert script.headers["content-type"].startswith("text/javascript")
    assert client.get("/app/app.css").status_code == 200
    for path in ("/app/app.py", "/app/..%2Fapp.py", "/app/app.html", f"/app/{version}/app.html"):
        assert client.get(path).status_code == 404


def test_every_import_names_a_file_that_is_served(client):
    """A feature is a file and one import line; this catches the line without the file."""
    version = asset_version()
    imports = set()
    for script in WEB.glob("*.js"):
        imports.update(re.findall(r'^import .*?"\./([^"]+)";', script.read_text(), re.MULTILINE))
    sheet = (WEB / "app.css").read_text()
    imports.update(re.findall(r'^@import "\./([^"]+)";', sheet, re.MULTILINE))
    assert {"core.js", "base.css"} <= imports
    for name in sorted(imports):
        assert (WEB / name).is_file(), name
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_login_and_notes_addresses_lead_to_the_app(client):
    for path in ("/login", "/notes"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "/app"


def test_install_page_links_to_the_app(client):
    assert 'href="/app"' in client.get("/").text


def test_tree_previews_show_what_a_note_says(client, auth):
    client.post(
        "/api/notes/file",
        json={"path": "plan", "content": "# plan\n\n- [ ] ship it\nthen rest\nand more\n"},
        headers=auth,
    )
    client.post("/api/notes/file", json={"path": "blank", "content": ""}, headers=auth)

    plain = client.get("/api/notes/tree", headers=auth).json()
    assert all("preview" not in child for child in plain["children"])

    tree = client.get("/api/notes/tree", params={"previews": "true"}, headers=auth).json()
    previews = {child["name"]: child["preview"] for child in tree["children"]}
    # The heading repeats the file name and the list marker is noise: neither
    # is what the note says. Two lines is enough for a row.
    assert previews["plan.md"] == "ship it then rest"
    assert previews["blank.md"] == ""


def test_tree_previews_are_capped(client, auth):
    client.post(
        "/api/notes/file", json={"path": "long", "content": "x" * 500}, headers=auth
    )
    tree = client.get("/api/notes/tree", params={"previews": "true"}, headers=auth).json()
    preview = tree["children"][0]["preview"]
    assert len(preview) == 120
    assert preview.endswith("…")


# -- following a deploy -----------------------------------------------------
def test_the_page_says_which_deploy_it_was_built_from(client):
    """The page needs something to compare against, or it can never know."""
    page = client.get("/app").text
    assert f'data-deploy="{asset_version()}"' in page


def test_the_version_endpoint_says_what_is_being_served_now(client):
    response = client.get("/app/version")
    assert response.status_code == 200
    assert response.json()["deploy"] == asset_version()
    # Asked over and over by a page that is already open, so never cached.
    assert response.headers["cache-control"] == "no-cache"
    # It is a page's own business, like the page: no token needed.
    assert "authorization" not in {name.lower() for name in response.request.headers}


def test_the_version_endpoint_is_not_swallowed_by_the_asset_route(client):
    """`/app/<filename>` would answer this address with a 404 if it got there first."""
    assert client.get("/app/version").headers["content-type"].startswith("application/json")


# -- the front page, and where Me and the pen went ---------------------------
def test_the_app_opens_on_today_and_me_is_in_the_corner_not_the_bar():
    core = (WEB / "core.js").read_text()
    today = (WEB / "today.js").read_text()
    me = (WEB / "me.js").read_text()
    # The front page is the home, listed before every tab, and not a feature
    # anybody's switch can take away.
    assert 'import "./today.js";' in (WEB / "app.js").read_text()
    assert (WEB / "app.js").read_text().index("today.js") < (WEB / "app.js").read_text().index("quills.js")
    assert 'setHome("today");' in today
    assert "setHome(" not in (WEB / "kit_editor.js").read_text()
    # Me is a link in the bar's right corner on every top-level screen, and
    # no longer a tab; its own screen has a way back instead.
    assert 'class="button me-link" href="#/me"' in core
    assert "if (backTo === undefined) right += meLink();" in core
    assert "registerTab" not in me
    assert 'nav({ back, backLabel: "Back", title: "Me" })' in me


def test_what_a_screen_makes_is_beside_its_title_not_in_the_bar():
    """The bar's corner is Me's; the pen and the plus moved down to the title."""
    for name in ("kit_editor.js", "kit.js", "kit_grid.js", "kit_thread.js", "kit_calendar.js", "admin.js"):
        script = (WEB / name).read_text()
        for line in script.splitlines():
            if "right:" in line and ("compose" in line or 'class="add"' in line):
                raise AssertionError(f"{name} still puts a create button in the bar: {line.strip()}")
    for name in ("kit_editor.js", "kit.js", "kit_grid.js", "kit_thread.js", "kit_calendar.js", "admin.js"):
        assert "heading(" in (WEB / name).read_text(), name
    assert '.heading .compose' in (WEB / "desktop.js").read_text()


def test_a_calendar_screen_has_a_title_like_every_other_tab():
    calendar = (WEB / "kit_calendar.js").read_text()
    assert "heading(screen.label, actions)" in calendar
    # One h1 per page — the month's name stepped down so the bar watches the title.
    assert "<h2>${esc(title)}</h2>" in calendar
    assert ".month-bar h2" in (WEB / "kit_calendar.css").read_text()
