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
    assert 'isAdmin(me) ? adminRow() : ""' in me
    assert "is_admin" in ADMIN_JS, "and isAdmin reads the server's own answer"


def test_it_calls_the_endpoints_that_exist(client, auth):
    """Every path the panel asks for answers an administrator."""
    for path in ("/api/users", "/api/health"):
        assert path in ADMIN_JS, path
        assert client.get(path, headers=auth).status_code == 200, path


def test_there_is_no_features_side_any_more():
    """What the server offers is its Quills: the switch is on each Quill's sheet
    (quillsadmin.js), and the side that listed them all is gone. Whoever last
    stood on it lands on the Quills."""
    assert 'data-side="features"' not in ADMIN_JS
    assert "drawFeatures" not in ADMIN_JS
    assert '=== "features" ? "quills"' in ADMIN_JS


# -- where it is -------------------------------------------------------------------
def test_each_side_is_a_tab_of_the_rail_for_an_administrator():
    """On a computer the sides are under Administration in the rail, as the
    terminal app's sidebar lists them; each has an address of its own so the
    rail can light it, and the shell draws them only when the server has said
    this account administers."""
    sides = ADMIN_JS.split("const SIDES = [", 1)[1].split("\n];", 1)[0]
    assert re.findall(r'^\s*\["([a-z]+)", "([A-Za-z]+)"', sides, re.MULTILINE) == [
        ("users", "Users"),
        ("circles", "Circles"),
        ("roles", "Roles"),
        ("quills", "Quills"),
        ("server", "Server"),
        ("backups", "Backups"),
    ]
    assert 'registerTab({ name: "admin." + key, label, icon, href: () => sideHash(key), admin: true })' in ADMIN_JS
    assert 'export const sideHash = (side) => "#/admin/" + side;' in ADMIN_JS
    assert 'tabs("admin." + which)' in ADMIN_JS
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "(!t.admin || session.admin)" in core
    assert 'section("Administration", shown.filter((t) => t.admin))' in core
    # The answer is the server's: on signing in, and again once per load.
    assert "setAdmin(data.user.is_admin)" in core
    assert "setAdmin(me.is_admin)" in ADMIN_JS
    # The pages inside a side come back to that side, not to a bare #/admin.
    for js, side in (("circlesadmin.js", "circles"), ("rolesadmin.js", "roles"), ("quillsadmin.js", "quills")):
        assert f'replace("#/admin/{side}")' in (WEB / js).read_text(encoding="utf-8"), js
        assert 'replace("#/admin")' not in (WEB / js).read_text(encoding="utf-8"), js


def test_the_phone_keeps_the_row_in_me_and_the_switch_and_the_computer_the_rail():
    """A phone's bar has no room for a section, so its way in is still the
    row in Me and its way between the sides the switch above the page; a
    computer has the rail, and the same stylesheet hides what it does not need."""
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    assert ".tabs .tab.admin { display: none; }" in desktop
    assert ".tabs .rail-section { display: none; }" in desktop
    inside = desktop.split("@media (min-width: 900px)", 1)[1]
    assert ".tabs .tab.admin { display: flex; }" in inside
    assert "main.admin .seg { display: none; }" in inside
    assert ".admin-group { display: none; }" in inside
    assert 'class="group admin-group"' in ADMIN_JS
    assert 'data-side="${key}"' in ADMIN_JS and 'href="${sideHash(key)}"' in ADMIN_JS
    quills = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
    assert '"/api/server/features/"' in quills and "On for everybody" in quills


def test_those_endpoints_turn_an_ordinary_account_away(client):
    """The redirect in the browser is a courtesy; this is the guard."""
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.get("/api/users", headers=guest).status_code == 403
    assert client.patch("/api/server/features/notes", json={"enabled": False}, headers=guest).status_code == 403


# -- circles ---------------------------------------------------------------------
CIRCLES_JS = (WEB / "circlesadmin.js").read_text(encoding="utf-8")


def test_the_circles_section_is_wired_in():
    assert 'import "./circlesadmin.js";' in (WEB / "app.js").read_text(encoding="utf-8")
    assert '@import "./circlesadmin.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    assert 'registerScreen("admincircle"' in CIRCLES_JS
    assert '["circles", "Circles"' in ADMIN_JS and "drawCircles(panel)" in ADMIN_JS


def test_the_access_it_offers_is_the_access_the_server_takes():
    from cloudmorrow.server.circles import ACCESS, EVERY

    listed = CIRCLES_JS.split("export const ACCESS = [", 1)[1].split("\n];", 1)[0]
    assert re.findall(r'^\s*\["([a-z]+)"', listed, re.MULTILINE) == list(ACCESS)
    assert f'export const EVERY = "{EVERY}";' in CIRCLES_JS


def test_somebody_in_no_circle_is_flagged_in_the_accounts_list():
    assert "reaches no data" in ADMIN_JS
    assert "circlesByPerson(circles)" in ADMIN_JS


def test_the_circle_calls_answer_an_administrator(tasks_quill, auth):
    client = tasks_quill
    for path in ("/api/circles", "/api/datamodels", "/api/users"):
        assert path in CIRCLES_JS, path
        assert client.get(path, headers=auth).status_code == 200, path
    # What a circle's page sends on save.
    changed = client.patch(
        "/api/circles/members",
        json={"name": "Everyone", "rules": {"*": "read"}, "default": True},
        headers=auth,
    )
    assert changed.status_code == 200 and changed.json()["name"] == "Everyone"
    # An administrator in a `*` circle is sent every datamodel, each with a domain
    # to shelve it under.
    models = client.get("/api/datamodels", headers=auth).json()
    assert {m["id"]: m["domain"] for m in models if m["id"] in ("task", "board")} == {
        "task": "tasks",
        "board": "tasks",
    }


def test_the_install_sheet_gives_ticked_circles_the_new_data(client, auth):
    """quillsadmin.js puts one rule per ticked circle and new datamodel."""
    quills = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
    assert "/rules/" in quills and 'access: "write"' in quills
    assert ".filter((d) => d.new)" in quills
    plan = client.post("/api/quills/plan", json={"id": "calendar"}, headers=auth).json()
    assert {d["id"] for d in plan["data"] if d["new"]} == {"calendar", "event"}
    client.post("/api/circles", json={"name": "Kids"}, headers=auth)
    for model in ("calendar", "event"):
        put = client.put(f"/api/circles/kids/rules/{model}", json={"access": "write"}, headers=auth)
        assert put.status_code == 200
    assert client.get("/api/circles/kids", headers=auth).json()["rules"] == {
        "calendar": "write",
        "event": "write",
    }


# -- the server itself -------------------------------------------------------------
def test_the_server_section_updates_through_the_api_the_command_uses(client, auth):
    """`Update server` on the phone is `cloudmorrow update server` without the
    computer: the same POST, the same words for what it did, and the same
    witness — /api/health's commit — for whether the restart landed."""
    assert '["server", "Server"' in ADMIN_JS.split("const SIDES = [", 1)[1].split("\n];", 1)[0]
    assert 'api("POST", "/api/server/update", {})' in ADMIN_JS
    assert 'api("GET", "/api/health?t=" + Date.now())' in ADMIN_JS
    # A restart puts everybody offline for a moment: it is asked about first.
    assert "await ask(" in ADMIN_JS.split("async function drawServer", 1)[1].split("const shortCommit", 1)[0]
    # The page is the old app once the server is back: it reloads onto the new one.
    assert "location.reload()" in ADMIN_JS
    # The same route, which only an administrator may call (test_server_update_api.py).
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    assert client.post("/api/server/update", json={}, headers=guest).status_code == 403


def test_the_server_section_says_what_a_deploy_did_in_the_commands_words():
    """The CLI's lines and the phone's are written apart; these are the phrases
    a person would notice differing between the two."""
    cli = (WEB.parents[1] / "cli" / "update.py").read_text(encoding="utf-8")
    web = ADMIN_JS.split("export function deployLines", 1)[1]
    for phrase in ("Already up to date", "Rewound onto origin/", "Not restarted:", "reinstalled", "published "):
        assert phrase in cli, phrase
        assert phrase in web, phrase
    assert "the old code is still serving" in cli and "the old code is still serving" in web


def test_the_server_side_has_the_settings_form_before_the_update_button():
    """The name and the weather place are set here, not in a config file."""
    server = ADMIN_JS.split("async function drawServer", 1)[1].split("const shortCommit", 1)[0]
    assert server.index('class="server-settings"') < server.index("update-server")
    assert 'name="weather_place"' in server and 'name="name"' in server
    assert 'api("PATCH", "/api/server/settings"' in server
    today = (WEB / "today.js").read_text(encoding="utf-8")
    assert "weather_place" not in today and "Administration" in today


def test_the_server_side_says_when_a_newer_version_is_out():
    """A box above the Update button, with the version, and Release notes in a
    sheet of its own (never a browser window): every release from the running
    one to the latest."""
    server = ADMIN_JS.split("async function drawServer", 1)[1].split("const shortCommit", 1)[0]
    assert server.index('class="update-notice"') < server.index("update-server")
    assert "lookForUpdates(" in server
    look = ADMIN_JS.split("async function lookForUpdates", 1)[1]
    assert 'api("GET", "/api/server/updates")' in look
    assert "is out" in look and 'class="act-chip release-notes"' in look
    assert "openSheet(" in look and "Release notes" in look
    assert "newest first" in look
    # Quiet when there is nothing new, or nothing to look at.
    assert "runs the latest version" in look
    assert "Could not look for a newer version" in look


def test_the_update_button_sleeps_until_a_newer_version_is_found():
    """Nothing to press for while the server runs the latest: the button is
    drawn disabled, and only the look wakes it — for a newer release, or when
    it could not tell (the update itself still can)."""
    server = ADMIN_JS.split("async function drawServer", 1)[1].split("const shortCommit", 1)[0]
    assert 'class="row primary update-server" type="button" disabled>' in server
    assert 'lookForUpdates(panel.querySelector(".update-notice"), panel.querySelector(".update-server"))' in server
    look = ADMIN_JS.split("async function lookForUpdates", 1)[1].split("\nfunction showReleaseNotes", 1)[0]
    latest, newer = look.split("if (!found.available) {", 1)
    assert latest.count("button.disabled = false;") == 2, "woken when the look fails, and when the route is missing"
    quiet = newer.split("const count = ", 1)[0]
    assert "button.disabled" not in quiet, "asleep on the latest version"
    assert newer.rstrip().endswith("button.disabled = false;\n}"), "woken once a newer release is listed"


# -- the Backups side ---------------------------------------------------------------
def test_backups_is_a_side_of_administration():
    """The sixth side, with its own file, imported by the app and drawn by the switch."""
    assert '["backups", "Backups"' in ADMIN_JS
    assert 'import { drawBackups } from "./backupsadmin.js";' in ADMIN_JS
    assert 'which === "backups") await drawBackups(panel)' in ADMIN_JS
    assert 'import "./backupsadmin.js";' in (WEB / "app.js").read_text(encoding="utf-8")


def test_the_parts_it_offers_are_the_parts_the_server_backs_up():
    from cloudmorrow.server.backups import PARTS

    source = (WEB / "backupsadmin.js").read_text(encoding="utf-8")
    listed = source.split("const PARTS = [", 1)[1].split("\n];", 1)[0]
    assert re.findall(r'^\s*\["([a-z_]+)"', listed, re.MULTILINE) == list(PARTS)


def test_the_backups_page_asks_on_the_page_and_calls_the_backup_api():
    """Every question is a sheet (dialog.js), never the browser's; and the
    calls are the ones routes/backups.py answers."""
    source = (WEB / "backupsadmin.js").read_text(encoding="utf-8")
    assert "window.confirm" not in source and "confirm(" not in source.replace("ask(", "")
    assert 'import { ask, openSheet } from "./dialog.js";' in source
    for call in (
        '"GET", "/api/server/backup"',
        '"PATCH", "/api/server/backup"',
        '"POST", "/api/server/backup/test"',
        '"POST", "/api/server/backup/run"',
        '"GET", "/api/server/backups"',
        '"DELETE", "/api/server/backups/"',
        "/restore`",
        "/files?where=",
        "/file?path=",
    ):
        assert call in source, call


def test_the_restore_sheet_browses_a_backup_and_sends_the_picked_paths():
    """A drive or a share row opens a look inside (format 2 only), each file
    and folder with a tick, and what is ticked goes as `paths` with the
    restore. Saving a copy goes through apiRaw, never a bare link that would
    lose the token."""
    source = (WEB / "backupsadmin.js").read_text(encoding="utf-8")
    assert "const browsable = (m.cloudmorrow_backup || 1) >= 2;" in source
    assert 'class="browse-in"' in source and 'class="browse-pane"' in source
    assert "paths: [...picked]," in source
    assert 'apiRaw("GET", `/api/server/backups/${encodeURIComponent(stamp)}/file?path=' in source
    assert "a.download = pull.dataset.name;" in source
    assert "In the store" in source, "the page says what the store holds"


def test_a_quill_row_answers_at_once_with_the_loader():
    """A tap on a Quill row clears what was open and shows the loader before the
    sheet is read; a row tapped meanwhile wins over the slower one."""
    quills = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "export function loader(" in core
    assert 'class="loader" role="status" aria-live="polite"' in core
    assert 'class="pixel-loader"' in core and 'style="--i: ${x + y}"' in core
    # On a computer: into the page beside the list, before buildSheet.
    split = quills.split("async function openSheet(", 1)[1].split("\nasync function", 1)[0]
    assert split.index("page.innerHTML = loader(`Reading ${nameOf(ctx, id)}`)") < split.index("await buildSheet(id)")
    assert "const turn = ++asked;" in split and "if (turn !== asked) return;" in split
    # On a phone: the screen with the loader is mounted before anything is read.
    phone = quills.split("async function renderQuill(", 1)[1].split("\nasync function", 1)[0]
    assert phone.index('loader("Reading the Quill")') < phone.index('api("GET", "/api/auth/me")')
    assert phone.index('loader("Reading the Quill")') < phone.index("await buildSheet(id, me)")
    assert "if (turn !== asked) return;" in phone
    css = (WEB / "base.css").read_text(encoding="utf-8")
    assert "@keyframes pixel-wave" in css and "calc(var(--i, 0) * 55ms)" in css
    assert ".loader .pixel-loader rect { animation: none;" in css, "reduced motion gets a still cloud"


def test_a_quill_sheet_tells_its_facts_from_its_buttons():
    """On an installed Quill's sheet the settings box comes first, the version box
    with its buttons under it; a fact is a row that does not light up, and a
    thing to do is a button drawn as one."""
    quills = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
    html = quills.split("const html = `", 1)[1].split("const wire =", 1)[0]
    assert html.index("settingsBox(name, feature)") < html.index('<p class="group-label">Version</p>')
    assert html.index('<p class="group-label">Version</p>') < html.index("standingRow(plan, installed, entry, newer, origin)")
    assert html.index("standingRow(") < html.index('<div class="sheet-buttons">')
    assert '<p class="group-label">Settings</p><div class="group quill-settings">${switchRow(name, feature)}</div>' in quills
    # Up to date is a fact, not a dead button.
    assert 'disabled>Up to date</button>' not in quills
    assert 'fact("Up to date"' in quills
    for button in ("add-quill", "change-audience", "update-quill", "reinstall-quill", "remove-quill", "confirm", "cancel"):
        assert f'class="act-button' in quills and f' {button}"' in quills or f'class="act-button {button}"' in quills, button
    assert 'class="row ' not in html.split("sheet-buttons")[1].split("</div>")[0]
    css = (WEB / "quillsadmin.css").read_text(encoding="utf-8")
    assert ".row.sheet-fact:active { background: none; }" in css
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    assert ".row:not(.primary):not(.sheet-fact):hover" in desktop
