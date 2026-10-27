"""Local backups in the browser: the page, and the way in from Files."""

from __future__ import annotations

from cloudmorrow.server.routes.web import WEB
from tests.conftest import js_code

JS = (WEB / "localbackups.js").read_text(encoding="utf-8")


def test_the_page_is_reached_from_the_files_list_and_registered():
    code = js_code(JS)
    assert 'registerScreen("localbackups"' in code
    assert 'label: "Local backups…", run: () => go(PAGE)' in code and 'const PAGE = "#/localbackups"' in code
    assert 'import "./localbackups.js";' in (WEB / "app.js").read_text(encoding="utf-8")
    assert '@import "./localbackups.css";' in (WEB / "app.css").read_text(encoding="utf-8")


def test_setting_one_up_needs_a_machine_that_can_copy():
    """The desktop app with its agent running, or any machine of yours
    online: else the button is off and the page says what is needed."""
    code = js_code(JS)
    assert "const can = online.length > 0 || Boolean(thisOne && thisOne.running && thisAgent);" in code
    assert 'class="row primary add-sync"${can ? "" : " disabled"}' in code
    assert (
        "needs the desktop app on a computer, or the command line (cm) installed there with its agent running" in code
    )
    # On this computer the folder is picked in the system's dialog; elsewhere it is typed.
    assert 'await call("pick_folder")' in code and "askText(`Folder on ${agent.name}`" in code
    # Nothing here is a browser popup.
    assert "confirm(" not in code and "prompt(" not in code and "alert(" not in code
