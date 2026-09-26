"""The kit's list, picked through, in the browser: wired in, generic, and hiding what it should.

The screens are driven in a browser, not from here (the Secrets Quill was
looked at at 390 and 1280 pixels). What a test holds on to is what goes
wrong quietly: the file not being served or imported, a word from the one
Quill that uses it today hard-coded into what draws every Quill, and a
hidden field drawn as anything but hidden.
"""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB, asset_version

GROUPED_JS = (WEB / "kit_grouped.js").read_text(encoding="utf-8")
GROUPED_CSS = (WEB / "kit_grouped.css").read_text(encoding="utf-8")
KIT_JS = (WEB / "kit.js").read_text(encoding="utf-8")
QUILLS_JS = (WEB / "quills.js").read_text(encoding="utf-8")
APP_CSS = (WEB / "app.css").read_text(encoding="utf-8")


def _code(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)


def test_it_is_served_and_wired_in(client):
    version = asset_version()
    assert '@import "./kit_grouped.css";' in APP_CSS
    assert 'from "./kit_grouped.js";' in KIT_JS
    for name in ("kit_grouped.js", "kit_grouped.css"):
        assert client.get(f"/app/{version}/{name}").status_code == 200, name
    # A list with a group, or a hidden field, is drawn there; the rest as before.
    assert 'kit === "list" && drawsHere(' in KIT_JS
    # The address carries a group and a subgroup: everything after the screen.
    assert "const [quillId, screenId, ...rest] = arg.split(\"/\");" in QUILLS_JS


def test_nothing_in_it_is_named_for_one_quill():
    for source, name in ((GROUPED_JS, "kit_grouped.js"), (GROUPED_CSS, "kit_grouped.css")):
        code = _code(source)
        for word in ("vault", "environment", "secrets", "key", "production", "task"):
            assert not re.search(rf"[\"'.`#]{word}[\"'`\s.-]", code, re.IGNORECASE), f"{name} names {word!r}"


def test_a_hidden_field_is_dots_until_one_record_is_asked_for():
    # In a row: the mask, and the value only from reading that one record.
    assert 'export const MASK = "••••••••";' in GROUPED_JS
    assert "api(\"GET\", recordsUrl(model.id, id))" in GROUPED_JS
    # On the sheet: a password box with an eye, for every surface's same promise.
    assert 'type="password"' in GROUPED_JS
    assert "if (f.secret) return secretWidget(f, value);" in KIT_JS
    assert "wireSecretWidgets(box);" in KIT_JS
    # Typed into like any text box, and never trimmed on its way to the server.
    assert '"number", "password"].includes(el.type)' in KIT_JS
    assert 'f.kind === "string" && !f.secret' in KIT_JS


def test_a_new_record_lands_in_both_levels_and_opens():
    assert "levels.forEach((f, i) => { if (chosen[i] !== null) fields[f.name] = chosen[i]; });" in GROUPED_JS
    assert "go(sheetHash(at, model.id, made.id));" in GROUPED_JS


def test_the_sheet_goes_back_to_the_group_and_subgroup_it_came_from():
    assert "const sub = screen.subgroup ? fieldOf(model, screen.subgroup) : null;" in KIT_JS


def test_the_secrets_quill_is_drawn_by_it(secrets_quill, auth):
    quills = secrets_quill.get("/api/quills", headers=auth).json()
    screen = next(q for q in quills if q["id"] == "secrets")["screens"][0]
    model = next(q for q in quills if q["id"] == "secrets")["models"]["secret"]
    assert (screen["kit"], screen["group"], screen["subgroup"]) == ("list", "vault", "environment")
    value = next(f for f in model["fields"] if f["name"] == screen["subtitle"])
    assert value["secret"] is True
