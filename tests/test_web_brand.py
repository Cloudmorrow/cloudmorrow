"""The web app on the brand guide: its colours, its type and its icon.

The guide lives in the cloudmorrow-web repository (brand/index.html and
brand/tokens.css). Nothing makes the app follow it but these tests: the
colours have to be the palette's, a fill has to be one of the two the guide
allows, the type has to be served from here rather than from Google, and
the icon has to be the hedgehog rather than the pixel C.
"""

from __future__ import annotations

import re

from cloudmorrow import palette
from cloudmorrow.server.routes.web import WEB, asset_version

BASE = (WEB / "base.css").read_text(encoding="utf-8")
ROOT = BASE.split(":root {", 1)[1].split("}", 1)[0]


def _var(name: str) -> str:
    return re.search(rf"^\s*{re.escape(name)}:\s*([^;]+);", ROOT, re.M).group(1).strip()


def _stylesheets() -> list[tuple[str, str]]:
    return [
        (path.name, re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S))
        for path in sorted(WEB.glob("*.css"))
        # /brand stands alone and paints from its own theme; fonts.css is faces.
        if path.name not in ("brand.css", "fonts.css")
    ]


# -- colour ----------------------------------------------------------------------
def test_the_colours_are_the_palettes():
    """One set of values for the app, the CLI and the terminal app."""
    pairs = {
        "--bg": palette.INK, "--card": palette.SURFACE, "--card-2": palette.PANEL,
        "--line": palette.LINE, "--line-bright": palette.LINE_BRIGHT,
        "--ink": palette.TEXT, "--muted": palette.MUTED,
        "--accent": palette.ACCENT, "--bar-accent": palette.ACCENT, "--second": palette.SECOND,
        "--good": palette.GOOD, "--warn": palette.WARN, "--bad": palette.BAD,
    }
    for name, value in pairs.items():
        assert _var(name).lower() == value.lower(), name


def test_blue_is_the_platform_and_amber_is_the_action():
    assert _var("--accent").lower() == "#5aa6e0"      # Sky: links, the tab you are on
    assert _var("--fill").lower() == "#1c70b1"        # Cloud: a chosen thing, white on it
    assert _var("--fill-ink").lower() == "#ffffff"
    assert _var("--fill-hover").lower() == "#3685bd"  # Puff
    assert _var("--fill-pressed").lower() == "#0a3f75"  # Deep
    assert _var("--action").lower() == "#e0a84c"      # Lens: the one action
    assert _var("--action-ink").lower() == _var("--bg").lower()
    assert _var("--warn").lower() == "#ff9f5a"        # orange, never amber
    assert "#0a3f75" in _var("--brand") and "#5aa6e0" in _var("--brand")


def test_nothing_is_filled_with_the_text_blue():
    """Sky is text, lines and dots. Anything with words on it is filled Cloud,
    with white, or is the amber action, with ink."""
    for name, css in _stylesheets():
        assert "var(--accent-ink)" not in css, name
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if re.search(r"background:\s*var\(--accent\)", body):
                assert not re.search(r"(^|;|\s)color:", body), f"{name}: {head.strip()}"


def test_the_old_palette_is_gone():
    for name, css in _stylesheets():
        for old in ("#4fe3d7", "#a78bfa", "#ffc857", "#7c8cf8", "#f472b6"):
            # Calendar colours are the person's choice by name, and keep theirs.
            if name == "calendar.css" and old in ("#4fe3d7", "#a78bfa"):
                continue
            assert old not in css.lower(), f"{name} still has {old}"


def test_the_amber_fills_are_the_actions():
    """Amber fills the one action a screen is for; anything else is blue or a ghost."""
    allowed = {
        ".nav button.strong", ".login .submit", ".row.primary", ".composer button",
    }
    for name, css in _stylesheets():
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if re.search(r"background:\s*var\(--action\)", body):
                selectors = {s.strip() for s in head.split(",")}
                assert selectors <= allowed | {".row.primary:active"}, f"{name}: {head.strip()}"


# -- type ------------------------------------------------------------------------
def test_the_type_is_served_from_here():
    fonts = (WEB / "fonts.css").read_text(encoding="utf-8")
    files = re.findall(r'url\("\./([^"]+)"\)', fonts)
    assert files and all(f.endswith(".woff2") for f in files)
    for name in files:
        assert (WEB / name).is_file(), name
    families = set(re.findall(r'font-family: "([^"]+)"', fonts))
    assert families == {"Barlow", "Barlow Semi Condensed"}
    # The licence goes with the files.
    assert "SIL Open Font License" in (WEB / "OFL-Barlow.txt").read_text(encoding="utf-8")
    assert '@import "./fonts.css";' in (WEB / "app.css").read_text(encoding="utf-8")
    # And nothing asks anybody else for them.
    for path in WEB.iterdir():
        if path.suffix in (".css", ".js", ".html"):
            assert "fonts.googleapis" not in path.read_text(encoding="utf-8"), path.name


def test_the_type_is_served(client):
    """The server has to hand out a .woff2 for any of the above to arrive."""
    response = client.get(f"/app/{asset_version()}/barlow-400-latin.woff2")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("font/woff2")


def test_notes_keep_the_system_face():
    """The guide's one exception: a note is prose, set in the system's own face."""
    body = BASE.split(".editor .body {", 1)[1].split("}", 1)[0]
    assert "font-family: var(--system);" in body
    assert _var("--sans").startswith('"Barlow"')
    assert _var("--display").startswith('"Barlow Semi Condensed"')


# -- the hedgehog ------------------------------------------------------------------
def test_the_icon_is_the_hedgehog(client):
    page = client.get("/app").text
    assert 'href="/app/favicon-32.png"' in page and 'href="/app/favicon-16.png"' in page
    assert 'rel="apple-touch-icon" href="/app/icon-180.png"' in page
    for name, size in (("favicon-16.png", 16), ("favicon-32.png", 32), ("icon-180.png", 180),
                       ("icon-192.png", 192), ("icon-512.png", 512)):
        data = (WEB / name).read_bytes()
        assert data.startswith(b"\x89PNG"), name
        width = int.from_bytes(data[16:20], "big")
        assert width == size, name
        assert client.get(f"/app/{name}").status_code == 200, name


def test_empty_screens_may_show_the_hedgehog(client):
    assert 'url("./mascot-320.png")' in BASE
    assert client.get(f"/app/{asset_version()}/mascot-320.png").status_code == 200
    for name in ("notes.js", "kit.js", "kit_grid.js"):
        source = (WEB / name).read_text(encoding="utf-8")
        assert 'class="empty mascot"><b>Nothing here yet</b>' in source, name
