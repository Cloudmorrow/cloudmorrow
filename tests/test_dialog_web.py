"""Every question the web app asks is asked on the page (dialog.js), never in a browser window."""

from __future__ import annotations

import re

from cloudmorrow.server.routes.web import WEB

# A bare call: `prompt.prompt()` is the install banner's, and is not this.
POPUP = re.compile(r"(?<![.\w])(confirm|prompt|alert)\(")


def scripts() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(WEB.glob("*.js"))}


def test_no_script_opens_a_browser_window():
    found = {name: POPUP.findall(code) for name, code in scripts().items()}
    assert not {name: hits for name, hits in found.items() if hits}


def test_every_question_is_awaited_and_comes_from_the_dialog_module():
    for name, code in scripts().items():
        if name == "dialog.js":
            continue
        uses = {word for word in ("ask", "askText") if re.search(rf"\b{word}\(", code)}
        if not uses:
            continue
        line = re.search(r'^import \{([^}]*)\} from "./dialog.js";', code, flags=re.M)
        assert line, f"{name} asks without importing dialog.js"
        imported = {part.strip() for part in line.group(1).split(",")}
        assert uses <= imported, (name, uses, imported)
        # A question answers a promise: a call that is not awaited is a question nobody waits for.
        assert not re.search(r"(?<!await )(?<![\w.])(ask|askText)\(", code), name


def test_the_dialog_is_the_sheet_every_screen_shares():
    code = (WEB / "dialog.js").read_text(encoding="utf-8")
    assert "sheet-backdrop" in code and 'role="dialog"' in code
    assert "export function ask(" in code and "export function askText(" in code
    assert "./dialog.css" in (WEB / "app.css").read_text(encoding="utf-8")


def test_a_sheet_sits_above_the_phone_keyboard():
    """A phone keyboard covers the bottom of the window without shrinking it:
    core.js measures what it hides into `--keyboard`, and every sheet — and
    the formatting bar — keeps its bottom above that, so a line to type in
    is never behind the keys."""
    core = (WEB / "core.js").read_text(encoding="utf-8")
    assert "window.visualViewport" in core
    assert 'setProperty("--keyboard"' in core
    assert "watchKeyboard();" in core.split("export function start()")[1]
    assert "--keyboard: 0px;" in (WEB / "base.css").read_text(encoding="utf-8")
    sheet = (WEB / "kit_grid.css").read_text(encoding="utf-8")
    backdrop = sheet.split(".sheet-backdrop {")[1].split("}")[0]
    assert "bottom: var(--keyboard);" in backdrop
    assert "var(--keyboard)" in (WEB / "actions.css").read_text(encoding="utf-8")
    assert "bottom: var(--keyboard);" in (WEB / "format.css").read_text(encoding="utf-8")
    # One measurement, in one place: the bar no longer takes its own.
    assert "visualViewport" not in (WEB / "format.js").read_text(encoding="utf-8")
