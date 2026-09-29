"""The kit in the browser: that it is wired in, generic, and agrees with the server.

The screens are driven in a browser, not from here. What a test can hold on
to is what goes wrong quietly: the kit drawing a different set of elements
than the server lets a Quill install, a field kind with no widget, a word
from one Quill hard-coded into what draws all of them, or the old task
screen coming back by the side door. The same kind of gap the brand page
has against the tab icons, and caught the same way.
"""

from __future__ import annotations

import re

from cloudmorrow.server.datamodels import FIELD_KINDS
from cloudmorrow.server.quills import KIT_READY
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import js_code

KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
# The elements that are more than rows, and spaces, each in files of their own.
OWN_FILES = (
    "kit_calendar.js",
    "kit_calendar.css",
    "kit_space.js",
    "kit_space.css",
    "kit_view.js",
    "kit_view.css",
    "actions.js",
    "actions.css",
)
KIT_CSS = (WEB / "kit.css").read_text(encoding="utf-8")
QUILLS_JS = (WEB / "quills.js").read_text(encoding="utf-8")
ADMIN_JS = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
APP_JS = (WEB / "app.js").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")


def _widgets() -> dict[str, str]:
    block = KIT_JS.split("export const WIDGET = {", 1)[1].split("\n};", 1)[0]
    return dict(re.findall(r'^\s+(\w+): "([\w-]+)",$', block, re.MULTILINE))


# -- wired in ------------------------------------------------------------------
def test_the_kit_is_listed_and_served(client):
    version = asset_version()
    assert 'import "./quills.js";' in APP_JS
    assert 'import "./quillsadmin.js";' in APP_JS
    assert '@import "./kit.css";' in APP_CSS
    assert '@import "./quillsadmin.css";' in APP_CSS
    for name in ("kit.js", "kit.css", "quills.js", "quillsadmin.js", "quillsadmin.css", *OWN_FILES):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_the_quill_tabs_sit_where_notes_and_tasks_were():
    """After Today: the order of app.js is the order of the bar."""
    assert APP_JS.index('"./today.js"') < APP_JS.index('"./quills.js"')
    # They arrive after the bar is first drawn, so core.js holds their place.
    assert "const fillTabs = tabSlot();" in QUILLS_JS
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "export function tabSlot()" in core
    # And the feature switches see them like any other tab.
    assert "tabList.flatMap((t) => t.tabs || [t])" in core
    assert "feature: quill.id," in QUILLS_JS


def test_the_old_task_screen_is_gone():
    assert not (WEB / "tasks.js").exists()
    assert not (WEB / "tasks.css").exists()
    for path in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")):
        text = path.read_text(encoding="utf-8")
        assert "tasks.js" not in text and "tasks.css" not in text, path.name
        assert "/api/boards" not in text, path.name
    # The tab is the Quill's now, not one core registers by name.
    assert 'name: "tasks"' not in APP_JS + QUILLS_JS + KIT_JS


def test_both_addresses_are_registered():
    assert 'registerScreen("q",' in QUILLS_JS
    assert 'registerScreen("r",' in QUILLS_JS
    assert "`#/q/${" in QUILLS_JS
    assert "`#/r/${" in KIT_JS


# -- generic -------------------------------------------------------------------
def test_nothing_in_the_kit_is_named_for_one_quill():
    """The kit reads names out of the screen and the datamodel, never its own."""
    own = [((WEB / name).read_text(encoding="utf-8"), name) for name in OWN_FILES]
    for source, name in ((KIT_JS, "kit.js"), (KIT_CSS, "kit.css"), (QUILLS_JS, "quills.js"), *own):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
        for word in ("todo", "doing", "task", "tasks", "lane-done", "new-board"):
            assert not re.search(rf"[\"'.`]{word}[\"'`\s]", code), f"{name} names {word!r}"
        assert ".row.task" not in code, name


def test_it_draws_what_the_server_installs():
    drawn = re.search(r"export const DRAWS = \[(.*?)\];", KIT_JS).group(1)
    assert set(re.findall(r'"(\w+)"', drawn)) == set(KIT_READY)


def test_a_view_screen_is_drawn_by_its_own_file():
    """`view` is in the list the server installs, and the kit hands it to kit_view.js."""
    assert "view" in KIT_READY
    assert 'import { renderView } from "./kit_view.js";' in KIT_JS
    assert "view: renderView" in KIT_JS


def test_every_record_sheet_has_the_actions_on_its_datamodel():
    sheet = js_code(_function(KIT_JS, "renderRecordSheet"))
    assert "${sheetSection(model.id)}" in sheet
    assert "wireSheetSection(app," in sheet
    # Read-only sheets have them too: the gate says no if the code writes.
    assert sheet.index("wireSheetSection(app,") < sheet.index("if (looked) return;")
    # What is being typed is saved first, and the sheet is drawn again after.
    assert "before: () => settle(ed)" in sheet and "after: () => again(ed)" in sheet
    # The widgets an action's form is drawn with are the sheet's own.
    for name in ("export function widget(", "export const segments =", "export function read("):
        assert name in KIT_JS, name


def test_a_quills_loose_actions_are_on_each_of_its_screens():
    assert "knowQuills(quills);" in QUILLS_JS
    assert "placeActionBar(quill);" in QUILLS_JS


def test_every_field_kind_has_a_widget():
    assert set(_widgets()) == set(FIELD_KINDS)


def test_the_sheet_never_sends_what_the_server_sets():
    """A stamped field is the server's: sending one is refused."""
    assert "if (!f || f.stamp) continue;" in KIT_JS
    assert "data-readonly" in KIT_JS


def test_the_sheet_saves_with_the_revision_it_read():
    """A stale write is a 409, shown afresh, rather than a quiet loss."""
    assert "{ fields, rev: ed.record.rev }" in KIT_JS
    assert "err.status === 409" in KIT_JS
    assert "SAVE_DELAY" in KIT_JS


def test_the_desktop_layer_follows_the_rename():
    desktop = (WEB / "desktop.css").read_text(encoding="utf-8")
    assert ".row.task" not in desktop and ".lanes " not in desktop
    assert ".row.card .tick" in desktop and ".segments button:hover" in desktop
    # A board is as many columns as its enum has values, not three.
    assert "repeat(var(--lanes, 3)" in KIT_CSS
    assert 'style="--lanes: ${lanes.length}"' in KIT_JS


# -- agrees with the server ----------------------------------------------------
def test_every_installed_screen_is_one_the_kit_draws(client, auth, tasks_quill):
    quills = client.get("/api/quills", headers=auth).json()
    assert quills, "the Tasks Quill should be installed"
    widgets = _widgets()
    for quill in quills:
        for screen in quill["screens"]:
            assert screen["kit"] in KIT_READY
            model = quill["models"][screen["model"]]
            for name in ("title", "lane", "body", "group", "subtitle", "tick"):
                if screen.get(name):
                    assert any(f["name"] == screen[name] for f in model["fields"]), (screen, name)
        for model in quill["models"].values():
            for field in model["fields"]:
                assert field["kind"] in widgets, field
            # A link is drawn as a choice of the target's records, by title.
            for field in model["fields"]:
                if field["kind"] == "link":
                    assert field["to"] in quill["models"], field


def test_the_record_calls_it_makes_exist(client, auth, tasks_quill):
    """What the board does, by the same calls the kit makes."""
    boards = client.get("/api/records/board", headers=auth).json()
    assert boards, "listing seeds the first board"
    board = boards[0]["id"]
    made = client.post(
        "/api/records/task",
        json={"fields": {"title": "Repot the fig", "lane": "todo", "board": board}},
        headers=auth,
    )
    assert made.status_code == 201
    task = made.json()
    listed = client.get("/api/records/task", params={"board": board}, headers=auth).json()
    assert [t["id"] for t in listed] == [task["id"]]
    moved = client.post(
        f"/api/records/task/{task['id']}/move", json={"fields": {"lane": "done"}, "index": 0}, headers=auth
    ).json()
    assert moved["fields"]["done_at"] and moved["expires_at"]
    stale = client.patch(
        f"/api/records/task/{task['id']}", json={"fields": {"title": "x"}, "rev": task["rev"]}, headers=auth
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["rev"] == moved["rev"]
    assert client.delete(f"/api/records/board/{board}", headers=auth).status_code == 204
    assert client.get(f"/api/records/task/{task['id']}", headers=auth).status_code == 404


# -- the administrator's Quills --------------------------------------------------
def test_the_quills_section_is_in_administration():
    admin = (WEB / "admin.js").read_text(encoding="utf-8")
    assert 'data-side="quills"' in admin
    assert "drawQuills(panel)" in admin
    assert 'registerScreen("adminquill", renderQuill);' in ADMIN_JS


def test_the_install_sheet_calls_the_endpoints_that_exist(client, auth):
    for call in ('"/api/quills/catalog"', '"/api/quills/plan"', 'api("POST", "/api/quills"'):
        assert call in ADMIN_JS, call
    catalog = client.get("/api/quills/catalog", headers=auth)
    assert catalog.status_code == 200
    plan = client.post("/api/quills/plan", json={"id": "tasks"}, headers=auth)
    assert plan.status_code == 200
    # Everything the sheet reads is in what the server sends.
    for key in (
        "data",
        "datasets",
        "screens",
        "jobs",
        "services",
        "webhooks",
        "apis",
        "surfaces",
        "runs_code",
        "runs_as",
        "reach",
        "installed_version",
        "readme",
    ):
        assert key in plan.json(), key
    for key in ("how", "label", "new", "foundation"):
        assert all(key in row for row in plan.json()["data"]), key


def test_the_install_buttons_do_not_borrow_the_install_card():
    """`.install` is the home-screen card's; a button called that grew its padding."""
    assert 'class="row primary add-quill"' in ADMIN_JS
    assert '"row primary install"' not in ADMIN_JS


# -- the calendar, and spaces ----------------------------------------------------
def test_the_calendar_asks_the_record_api_for_a_window_of_days():
    """One call per window, a range on each of the screen's two moments."""
    calendar = (WEB / "kit_calendar.js").read_text(encoding="utf-8")
    assert 'b.starts + "__lte"' in calendar and 'b.ends + "__gte"' in calendar
    for field in ('"starts_at"', '"ends_at"', '"all_day"', '"calendar"', '"event"'):
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", calendar, flags=re.DOTALL)
        assert field not in code, field
    # Drawn by the kit, and its sheet changed by it, from its own file.
    own = "const OWN = { calendar: renderCalendar, thread: renderThread, view: renderView };"
    assert own in KIT_JS
    assert "const SHEETS = { calendar: calendarSheet };" in KIT_JS


def test_a_space_has_its_people_on_its_sheet():
    space = (WEB / "kit_space.js").read_text(encoding="utf-8")
    assert "/members" in space and '"/api/people"' in space
    assert "export async function spaceSection" in space and "export function wireSpace" in space
    assert "model.space ? await spaceSection(model, record)" in KIT_JS


def test_today_draws_every_calendar_screen_through_the_record_api():
    today = (WEB / "today.js").read_text(encoding="utf-8")
    assert "/api/calendar" not in today
    assert 'screen.kit === "calendar"' in today
    assert "occasion(b, r, bySpace)" in today


def test_the_old_calendar_screen_is_gone():
    assert not (WEB / "calendar.js").exists() and not (WEB / "calendar.css").exists()
    for path in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")):
        text = path.read_text(encoding="utf-8")
        assert "calendar.js" not in text.replace("kit_calendar.js", ""), path.name
        assert "/api/calendar" not in text, path.name


# -- read is drawn as read (docs/CIRCLES.md) ----------------------------------------
def _function(source: str, name: str) -> str:
    """One top-level function's text, up to the next one."""
    start = source.index(f"function {name}(")
    following = re.search(r"\n(?:export )?(?:async )?function \w+\(", source[start + 1 :])
    return source[start : start + 1 + following.start()] if following else source[start:]


def test_what_may_be_written_is_asked_in_one_place():
    """Every kit file asks kit.js, per datamodel; none reads `access` itself."""
    assert 'export const mayWrite = (model) => !!model && model.access !== "read";' in KIT_JS
    assert "export const canWrite = (at, modelId) => mayWrite(at.quill.models[modelId]);" in KIT_JS
    for name in ("kit_calendar.js", "kit_editor.js", "kit_grid.js", "kit_grouped.js", "kit_space.js", "kit_thread.js"):
        source = js_code((WEB / name).read_text(encoding="utf-8"))
        assert "mayWrite" in source or "canWrite" in source, name
        assert ".access" not in source, name


def test_the_access_the_kit_reads_is_the_one_the_server_sends(client, tasks_quill):
    from tests.conftest import GUEST, token_for

    circles = client.app.state.cloudmorrow.circles
    circles.leave("members", GUEST[0])
    circles.create("Kids", {"task": "read", "board": "read"}, [GUEST[0]])
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    (tasks,) = [q for q in client.get("/api/quills", headers=guest).json() if q["id"] == "tasks"]
    assert {m["access"] for m in tasks["models"].values()} == {"read"}
    assert tasks["screens"], "a board you may read is still drawn"


def test_a_board_you_may_only_read_is_one_you_look_at():
    board = js_code(_function(KIT_JS, "renderBoard"))
    assert "const writes = mayWrite(model);" in board
    # No add row or pen, no new board, no ticking, no dragging.
    assert "const canAdd = (!groupModel || group) && writes &&" in board
    assert '(writes ? `<button class="compose"' in board
    assert 'mayWrite(groupModel) ? `<button class="chip new-group"' in board
    assert "writes && canDrag()" in board and "if (writes) wireDragging();" in board
    assert '${writes ? `<button class="tick"' in board and "stillTick(state," in board
    # The still circle is not a button, so nothing wires a click to it.
    assert 'querySelectorAll("button.tick")' in board
    assert 'class="tick still" role="img"' in KIT_JS


def test_a_list_you_may_only_read_has_no_add_row_and_no_ticking():
    listing = js_code(_function(KIT_JS, "renderList"))
    assert "const writes = mayWrite(model);" in listing
    assert '${writes ? `<form class="add">' in listing
    assert '${writes ? `<button class="tick"' in listing
    assert 'querySelectorAll("button.tick")' in listing
    grouped = js_code((WEB / "kit_grouped.js").read_text(encoding="utf-8"))
    assert '${writes ? `<form class="add">' in grouped
    assert 'tick && writes ? `<button class="tick"' in grouped
    assert 'namesGroups(f) ? `<button class="chip new-group"' in grouped


def test_the_sheet_of_a_record_you_may_only_read_says_it():
    sheet = js_code(_function(KIT_JS, "renderRecordSheet"))
    assert "const looked = !mayWrite(model) || (model.space && !record.can_manage);" in sheet
    # Said rather than typed, nothing to delete, and none of the saving wired.
    assert "looked && !f.secret ? sayWidget(" in sheet
    assert "const deletable = !looked &&" in sheet
    assert '(looked ? "" : `<button class="done strong" hidden>Done</button>`)' in sheet
    assert sheet.index("if (looked) return;") < sheet.index("const changed = ")
    assert sheet.index("if (looked) return;") < sheet.index('del.addEventListener("click"')
    assert ".record.read-only .field .value" in KIT_CSS


def test_a_link_to_a_datamodel_that_is_not_there_is_left_off():
    """A datamodel you may not read is not sent; a link to it is not a picker of nothing."""
    sheet = js_code(_function(KIT_JS, "renderRecordSheet"))
    assert '(f.kind !== "link" || !f.to || quill.models[f.to])' in sheet
    assert "!quill.models[f.to]) continue;" in js_code(_function(KIT_JS, "linkTitles"))


def test_a_quill_with_nothing_left_has_no_tab():
    assert "const yours = (quill) => quill.available !== false;" in QUILLS_JS
    assert "quills = list.filter(yours);" in QUILLS_JS


def test_spaces_you_may_only_read_are_not_made_or_changed():
    space = js_code((WEB / "kit_space.js").read_text(encoding="utf-8"))
    assert "if (!mayWrite(model)) return notYours(" in space
    assert space.count("return notYours(") == 2  # making one, and writing to somebody
    section = js_code(_function(space, "spaceSection"))
    assert "const writes = mayWrite(model);" in section
    assert section.count("writes &&") >= 3  # adding, taking out, leaving
    calendar = js_code((WEB / "kit_calendar.js").read_text(encoding="utf-8"))
    assert "const adds = mayWrite(b.model);" in calendar
    assert 'const addLine = !adds ? "" :' in calendar
    assert "if (!form) return;" in calendar


def test_the_editor_opens_pages_you_may_only_read_read_only():
    editor = js_code((WEB / "kit_editor.js").read_text(encoding="utf-8"))
    assert "writes: mayWrite(model)," in editor
    page = js_code(_function(editor, "renderPage"))
    assert 'const actions = !b.writes ? "" :' in page
    assert '${b.writes ? "" : " readonly"}' in page
    assert "area.readOnly = true;" in page
    # A paste, a drop or a backspace would add or take a picture: stopped.
    assert '["paste", "drop", "dragover", "keydown"]' in page
    assert 'const compose = !b.writes ? "" :' in editor
