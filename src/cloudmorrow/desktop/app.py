"""Opening the window: the signed-in server's `/app`, with this computer behind it.

The window shows the web app exactly as a browser would — it is the same
page from the same server, so a deploy updates the desktop app the moment
it updates the phone. What differs is `window.pywebview.api` (the bridge),
which the page finds on its own and uses to offer what only a program on
this machine can do.

**One sign-in.** The token in `credentials.json` is the machine's sign-in:
the terminal app and the command line use it, and so does the window. When
the window opens, the page asks the bridge for it and takes it, so someone
signed in with `cloudmorrow login` is not asked again; when they sign in in
the window instead, the page hands the token back and the terminal app is
signed in too. At start the stored one wins — it is the most recent sign-in
from either side, since the window writes its own through.

The page's own storage — which sort a folder was left in, which tabs are
hidden — is kept between launches, in `desktop/` beside the client config,
so an uninstall takes it with everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from cloudmorrow.client.config import ClientConfig, StoredCredentials, config_dir
from cloudmorrow.desktop import system
from cloudmorrow.desktop.bridge import Bridge
from cloudmorrow.transport import InsecureUrlError, check_url

ICON = system.ICON
DEFAULT_NAME = "Cloudmorrow"
# Big enough for the rail and a folder beside it, which is what the web app
# draws from 900 points across; small enough for a laptop.
SIZE = (1280, 860)
MIN_SIZE = (400, 560)
# The page's own background, so the window is not white for the moment
# before the page paints.
BACKGROUND = "#14171f"
INSTALL_HINT = (
    "the desktop app is not installed on this machine — "
    "`pip install 'cloudmorrow[desktop]'` into the client's venv adds it "
    "(install.sh does this on a computer with a desktop); `cm` is the terminal app"
)


class DesktopError(RuntimeError):
    """The window cannot be opened here; the message says why and what to do."""


def app_url(config: ClientConfig) -> str:
    return config.api_url.rstrip("/") + "/app"


def storage_dir() -> Path:
    return config_dir() / "desktop"


def gui() -> str | None:
    """Which of pywebview's back ends to use: Qt on Linux, the system's own elsewhere.

    Qt because it comes as wheels (the `desktop` extra), so a Linux machine
    needs no system packages; GTK would want WebKitGTK from the distribution.
    """
    return "qt" if system.os_name() == system.LINUX else None


def cloud_name(config: ClientConfig, *, timeout: float = 3.0) -> str:
    """What this cloud is called, for the window's title. Cloudmorrow if it will not say."""
    try:
        response = httpx.get(
            config.api_url.rstrip("/") + "/api/health", timeout=timeout, verify=config.verify_tls
        )
        name = str(response.json().get("name") or "").strip()
    except (httpx.HTTPError, ValueError, AttributeError):
        name = ""
    return name or DEFAULT_NAME


@dataclass(slots=True)
class Plan:
    """What `launch` would open, worked out without opening anything: `cm app --dry-run`."""

    url: str
    title: str
    gui: str | None
    icon: Path
    storage: Path
    signed_in_as: str
    display: bool

    def lines(self) -> list[tuple[str, str]]:
        return [
            ("url", self.url),
            ("title", self.title),
            ("window", self.gui or "the system's own web view"),
            ("icon", str(self.icon)),
            ("storage", str(self.storage)),
            ("signed in", self.signed_in_as or "no — the window will ask"),
            ("display", "yes" if self.display else "none — a window cannot open here"),
        ]


def plan(config: ClientConfig | None = None, *, title: str | None = None) -> Plan:
    config = config or ClientConfig.load()
    credentials = StoredCredentials.load()
    signed_in = (
        credentials.username
        if credentials and credentials.api_url.rstrip("/") == config.api_url
        else ""
    )
    return Plan(
        url=app_url(config),
        title=title if title is not None else cloud_name(config),
        gui=gui(),
        icon=ICON,
        storage=storage_dir(),
        signed_in_as=signed_in,
        display=system.has_display(),
    )


def launch(config: ClientConfig | None = None, *, debug: bool = False, on_start=None) -> None:
    """Open the window and run until it is closed.

    *on_start* runs on a thread of its own once the window is up, with the
    window — what the smoke test uses to look inside and then close it.
    """
    config = config or ClientConfig.load()
    try:
        check_url(config.api_url, allow_insecure=config.allow_insecure_http)
    except InsecureUrlError as exc:
        raise DesktopError(str(exc)) from exc
    if not system.has_display():
        raise DesktopError(
            "there is no display here to open a window on — `cm` is the terminal app"
        )
    try:
        import webview
    except ImportError as exc:
        raise DesktopError(INSTALL_HINT) from exc

    found = plan(config)
    found.storage.mkdir(parents=True, exist_ok=True)
    # A link to somewhere else opens in the browser, not in this window:
    # the window is for this cloud, and the bridge only answers its pages.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    # A server on a private network with its own certificate, which the
    # client config already says to accept.
    webview.settings["IGNORE_SSL_ERRORS"] = not config.verify_tls

    bridge = Bridge(config)
    window = webview.create_window(
        found.title,
        found.url,
        js_api=bridge,
        width=SIZE[0],
        height=SIZE[1],
        min_size=MIN_SIZE,
        background_color=BACKGROUND,
    )
    bridge._attach(window)
    start_args = {
        "gui": found.gui,
        "private_mode": False,
        "storage_path": str(found.storage),
        "icon": str(found.icon),
        "debug": debug,
    }
    if on_start is not None:
        webview.start(on_start, window, **start_args)
    else:
        webview.start(**start_args)
