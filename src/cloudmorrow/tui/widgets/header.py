"""The top of the workspace: the wordmark, and who and where you are beside it.

The mark is the app's own 5×7 pixel wordmark (cloudmorrow.pixelfont), the
same drawing as the web app's — "pixels for the marks, type for the words" —
painted with the brand's blue gradient running diagonally, so the letters read
as lit from one corner rather than striped. Beside it, three lines:

    BRAM'S CLOUD · cloudmorrow            whose this is, in amber: it is yours
    bram@cm.example.org   ⚙ Settings ^g   the account (click: password), settings
    server ● connected    🔔 1  f8        whether the server answers, and the bell

A terminal too narrow for the mark gets a one-line header instead: a small
mark, then the same things along one row.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from cloudmorrow import pixelfont
from cloudmorrow.palette import MARK_GRADIENT
from cloudmorrow.tui.theme import BAD, FAINT, GOOD, LENS, MUTED, SKY

# Narrower than this and the mark and the lines beside it do not both fit.
WIDE = 104
# How far into the gradient the mark starts: Deep, the dark end, is for fills
# and shadows, and a dot of it on the page is barely there.
MARK_START = 0.3
COMPACT_MARK = "▞▚ CLOUDMORROW"


def _rgb(colour: str) -> tuple[int, int, int]:
    n = int(colour.lstrip("#"), 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def gradient(t: float, stops=MARK_GRADIENT) -> str:
    """The colour at *t* (0..1) along the stops, mixed in plain sRGB."""
    t = min(1.0, max(0.0, t)) * (len(stops) - 1)
    index = min(len(stops) - 2, int(t))
    weight = t - index
    start, end = _rgb(stops[index]), _rgb(stops[index + 1])
    return "#{:02x}{:02x}{:02x}".format(
        *(round(a + (b - a) * weight) for a, b in zip(start, end, strict=True))
    )


def painted_mark(word: str = "CLOUDMORROW") -> Text:
    """The pixel wordmark, lit diagonally: darker at the top left, Sky at the far end."""
    rows = pixelfont.rows(word)
    width = len(rows[0]) if rows else 1
    out = Text(no_wrap=True)
    for y, row in enumerate(rows):
        if y:
            out.append("\n")
        for x, char in enumerate(row):
            if char == " ":
                out.append(char)
                continue
            t = MARK_START + (1 - MARK_START) * (x + y * 3) / (width + 9)
            out.append(char, style=gradient(t))
    return out


def mark_width() -> int:
    rows = pixelfont.rows("CLOUDMORROW")
    return len(rows[0]) if rows else 0


def title_line(owner: str, *, dev: bool) -> Text:
    """BRAM'S CLOUD · cloudmorrow — whose cloud, in amber, and what it is."""
    text = Text()
    name = f"{owner.upper()}'S CLOUD" if owner else "YOUR CLOUD"
    text.append(name, style=f"bold {LENS}")
    text.append(" · cloudmorrow", style=FAINT)
    if dev:
        # Running from the checkout looks exactly like the installed client,
        # which is a good way to wonder why an edit did nothing.
        text.append(" dev", style="bold #ff9f5a")
    return text


def health_line(state: str, *, compact: bool = False) -> Text:
    """server ● connected, ✗ unreachable, or ◌ while it has not answered yet."""
    text = Text("" if compact else "server ", style=MUTED)
    if state == "up":
        text.append("● connected", style=GOOD)
    elif state == "down":
        text.append("✗ not answering", style=BAD)
    else:
        text.append("◌ asking…", style=FAINT)
    return text


class Header(Horizontal):
    """The mark and the three lines. `wide` switches between the two shapes."""

    def __init__(self, *, owner: str, account: str, bell: str, dev: bool) -> None:
        super().__init__(id="topbar")
        self.owner = owner
        self.account = account
        self.bell = bell
        self.dev = dev

    def compose(self) -> ComposeResult:
        yield Static(painted_mark(), id="topbar-mark")
        yield Static(Text(COMPACT_MARK, style=f"bold {SKY}"), id="topbar-compact")
        with Vertical(id="topbar-info"):
            yield Static(title_line(self.owner, dev=self.dev), id="topbar-left")
            with Horizontal(id="topbar-right", classes="topbar-row"):
                account = Button(self.account, id="topbar-account", compact=True, flat=True)
                account.tooltip = "Change your password"
                yield account
                settings = Button("⚙ Settings  ^g", id="open-settings", compact=True, flat=True)
                settings.tooltip = "This machine, and its Omarchy config"
                yield settings
            with Horizontal(id="topbar-status", classes="topbar-row"):
                yield Static(health_line(""), id="topbar-health")
                bell = Button(self.bell, id="open-notifications", compact=True, flat=True)
                bell.tooltip = "What the machines have been up to"
                yield bell

    health = ""

    def set_health(self, state: str) -> None:
        self.health = state
        self.query_one("#topbar-health", Static).update(
            health_line(state, compact=self.has_class("-compact"))
        )

    def fit(self, width: int) -> None:
        """The full mark when there is room for it and the lines beside it."""
        self.set_class(width < WIDE, "-compact")
        self.set_health(self.health)
