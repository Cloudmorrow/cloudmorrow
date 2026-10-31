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
    assert 'import "./myquills.js";' in APP_JS and '@import "./myquills.css";' in APP_CSS
    mine = ("myquills.js", "myquills.css")
    for name in ("kit.js", "kit.css", "quills.js", "quillsadmin.js", "quillsadmin.css", *mine, *OWN_FILES):
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
    assert "feature: quill.key || quill.id," in QUILLS_JS


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
    # Every sheet but a data screen's, which is for looking (kit_data.js).
    assert '${screen.kit === "data" ? "" : sheetSection(model.id)}' in sheet
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
            if not screen.get("model"):
                # A data screen is over every datamodel the Quill has.
                assert screen["kit"] == "data"
                continue
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
    assert '["quills", "Quills"' in admin
    assert "drawQuills(panel)" in admin
    assert 'registerScreen("adminquill", renderQuill);' in ADMIN_JS


def test_your_quills_has_its_three_tabs_a_sheet_and_the_endpoints_that_answer_a_member(client, guest_auth):
    """Server Quills, Yours and the Catalog; a sheet per Quill, as a screen on a
    phone; updating a Quill of your own is installing it again."""
    mine = (WEB / "myquills.js").read_text(encoding="utf-8")
    for tab in ('["server", "Server Quills"]', '["mine", "Yours"]', '["catalog", "Catalog"]'):
        assert tab in mine, tab
    for screen in ("myquills", "myquill"):
        assert f'registerScreen("{screen}"' in mine, screen
    assert 'class="chip-button update-all"' in mine and 'class="row primary update-mine"' in mine
    assert 'api("POST", "/api/quills/mine", body)' in mine
    for path in ("/api/quills/mine", "/api/quills", "/api/me/features", "/api/quills/catalog"):
        assert f'"{path}"' in mine, path
        assert client.get(path, headers=guest_auth).status_code == 200, path


def test_the_quills_split_fills_the_window_and_its_columns_scroll_on_their_own():
    """On a computer the list and the sheet are the window's height under the
    bar, each scrolling itself — never a list column stuck to the bar and
    sized to the window, which starts lower than that and ran below it."""
    css = (WEB / "quillsadmin.css").read_text(encoding="utf-8")
    wide = css.split("@media (min-width: 900px) and (min-height: 600px) {", 1)[1]
    assert "#app:has(.quills-split) { height: 100dvh; }" in wide
    main = wide.split("main:has(> .quills-split) {", 1)[1].split("}", 1)[0]
    assert "flex: 1;" in main and "min-height: 0;" in main and "flex-direction: column;" in main
    split = wide.split("  .quills-split {", 1)[1].split("}", 1)[0]
    assert "grid-template-rows: minmax(0, 1fr);" in split and "min-height: 0;" in split
    for column in (".side", ".page"):
        rules = wide.split(f".quills-split {column} {{", 1)[1].split("}", 1)[0]
        assert "overflow-y: auto;" in rules and "min-height: 0;" in rules, column
        assert "sticky" not in rules and "100vh" not in rules, column
    # Both pages put the split right under the main it fills.
    admin_js = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
    mine_js = (WEB / "myquills.js").read_text(encoding="utf-8")
    assert 'panel.classList.toggle("quills-split", split);' in admin_js
    assert '<div class="${split ? "quills-split" : "quills-stack"}">' in mine_js


def test_the_quills_side_has_its_three_tabs_and_the_update_buttons():
    """Server Quills, User Quills and the Catalog; a tick per installed Quill, and
    an update of the ticked ones or of all, each an install again from the catalog
    that keeps who the Quill is for."""
    for tab in ('["server", "Server Quills"]', '["own", "User Quills"]', '["catalog", "Catalog"]'):
        assert tab in ADMIN_JS, tab
    assert 'class="chip-button update-picked"' in ADMIN_JS
    assert 'class="chip-button update-all"' in ADMIN_JS
    assert "update_available" in ADMIN_JS
    assert "{ id: quill.id, audience }" in ADMIN_JS
    for button in (
        'class="act-button primary update-quill"',
        'class="act-button reinstall-quill"',
        'class="act-button danger remove-quill"',
    ):
        assert button in ADMIN_JS, button


def test_user_quills_have_a_remove_beside_promote_and_switch():
    """Somebody's own Quill comes off the server from its row, with the same choice of what goes."""
    assert '<button type="button" class="quill-chip remove-own">Remove</button>' in ADMIN_JS
    assert "`/api/quills/personal/${encodeURIComponent(owner)}/${encodeURIComponent(quill)}`" in ADMIN_JS
    assert "removeSheet(`${owner}'s ${name}`, brought)" in ADMIN_JS


def test_a_quill_the_catalog_dropped_offers_no_reinstall_and_no_update():
    """Installing it again would ask the catalog for an id it no longer has."""
    assert "(entry || (!origin.dev && !origin.catalog && origin.repo))" in ADMIN_JS
    assert 'said: "no longer in the catalog"' in ADMIN_JS
    mine = (WEB / "myquills.js").read_text(encoding="utf-8")
    assert "if (!entry && catalog && origin.catalog) return { entry: null, newer: false," in mine
    assert "stood.entry || (!(own.origin || {}).catalog && (own.origin || {}).repo)" in mine


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
    assert 'class="act-button primary add-quill"' in ADMIN_JS
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
    own = (
        "const OWN = { calendar: renderCalendar, thread: renderThread, timeline: renderTimeline,"
        " view: renderView, data: renderData };"
    )
    assert own in KIT_JS
    assert (
        "const SHEETS = { calendar: calendarSheet, timeline: timelineSheet, data: dataSheet, list: projectsSheet };"
        in KIT_JS
    )


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


def test_a_lane_has_a_plus_that_makes_a_card_in_it():
    """Under each lane's name a plus opens the pen's sheet with the card already in that lane."""
    board = js_code(_function(KIT_JS, "renderBoard"))
    assert 'class="lane-add" data-lane="${esc(lane)}" aria-label="New ${esc(noun)} in ${esc(label)}"' in board
    # Only where the pen would be: a board you may only read has no plus.
    assert "${esc(label)}${canAdd" in board
    assert 'querySelectorAll("button.lane-add")' in board
    assert "given: { ...given, [laneField.name]: lane }" in board
    # The plus and the pen make a card the same way, on the same sheet.
    assert "createSheet(quill, model, title, make, {" in board
    assert "if (canAdd) wirePen(quill, model, title, make, offer);" in board
    assert ".lane-add" in (WEB / "base.css").read_text(encoding="utf-8"), "the plus is a ghost button like the rest"


def test_the_sheet_that_makes_a_card_offers_its_body():
    """A board's `body` is on the sheet that makes a card, so subtasks are typed as it is made."""
    board = js_code(_function(KIT_JS, "renderBoard"))
    assert "also: screen.body ? [screen.body] : []" in board
    sheet = js_code(_function(KIT_JS, "createSheet"))
    assert "const offered = also.map((n) => fieldOf(model, n))" in sheet
    assert "const fields = [head, ...needed, ...offered];" in sheet
    # Offered, not needed: an offered field is never marked required, and
    # one the screen already gives, or the title, is not asked twice.
    assert "f && f.name !== title && !(f.name in given) && !needed.includes(f)" in sheet
    assert "{ given, where, also }" in js_code(_function(KIT_JS, "wirePen"))


def test_a_list_you_may_only_read_has_no_pen_and_no_ticking():
    listing = js_code(_function(KIT_JS, "renderList"))
    assert "const writes = mayWrite(model);" in listing
    assert '${heading(screen.label, writes ? `<button class="compose"' in listing
    assert '${writes ? `<button class="tick"' in listing
    assert 'querySelectorAll("button.tick")' in listing
    grouped = js_code((WEB / "kit_grouped.js").read_text(encoding="utf-8"))
    assert '${heading(screen.label, writes ? `<button class="compose"' in grouped
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
    assert '(adds ? `<button class="compose"' in calendar
    assert "if (!pen) return;" in calendar


def test_nothing_is_made_from_a_line_typed_into_the_page():
    """No add row under a title, on any screen: the pen at the top opens a sheet that makes one."""
    for path in sorted(WEB.glob("*.js")):
        code = js_code(path.read_text(encoding="utf-8"))
        assert '<form class="add' not in code, path.name
        assert "wireAdd" not in code, path.name
    kit = js_code((WEB / "kit.js").read_text(encoding="utf-8"))
    sheet = js_code(_function(kit, "createSheet"))
    assert "openSheet(" in sheet and "formFields(fields, {}, links)" in sheet and "readFields(form, fields)" in sheet
    assert "f.required && f.name !== title" in sheet
    assert 'pen.addEventListener("click", () => createSheet(' in js_code(_function(kit, "wirePen"))
    for name in ("kit.js", "kit_grouped.js"):
        assert "wirePen(quill, model, title," in js_code((WEB / name).read_text(encoding="utf-8")), name
    for words in ("Add ${esc(aOr(model.label))} above", "Add something above"):
        for name in ("kit.js", "kit_grouped.js", "kit_calendar.js"):
            assert words not in (WEB / name).read_text(encoding="utf-8"), (name, words)


def test_a_sheet_goes_when_its_screen_does():
    dialog = js_code((WEB / "dialog.js").read_text(encoding="utf-8"))
    assert 'addEventListener("hashchange", onLeave);' in dialog
    assert 'removeEventListener("hashchange", onLeave);' in dialog


def test_a_text_box_is_measured_without_the_page_shrinking_under_the_window():
    """A box fitted to its text is measured by letting it collapse for an
    instant; left alone, the shorter page clamps the window's scroll and the
    line being typed lands at the bottom edge on every keystroke. One helper
    holds the box's parent at its height for the measure, and the editors
    with boxes like that use it rather than measuring on their own. (A page
    of Markdown is a box that grows with its lines, and is never measured.)"""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    fit = js_code(_function(core, "fitArea"))
    assert 'holder.style.minHeight = holder.offsetHeight + "px";' in fit
    assert 'area.style.height = "auto";' in fit and 'area.style.height = area.scrollHeight + "px";' in fit
    assert "holder.style.minHeight = held;" in fit
    source = (WEB / "kit.js").read_text(encoding="utf-8")
    assert "fitArea" in source and 'style.height = "auto"' not in source
    for name in ("pictures.js", "markdown.js"):
        assert "style.height" not in (WEB / name).read_text(encoding="utf-8"), name


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


def test_every_list_row_and_board_card_has_the_shared_menu():
    """A right-click or a long press on a row or a card opens the one menu
    actions.js draws — Open, and the actions on the record's datamodel, the
    ones its sheet has — wired once on the listing for the list and the board."""
    code = js_code(KIT_JS)
    assert 'contextMenus(listing, ".row[data-id]"' in code
    assert "recordChoices(record, { open: sheetHash(at, model.id, record.id)" in code
    assert code.count("recordMenus(listing, at, model, () => records") == 2
    # A row without a tick is a link, and it carries its id like the others.
    assert '<a class="row" data-id="${esc(r.id)}" href="${sheetHash(at, model.id, r.id)}"' in code


def test_an_admin_screen_is_on_the_quills_sheet_and_never_under_its_tab():
    """A screen marked admin is the Quill's settings: quills.js leaves it out of
    the items under the tab, quillsadmin.js draws it in the Settings box of the
    Quill's sheet through kit_view.js's embedView, and a go to itself is drawn
    again there rather than leaving Administration."""
    quills = (WEB / "quills.js").read_text(encoding="utf-8")
    assert "quill.screens.filter((screen) => !screen.admin)" in quills
    assert "quill.screens.some((screen) => !screen.admin)" in quills
    view = (WEB / "kit_view.js").read_text(encoding="utf-8")
    assert "export async function embedView(root, at, params = {})" in view
    assert "if (at.embedded) at.goHere = " in view
    admin = (WEB / "quillsadmin.js").read_text(encoding="utf-8")
    assert 'import { embedView } from "./kit_view.js";' in admin
    assert 'class="quill-admin-screen" data-screen="${esc(s.id)}"' in admin
    assert 'embedView(box, { quill: here, screen, tab: "", base: "", embedded: true }, {})' in admin
    actions = (WEB / "actions.js").read_text(encoding="utf-8")
    assert "if (here && here.goHere && effect.screen === here.screen.id)" in actions
    # Its actions are not on the bar either: the settings screen draws their buttons.
    assert "filter((a) => !a.on && !a.admin)" in actions


# -- Done means there is something to be done ------------------------------------
def test_done_is_lit_by_a_change_not_by_the_caret():
    """Moving the caret about lights nothing; typing does, and a save puts it out.

    Every editor hands its Done to `ed.doneEl`, and `setStatus` — called on every
    change and every save — keeps the button in step with `ed.dirty`. Ctrl+S (⌘S)
    saves now rather than after the pause, in every editor alike.
    """
    core = js_code((WEB / "core.js").read_text(encoding="utf-8"))
    assert "export function litDone(ed) {\n  if (ed.doneEl) ed.doneEl.disabled = !ed.dirty;\n}" in core
    status = _function(core, "setStatus")
    assert "litDone(ed);" in status
    assert "export function wireSaveKey(ed, box, save) {" in core
    save_key = _function(core, "wireSaveKey")
    assert 'event.key.toLowerCase() !== "s"' in save_key
    assert "event.preventDefault();" in save_key and "clearTimeout(ed.timer);" in save_key
    editors = {
        "kit.js": "saveSheet",
        "kit_editor.js": "saveEditor",
        "kit_docs.js": "savePage",
        "kit_cells.js": "(e) => { commit(e); e.wrap.focus(); saveSheet(e); }",
    }
    for name, save in editors.items():
        source = js_code((WEB / name).read_text(encoding="utf-8"))
        assert "ed.doneEl = done;" in source, name
        # Shown again on focus, it is lit or dark for what is unsaved then.
        assert source.index("ed.doneEl = done;") < source.index("litDone(ed)"), name
        assert f"wireSaveKey(ed, box, {save});" in source, name
    assert ".nav button.strong:disabled {" in (WEB / "base.css").read_text(encoding="utf-8")


def test_a_form_suggests_people_warns_of_outsiders_and_keeps_extra_fields_behind_more():
    """A field with `suggest = "people"` is chips with the server's people offered as
    typed (from /api/people, read once); its `outside` warning shows while an
    address is in it; fields marked extra wait behind one link naming them."""
    actions = (WEB / "actions.js").read_text(encoding="utf-8")
    assert 'peopleKnown = api("GET", "/api/people").catch(() => [])' in actions
    assert "export function formFields(fields, values = {}, links = {}, people = [])" in actions
    assert 'if (f.suggest === "people") {' in actions
    assert '<input type="hidden" data-field="${esc(f.name)}" value="${esc(names.join(", "))}">' in actions
    assert 'const outside = field.dataset.outside && [...names(), typed].some((n) => n.includes("@"));' in actions
    assert '<button type="button" class="fields-more">${esc(extra.map((e) => e.label).join(", "))}</button>' in actions
    assert 'for (const field of root.querySelectorAll(".people-field")) wirePeople(field);' in actions
    view = (WEB / "kit_view.js").read_text(encoding="utf-8")
    assert "await fetchPeople(v, v.tree);" in view
    assert 'if (n.ui === "split") { yield* walk(n.side); yield* walk(n.main); }' in view
    css = (WEB / "kit_view.css").read_text(encoding="utf-8")
    assert (
        '.v-split[data-show="main"] > .v-split-side, .v-split[data-show="side"] > .v-split-main { display: none; }'
        in css
    )
    assert ".v-card.current {" in css


def test_typed_words_run_from_the_left_on_a_sheet_row():
    """A string, email, url or phone box on a sheet row is left-aligned: typing
    into a right-aligned box reads as right-to-left. Numbers, dates and choices
    keep to the right, where a row's value sits."""
    css = KIT_CSS
    assert '.record .field input:not([type="checkbox"]),' in css
    left = css.split('.record .field input[type="text"],', 1)[1].split("}", 1)[0]
    assert "text-align: left;" in left
    for kind in ("email", "url", "tel"):
        assert f'.record .field input[type="{kind}"],' in css, kind
    assert '.record .field input[type="number"]' not in left and '.record .field input[type="date"]' not in left


def test_a_views_pen_is_drawn_in_the_heading_like_a_lists_new():
    view = (WEB / "kit_view.js").read_text(encoding="utf-8")
    assert "const compose = at.screen.compose && findAction(at.quill.id, at.screen.compose.action);" in view
    assert (
        '<button class="compose" aria-label="${esc(penLabel)}" title="${esc(penLabel)}">${icons.compose}</button>'
        in view
    )
    assert 'if (pen && compose) pen.addEventListener("click", () => press(at.quill, compose, ' in view
    assert "if (v.at.screen.compose) pressed.add(v.at.screen.compose.action);" in view


def test_a_button_whose_args_answer_every_field_runs_the_action_at_once():
    """The form is for what is left to fill in; a view's button that carries every
    field runs without one, as the terminal already did (run_action in quill_actions.py)."""
    actions = (WEB / "actions.js").read_text(encoding="utf-8")
    assert "const unanswered = fields.some((f) => args[f.name] === undefined || args[f.name] === null" in actions
    assert "if (fields.length && unanswered) return openForm(quill, action, { record, args, here, after });" in actions
    tui = (WEB.parents[1] / "tui" / "quill_actions.py").read_text(encoding="utf-8")
    assert 'if any(field["name"] not in values for field in fields):' in tui


def test_a_views_button_shows_it_is_busy_while_its_action_runs():
    """An action that reaches out takes a while: the pressed button is marked
    busy and disabled until it is over, and the stylesheet dims it."""
    view = (WEB / "kit_view.js").read_text(encoding="utf-8")
    assert 'if (outcome && typeof outcome.then === "function") {' in view
    assert 'el.setAttribute("aria-busy", "true");' in view and 'el.removeAttribute("aria-busy");' in view
    css = (WEB / "kit_view.css").read_text(encoding="utf-8")
    assert '.quill-view .act-button[aria-busy="true"]' in css
