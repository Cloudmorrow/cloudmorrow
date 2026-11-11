"""A Quill's Python on the server: views, actions, hooks, jobs, webhooks, APIs, and the walls.

Installs `fixtures/quill-fleet`, whose `quill.py` has one handler of every
kind. Most tests run its code in the server's own interpreter (`quill_code
= "trusted"`), which is the same dispatch without the wall and quick; the
sandbox tests at the end run it in the real one, CPython in WebAssembly,
and are skipped where the runtime cannot be had.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow import sandbox
from cloudmorrow.quill import context as sdk
from cloudmorrow.server.app import create_app
from cloudmorrow.server.quills import QuillError, parse_manifest
from cloudmorrow.server.quills.code import HostCalls
from cloudmorrow.server.records import Principal
from tests.conftest import ADMIN, GUEST, token_for

FLEET = Path(__file__).parent / "fixtures" / "quill-fleet"


def _app(config, users, mode: str):
    config.quill_code = mode
    return create_app(config)


@pytest.fixture()
def fleet(config, users):
    client = TestClient(_app(config, users, "trusted"))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    answer = client.post("/api/quills", json={"source": str(FLEET)}, headers=admin)
    assert answer.status_code == 201, answer.text
    guest = {"Authorization": "Bearer " + token_for(client, *GUEST)}
    return client, admin, guest


def state_of(client: TestClient):
    return client.app.state.cloudmorrow


def press(client, headers, action, **body):
    return client.post(f"/api/quills/fleet/actions/{action}", json=body, headers=headers)


def add_van(client, headers, name="Van", registration="AB 12 345"):
    answer = press(client, headers, "add-van", fields={"name": name, "registration": registration})
    assert answer.status_code == 200, answer.text
    return answer.json()["effects"][1]["id"]


# -- the manifest ---------------------------------------------------------------------------
def test_the_install_sheet_says_what_the_code_does_without_running_it(fleet):
    client, admin, _ = fleet
    plan = client.post("/api/quills/plan", json={"source": str(FLEET)}, headers=admin).json()
    code = plan["quill_code"]
    assert code["sandboxed"] is True
    assert code["views"] == ["Garage", "Keys", "Tracker"]
    assert "Log a service" in code["actions"]
    assert code["hooks"] == ["when a fleet.visit is created"]
    assert code["fetch"] == [{"host": "api.example.com", "why": "to read each van's odometer from the tracker"}]
    assert code["secrets"][0]["key"] == "TRACKER_KEY"
    assert code["machine"][0]["folders"] == ["exports (read)"]


def test_every_client_is_told_the_actions_and_the_view(fleet):
    client, admin, _ = fleet
    quill = next(q for q in client.get("/api/quills", headers=admin).json() if q["id"] == "fleet")
    assert [s["kit"] for s in quill["screens"]] == ["view", "list", "view", "view"]
    log_service = next(a for a in quill["actions"] if a["id"] == "log-service")
    assert log_service["on"] == "vehicle"
    assert [f["name"] for f in log_service["fields"]] == ["date", "km", "note"]
    assert log_service["fields"][0]["required"] is True


def test_an_admin_screen_is_the_administrators_alone(fleet):
    client, admin, guest = fleet
    for_admin = next(q for q in client.get("/api/quills", headers=admin).json() if q["id"] == "fleet")
    for_guest = next(q for q in client.get("/api/quills", headers=guest).json() if q["id"] == "fleet")
    assert [s["id"] for s in for_admin["screens"]] == ["garage", "vans", "keys", "tracker"]
    assert [s["id"] for s in for_guest["screens"]] == ["garage", "vans", "tracker"]
    drawn = client.get("/api/quills/fleet/views/keys", headers=admin)
    assert drawn.status_code == 200 and "for an administrator" in str(drawn.json()["tree"])
    # And the code knows what the cloud is called, for an address on it.
    assert f"of {state_of(client).cloud_name()}" in str(drawn.json()["tree"])
    refused = client.get("/api/quills/fleet/views/keys", headers=guest)
    assert refused.status_code == 403 and "Keys is for an administrator" in refused.text
    # An action marked admin goes with the screen: not theirs, and refused when pressed.
    assert "rotate-keys" in [a["id"] for a in for_admin["actions"]]
    assert "rotate-keys" not in [a["id"] for a in for_guest["actions"]]
    assert press(client, admin, "rotate-keys").status_code == 200
    pressed = press(client, guest, "rotate-keys")
    assert pressed.status_code == 403 and "Rotate the keys is for an administrator" in pressed.text


def test_a_job_delivers_a_record_of_its_own_to_somebody_and_an_action_may_not(fleet):
    client, admin, guest = fleet
    state_of(client).code.run_job("fleet", "deliver")
    theirs = client.get("/api/records/fleet.notice", headers=guest).json()
    assert [(r["fields"]["text"], r["owner"]) for r in theirs] == [("delivered", "guest")]
    # ctx.people() is everybody but the installer, and the installer sees no delivery.
    assert client.get("/api/records/fleet.notice", headers=admin).json() == []
    pressed = press(client, admin, "hand-over", fields={"who": "guest"})
    assert pressed.status_code == 403 and "only a job or a webhook delivers" in pressed.text
    assert len(client.get("/api/records/fleet.notice", headers=guest).json()) == 1


def test_an_action_admin_flag_is_a_bool():
    with pytest.raises(QuillError, match="admin is true or false"):
        parse_manifest(_manifest('code = "quill.py"\n[[actions]]\nid = "a"\nlabel = "A"\nadmin = "yes"\n'))


def test_an_action_marked_settings_is_a_bool_on_no_record_and_not_admin():
    """A person's own setting: drawn behind the gear, on no bar or palette."""
    head = 'code = "quill.py"\n[[actions]]\nid = "a"\nlabel = "A"\n'
    with pytest.raises(QuillError, match="settings is true or false"):
        parse_manifest(_manifest(head + 'settings = "yes"\n'))
    with pytest.raises(QuillError, match="settings or admin, not both"):
        parse_manifest(_manifest(head + "settings = true\nadmin = true\n"))
    with pytest.raises(QuillError, match="on no record"):
        parse_manifest(_manifest(head + 'settings = true\non = "task"\n'))
    with pytest.raises(QuillError, match="bar is true or false"):
        parse_manifest(_manifest(head + 'bar = "no"\n'))
    (kept,) = parse_manifest(_manifest(head + "bar = false\n")).actions
    assert kept["bar"] is False


def test_a_toggle_and_a_conversation_are_primitives_every_surface_draws():
    """A setting is a switch that runs its action with the new state; a chat is
    its lines with a box under them that runs `ask`. Both are checked against
    the manifest, and both are said as text."""
    from cloudmorrow.quill import text as as_text
    from cloudmorrow.quill import ui
    from cloudmorrow.quill.ui import TreeError

    lines = [
        {"id": "m1", "model": "chat.line", "fields": {"body": "How many?", "mine": True, "at": "2026-11-10T09:00"}},
        {"id": "m2", "model": "chat.line", "fields": {"body": "**Four**", "mine": False, "note": "Looked at: tasks"}},
        {"id": "m3", "model": "chat.line", "fields": {"body": "Sure?", "mine": True, "failed": True}},
    ]
    tree = ui.stack(
        ui.toggle("Morrow may change things", action="allow", on=True, field="changes", hint="Or only read"),
        ui.conversation(
            lines,
            body="body",
            mine="mine",
            at="at",
            note="note",
            failed="failed",
            ask="ask",
            name="Morrow",
            record={"id": "c1", "model": "chat.conversation"},
            placeholder="Ask Morrow",
            hint="Reads only",
            close="forget",
        ),
    )
    ui.check(tree, actions={"allow", "ask", "forget"}, screens=set())
    # The X in the corner runs `close`, an action the manifest must declare too.
    with pytest.raises(TreeError, match="runs 'forget'"):
        ui.check(tree, actions={"allow", "ask"}, screens=set())
    toggle, chat = tree["children"]
    assert toggle["on"] is True and toggle["field"] == "changes" and "args" not in toggle
    assert chat["record"] == {"id": "c1", "model": "chat.conversation", "rev": None, "fields": {}}
    with pytest.raises(TreeError, match="runs 'ask'"):
        ui.check(tree, actions={"allow", "forget"}, screens=set())
    with pytest.raises(TreeError, match="a conversation needs 'mine'"):
        ui.check({"ui": "conversation", "records": [], "body": "body"})
    said = as_text.render(tree, actions={"allow": "What Morrow may do", "ask": "Send", "forget": "Delete"})
    assert "[x] Morrow may change things" in said and "    Or only read" in said
    assert "[✕ Delete]\nYou:" in said
    assert "You:  2026-11-10T09:00\n  How many?\nMorrow:\n  **Four**\n  Looked at: tasks\n" in said
    assert "You:\n  Sure?\n  (did not go through)" in said
    assert said.rstrip().endswith("[Ask Morrow…]\nReads only")
    empty = ui.conversation([], body="body", mine="mine", empty="Hello. Ask me anything.", backdrop="mascot")
    assert empty["backdrop"] == "mascot"
    assert as_text.render(empty, actions={}).strip() == "(Hello. Ask me anything.)"
    with pytest.raises(TreeError, match="backdrop is one of"):
        ui.conversation([], body="body", mine="mine", backdrop="dragon")
    # Rows are the app's list rows: as cards, but a line each, the open one lit.
    listed = ui.rows(lines, title="body", subtitle="note", go="chat", param="line", current="m2")
    assert listed["param"] == "line" and listed["current"] == "m2" and "open" not in listed
    ui.check(listed, actions=set(), screens={"chat"})
    assert as_text.render(listed, actions={}).splitlines()[:2] == ["• How many?", "▶ **Four** — Looked at: tasks"]


def test_a_settings_screen_is_everybodys_own_and_never_a_tab(fleet):
    """Tracker is marked settings: the person's own settings for Fleet. Everybody
    is told it and may draw it — it is theirs — and it is kept apart from the
    server's (admin) screen, which the guest is not told at all."""
    client, admin, guest = fleet
    for_guest = next(q for q in client.get("/api/quills", headers=guest).json() if q["id"] == "fleet")
    assert [s["id"] for s in for_guest["screens"]] == ["garage", "vans", "tracker"]
    tracker = next(s for s in for_guest["screens"] if s["id"] == "tracker")
    assert tracker["settings"] is True and tracker["kit"] == "view" and not tracker.get("admin")
    drawn = client.get("/api/quills/fleet/views/tracker", headers=guest)
    assert drawn.status_code == 200 and "your own settings" in str(drawn.json()["tree"])


def test_a_settings_screen_is_a_view_and_not_the_servers():
    with pytest.raises(QuillError, match="settings is true or false"):
        screen = '[[screens]]\nid = "own"\nkit = "list"\nmodel = "vehicle"\ntitle = "name"\nsettings = "yes"\n'
        parse_manifest(_manifest(screen))
    with pytest.raises(QuillError, match="is settings, so it is a view"):
        screen = '[[screens]]\nid = "own"\nkit = "list"\nmodel = "vehicle"\ntitle = "name"\nsettings = true\n'
        parse_manifest(_manifest(screen))
    with pytest.raises(QuillError, match="settings or admin, not both"):
        screen = '[[screens]]\nid = "own"\nlabel = "Own"\nview = "own"\nsettings = true\nadmin = true\n'
        parse_manifest(_manifest('code = "quill.py"\n' + screen))


def test_a_screen_admin_flag_is_a_bool():
    with pytest.raises(QuillError, match="admin is true or false"):
        screen = '[[screens]]\nid = "keys"\nkit = "list"\nmodel = "vehicle"\ntitle = "name"\nadmin = "yes"\n'
        parse_manifest(_manifest(screen))


def _manifest(extra: str) -> dict:
    import tomllib

    return tomllib.loads('[quill]\nid = "demo"\nname = "Demo"\nversion = "1.0.0"\n' + extra)


def test_a_handler_without_code_to_find_it_in_is_refused():
    with pytest.raises(QuillError, match="code = "):
        parse_manifest(_manifest('[[actions]]\nid = "go"\nlabel = "Go"\n'))


def test_a_handler_the_code_does_not_have_is_refused(tmp_path):
    (tmp_path / "quill.py").write_text(
        "from cloudmorrow.quill import action\n\n@action\ndef go(ctx):\n    pass\n", encoding="utf-8"
    )
    data = _manifest('code = "quill.py"\n[[actions]]\nid = "stop"\nlabel = "Stop"\n')
    with pytest.raises(QuillError, match="action 'stop'"):
        parse_manifest(data, tmp_path)
    data = _manifest('code = "quill.py"\n[[actions]]\nid = "go"\nlabel = "Go"\n')
    assert parse_manifest(data, tmp_path).actions[0]["handler"] == "go"


@pytest.mark.parametrize(
    ("extra", "words"),
    [
        ('[[fetch]]\nhost = "http://example.com"\nwhy = "x"\n', "fetch host"),
        ('[[fetch]]\nhost = "example.com"\n', "says why"),
        ('[[secrets]]\nkey = "lower"\nwhy = "x"\n', "TRACKER_API_KEY"),
        ('[[actions]]\nid = "go"\n', "label"),
        ('[[actions]]\nid = "go"\nlabel = "Go"\n[actions.fields]\nx = "colour"\n', "kind"),
        ('[[hooks]]\non = "task"\nwhen = "renamed"\nhandler = "h"\n', "when is"),
        ('[[machine]]\nid = "m"\n', "why"),
        ('[[actions]]\nid = "go"\nlabel = "Go"\ntimeout = "soon"\n', "duration"),
        ('[[actions]]\nid = "go"\nlabel = "Go"\ntimeout = "10m"\n', "at most 5m"),
        ("[assistant]\ntools = true\n", "says why"),
        ('[assistant]\ntools = true\nwhy = "x"\nmodels = ["task"]\n', "knows tools and why"),
        ("[quill]\n", ""),
    ],
)
def test_the_code_half_of_a_manifest_is_checked(extra, words):
    if extra == "[quill]\n":
        return
    with pytest.raises(QuillError, match=words):
        parse_manifest(_manifest('code = "quill.py"\n' + extra))


# -- actions ---------------------------------------------------------------------------------
def test_an_action_runs_as_whoever_pressed_it(fleet):
    client, admin, guest = fleet
    van_id = add_van(client, guest, "Guest's van")
    state = state_of(client)
    van = state.records.get(Principal.person(GUEST[0]), "vehicle", van_id)
    assert van.owner == GUEST[0]
    assert van.fields["name"] == "Guest's van"
    # Personal: the administrator does not see it.
    listed = client.get("/api/records/vehicle", headers=admin).json()
    assert listed == []
    # What the handler printed is in the Quill's log.
    assert any(f"added {van_id} for guest" in line for line in state.code.tail("fleet"))


def test_an_actions_form_is_checked_before_its_code_runs(fleet):
    client, admin, _ = fleet
    van_id = add_van(client, admin)
    missing = press(client, admin, "log-service", record=van_id, fields={"date": "2026-09-28"})
    assert missing.status_code == 400
    assert "Km is needed" in missing.json()["detail"]["message"]
    wrong = press(client, admin, "log-service", record=van_id, fields={"date": "soon", "km": 1})
    assert wrong.status_code == 400
    unknown = press(client, admin, "log-service", record=van_id, fields={"colour": "red"})
    assert unknown.status_code == 400
    nowhere = press(client, admin, "log-service", fields={"date": "2026-09-28", "km": 1})
    assert "which one" in nowhere.json()["detail"]["message"]


def test_an_action_on_a_record_you_cannot_see_is_not_found(fleet):
    client, admin, guest = fleet
    van_id = add_van(client, admin)
    answer = press(client, guest, "log-service", record=van_id, fields={"date": "2026-09-28", "km": 5})
    assert answer.status_code == 404


def test_the_gate_holds_for_code_as_for_anybody(fleet):
    client, admin, _ = fleet
    answer = press(client, admin, "reach-out")
    assert answer.status_code == 403
    assert "did not ask for contact" in answer.json()["detail"]["message"]


def test_a_hook_runs_when_a_record_changes_and_its_own_writes_do_not_loop(fleet):
    client, admin, _ = fleet
    van_id = add_van(client, admin)
    answer = press(client, admin, "log-service", record=van_id, fields={"date": "2026-09-28", "km": 1200})
    assert answer.json()["effects"] == [{"effect": "toast", "text": "Logged Van at 1200 km"}]
    state = state_of(client)
    state.code.drain()
    van = client.get(f"/api/records/vehicle/{van_id}", headers=admin).json()
    assert van["fields"]["fleet.odometer"] == 1200
    assert van["written_by"] == "fleet"


# -- views -----------------------------------------------------------------------------------
def test_a_view_is_a_tree_drawn_from_what_the_person_may_see(fleet):
    client, admin, guest = fleet
    add_van(client, admin, "Admin's van")
    tree = client.get("/api/quills/fleet/views/garage", headers=admin).json()["tree"]
    assert tree["ui"] == "stack"
    table = next(c for c in tree["children"] if c["ui"] == "table")
    assert [r["fields"]["name"] for r in table["records"]] == ["Admin's van"]
    guest_tree = client.get("/api/quills/fleet/views/garage", headers=guest).json()["tree"]
    guest_table = next(c for c in guest_tree["children"] if c["ui"] == "table")
    assert guest_table["records"] == []


def test_a_view_that_is_not_a_view_is_not_found(fleet):
    client, admin, _ = fleet
    assert client.get("/api/quills/fleet/views/vans", headers=admin).status_code == 404
    assert client.get("/api/quills/fleet/views/nope", headers=admin).status_code == 404


# -- secrets, fetch ------------------------------------------------------------------------------
def test_a_secret_is_the_persons_own_and_named_in_the_manifest(fleet):
    client, admin, _ = fleet
    missing = press(client, admin, "peek")
    assert missing.status_code == 404
    assert "cm secret set TRACKER_KEY" in missing.json()["detail"]["message"]
    state = state_of(client)
    from cloudmorrow.server.secrets import DEFAULT_ENVIRONMENT, DEFAULT_VAULT

    state.secrets.set(ADMIN[0], DEFAULT_VAULT, DEFAULT_ENVIRONMENT, "TRACKER_KEY", "s3cret-value")
    assert press(client, admin, "peek").json()["effects"][0]["text"] == "s3c…"
    manifest = state.quills.quills["fleet"]
    calls = HostCalls(state.code, manifest, Principal("quill", ADMIN[0], quill="fleet"), via="person")
    with pytest.raises(sdk.Refused, match="does not list"):
        calls("secret", {"key": "OTHER"})
    assistant = HostCalls(state.code, manifest, Principal("quill", ADMIN[0], quill="fleet"), via="assistant")
    with pytest.raises(sdk.Refused, match="assistant"):
        assistant("secret", {"key": "TRACKER_KEY"})


def test_fetch_reaches_only_the_hosts_the_manifest_lists_and_only_https(fleet):
    client, _, _ = fleet
    state = state_of(client)
    manifest = state.quills.quills["fleet"]
    calls = HostCalls(state.code, manifest, Principal("quill", ADMIN[0], quill="fleet"), via="person")
    with pytest.raises(sdk.Refused, match="does not list evil.example.org"):
        calls("fetch", {"url": "https://evil.example.org/"})
    with pytest.raises(sdk.Refused, match="https"):
        calls("fetch", {"url": "http://api.example.com/"})
    with pytest.raises(sdk.Refused, match="machine"):
        calls("run", {"command": ["ls"]})


# -- jobs, webhooks, APIs ------------------------------------------------------------------------
def test_a_call_job_runs_as_the_installer_and_is_not_run_again_before_its_time(fleet):
    client, admin, _ = fleet
    add_van(client, admin)
    state = state_of(client)
    started = state.code.run_due()
    assert started == ["fleet/nightly", "fleet/deliver", "fleet/each"]
    import time

    for _ in range(200):
        if not state.code.jobs_status("fleet")[0]["running"]:
            break
        time.sleep(0.02)
    assert any("checked 1 vans" in line for line in state.code.tail("fleet"))
    assert state.code.run_due() == []
    status = state.code.jobs_status("fleet")[0]
    assert status["last_run"] and status["last_error"] == ""


def test_a_job_as_everybody_runs_once_as_each_person_over_their_own_records(fleet):
    client, admin, guest = fleet
    state_of(client).code.run_job("fleet", "each")
    for headers, who in ((admin, ADMIN[0]), (guest, GUEST[0])):
        theirs = client.get("/api/records/fleet.notice", headers=headers).json()
        assert [(r["fields"]["text"], r["owner"]) for r in theirs] == [(f"for {who}", who)]
    plan = client.post("/api/quills/plan", json={"source": str(FLEET)}, headers=admin).json()
    assert "each every 1d, as everybody" in plan["quill_code"]["jobs"]


@pytest.mark.parametrize(
    "extra",
    [
        '[[jobs]]\nid = "xx"\naction = "call"\nhandler = "xx"\nevery = "1h"\nas = "somebody"\n',
        '[[jobs]]\nid = "xx"\naction = "expire"\nmodel = "m"\nfield = "f"\nafter = "1d"\nas = "everybody"\n',
    ],
)
def test_a_job_runs_as_everybody_or_as_the_installer_and_nothing_else(extra):
    with pytest.raises(QuillError, match="as = "):
        parse_manifest(_manifest('code = "quill.py"\n' + extra))


def test_a_quill_may_fetch_from_any_host_out_on_the_internet_and_no_private_one():
    from cloudmorrow.server.quills.code import _host_allowed

    anywhere = ({"host": "*", "why": "to read the feeds people paste"},)
    assert _host_allowed("93.184.216.34", anywhere)
    for inside in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "100.100.1.1", "169.254.1.1", "::1", "localhost", ""):
        assert not _host_allowed(inside, anywhere), inside
    assert not _host_allowed("example.com", ({"host": "api.example.com", "why": "x"},))
    # A test's double answers for any name, but never for an address inside.
    assert _host_allowed("calendar.example", anywhere, resolve=False)
    assert not _host_allowed("10.0.0.1", anywhere, resolve=False)
    code = parse_manifest(_manifest('code = "quill.py"\n[[fetch]]\nhost = "*"\nwhy = "the feeds people paste"\n'))
    assert code.fetch[0]["host"] == "*"


def test_a_webhook_answered_by_code_needs_its_secret(fleet):
    client, admin, _ = fleet
    van_id = add_van(client, admin, registration="CD 34 567")
    state = state_of(client)
    secret = state.quill_tokens.webhook_secret("fleet", "tracker")
    body = {"registration": "CD 34 567", "km": 4321}
    assert client.post("/hooks/fleet/tracker", json=body).status_code == 401
    answer = client.post(f"/hooks/fleet/tracker?token={secret}", json=body)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"updated": van_id}
    van = client.get(f"/api/records/vehicle/{van_id}", headers=admin).json()
    assert van["fields"]["fleet.odometer"] == 4321


def test_an_api_answered_by_code_is_told_who_asked(fleet):
    client, admin, guest = fleet
    add_van(client, admin)
    answer = client.get("/api/q/fleet/summary", headers=guest)
    assert answer.status_code == 200, answer.text
    # It runs as the installer, so it counts their vans, and is told a guest asked.
    assert answer.json() == {"vans": 1, "asked_by": "guest"}
    assert client.get("/api/q/fleet/summary").status_code == 401


def test_the_code_log_is_one_of_the_logs(fleet):
    client, admin, _ = fleet
    add_van(client, admin)
    logs = client.get("/api/quillservices/fleet/logs", headers=admin).json()
    assert any("added" in line for line in logs["code"])


def test_switching_a_quill_off_stops_its_code(fleet):
    client, admin, _ = fleet
    state = state_of(client)
    state.features.set("fleet", False)
    answer = press(client, admin, "add-van", fields={"name": "x"})
    assert answer.status_code == 403


# -- the sandbox ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    if not sandbox.available():
        pytest.skip("wasmtime is not installed")
    try:
        return sandbox.ensure_runtime(Path(sandbox.runtime_dir()))
    except sandbox.SandboxError as exc:
        pytest.skip(f"no sandbox runtime here: {exc}")


@pytest.fixture()
def boxed(config, users, runtime, monkeypatch):
    monkeypatch.setenv("CLOUDMORROW_SANDBOX_DIR", str(runtime.parent))
    config.quill_code = "sandbox"
    app = create_app(config)
    # The server keeps its runtime under its data folder; point it at the cached one.
    (config.data_dir / "sandbox").parent.mkdir(parents=True, exist_ok=True)
    if not (config.data_dir / "sandbox").exists():
        (config.data_dir / "sandbox").symlink_to(runtime.parent, target_is_directory=True)
    client = TestClient(app)
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    assert client.post("/api/quills", json={"source": str(FLEET)}, headers=admin).status_code == 201
    yield client, admin
    client.app.state.cloudmorrow.code.stop()


def test_in_the_sandbox_an_action_and_a_view_work_the_same(boxed):
    client, admin = boxed
    van_id = add_van(client, admin, "Boxed van")
    answer = press(client, admin, "log-service", record=van_id, fields={"date": "2026-09-28", "km": 99})
    assert answer.status_code == 200, answer.text
    state_of(client).code.drain()
    tree = client.get("/api/quills/fleet/views/garage", headers=admin).json()["tree"]
    table = next(c for c in tree["children"] if c["ui"] == "table")
    assert table["records"][0]["fields"]["fleet.odometer"] == 99


def test_in_the_sandbox_the_code_can_reach_nothing_but_the_host(boxed, tmp_path):
    client, _ = boxed
    state = state_of(client)
    manifest = state.quills.quills["fleet"]
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "quill.py").write_text(
        "import os, socket\n"
        "from cloudmorrow.quill import action, toast\n\n"
        "@action\n"
        "def probe(ctx):\n"
        "    found = []\n"
        "    for attempt in (lambda: open('/etc/passwd').read(),\n"
        "                    lambda: open('/quill/x', 'w'),\n"
        "                    lambda: socket.create_connection(('1.1.1.1', 80), timeout=1),\n"
        "                    lambda: os.environ['HOME']):\n"
        "        try:\n"
        "            attempt()\n"
        "            found.append('reached')\n"
        "        except Exception as exc:\n"
        "            found.append(type(exc).__name__)\n"
        "    return toast(' '.join(found))\n",
        encoding="utf-8",
    )
    guest = sandbox.Guest(probe, "quill.py", runtime_base=Path(sandbox.runtime_dir()))
    try:
        effects = guest.call("action", "probe", {}, {}, lambda op, args: None)
    finally:
        guest.stop()
    assert "reached" not in effects[0]["text"], effects
    assert manifest.code == "quill.py"


def test_a_handler_that_runs_forever_is_stopped(boxed, tmp_path):
    (tmp_path / "quill.py").write_text(
        "from cloudmorrow.quill import action\n\n@action\ndef spin(ctx):\n    while True:\n        pass\n",
        encoding="utf-8",
    )
    guest = sandbox.Guest(tmp_path, "quill.py", runtime_base=Path(sandbox.runtime_dir()))
    try:
        with pytest.raises(sandbox.Failed) as failed:
            guest.call("action", "spin", {}, {}, lambda op, args: None, timeout=1.0)
        assert failed.value.kind == "timeout"
        assert not guest.running
    finally:
        guest.stop()


# -- to an assistant ------------------------------------------------------------------------------
def test_every_action_is_an_assistants_tool_but_the_ones_kept_from_it(fleet):
    from cloudmorrow.server import mcptools

    client, _, _ = fleet
    state = state_of(client)
    admin = state.users.get(ADMIN[0])
    tools = {t.name: t for t in mcptools.available(state, admin)}
    assert "fleet_add_van" in tools and "fleet_log_service" in tools
    assert "fleet_peek" not in tools  # assistant = false
    schema = tools["fleet_log_service"].schema
    assert schema["required"] == ["record", "date", "km"]
    assert schema["properties"]["km"]["type"] == "integer"

    made = mcptools.call(state, admin, "fleet_add_van", {"name": "Via assistant"})
    assert not made.get("isError"), made
    van_id = made["structuredContent"]["opened"][0]["id"]
    logged = mcptools.call(state, admin, "fleet_log_service", {"record": van_id, "date": "2026-09-28"})
    assert logged["isError"] and "Km is needed" in logged["content"][0]["text"]
    with pytest.raises(KeyError):
        mcptools.call(state, admin, "fleet_peek", {})


# -- on the command line ------------------------------------------------------------------------
@pytest.fixture()
def cm(fleet, monkeypatch):
    import asyncio
    import io

    import httpx
    from rich.console import Console

    from cloudmorrow.cli import quillrun
    from cloudmorrow.client.api import CloudmorrowClient
    from cloudmorrow.client.config import ClientConfig

    client, _, _ = fleet

    def run(*argv: str, screen: str = "", plain: bool = False) -> str:
        screen_out = Console(file=io.StringIO(), width=200, color_system=None)
        monkeypatch.setattr(quillrun, "out", screen_out)
        monkeypatch.setattr(quillrun, "console", screen_out)
        monkeypatch.setattr(quillrun, "emit", screen_out.file.write)
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token_for(client, *ADMIN))
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver")

        async def go() -> None:
            try:
                await quillrun.dispatch(api, "fleet", argv[0], list(argv[1:]), screen_id=screen, plain=plain)
            finally:
                await api.aclose()

        asyncio.run(go())
        return screen_out.file.getvalue()

    return run


def test_on_the_command_line_every_action_is_a_command_and_a_view_prints(cm, fleet):
    import typer

    from cloudmorrow.client.api import ApiError

    listed = cm("actions")
    assert "log-service <vehicle> date=… km=… [note=…]" in listed
    assert "Added Transit" in cm("add-van", "name=Transit", "registration=AB 12 345")
    assert "Logged Transit at 1200 km" in cm("log-service", "Transit", "date=2026-09-28", "km=1200")
    state_of(fleet[0]).code.drain()
    garage = cm("list")
    assert "Garage" in garage and "Transit" in garage and "1200" in garage and "[Add a van]" in garage
    assert '"ui": "stack"' in cm("list", plain=True)
    assert "Transit" in cm("list", screen="vans")
    # The server's refusal, in its own words: `cm` prints it and exits 1.
    with pytest.raises(ApiError, match="Km is needed"):
        cm("log-service", "Transit", "date=2026-09-28")
    with pytest.raises(typer.Exit):
        cm("log-service", "date=2026-09-28", "km=1")  # which van?


# -- on a person's own machine ---------------------------------------------------------------------
def _machine(client, tmp_path, guest=None, *, switched_on=True):
    from cloudmorrow.agent.client import AgentClient
    from cloudmorrow.agent.config import AgentConfig
    from cloudmorrow.agent.quills import MachineQuills

    state = state_of(client)
    _, token = state.agents.enroll_for_user(ADMIN[0], name="laptop")
    exports = tmp_path / "Tracker"
    exports.mkdir(exist_ok=True)
    (exports / "week.csv").write_text("registration,date,km\nAB 12 345,2026-09-20,1500\n", encoding="utf-8")
    config = AgentConfig(server_url="http://testserver", agent_token=token, allow_insecure_http=True)
    config.path = tmp_path / "agent.toml"
    if switched_on:
        config.quills = {"fleet": {"import-exports": {"folders": {"exports": str(exports)}}}}
    config.save()
    agent = AgentClient(config)
    agent._client = client  # the TestClient is an httpx.Client
    agent._client.headers["User-Agent"] = "cloudmorrow-agent/test"
    return MachineQuills(config, agent, base=tmp_path / "quills", guest=guest), state


def test_a_machine_handler_runs_only_where_it_was_switched_on(fleet, tmp_path):
    from cloudmorrow.sandbox import InProcessGuest

    client, admin, _ = fleet
    add_van(client, admin)
    machine, _ = _machine(client, tmp_path, InProcessGuest, switched_on=False)
    with pytest.raises(sdk.Refused, match="not switched on"):
        machine.run("fleet", "import-exports")
    assert machine.tick() == []


def test_a_machine_handler_reads_its_folder_and_writes_records_as_the_owner(fleet, tmp_path):
    from cloudmorrow.sandbox import InProcessGuest

    client, admin, _ = fleet
    van_id = add_van(client, admin)
    machine, state = _machine(client, tmp_path, InProcessGuest)
    assert machine.run("fleet", "import-exports") == {"made": 1}
    visits = client.get("/api/records/fleet.visit", headers=admin).json()
    assert [v["fields"]["km"] for v in visits] == [1500]
    assert visits[0]["fields"]["vehicle"] == van_id
    # On its clock: once now, then not again before its `every`.
    assert machine.tick() == ["fleet/import-exports"]
    assert machine.tick() == []


def test_a_machine_handlers_requests_are_bound_by_the_manifest_on_the_server(fleet, tmp_path):
    client, _, _ = fleet
    machine, _ = _machine(client, tmp_path)
    refused = machine.client.quill_host("fleet", "records.list", {"model": "contact"})
    assert refused["ok"] is False and refused["kind"] == "refused"
    assert machine.client.quill_host("fleet", "run", {"command": ["ls"]})["kind"] == "refused"
    ok = machine.client.quill_host("fleet", "records.list", {"model": "vehicle"})
    assert ok == {"ok": True, "value": []}


def test_in_the_sandbox_a_machine_handler_sees_only_its_folder(fleet, tmp_path, runtime, monkeypatch):
    client, admin, _ = fleet
    add_van(client, admin)
    machine, _ = _machine(client, tmp_path)
    monkeypatch.setattr(machine, "base", tmp_path / "quills")
    (tmp_path / "quills").mkdir(exist_ok=True)
    (tmp_path / "quills" / "sandbox").symlink_to(runtime.parent, target_is_directory=True)
    assert machine.run("fleet", "import-exports") == {"made": 1}


def test_a_table_or_cards_may_go_to_a_screen_of_the_quills_own():
    from cloudmorrow.quill import ui
    from cloudmorrow.quill.ui import TreeError

    rows = [{"id": "r1", "model": "letter", "fields": {"subject": "Hi"}}]
    table = ui.table(rows, columns=["subject"], go="one", param="letter", params={"folder": "inbox"})
    assert table["go"] == "one" and table["param"] == "letter" and table["params"] == {"folder": "inbox"}
    assert "go" not in ui.table(rows, columns=["subject"]) and "param" not in ui.table(rows, columns=["subject"])
    assert ui.cards(rows, title="subject", go="one")["param"] == "record"
    ui.check(ui.stack(table), actions=set(), screens={"one", "post"})
    with pytest.raises(TreeError, match="goes to 'two'"):
        ui.check(ui.stack(ui.cards(rows, title="subject", go="two")), actions=set(), screens={"one"})


def test_a_form_field_may_suggest_people_warn_of_outsiders_and_wait_behind_more():
    """`suggest`, `outside` and `extra` reach the client on the field, and are checked."""
    manifest = parse_manifest(
        _manifest(
            'code = "quill.py"\n[[actions]]\nid = "send"\nlabel = "Send"\n[actions.fields]\n'
            'to = { kind = "string", required = true, suggest = "people", outside = "Outside the server" }\n'
            'cc = { kind = "string", suggest = "people", extra = true }\n'
        )
    )
    (action,) = manifest.actions
    to, cc = action["fields"]
    assert to["suggest"] == "people" and to["outside"] == "Outside the server" and "extra" not in to
    assert cc["extra"] is True
    with pytest.raises(QuillError, match="suggest is"):
        parse_manifest(
            _manifest(
                'code = "quill.py"\n[[actions]]\nid = "a"\nlabel = "A"\n[actions.fields]\n'
                'to = { kind = "string", suggest = "robots" }\n'
            )
        )
    with pytest.raises(QuillError, match="outside goes with suggest"):
        parse_manifest(
            _manifest(
                'code = "quill.py"\n[[actions]]\nid = "a"\nlabel = "A"\n[actions.fields]\n'
                'to = { kind = "string", outside = "x" }\n'
            )
        )
    with pytest.raises(QuillError, match="is a string"):
        parse_manifest(
            _manifest(
                'code = "quill.py"\n[[actions]]\nid = "a"\nlabel = "A"\n[actions.fields]\n'
                'to = { kind = "text", suggest = "people" }\n'
            )
        )


def test_a_view_may_name_its_pen(fleet):
    """`compose` on a view is one of the Quill's actions, told to the client with the screen."""
    client, admin, _ = fleet
    quill = next(q for q in client.get("/api/quills", headers=admin).json() if q["id"] == "fleet")
    garage = next(s for s in quill["screens"] if s["id"] == "garage")
    assert garage["compose"] == {"action": "add-van", "label": "New van"}
    with pytest.raises(QuillError, match="compose is"):
        parse_manifest(
            _manifest('code = "quill.py"\n[[screens]]\nid = "home"\nlabel = "Home"\nview = "home"\ncompose = "send"\n')
        )
    with pytest.raises(QuillError, match="compose is"):
        parse_manifest(
            _manifest(
                'code = "quill.py"\n[[screens]]\nid = "home"\nlabel = "Home"\nview = "home"\n'
                'compose = { action = "nope" }\n[[actions]]\nid = "send"\nlabel = "Send"\n'
            )
        )


# -- an assistant's tools, as the person (fixtures/quill-aide) ----------------------------------
AIDE = Path(__file__).parent / "fixtures" / "quill-aide"


@pytest.fixture()
def aide(config, users):
    client = TestClient(_app(config, users, "trusted"))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    answer = client.post("/api/quills", json={"source": str(AIDE)}, headers=admin)
    assert answer.status_code == 201, answer.text
    guest = {"Authorization": "Bearer " + token_for(client, *GUEST)}
    return client, admin, guest


def aide_press(client, headers, action, **fields):
    return client.post(f"/api/quills/aide/actions/{action}", json={"fields": fields}, headers=headers)


def test_the_install_sheet_says_the_code_has_an_assistants_tools_and_how_long_an_action_has(aide):
    client, admin, _ = aide
    plan = client.post("/api/quills/plan", json={"source": str(AIDE)}, headers=admin).json()
    assert plan["quill_code"]["assistant"] == {"tools": True, "why": "to answer questions over the person's own data"}
    # `timeout = "2m"` is kept as seconds; an action without one has a call's fifteen.
    actions = {a["id"]: a for a in plan["actions"]}
    assert actions["count"]["timeout"] == 120.0 and "timeout" not in actions["tools"]


def test_a_quills_code_has_an_assistants_tools_as_the_person(aide):
    client, admin, guest = aide
    said = aide_press(client, admin, "tools").json()["effects"][0]["text"]
    assert "list_records" in said and "quill_dev_install" in said and "get_record" in said
    # As the person, through the gate: the administrator's public record is
    # everybody's to count; a guest's own vehicle would not be the administrator's.
    assert aide_press(client, admin, "connect", key="sk-ant-1").status_code == 200
    counted = aide_press(client, guest, "count", model="aide.settings").json()["effects"][0]["text"]
    assert counted == "1"
    nowhere = aide_press(client, guest, "count", model="spaceship").json()["effects"][0]
    assert nowhere["effect"] == "error" and "no datamodel" in nowhere["text"]


def test_the_tools_are_refused_without_the_declaration_and_to_code_an_assistant_started(aide, fleet):
    client, admin, _ = aide
    state = state_of(client)
    manifest = state.quills.quills["aide"]
    started = HostCalls(state.code, manifest, Principal("quill", ADMIN[0], quill="aide"), via="assistant")
    with pytest.raises(sdk.Refused, match="assistant"):
        started("assistant.tools", {})
    fleet_client, _, _ = fleet
    fleet_state = state_of(fleet_client)
    plain = HostCalls(
        fleet_state.code, fleet_state.quills.quills["fleet"], Principal("quill", ADMIN[0], quill="fleet"), via="person"
    )
    with pytest.raises(sdk.Refused, match="does not say"):
        plain("assistant.call", {"name": "list_datamodels"})
    with pytest.raises(sdk.NotFound, match="no tool"):
        HostCalls(state.code, manifest, Principal("quill", ADMIN[0], quill="aide"), via="person")(
            "assistant.call", {"name": "launch_rockets"}
        )


def test_an_administrator_builds_a_quill_of_their_own_through_the_quills_code(aide):
    client, admin, _ = aide
    manifest = '[quill]\nid = "plants"\nname = "Plants"\nversion = "0.1.0"\nsummary = "x"\ncategory = "home"\n'
    said = aide_press(client, admin, "build", manifest=manifest).json()["effects"][0]
    assert said == {"effect": "toast", "text": ADMIN[0]}
    mine = {q["id"]: q for q in client.get("/api/quills", headers=admin).json()}
    assert mine["plants"]["key"] == f"~{ADMIN[0]}.plants"


def test_a_secret_of_an_introduced_datamodel_is_the_quills_own_code_to_read(aide):
    client, admin, guest = aide
    assert aide_press(client, admin, "connect", key="sk-ant-1").status_code == 200
    record = client.get("/api/records/aide.settings", headers=admin).json()[0]
    # Through the record API the one record says null there — to the
    # administrator who typed it, to anybody, to an assistant.
    for headers in (admin, guest):
        got = client.get(f"/api/records/aide.settings/{record['id']}", headers=headers).json()
        assert got["fields"]["status"] == "set" and got["fields"]["key"] is None
    state = state_of(client)
    assert (
        state.records.get(Principal.assistant(ADMIN[0], admin=True), "aide.settings", record["id"]).fields["key"]
        is None
    )
    # The Quill's own code reads it, as whoever is using the Quill.
    assert aide_press(client, guest, "peek").json()["effects"][0]["text"] == "sk-ant-1"
    assert aide_press(client, admin, "peek").json()["effects"][0]["text"] == "sk-ant-1"
