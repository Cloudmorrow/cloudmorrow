"""A Quill's code, run: services kept up, its token's reach, APIs, webhooks, run jobs.

These start a real server on a loopback port — a service reaches the record
API over HTTP like any client — and install `fixtures/quill-relay`, whose
service writes a ping with its token when it starts and answers a few
routes. The supervisor's waits are made short so the whole file is quick.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from cloudmorrow.server import quillservices
from cloudmorrow.server.app import create_app
from cloudmorrow.server.quillhooks import PathError, RateLimit, apply_map, parse_path
from cloudmorrow.server.quilljobs import Clock
from cloudmorrow.server.quills import QuillError, parse_manifest
from cloudmorrow.server.quillservices import Supervisor, free_port
from tests.conftest import ADMIN, GUEST

RELAY = Path(__file__).parent / "fixtures" / "quill-relay"


def wait_for(check, timeout: float = 15.0, what: str = "it"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"waited {timeout}s for {what}")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie is not alive: it has exited and waits to be reaped.
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


class Live:
    """A running server, its state, and a client for it."""

    def __init__(self, config, app, server, thread) -> None:
        self.config = config
        self.app = app
        self.server = server
        self.thread = thread
        self.state = app.state.cloudmorrow
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{config.port}", timeout=10)
        self.admin = {"Authorization": "Bearer " + self._login(*ADMIN)}
        self.guest = {"Authorization": "Bearer " + self._login(*GUEST)}

    def _login(self, username: str, password: str) -> str:
        answer = self.http.post("/api/auth/login", json={"username": username, "password": password})
        assert answer.status_code == 200, answer.text
        return answer.json()["access_token"]

    @property
    def supervisor(self) -> Supervisor:
        return self.state.services

    def install(self) -> dict:
        answer = self.http.post("/api/quills", json={"source": str(RELAY)}, headers=self.admin)
        assert answer.status_code == 201, answer.text
        return answer.json()

    def service(self, name: str = "web") -> dict:
        rows = self.http.get("/api/quillservices", headers=self.admin).json()
        relay = next(r for r in rows if r["id"] == "relay")
        return next(s for s in relay["services"] if s["id"] == name)

    def running(self, name: str = "web") -> dict:
        return wait_for(
            lambda: (s := self.service(name))["state"] == "running" and s["port"] and s,
            what=f"{name} running",
        )

    def pings(self, headers: dict | None = None, **where) -> list[dict]:
        answer = self.http.get("/api/records/relay.ping", params=where, headers=headers or self.admin)
        assert answer.status_code == 200, answer.text
        return answer.json()

    def quill_token(self) -> dict:
        return {"Authorization": "Bearer " + self.supervisor.token("relay")}


@pytest.fixture()
def live(config, users, monkeypatch):
    # Short waits: a failed service is back in a tenth of a second.
    monkeypatch.setattr(Supervisor, "TICK", 0.05)
    monkeypatch.setattr(Supervisor, "BACKOFF_FIRST", 0.1)
    monkeypatch.setattr(Supervisor, "GRACE", 3.0)
    # The clock's boot work and its half-minute run jobs are not what is
    # tested here; `run_due` is called by hand.
    monkeypatch.setattr(Clock, "start", lambda self: None)
    config.port = free_port()
    app = create_app(config)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=config.port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for(lambda: server.started, what="the server")
    here = Live(config, app, server, thread)
    yield here
    here.http.close()
    server.should_exit = True
    thread.join(timeout=15)


# -- running ------------------------------------------------------------------------------
def test_a_service_starts_and_writes_with_its_own_token(live):
    live.install()
    service = live.running()
    assert service["command"] == ["python", "services/web.py"]
    ping = wait_for(lambda: live.pings(source="service"), what="the service's ping")[0]
    # Written as the Quill, into the records of the admin who installed it.
    assert ping["written_by"] == "relay" and ping["owner"] == ADMIN[0]
    assert ping["fields"]["text"] == "hello from the service"
    log = live.http.get("/api/quillservices/relay/logs", params={"service": "web"},
                        headers=live.admin).json()["web"]
    assert any("started python services/web.py" in line for line in log)
    assert any(line.startswith("wrote ") for line in log)
    log_file = live.config.data_dir / "logs" / "quills" / "relay" / "web.log"
    assert log_file.is_file()


def test_a_service_is_given_what_it_needs_and_nothing_of_the_servers(live, monkeypatch):
    monkeypatch.setenv("CLOUDMORROW_SECRET_KEY", "the-servers-own-secret")
    monkeypatch.setenv("CLOUDMORROW_CONFIG", "/etc/cloudmorrow/server.toml")
    live.install()
    live.running()
    answer = live.http.get("/api/q/relay/env", headers=live.admin)
    assert answer.status_code == 200, answer.text
    env = answer.json()
    assert set(env) - {"PWD", "LC_CTYPE", "SHLVL", "_"} == {
        "PATH", "LANG", "HOME", "PYTHONUNBUFFERED", "CLOUDMORROW_URL",
        "CLOUDMORROW_TOKEN", "CLOUDMORROW_QUILL", "CLOUDMORROW_SERVICE", "PORT",
    }
    assert env["CLOUDMORROW_URL"] == f"http://127.0.0.1:{live.config.port}"
    assert env["CLOUDMORROW_QUILL"] == "relay" and env["CLOUDMORROW_SERVICE"] == "web"
    assert env["CLOUDMORROW_TOKEN"].startswith("cmq_")
    assert env["HOME"] == str(live.config.data_dir / "quill-homes" / "relay")
    everything = json.dumps(env)
    assert "the-servers-own-secret" not in everything
    assert live.config.secret_key not in everything
    assert str(live.config.secrets_key_path) not in everything


def test_a_service_that_falls_over_is_started_again(live):
    live.install()
    first = live.running()
    assert live.http.get("/api/q/relay/crash", headers=live.admin).status_code == 502
    again = wait_for(
        lambda: (s := live.service())["state"] == "running" and s["pid"] != first["pid"] and s,
        what="a restart",
    )
    assert again["last_exit"] == 3 and again["restarts"] >= 1
    assert not alive(first["pid"])


def test_the_services_stop_with_the_server(live):
    live.install()
    pid = live.running()["pid"]
    live.server.should_exit = True
    live.thread.join(timeout=15)
    assert not alive(pid)


def test_switching_a_quill_off_stops_it_and_its_token(live):
    live.install()
    pid = live.running()["pid"]
    token = live.quill_token()
    assert live.http.get("/api/records/relay.ping", headers=token).status_code == 200
    off = live.http.patch("/api/server/features/relay", json={"enabled": False}, headers=live.admin)
    assert off.status_code == 200, off.text
    wait_for(lambda: live.service()["state"] == "stopped", what="the service to stop")
    assert not alive(pid)
    assert live.http.get("/api/records/relay.ping", headers=token).status_code == 401
    assert live.http.get("/api/q/relay/whoami", headers=live.admin).status_code == 403
    live.http.patch("/api/server/features/relay", json={"enabled": True}, headers=live.admin)
    assert live.running()["pid"] != pid


def test_uninstalling_stops_everything_and_revokes_the_token(live):
    live.install()
    pid = live.running()["pid"]
    token = live.quill_token()
    secret = live.state.quill_tokens.webhook_secret("relay", "inbound")
    assert live.http.delete("/api/quills/relay", headers=live.admin).status_code == 204
    wait_for(lambda: not alive(pid), what="the service to stop")
    assert live.http.get("/api/records/relay.ping", headers=token).status_code == 401
    assert live.state.quill_tokens.holders() == []
    assert live.http.post(f"/hooks/relay/inbound?token={secret}", json={}).status_code == 404
    assert live.supervisor.token("relay") == ""


# -- the token's reach -------------------------------------------------------------------
def test_a_quill_token_opens_the_record_api_for_its_own_models_only(live):
    for other in ("tasks", "notes", "secrets"):
        live.state.quills.install_from_catalog(other)
    live.install()
    live.running()
    token = live.quill_token()
    assert live.http.get("/api/records/relay.ping", headers=token).status_code == 200
    made = live.http.post("/api/records/relay.ping", json={"fields": {"text": "by hand"}},
                          headers=token)
    assert made.status_code == 201 and made.json()["written_by"] == "relay"
    # Not a datamodel it declared.
    refused = live.http.get("/api/records/task", headers=token)
    assert refused.status_code == 403 and "did not ask for task" in refused.text
    # And nothing else the server has: to every other door it is nobody.
    for path in ("/api/notes/tree", "/api/secrets", "/api/users", "/api/auth/me", "/api/quills",
                 "/api/datamodels", "/api/people", "/api/quillservices", "/api/today",
                 "/api/shares", "/api/me/features"):
        assert live.http.get(path, headers=token).status_code == 401, path
    assert live.http.get("/api/secrets", headers=live.admin).status_code == 200
    assert live.http.post("/mcp", json={}, headers=token).status_code == 401
    # A token nobody issued is nobody.
    bogus = {"Authorization": "Bearer cmq_not-a-token"}
    assert live.http.get("/api/records/relay.ping", headers=bogus).status_code == 401


def test_rotating_the_token_cuts_off_the_old_one_and_restarts_the_services(live):
    live.install()
    first = live.running()
    wait_for(lambda: live.pings(source="service"), what="the first ping")
    old = live.quill_token()
    rotated = live.http.post("/api/quillservices/relay/token", headers=live.admin)
    # Said to have happened; the token itself is never handed out.
    assert rotated.status_code == 200 and "cmq_" not in rotated.text
    assert live.http.get("/api/records/relay.ping", headers=old).status_code == 401
    wait_for(lambda: live.service()["pid"] not in (None, first["pid"]), what="a restart")
    # The restarted service wrote again, with the new token.
    wait_for(lambda: len(live.pings(source="service")) == 2, what="the second ping")


# -- APIs ------------------------------------------------------------------------------------
def test_an_api_is_proxied_with_who_is_asking_and_not_their_token(live):
    live.install()
    live.running()
    answer = live.http.get(
        "/api/q/relay/whoami?x=1",
        headers=live.guest | {"X-Cloudmorrow-User": "somebody-else", "Cookie": "a=b"},
    )
    assert answer.status_code == 200, answer.text
    seen = answer.json()
    assert seen == {"path": "/whoami?x=1", "user": GUEST[0], "quill": None, "api": "api",
                    "authorization": None, "cookie": None}
    # A service does not set cookies on the cloud's own address.
    assert "set-cookie" not in answer.headers
    assert live.http.get("/api/q/relay/whoami").status_code == 401
    own = live.http.get("/api/q/relay/whoami", headers=live.quill_token()).json()
    assert own["quill"] == "relay" and own["user"] is None
    assert live.http.get("/api/q/nothing/whoami", headers=live.admin).status_code == 404


def test_an_api_whose_service_is_down_says_so(live):
    live.install()
    live.running()
    live.supervisor.stop()
    answer = live.http.get("/api/q/relay/whoami", headers=live.admin)
    assert answer.status_code == 503 and "not running" in answer.text


# -- webhooks --------------------------------------------------------------------------------
def test_a_webhook_makes_a_record_from_its_body_with_the_secret(live):
    live.install()
    secret = live.state.quill_tokens.webhook_secret("relay", "inbound")
    body = {"message": {"text": "from outside"}, "items": [{"n": 1}, {"n": 7}], "from": "stripe"}
    assert live.http.post("/hooks/relay/inbound", json=body).status_code == 401
    assert live.http.post("/hooks/relay/inbound?token=wrong", json=body).status_code == 401
    made = live.http.post(f"/hooks/relay/inbound?token={secret}", json=body)
    assert made.status_code == 201, made.text
    record = live.http.get(f"/api/records/relay.ping/{made.json()['id']}", headers=live.admin).json()
    assert record["fields"] == {"text": "from outside", "count": 7, "source": "stripe"}
    assert record["written_by"] == "relay"
    by_header = live.http.post("/hooks/relay/inbound", json=body,
                               headers={"X-Cloudmorrow-Webhook-Token": secret})
    assert by_header.status_code == 201
    # A body the map finds nothing in is a record the datamodel refuses.
    assert live.http.post(f"/hooks/relay/inbound?token={secret}", json={}).status_code == 400
    assert live.http.post(f"/hooks/relay/inbound?token={secret}",
                          content=b"x" * (1024 * 1024 + 1)).status_code == 413


def test_a_webhook_may_be_signed_instead(live):
    live.install()
    secret = live.state.quill_tokens.webhook_secret("relay", "signed")
    body = json.dumps({"text": "signed"}).encode()
    good = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    bad = "sha256=" + hmac.new(b"nope", body, hashlib.sha256).hexdigest()
    assert live.http.post("/hooks/relay/signed", content=body,
                          headers={"X-Hub-Signature-256": bad}).status_code == 401
    assert live.http.post("/hooks/relay/signed", content=body,
                          headers={"X-Hub-Signature-256": good}).status_code == 201


def test_a_forwarding_webhook_reaches_the_service_without_its_secret(live):
    live.install()
    live.running()
    secret = live.state.quill_tokens.webhook_secret("relay", "raw")
    answer = live.http.post("/hooks/relay/raw?token=" + secret, content=b"hello",
                            headers={"X-Cloudmorrow-Webhook-Token": secret})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"path": "/hooks/raw", "body": "hello", "webhook": "raw", "token": None}


def test_rotating_a_webhook_secret_refuses_the_old_one(live):
    live.install()
    old = live.state.quill_tokens.webhook_secret("relay", "inbound")
    rotated = live.http.post("/api/quillservices/relay/webhooks/inbound/secret", headers=live.admin)
    assert rotated.status_code == 200
    new = rotated.json()["secret"]
    assert new != old and rotated.json()["url"].endswith("/hooks/relay/inbound")
    body = {"message": {"text": "x"}}
    assert live.http.post(f"/hooks/relay/inbound?token={old}", json=body).status_code == 401
    assert live.http.post(f"/hooks/relay/inbound?token={new}", json=body).status_code == 201


# -- run jobs --------------------------------------------------------------------------------
def test_a_run_job_starts_its_service_once_when_due(live):
    live.install()
    # A service a job names is the job's: not kept up on its own.
    assert live.service("tick")["state"] == "stopped"
    assert live.supervisor.run_due() == ["relay.tick"]
    wait_for(lambda: live.pings(source="job"), what="the job's ping")
    assert live.supervisor.run_due() == []  # not due again for an hour
    job = wait_for(
        lambda: (j := next(j for j in live.http.get("/api/quillservices", headers=live.admin)
                           .json()[0]["jobs"])) and j["last_exit"] is not None and j,
        what="the job to finish",
    )
    assert job["last_exit"] == 0 and job["last_started"]


def test_a_run_job_never_runs_twice_at_once(live, monkeypatch):
    live.install()
    # Due every time it is asked…
    monkeypatch.setattr(quillservices, "parse_duration", lambda text: dt.timedelta(0))
    # …and still running from last time.
    sleeper = subprocess.Popen(["sleep", "30"])
    live.supervisor._jobs[("relay", "tick")] = sleeper
    try:
        assert live.supervisor.run_due() == []
    finally:
        sleeper.kill()
        sleeper.wait()
    assert live.supervisor.run_due() == ["relay.tick"]
    wait_for(lambda: live.pings(source="job"), what="the job's ping")


# -- administration ----------------------------------------------------------------------------
def test_an_administrator_sees_what_runs_and_the_webhooks(live):
    live.install()
    live.running()
    rows = live.http.get("/api/quillservices", headers=live.admin)
    assert rows.status_code == 200
    relay = rows.json()[0]
    assert relay["runs_as"] == ADMIN[0] and relay["reach"] == ["relay.ping"]
    assert relay["token"]["issued_at"]
    hooks = {h["id"]: h for h in relay["webhooks"]}
    assert hooks["inbound"]["url"].endswith("/hooks/relay/inbound")
    assert hooks["inbound"]["secret"] == live.state.quill_tokens.webhook_secret("relay", "inbound")
    assert hooks["signed"]["signature"] == "X-Hub-Signature-256"
    web = next(s for s in relay["services"] if s["id"] == "web")
    assert any("started" in line for line in web["log"])
    assert live.http.get("/api/quillservices", headers=live.guest).status_code == 403
    assert live.http.post("/api/quillservices/relay/token", headers=live.guest).status_code == 403


def test_the_install_sheet_says_what_runs_and_as_whom(live):
    plan = live.http.post("/api/quills/plan", json={"source": str(RELAY)}, headers=live.admin).json()
    assert plan["runs_code"] == ["python services/web.py", "python services/tick.py"]
    assert plan["reach"] == ["relay.ping"] and plan["runs_as"] == ""
    assert "not_running_yet" not in plan
    live.install()
    installed = live.http.get("/api/quills/relay", headers=live.admin).json()
    assert installed["runs_as"] == ADMIN[0]


# -- pieces, without a server ----------------------------------------------------------------
def test_map_paths_are_a_small_safe_subset():
    assert parse_path("$.a.b[0].c") == ("a", "b", 0, "c")
    assert parse_path('$["odd name"][-1]') == ("odd name", -1)
    assert parse_path("$") == ()
    for bad in ("a.b", "$..a", "$.a[?(@.x)]", "$.a[*]", "$.a()", ""):
        with pytest.raises(PathError):
            parse_path(bad)
    body = {"a": {"b": [{"c": 1}]}, "list": [1, 2]}
    assert apply_map(body, {"x": "$.a.b[0].c", "y": "$.list[5]", "z": "$.nope"}) == {"x": 1}
    assert apply_map([1], {"x": "$.a"}) == {}


def test_a_rate_limit_slows_a_noisy_sender():
    limit = RateLimit(limit=2, window=60)
    assert limit.allow("k") and limit.allow("k") and not limit.allow("k")
    assert limit.allow("other")


def _manifest(**extra) -> dict:
    data = {"quill": {"id": "relay", "name": "Relay", "version": "1.0.0"},
            "services": [{"id": "web", "command": ["python", "web.py"]}]}
    data.update(extra)
    return data


def test_the_manifest_is_checked_for_what_runs():
    with pytest.raises(QuillError, match="runs one of its services"):
        parse_manifest(_manifest(jobs=[{"id": "tick", "action": "run", "every": "1h"}]))
    with pytest.raises(QuillError, match="runs every so often"):
        parse_manifest(_manifest(jobs=[{"id": "tick", "action": "run", "service": "web"}]))
    with pytest.raises(QuillError, match="one of them"):
        parse_manifest(_manifest(webhooks=[{"id": "hook", "model": "x", "forward": "web"}]))
    with pytest.raises(QuillError, match="map"):
        parse_manifest(_manifest(webhooks=[{"id": "hook", "model": "x", "map": {"a": "b.c"}}]))
    with pytest.raises(QuillError, match="path"):
        parse_manifest(_manifest(webhooks=[{"id": "hook", "path": "../x", "forward": "web"}]))
    with pytest.raises(QuillError, match="always"):
        parse_manifest(_manifest(services=[{"id": "web", "command": ["x"], "always": "yes"}]))
    ok = parse_manifest(_manifest(webhooks=[{"id": "hook", "forward": "web"}]))
    assert ok.webhooks[0]["path"] == "hook"


def test_the_clock_asks_for_due_jobs(config, users):
    app = create_app(config)
    state = app.state.cloudmorrow
    asked = threading.Event()
    clock = Clock(config.db_path, state.quills, state.records, on_tick=asked.set)
    clock.start()
    try:
        assert asked.wait(10)
    finally:
        clock.stop()


def test_the_command_line_shows_services_and_logs(client, monkeypatch):
    from typer.testing import CliRunner

    from cloudmorrow.cli import quill as quill_cli
    from cloudmorrow.client.api import CloudmorrowClient
    from cloudmorrow.client.config import ClientConfig
    from tests.conftest import token_for

    client.app.state.cloudmorrow.quills.install(RELAY, origin={"installed_by": ADMIN[0]})
    token = token_for(client, *ADMIN)

    def api_for():
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
        api._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        )
        return None, api

    monkeypatch.setattr(quill_cli, "client", api_for)
    runner = CliRunner()
    shown = runner.invoke(quill_cli.app, ["services"], terminal_width=200)
    assert shown.exit_code == 0, shown.output
    assert "service web" in shown.output and "job tick" in shown.output
    assert "/hooks/relay/inbound?token=" in shown.output
    logs = runner.invoke(quill_cli.app, ["logs", "relay", "web"])
    assert logs.exit_code == 0 and "(nothing yet)" in logs.output
    missing = runner.invoke(quill_cli.app, ["logs", "relay", "nope"])
    assert missing.exit_code != 0
