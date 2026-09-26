"""The desktop app, opened for real: a window on a running server, with no screen.

Qt can draw off the screen (`QT_QPA_PLATFORM=offscreen`), so the window is
the real one — pywebview, Qt WebEngine, the served web app and the bridge —
on a machine with no display and no Xvfb. It is opened in a process of its
own, because a GUI toolkit owns the main thread and is started once per
process, and it is looked inside and closed by `launch(on_start=…)`.

Skipped where the `desktop` extra is not installed: that is most machines
running the tests, and the rest of the desktop app is tested without it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time

import pytest

from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.client.config import ClientConfig, StoredCredentials
from tests.conftest import ADMIN, token_for

pytestmark = pytest.mark.skipif(
    platform.system() != "Linux"
    or not all(importlib.util.find_spec(name) for name in ("webview", "qtpy", "PyQt6")),
    reason="needs the desktop extra (pywebview and Qt) on Linux",
)

PROBE = r"""
import json, sys, time
from cloudmorrow.desktop import app

found = {}

def probe(window):
    deadline = time.time() + 40
    js = (
        "JSON.stringify({desktop: document.documentElement.hasAttribute('data-desktop'),"
        " token: localStorage.getItem('cm.token'), hash: location.hash,"
        " title: document.title})"
    )
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            state = json.loads(window.evaluate_js(js) or "{}")
        except Exception as exc:
            state = {"error": repr(exc)}
        found.update(state)
        if state.get("desktop") and state.get("token") and "login" not in state.get("hash", ""):
            break
    found["window_title"] = window.title
    window.destroy()

app.launch(on_start=probe)
print("PROBE " + json.dumps(found), flush=True)
"""


@pytest.fixture()
def server(client):
    """The test app, served on a real port so a web view can load it."""
    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    instance = uvicorn.Server(
        uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not instance.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    instance.should_exit = True
    thread.join(timeout=10)


def open_window(tmp_path, probe: str) -> dict:
    """Run *probe* against a real window, and hand back what it found."""
    # An agent that is already enrolled, so a sign-in in the window does
    # not go on to install a real agent service on the machine running this.
    agent = tmp_path / "agent.toml"
    AgentConfig(server_url="http://127.0.0.1", agent_token="agent-tok", name="desk").save(agent)
    script = tmp_path / "probe.py"
    script.write_text(probe)
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": os.pathsep.join(sys.path),
        "CLOUDMORROW_AGENT_CONFIG": str(agent),
    }
    done = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=120
    )
    line = next(
        (line for line in done.stdout.splitlines() if line.startswith("PROBE ")), None
    )
    assert line, f"no answer from the window:\n{done.stdout}\n{done.stderr[-3000:]}"
    return json.loads(line.removeprefix("PROBE "))


def test_the_window_opens_signed_in_with_the_stored_token(server, client, tmp_path):
    token = token_for(client, *ADMIN)
    ClientConfig(api_url=server).save()
    StoredCredentials(api_url=server, username=ADMIN[0], access_token=token).save()
    found = open_window(tmp_path, PROBE)
    # The page found the bridge…
    assert found.get("desktop") is True, found
    # …took the machine's sign-in rather than asking for one…
    assert found.get("token") == token, found
    assert "login" not in found.get("hash", ""), found
    # …and the window is named after the cloud.
    assert found.get("window_title") == client.app.state.cloudmorrow.cloud_name()


SIGN_IN = r"""
import json, time
from cloudmorrow.desktop import app

USER, PASSWORD = %(user)s, %(password)s

found = {}

def probe(window):
    deadline = time.time() + 40
    submitted = False
    while time.time() < deadline:
        time.sleep(0.5)
        ready = window.evaluate_js(
            "document.documentElement.hasAttribute('data-desktop')"
            " && !!document.querySelector('form.login')"
        )
        if ready and not submitted:
            window.evaluate_js(
                "(() => { const f = document.querySelector('form.login');"
                f" f.username.value = {json.dumps(USER)};"
                f" f.password.value = {json.dumps(PASSWORD)};"
                " f.requestSubmit(); })()"
            )
            submitted = True
        if submitted:
            from cloudmorrow.client.config import StoredCredentials
            stored = StoredCredentials.load()
            if stored:
                found.update(user=stored.username, token=stored.access_token)
                break
    window.destroy()

app.launch(on_start=probe)
print("PROBE " + json.dumps(found), flush=True)
"""


def test_a_sign_in_in_the_window_is_stored_for_the_terminal_app(server, tmp_path):
    ClientConfig(api_url=server).save()
    assert StoredCredentials.load() is None
    found = open_window(
        tmp_path, SIGN_IN % {"user": json.dumps(ADMIN[0]), "password": json.dumps(ADMIN[1])}
    )
    assert found.get("user") == ADMIN[0], found
    assert found.get("token"), found
