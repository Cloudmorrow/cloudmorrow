"""Every button in the web app is a pixel: one set of states, in base.css, and no
screen's own hover that turns a button grey.

The person who runs the servers asked for it: the amber Save under the pointer
had gone grey with its amber edge left under it, because it was a `.row` as
well as a button, and the rail's generic row hover reached it.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB

BASE = (WEB / "base.css").read_text(encoding="utf-8")
DESKTOP = (WEB / "desktop.css").read_text(encoding="utf-8")
FILLED = [
    ".act-button.primary",
    ".act-button.fill",
    ".row.primary",
    ".nav button.strong",
    ".login .submit",
    ".push-card button",
    ".install .actions button.strong",
    ".desk-button.cloud",
    ".composer button",
]
GHOSTS = [".act-chip", ".desk-button.ghost", ".add-button", ".chip-button", "button.quill-chip"]


def test_a_filled_button_has_an_edge_a_lit_side_and_a_press():
    for selector in FILLED:
        assert f"{selector}:enabled:hover" in BASE, selector
        assert f"{selector}:enabled:active" in BASE, selector
    # The edge is the shadow side of the pixel; the pointer lights the top;
    # the press goes two dots down onto a one-dot edge.
    assert "box-shadow: inset 0 calc(0px - var(--edge-h, 3px)) 0 var(--edge);" in BASE
    lit = "box-shadow: inset 0 1px 0 rgba(255, 255, 255, .24), inset 0 calc(0px - var(--edge-h, 3px)) 0 var(--edge);"
    assert lit in BASE
    assert "transform: translateY(2px);\n  box-shadow: inset 0 -1px 0 var(--edge);" in BASE


def test_a_ghost_turns_sky_under_the_pointer_and_sinks_a_dot_pressed():
    for selector in GHOSTS:
        assert f"{selector}:enabled:hover" in BASE, selector
        assert f"{selector}:enabled:active" in BASE, selector
    assert "transform: translateY(1px);\n  background: var(--card-2);" in BASE


def test_the_hover_is_behind_hover_and_the_press_is_not():
    hover_block = BASE.split("@media (hover: hover) and (pointer: fine) {", 1)[1].split("\n}\n", 1)[0]
    assert ":enabled:hover" in hover_block
    assert ":enabled:active" not in hover_block
    press = BASE.split("@media (hover: hover) and (pointer: fine) {", 1)[1].split("\n}\n", 1)[1]
    assert ".row.primary:enabled:active" in press


def test_no_screen_turns_a_button_grey_or_brightens_it_on_its_own():
    """The generic row hover stops at the row that is a button, and no stylesheet
    keeps a hover or a press of its own for a button base.css already has."""
    assert ".row:not(.primary):hover { background: var(--card-2); }" in DESKTOP
    assert ".row.primary:hover" not in DESKTOP
    assert ".nav button:not(.strong):hover" in DESKTOP
    own = re.compile(
        r"(\.act-button|\.act-chip|\.row\.primary|\.nav button\.strong|\.login \.submit|\.push-card button|"
        r"\.install \.actions button|\.desk-button|\.add-button|\.chip-button|button\.quill-chip|\.composer button)"
        r"[^{\n]*:(hover|active)\b"
    )
    for path in sorted(WEB.glob("*.css")):
        if path.name in ("base.css", "brand.css"):
            continue
        text = path.read_text(encoding="utf-8")
        found = [m.group(0) for m in own.finditer(text)]
        # The amber row keeps its colour under a finger: that one line is allowed.
        found = [f for f in found if f != ".row.primary:active"]
        assert not found, f"{path.name} styles a button's own states: {found}"
    for name in ("actions.css", "me.css", "install.css", "desktopbridge.css", "kit_thread.css", "admin.css"):
        assert "box-shadow: inset 0 -" not in (WEB / name).read_text(encoding="utf-8"), name


def test_buttons_share_one_radius_squarer_than_a_control():
    assert "--radius-button: 6px;" in BASE
    assert "border-radius: var(--radius-button);" in BASE
    for name in ("actions.css", "me.css", "install.css", "desktopbridge.css", "adddevice.css", "quillservices.css"):
        text = (WEB / name).read_text(encoding="utf-8")
        assert "border-radius: 999px" not in text, name
