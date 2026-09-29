"""Administration → Access: how this cloud is reached.

The same as Administration → Access in the web app:

- **Home network.** Always on: the box announces itself as `<name>.local`,
  and clients on the same network find it.
- **The mesh.** Once the box is linked to a cloudmorrow.com account: its
  name (`larsens.cloudmorrow.tech`), the box's own state on the mesh, and
  every device on it, with whose it is — which the box knows and the relay
  does not.

Before the box is linked, the one primary action is Link: it asks the
relay for a code, and the pane shows *Open cloudmorrow.com/link and enter
KXRT-4829*, with the link and a QR code of it, and looks again every few
seconds until the code is entered or runs out. Unlinking is last, in red.
The name is chosen and changed on the website, not here.
"""

from __future__ import annotations

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from cloudmorrow.client.api import ApiError
from cloudmorrow.qrtext import qr_markup
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED, WARN
from cloudmorrow.tui.widgets.toolbar import Action

# How often the pane looks again while a link code waits.
POLL_SECONDS = 3.0


def _on(flag: bool, words: str = "on") -> str:
    return f"[b {GOOD}]{words}[/]" if flag else f"[{MUTED}]off[/]"


def _home(status: dict) -> list[str]:
    lan = status.get("lan") or {}
    shown = lan.get("on") and lan.get("announced", lan.get("hostname"))
    lines = [f"[b {ACCENT}]Home network[/]  {_on(bool(shown))}"]
    if shown and lan.get("hostname"):
        where = ", ".join(lan.get("addresses") or [])
        lines.append(f"  [{MUTED}]announced as[/] {escape(lan['hostname'])} [{MUTED}]{escape(where)}[/]")
    elif not lan.get("on"):
        lines.append(f"  [{MUTED}]access_lan is off in the server's config[/]")
    else:
        lines.append(f"  [{MUTED}]not announced: it listens only on this machine[/]")
    if lan.get("error"):
        lines.append(f"  [{WARN}]{escape(lan['error'])}[/]")
    return lines


def link_text(link: dict) -> list[str]:
    """The television's sentence, the link, and a QR code of it."""
    lines = [
        f"  Open [b]{escape(link.get('place') or '')}[/] and enter",
        "",
        f"      [b {ACCENT}]{escape(link.get('code') or '')}[/]",
        "",
        f"  [{MUTED}]or open {escape(link.get('link') or '')}[/]",
        f"  [{MUTED}]or scan this with your phone; this pane follows along[/]",
        "",
    ]
    picture = qr_markup(link.get("link") or "")
    if picture:
        lines += ["  " + line for line in picture.splitlines()]
    return lines


def access_text(status: dict, devices: list[dict] | None = None) -> str:
    """The home network and the mesh as markup; apart from the view, for a test to read."""
    lines = [f"[{MUTED}]address[/]  [b]{escape(status.get('address') or 'none set')}[/]", ""]
    lines += _home(status)
    lines.append("")
    mesh = status.get("mesh") or {}
    if not status.get("linked"):
        lines.append(f"[b {ACCENT}]The mesh[/]  [{MUTED}]not linked[/]")
        link = status.get("link")
        if link:
            lines += link_text(link)
        else:
            lines.append(
                f"  [{MUTED}]Link this cloud to a cloudmorrow.com account (Link), and the devices you\n"
                f"  invite reach it from anywhere, over a private mesh. Nothing about its people\n"
                f"  leaves it. Without it, the home network is all.[/]"
            )
            if status.get("link_state") == "expired":
                lines.append(f"  [{WARN}]the last code ran out before it was entered[/]")
        if status.get("link_error"):
            lines.append(f"  [{WARN}]{escape(status['link_error'])}[/]")
        return "\n".join(lines)

    host = escape(status.get("host") or "")
    lines.append(f"[b {ACCENT}]The mesh[/]  {_on(bool(mesh.get('on')))}  [b]{host}[/]")
    box = mesh.get("box") or {}
    if not box.get("installed", True):
        lines.append(f"  [{BAD}]tailscale is not installed on this box[/]")
    elif mesh.get("on"):
        lines.append(
            f"  [{MUTED}]the box is[/] {escape(mesh.get('address') or '?')} "
            f"[{MUTED}]on the mesh · tailscale {escape(box.get('state') or '?')}[/]"
        )
        lines.append(f"  [{MUTED}]login server[/] {escape(mesh.get('login_server') or '')}")
    else:
        lines.append(f"  [{WARN}]linked, and not on its mesh yet (Try again)[/]")
    if status.get("setup_error"):
        lines.append(f"  [{BAD}]{escape(status['setup_error'])}[/]")
    caddy = status.get("caddy") or {}
    if caddy.get("error"):
        lines.append(f"  [{WARN}]certificate: {escape(caddy['error'])}[/]")
    if devices is not None and mesh.get("on"):
        lines += ["", f"  [{MUTED}]devices on the mesh[/]"]
        if not devices:
            lines.append(f"    [{MUTED}]none yet: Invite a device, from Settings[/]")
        for device in devices:
            dot = f"[{GOOD}]●[/]" if device.get("online") else f"[{MUTED}]○[/]"
            label = escape(device.get("label") or "") or f"[{MUTED}]nobody's yet[/]"
            where = escape(device.get("address") or "")
            lines.append(f"    {dot} [b]{label}[/] {where} [{MUTED}]{escape(device.get('id') or '')}[/]")
    lines += ["", f"[{MUTED}]The name is chosen, and changed, on cloudmorrow.com, in My Clouds.[/]"]
    return "\n".join(lines)


class AccessView(Pane):
    """How the cloud is reached, and linking it."""

    TAB_LABEL = "Access"
    SUMMARY = "home network, and the mesh once linked"
    BINDINGS = [
        ("l", "fire('link')", "Link"),
        ("t", "fire('setup')", "Try again"),
        ("w", "fire('label')", "Say whose"),
        ("x", "fire('unlink')", "Unlink"),
    ]
    ACTIONS = (
        Action("link", "Link", "l", variant="primary", hint="Link to a cloudmorrow.com account"),
        Action("setup", "Try again", "t", hint="Put a linked cloud on its mesh again"),
        Action("label", "Say whose", "w", hint="Whose a device on the mesh is (kept on this box)"),
        Action("unlink", "Unlink", "x", variant="error"),
    )
    DEFAULT_CSS = """
    #admin-access-body { height: 1fr; padding: 1 2; }
    #admin-access-text { height: auto; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status: dict = {}
        self._devices: list[dict] = []
        self._timer = None

    def content(self) -> ComposeResult:
        with VerticalScroll(id="admin-access-body"):
            yield Static("", id="admin-access-text")

    def on_show(self) -> None:
        self.reload()

    def on_hide(self) -> None:
        self._stop_polling()

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
            if (self._status.get("mesh") or {}).get("on"):
                self._devices = await client.mesh_devices(everyone=True)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._draw()

    def _draw(self) -> None:
        self.query_one("#admin-access-text", Static).update(access_text(self._status, self._devices))
        if self._status.get("linked"):
            on = (self._status.get("mesh") or {}).get("on")
            self.status(f"linked as {self._status.get('host')}" + ("" if on else ", not on its mesh yet"), note=True)
        elif self._status.get("link"):
            self.status("waiting for the code to be entered", note=True)
        else:
            self.status("home network only", note=True)
        if self._status.get("link") and self._timer is None:
            self._timer = self.set_interval(POLL_SECONDS, self.reload)
        elif not self._status.get("link"):
            self._stop_polling()

    def _stop_polling(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    async def _apply(self, call, said: str) -> None:
        try:
            await call
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if said:
            self.status(said)
        self.reload()

    # -- actions -----------------------------------------------------------
    def act_link(self) -> None:
        self.link()

    @work(group="ui")
    async def link(self) -> None:
        if self._status.get("linked"):
            self.status(f"Already linked, as {self._status.get('host')}.", error=True)
            return
        await self._apply(self.api.start_link(), "")

    def act_setup(self) -> None:
        self.set_up()

    @work(group="ui")
    async def set_up(self) -> None:
        if not self._status.get("linked"):
            self.status("Link it first.", error=True)
            return
        await self._apply(self.api.access_setup(), "On the mesh.")

    def act_label(self) -> None:
        self.label()

    @work(group="ui")
    async def label(self) -> None:
        if not self._devices:
            self.status("No devices on the mesh to say anything about.", error=True)
            return
        listed = "\n".join(
            f"{d['id']}  {d.get('label') or 'nobody’s yet'}  {d.get('address', '')}" for d in self._devices
        )
        chosen = await self.app.push_screen_wait(
            PromptModal("Which device?", placeholder="its id", detail=f"[{MUTED}]{escape(listed)}[/]")
        )
        device = next((d for d in self._devices if d["id"] == (chosen or "").strip()), None)
        if device is None:
            return
        owner = await self.app.push_screen_wait(
            PromptModal("Whose is it?", value=device.get("owner") or "", placeholder="a username")
        )
        if owner is None:
            return
        name = await self.app.push_screen_wait(
            PromptModal("What is it called?", value=device.get("device") or "phone", placeholder="phone")
        )
        if name is None:
            return
        await self._apply(self.api.label_mesh_device(device["id"], owner.strip(), name.strip()), "Labelled.")

    def act_unlink(self) -> None:
        self.unlink()

    @work(group="ui")
    async def unlink(self) -> None:
        if self._status.get("link") and not self._status.get("linked"):
            await self._apply(self.api.cancel_link(), "Stopped waiting for the code.")
            return
        host = self._status.get("host")
        if not host:
            self.status("This cloud is not linked.", error=True)
            return
        if not await self.app.push_screen_wait(
            ConfirmModal(
                "Unlink the cloud?",
                detail=f"[b]{escape(host)}[/]\nThe name goes back, and every device on the mesh loses its way in. "
                "The home network keeps working.",
                confirm_label="Unlink",
            )
        ):
            return
        await self._apply(self.api.unlink(), f"{host} is unlinked.")
