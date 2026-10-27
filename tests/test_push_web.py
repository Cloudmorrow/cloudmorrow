"""The Notifications card in Me: who is asked, and who is sent to the home screen.

Only iOS refuses to push to a tab. A computer's browser, and Android's, is
asked for permission like any site is — so the card never tells a computer to
add the app to a home screen it does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "cloudmorrow" / "server" / "web"
PUSH_JS = (WEB / "push.js").read_text(encoding="utf-8")


def test_only_ios_has_to_be_on_the_home_screen_first():
    """The home-screen gate is iOS's; `state()` asks it, never `installed()` alone."""
    assert "export const needsInstall = () => isIOS() && !installed();" in PUSH_JS
    state = PUSH_JS.split("export function state()", 1)[1].split("\n}", 1)[0]
    assert 'if (needsInstall()) return "not-installed";' in state
    assert "installed()" not in state.replace("needsInstall()", "")
    # Then the browser's own answer, which is what the Turn on button acts on.
    assert "return Notification.permission;" in state


def test_ios_is_told_apart_the_way_the_install_card_does():
    """One test for an iPhone, an iPod, and an iPad calling itself a Mac."""
    install = (WEB / "install.js").read_text(encoding="utf-8")
    pattern = (
        r"/iPhone\|iPad\|iPod/\.test\(navigator\.userAgent\)\s*\|\|\s*"
        r"\(navigator\.platform === \"MacIntel\" && navigator\.maxTouchPoints > 1\)"
    )
    assert re.search(pattern, PUSH_JS)
    assert re.search(pattern, install)


def test_the_card_speaks_to_a_tab_and_to_an_installed_app_in_their_own_words():
    """A tab gets a banner and no count on an icon; turning them back on is in
    the browser's site settings, not the phone's Settings; an iPhone still
    hears about the Home Screen."""
    card = PUSH_JS.split("function words()", 1)[1].split("export function pushCard", 1)[0]
    assert "Add Cloudmorrow to your Home Screen first" in card
    assert "Get a banner from this browser when somebody writes." in card
    assert "This browser gets a banner while it is running." in card
    assert "Settings › Notifications › Cloudmorrow" in card and "browser's site settings" in card
    assert "isIOS()" in card and "installed()" in card
    # The Turn on button is the browser's permission prompt, from a tap.
    assert "await Notification.requestPermission();" in PUSH_JS
