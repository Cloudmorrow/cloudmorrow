"""The kit's thread and spaces in the browser: wired in, generic, and the old chat gone.

The screens are driven in a browser, not from here (see the screenshots in the
report). What a test can hold is what goes wrong quietly: a word from Chat in
the code that draws every thread, the old chat screen coming back by the side
door, or the thread calling an address the server does not answer.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB, asset_version

THREAD_JS = (WEB / "kit_thread.js").read_text(encoding="utf-8")
SPACE_JS = (WEB / "kit_space.js").read_text(encoding="utf-8")
THREAD_CSS = (WEB / "kit_thread.css").read_text(encoding="utf-8")
SPACE_CSS = (WEB / "kit_space.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
QUILLS_JS = (WEB / "quills.js").read_text(encoding="utf-8")


def code(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def test_the_thread_is_its_own_file_registered_from_the_kit(client):
    assert 'import { renderThread } from "./kit_thread.js";' in KIT_JS
    assert "thread: renderThread" in KIT_JS
    app_css = (WEB / "app.css").read_text(encoding="utf-8")
    assert '@import "./kit_thread.css";' in app_css and '@import "./kit_space.css";' in app_css
    version = asset_version()
    for name in ("kit_thread.js", "kit_thread.css", "kit_space.js", "kit_space.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


def test_the_old_chat_screen_is_gone():
    assert not (WEB / "chat.js").exists() and not (WEB / "chat.css").exists()
    for path in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.css")):
        text = path.read_text(encoding="utf-8")
        assert "chat.js" not in text and "chat.css" not in text, path.name
        assert "/api/chat" not in text, path.name
        assert '"#/chat' not in text, path.name


def test_nothing_in_the_thread_is_named_for_chat():
    for source, name in ((THREAD_JS, "kit_thread.js"), (SPACE_JS, "kit_space.js"),
                         (THREAD_CSS, "kit_thread.css"), (SPACE_CSS, "kit_space.css")):
        body = code(source)
        # `direct` is the kit's own word, a key of `made_as`, like `shared`.
        for word in ("chat", "channel", "message", "topic", "private"):
            assert not re.search(rf"[\"'.`#-]{word}[\"'`\s:]", body), f"{name} names {word!r}"


def test_a_thread_takes_the_rest_of_its_address():
    # #/q/<quill>/<screen>/<id>/about: everything after the screen is the screen's.
    assert "const [quillId, screenId, ...rest] = arg.split(\"/\");" in QUILLS_JS
    assert 'renderKitScreen(at, rest.join("/"))' in QUILLS_JS
    for part in ('first === "new"', 'first === "people"', 'second === "about"'):
        assert part in THREAD_JS, part


def test_the_calls_it_makes_are_the_generic_ones(chat_quill, auth):
    """The same calls the thread makes, against a server with Chat installed."""
    client = chat_quill
    for call in ('"/seen"', "&_last=", "&_since=", '"/api/people"', "unique: true", '"/members'):
        assert call in THREAD_JS + SPACE_JS, call
    general = client.get("/api/records/channel", headers=auth).json()[0]
    assert client.get(f"/api/records/message?channel={general['id']}&_last=100", headers=auth).status_code == 200
    assert client.post(f"/api/records/channel/{general['id']}/seen", headers=auth).status_code == 204
    assert client.get("/api/people", headers=auth).status_code == 200


def test_sending_is_the_one_amber_and_where_you_are_is_sky():
    assert "background: var(--action);" in THREAD_CSS.split(".composer button {", 1)[1].split("}", 1)[0]
    assert ".space-row.current { background: color-mix(in srgb, var(--accent)" in THREAD_CSS
