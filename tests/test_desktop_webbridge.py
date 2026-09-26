"""The web app's half of the desktop app: `desktopbridge.js`, and who uses it.

The same page is on a phone, in a browser and in the desktop app, so the
rule is that nothing of the desktop app's shows anywhere else. These read
the files for the lines that keep it so; test_desktop_window.py opens the
real window and sees the other side of it.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB


def test_it_is_listed_with_the_features():
    assert 'import "./desktopbridge.js";' in (WEB / "app.js").read_text()
    assert '@import "./desktopbridge.css";' in (WEB / "app.css").read_text()


def test_without_pywebview_it_only_listens():
    """In a browser there is no `window.pywebview`, and all that runs is one listener."""
    script = (WEB / "desktopbridge.js").read_text()
    assert 'addEventListener("pywebviewready", ready)' in script
    # The bridge is only ever the one pywebview put there…
    assert "bridge = api;" in script
    assert re.search(r"const api = window\.pywebview && window\.pywebview\.api;", script)
    # …and everything else asks for it first.
    assert "export const desktop = () => bridge;" in script
    assert "if (!bridge ||" in script
    assert 'computerCard = () => (bridge ? ' in script
    # The page says it is in the app, for anything that wants to know.
    assert "document.documentElement.dataset.desktop" in script


def test_files_draws_the_mount_buttons_only_in_the_app():
    files = (WEB / "files.js").read_text()
    assert 'import { call, desktop } from "./desktopbridge.js";' in files
    assert 'desktop() ? call("mounted_here") : null' in files
    assert 'const mountRow = here ? ' in files and ': () => "";' in files
    for words in ("Mount on this computer", "Unmount", "Open folder"):
        assert words in files
    # Cloud blue for the mount, ghosts for the rest: amber is the screen's one action.
    assert 'class="desk-button cloud" data-mount=' in files
    assert 'class="desk-button ghost" data-unmount=' in files
    assert 'class="desk-button ghost" data-open=' in files


def test_me_has_this_computer_only_in_the_app():
    me = (WEB / "me.js").read_text()
    assert "${computerCard()}" in me
    assert "wireComputerCard(app);" in me
    assert "This computer" in (WEB / "desktopbridge.js").read_text()


def test_its_buttons_are_never_amber():
    css = (WEB / "desktopbridge.css").read_text()
    assert "--action" not in css
    assert "var(--fill)" in css


def test_every_bridge_call_the_page_makes_is_one_the_bridge_has():
    from cloudmorrow.desktop.bridge import Bridge

    called = set()
    for name in ("desktopbridge.js", "files.js", "me.js"):
        called.update(re.findall(r'call\("([a-z_]+)"', (WEB / name).read_text()))
    # files.js names mount and unmount through a variable; they are listed by hand.
    called.update({"mount", "unmount"})
    assert called <= {name for name in dir(Bridge) if not name.startswith("_")}, called
