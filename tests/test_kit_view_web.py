"""A Quill's view and its actions, in the browser: wired in, complete, and on the brand.

The screens are driven in a browser, not from here (the fleet fixture and a
Quill using every primitive were looked at at 390 and 1280 pixels). What a
test holds on to is what goes wrong quietly: a primitive the SDK has and the
page cannot draw, an effect a handler can return and the page ignores, the
files not served or imported, a colour spelled out rather than taken from
base.css, and the calls the page makes not being the server's.
"""

from __future__ import annotations

import re
from pathlib import Path

from cloudmorrow.quill import effects as sdk_effects
from cloudmorrow.quill.ui import PRIMITIVES, TEXT_STYLES, TONES
from cloudmorrow.server.routes.web import WEB, asset_version
from tests.conftest import js_code

VIEW_JS = (WEB / "kit_view.js").read_text(encoding="utf-8")
VIEW_CSS = (WEB / "kit_view.css").read_text(encoding="utf-8")
ACTIONS_JS = (WEB / "actions.js").read_text(encoding="utf-8")
ACTIONS_CSS = (WEB / "actions.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")

FLEET = Path(__file__).parent / "fixtures" / "quill-fleet"


def _block(source: str, start: str) -> str:
    return source.split(start, 1)[1].split("\n};", 1)[0]


# -- wired in ------------------------------------------------------------------------
def test_it_is_served_and_wired_in(client):
    version = asset_version()
    assert '@import "./kit_view.css";' in APP_CSS
    assert '@import "./actions.css";' in APP_CSS
    # After the grid's, whose sheet the forms come up in.
    assert APP_CSS.index('"./kit_grid.css"') < APP_CSS.index('"./actions.css"')
    assert 'from "./kit_view.js";' in KIT_JS and 'from "./actions.js";' in KIT_JS
    for name in ("kit_view.js", "kit_view.css", "actions.js", "actions.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name


# -- complete ---------------------------------------------------------------------------
def test_every_primitive_has_a_renderer():
    """One per primitive in the SDK, and none the SDK does not have."""
    drawn = set(re.findall(r"^  (\w+):", _block(VIEW_JS, "const DRAW = {"), re.MULTILINE))
    assert drawn == set(PRIMITIVES)


def test_every_text_style_and_tone_is_drawn():
    for style in TEXT_STYLES:
        if style in ("body", "muted", "small"):
            assert f".v-text.{style}" in VIEW_CSS or style == "body", style
        else:
            assert f'style === "{style}"' in VIEW_JS, style
    for tone in TONES:
        assert f".tone-{tone}" in VIEW_CSS, tone


def test_every_effect_is_handled_in_one_place():
    """Everything effects.py can hand a surface, bar an API's answer, is a case here."""
    made = {
        sdk_effects.toast("x")["effect"],
        sdk_effects.open(model="m", id="i")["effect"],
        sdk_effects.go("s")["effect"],
        sdk_effects.confirm("x", then="a")["effect"],
        sdk_effects.error("x")["effect"],
        sdk_effects.redraw()["effect"],
    }
    handled = set(re.findall(r'case "(\w+)":', js_code(ACTIONS_JS)))
    assert made <= handled
    # And only there: the view hands its effects over rather than reading them.
    assert "export async function applyEffects(" in ACTIONS_JS
    assert "effect.effect" not in VIEW_JS


def test_every_way_to_press_goes_through_press():
    code = js_code(VIEW_JS)
    assert "press(quill, action," in code or "press(v.at.quill, action," in code
    # A button does exactly one of the three things ui.button allows.
    for key in ("n.action", "n.open", "n.go"):
        assert key in code, key
    # A form runs its action, and the view is drawn again after.
    assert "run(v.at.quill, action," in code and "after: v.draw" in code


# -- agrees with the server ---------------------------------------------------------------------
def test_the_calls_it_makes_are_the_servers():
    assert "/views/${encodeURIComponent(screen.id)}" in VIEW_JS
    assert "/actions/${encodeURIComponent(action.id)}" in ACTIONS_JS
    # A lane is moved with the board's own call; a field saved with its rev.
    assert '+ "/move"' in VIEW_JS
    assert "{ fields: { [n.field]: lane.dataset.lane }, index }" in VIEW_JS
    assert "rev: v.revs.get(key) ?? record.rev" in VIEW_JS
    # A picture comes through fetch, with the token an <img> cannot carry.
    assert '"/thumb?size="' in VIEW_JS and "authHeaders()" in VIEW_JS
    # The words a refusal comes with, not "request failed".
    assert "err.detail.message" in ACTIONS_JS


def test_the_fleet_quill_is_what_the_page_reads(config, users):
    """The shape the page reads: actions with fields and tone, a view screen, a tree."""
    from fastapi.testclient import TestClient

    from cloudmorrow.server.app import create_app
    from tests.conftest import ADMIN, token_for

    config.quill_code = "trusted"
    client = TestClient(create_app(config))
    admin = {"Authorization": "Bearer " + token_for(client, *ADMIN)}
    assert client.post("/api/quills", json={"source": str(FLEET)}, headers=admin).status_code == 201
    (fleet,) = [q for q in client.get("/api/quills", headers=admin).json() if q["id"] == "fleet"]
    garage = next(s for s in fleet["screens"] if s["id"] == "garage")
    assert garage["kit"] == "view" and garage["label"]
    for action in fleet["actions"]:
        assert {"id", "label", "fields"} <= set(action), action
        for field in action["fields"]:
            assert {"name", "kind", "label"} <= set(field), field
    assert any(a.get("on") == "vehicle" for a in fleet["actions"])
    assert any(not a.get("on") for a in fleet["actions"])
    tree = client.get("/api/quills/fleet/views/garage", headers=admin).json()["tree"]
    assert tree["ui"] in PRIMITIVES
    answer = client.post("/api/quills/fleet/actions/add-van", json={"fields": {}}, headers=admin)
    assert answer.status_code == 400 and answer.json()["detail"]["message"]


# -- on the brand ---------------------------------------------------------------------------------
def test_no_colour_is_spelled_out():
    for name, css in (("kit_view.css", VIEW_CSS), ("actions.css", ACTIONS_CSS)):
        code = js_code(css)
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", code), name
        assert not re.search(r"\brgba?\(|\bhsla?\(", code), name
    for name, js in (("kit_view.js", VIEW_JS), ("actions.js", ACTIONS_JS)):
        assert not re.search(r"#[0-9a-fA-F]{6}\b", js_code(js)), name


def test_amber_is_one_action_per_view():
    """The first primary button is amber; any other primary is the platform's blue."""
    assert 'if (v.amber) return "fill";' in VIEW_JS
    assert "v.amber = false;" in VIEW_JS
    assert ".act-button.primary {" in ACTIONS_CSS and "background: var(--action);" in ACTIONS_CSS
    assert ".act-button.fill {" in ACTIONS_CSS and "background: var(--fill);" in ACTIONS_CSS


def test_nothing_in_it_is_named_for_one_quill():
    for source, name in ((VIEW_JS, "kit_view.js"), (VIEW_CSS, "kit_view.css"),
                         (ACTIONS_JS, "actions.js"), (ACTIONS_CSS, "actions.css")):
        code = js_code(source)
        for word in ("fleet", "vehicle", "garage", "odometer", "task", "log-service"):
            named = re.search(rf"[\"'.`#]{word}[\"'`\s.-]", code, re.IGNORECASE)
            assert not named, f"{name} names {word!r}"


def test_a_phone_gets_one_column():
    """Columns stack and tables are cards below the computer's width; lanes too."""
    phone = VIEW_CSS.split("@media", 1)[0]
    assert ".v-columns { display: grid; grid-template-columns: minmax(0, 1fr);" in phone
    assert ".v-table thead { display: none; }" in phone
    assert ".v-row { display: flex; flex-wrap: wrap;" in phone
    assert "(min-width: 900px) and (min-height: 600px)" in VIEW_CSS
