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
    assert code["views"] == ["Garage"]
    assert "Log a service" in code["actions"]
    assert code["hooks"] == ["when a fleet.visit is created"]
    assert code["fetch"] == [{"host": "api.example.com", "why": "to read each van's odometer from the tracker"}]
    assert code["secrets"][0]["key"] == "TRACKER_KEY"
    assert code["machine"][0]["folders"] == ["exports (read)"]


def test_every_client_is_told_the_actions_and_the_view(fleet):
    client, admin, _ = fleet
    quill = next(q for q in client.get("/api/quills", headers=admin).json() if q["id"] == "fleet")
    assert [s["kit"] for s in quill["screens"]] == ["view", "list"]
    log_service = next(a for a in quill["actions"] if a["id"] == "log-service")
    assert log_service["on"] == "vehicle"
    assert [f["name"] for f in log_service["fields"]] == ["date", "km", "note"]
    assert log_service["fields"][0]["required"] is True


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
    assert started == ["fleet/nightly"]
    import time

    for _ in range(200):
        if not state.code.jobs_status("fleet")[0]["running"]:
            break
        time.sleep(0.02)
    assert any("checked 1 vans" in line for line in state.code.tail("fleet"))
    assert state.code.run_due() == []
    status = state.code.jobs_status("fleet")[0]
    assert status["last_run"] and status["last_error"] == ""


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
