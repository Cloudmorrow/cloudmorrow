"""The card that offers to put the app on a home screen: hand-held things only."""

from __future__ import annotations

import json

from cloudmorrow.server.routes.web import WEB


def test_a_computer_is_not_offered_the_install():
    """Desktop Chrome would make a browser window with its own title bar; a
    computer has the desktop app for this, so the card is for phones and
    tablets, told by user agent or by touch without hover."""
    source = (WEB / "install.js").read_text(encoding="utf-8")
    assert 'if (isStandalone() || !isHandheld()) return "";' in source
    assert "/Android|Mobile/.test(navigator.userAgent)" in source
    assert "(hover: none) and (pointer: coarse)" in source


def test_an_app_window_carries_the_screens_title_alone():
    """A home-screen app writes the cloud's name on itself; the page title
    does not say it again."""
    source = (WEB / "core.js").read_text(encoding="utf-8")
    assert "document.title = title ? (own ? title : `${title} · ${CLOUD_NAME}`) : CLOUD_NAME;" in source


def test_the_manifest_no_longer_says_notes_only():
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert "notes" in manifest["description"] and "Quill" in manifest["description"]
    assert manifest["display"] == "standalone"
