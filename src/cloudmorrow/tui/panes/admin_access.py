"""Administration → Access: how this cloud is reached.

Three ways, each with its state, the same three as Administration → Access
in the web app:

- **Home network.** Always on: the box announces itself as `<name>.local`,
  and clients on the same network find it.
- **Public.** A name at the control server (`larsens.cloudmorrow.com`) that
  anybody can open, carried to the box through the relay's tunnel: whether
  the tunnel is up, since when, how often it dropped, how much went through.
- **Private.** The same name, for enrolled devices only, over the mesh: the
  box's mesh address, tailscale's state, and every enrolled device.

One primary action, the name (claim one, or move to another); the switches
for public and private beside it; giving the name back last, in red.
"""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action

TUNNEL_COLOUR = {
    "connected": GOOD, "connecting": WARN, "waiting": WARN, "refused": BAD, "stopped": BAD,
}


def _size(count: int) -> str:
    value = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{count} B"


def _on(flag: bool) -> str:
    return f"[b {GOOD}]on[/]" if flag else f"[{MUTED}]off[/]"


def access_text(status: dict, devices: list[dict] | None = None) -> str:
    """The three ways as markup; apart from the view, for a test to read."""
    lan = status.get("lan") or {}
    public = status.get("public") or {}
    private = status.get("private") or {}
    host = escape(status.get("host") or "")
    lines = [f"[{MUTED}]address[/]  [b]{escape(status.get('address') or 'none set')}[/]", ""]

    lines.append(f"[b {ACCENT}]Home network[/]  {_on(bool(lan.get('on')))}")
    if lan.get("hostname"):
        where = ", ".join(lan.get("addresses") or [])
        lines.append(f"  [{MUTED}]announced as[/] {escape(lan['hostname'])} [{MUTED}]{escape(where)}[/]")
    else:
        lines.append(f"  [{MUTED}]not announced: nothing here listens where a neighbour could reach it[/]")
    if lan.get("error"):
        lines.append(f"  [{WARN}]{escape(lan['error'])}[/]")
    lines.append("")

    lines.append(f"[b {ACCENT}]Public[/]  {_on(bool(public.get('on')))}  {host}")
    if not status.get("enrolled", bool(host)):
        suggested = escape(status.get("suggested_name") or "")
        lines.append(
            f"  [{MUTED}]no name yet: Name claims one ({suggested}, say) to be reached from anywhere[/]"
        )
    tunnel = public.get("tunnel") or {}
    if public.get("on") and tunnel:
        state = tunnel.get("state", "off")
        line = f"  [{MUTED}]tunnel[/] [{TUNNEL_COLOUR.get(state, MUTED)}]{state}[/]"
        if tunnel.get("connected_since"):
            since = tunnel["connected_since"].replace("T", " ")[:16]
            line += f" [{MUTED}]since {escape(since)} UTC[/]"
        lines.append(line)
        lines.append(
            f"  [{MUTED}]{tunnel.get('reconnects', 0)} reconnects · "
            f"{_size(tunnel.get('bytes_in', 0))} in · {_size(tunnel.get('bytes_out', 0))} out · "
            f"{tunnel.get('streams', 0)} open[/]"
        )
        if tunnel.get("error"):
            lines.append(f"  [{WARN}]{escape(tunnel['error'])}[/]")
    lines.append("")

    lines.append(f"[b {ACCENT}]Private[/]  {_on(bool(private.get('on')))}")
    mesh = private.get("mesh") or {}
    if private.get("on"):
        lines.append(
            f"  [{MUTED}]the box is[/] {escape(private.get('address') or '?')} "
            f"[{MUTED}]on the mesh · tailscale {escape(mesh.get('state') or '?')}[/]"
        )
        lines.append(f"  [{MUTED}]login server[/] {escape(private.get('login_server') or '')}")
    elif mesh and not mesh.get("installed"):
        lines.append(f"  [{MUTED}]tailscale is not on this box; the server installer adds it (--private)[/]")
    if private.get("error"):
        lines.append(f"  [{WARN}]{escape(private['error'])}[/]")
    if devices:
        lines.append(f"  [{MUTED}]enrolled devices[/]")
        for device in devices:
            dot = f"[{GOOD}]●[/]" if device.get("online") else f"[{MUTED}]○[/]"
            lines.append(
                f"    {dot} [b]{escape(device.get('name') or '?')}[/] "
                f"{escape(device.get('address') or '')} [{MUTED}]{escape(device.get('for') or '')}[/]"
            )
    caddy = status.get("caddy") or {}
    if caddy.get("error"):
        lines += ["", f"[{WARN}]Caddy: {escape(caddy['error'])}[/]"]
    return "\n".join(lines)


class AccessView(Pane):
    """How the cloud is reached, and the switches that change it."""

    TAB_LABEL = "Access"
    SUMMARY = "home network, public name, private mesh"
    BINDINGS = [
        ("c", "fire('name')", "Name"),
        ("p", "fire('public')", "Public"),
        ("v", "fire('private')", "Private"),
        ("x", "fire('release')", "Give back"),
    ]
    ACTIONS = (
        Action("name", "Name", "c", variant="primary", hint="Claim a name, or move to another"),
        Action("public", "Public on/off", "p", hint="Anybody with the address; the sign-in page is the door"),
        Action("private", "Private on/off", "v", hint="Only devices you enrolled, from anywhere"),
        Action("release", "Give name back", "x", variant="error"),
    )
    DEFAULT_CSS = """
    #admin-access-body { height: 1fr; padding: 1 2; }
    #admin-access-text { height: auto; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status: dict = {}
        self._devices: list[dict] = []

    def content(self) -> ComposeResult:
        with VerticalScroll(id="admin-access-body"):
            yield Static("", id="admin-access-text")

    def on_show(self) -> None:
        self.reload()

    def act_refresh(self) -> None:
        self.reload()

    @work(exclusive=True, group="admin-access")
    async def reload(self) -> None:
        client = self.api
        if client is None:
            return
        try:
            self._status = await client.access()
            self._devices = []
            if (self._status.get("private") or {}).get("on"):
                self._devices = await client.mesh_devices(everyone=True)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._draw()

    def _draw(self) -> None:
        self.query_one("#admin-access-text", Static).update(access_text(self._status, self._devices))
        public = (self._status.get("public") or {}).get("on")
        private = (self._status.get("private") or {}).get("on")
        ways = [w for w, on in (("public", public), ("private", private)) if on]
        self.status(" and ".join(ways) + " on" if ways else "home network only", note=True)

    async def _apply(self, call, said: str) -> None:
        try:
            self._status = await call
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.status(said)
        self.reload()

    # -- actions -----------------------------------------------------------
    def act_name(self) -> None:
        self.claim()

    @work(group="ui")
    async def claim(self) -> None:
        current = self._status.get("name") or ""
        zone = self._status.get("zone") or "the relay's zone"
        wanted = await self.app.push_screen_wait(
            PromptModal(
                "Move to another name" if current else "Claim a name",
                value=current or self._status.get("suggested_name", ""),
                placeholder="larsens",
                detail=f"[{MUTED}]3 to 40 letters, digits or dashes; the cloud is then <name>.{escape(zone)}[/]",
            )
        )
        if not wanted or wanted == current:
            return
        if current:
            await self._apply(self.api.rename_access(wanted), f"The cloud is now {wanted}.")
            return
        await self._apply(self.api.claim_name(wanted, public=True), f"Claimed {wanted}; public access is on.")

    def act_public(self) -> None:
        self.toggle("public")

    def act_private(self) -> None:
        self.toggle("private")

    @work(group="ui")
    async def toggle(self, way: str) -> None:
        if not self._status.get("enrolled", bool(self._status.get("name"))):
            self.status("Claim a name first: both public and private use it.", error=True)
            return
        on = not (self._status.get(way) or {}).get("on")
        if not on:
            detail = (
                "Nobody outside the home network reaches it any more."
                if way == "public"
                else "Enrolled devices stop reaching it; they stay enrolled."
            )
            if not await self.app.push_screen_wait(
                ConfirmModal(f"Turn {way} access off?", detail=detail, confirm_label="Turn off")
            ):
                return
        call = self.api.set_public(on) if way == "public" else self.api.set_private(on)
        await self._apply(call, f"{way.capitalize()} access is {'on' if on else 'off'}.")

    def act_release(self) -> None:
        self.release()

    @work(group="ui")
    async def release(self) -> None:
        host = self._status.get("host")
        if not host:
            self.status("This cloud has no name to give back.", error=True)
            return
        if not await self.app.push_screen_wait(
            ConfirmModal(
                "Give the name back?",
                detail=f"[b]{escape(host)}[/]\nPublic and private access end, and enrolled devices are forgotten.",
                confirm_label="Give back",
            )
        ):
            return
        await self._apply(self.api.release_name(), f"{host} is given back.")
