"""Settings: this machine, and which of the app you want.

Two things, and they are the two that are yours rather than the server's.
The machine you happen to be sitting at, and who it is signed in as. And the
tabs: a tick box per feature, so an account that never opens Projects can
stop being offered them. What the
machines have actually been doing is not here: that is the bell in the top
bar.

The feature boxes are only ever the ones this server offers. One an
administrator has switched off is not listed at all — it is not a thing you
can have an opinion about, and a tick box that did nothing would be worse
than no tick box. Switching one off here hides its tab for you, on every
machine you sign in from; it does not close the API, because this is a
preference and a preference that locked you out would be a mistake with no
way back from the phone you made it on.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Label, Static

from cloudmorrow.agent.setup import machine_name
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.adddevice import AddDeviceModal
from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import BAD, MUTED, SECOND


class SettingsScreen(Modal[None]):
    """This machine, and which of the app you want."""

    BINDINGS = [("escape", "close", "Close"), ("ctrl+r", "reload", "Refresh")]

    def __init__(self) -> None:
        super().__init__()
        # The features this account may switch, keyed by feature, as the
        # server last said. Only what this server offers is ever in here.
        self._features: dict[str, dict] = {}

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Vertical(classes="modal modal-wide", id="settings-modal"):
            yield Label("Settings", classes="modal-title")
            # Everything scrolls together, so the buttons stay on screen on a
            # small terminal however much has happened.
            with VerticalScroll(id="settings-body"):
                yield Static(self._machine_text(), id="settings-machine")

                yield Static(f"[{MUTED}]what this app shows you[/]", classes="pane-title")
                yield Static(
                    f"[{MUTED}]A tab each. Switching one off takes it out of your "
                    f"terminal and your phone alike; nothing of yours is deleted, "
                    f"and you can switch it back on here.[/]",
                    id="settings-features-note",
                )
                yield Vertical(id="settings-features")

            with Horizontal(classes="modal-buttons"):
                yield Button("Close", variant="primary", id="close")
                # Me → Add a device, in the terminal (screens/adddevice.py).
                yield Button("Add a device", id="open-add-device")

    def on_mount(self) -> None:
        # The tick boxes and the buttons are what there is to reach, so the
        # scrolling body stays out of the way of the arrows.
        self.query_one("#settings-body", VerticalScroll).can_focus = False
        self.reload()

    # -- what this machine is ----------------------------------------------
    def _machine_text(self) -> str:
        """Name, host and account — the machine's own answer, not the server's."""
        config = self.app.client_config
        host = config.api_url.replace("https://", "").replace("http://", "")
        return (
            f"[b {SECOND}]{machine_name()}[/]   [{MUTED}]this machine[/]\n"
            f"[{MUTED}]signed in as[/] {getattr(self.app, 'username', '?') or '?'} "
            f"[{MUTED}]on[/] {host}"
        )

    # -- data --------------------------------------------------------------
    @work(exclusive=True, group="settings")
    async def reload(self) -> None:
        await self._draw_features()

    async def _draw_features(self) -> None:
        """A tick box per feature this server offers, set to your answer."""
        client = getattr(self.app, "client", None)
        box = self.query_one("#settings-features", Vertical)
        if client is None:
            return
        try:
            features = await client.my_features()
        except ApiError as exc:
            await box.remove_children()
            await box.mount(Static(f"[{BAD}]{exc}[/]"))
            return
        self._features = {feature["key"]: feature for feature in features}
        await box.remove_children()
        for feature in features:
            await box.mount(
                Vertical(
                    Checkbox(
                        feature["label"],
                        value=feature["enabled"],
                        id=f"myfeature-{feature['key']}",
                    ),
                    Static(f"[{MUTED}]{feature['description']}[/]", classes="feature-note"),
                    classes="feature-row",
                )
            )

    # -- acting ------------------------------------------------------------
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """A tick from you goes to the server; one from drawing the boxes does not.

        Mounting a box with the state we just read can fire this too, so the
        two are told apart by what they say, not by a flag: a tick that
        already agrees with the server is one of ours.
        """
        event.stop()
        box_id = event.checkbox.id or ""
        if box_id.startswith("myfeature-"):
            key = box_id[len("myfeature-") :]
            known = self._features.get(key)
            if known is not None and event.value != known["enabled"]:
                self.set_feature(key, event.value)

    @work(group="settings-features")
    async def set_feature(self, key: str, wanted: bool) -> None:
        client = getattr(self.app, "client", None)
        if client is None:
            return
        try:
            feature = await client.set_my_feature(key, wanted)
        except ApiError as exc:
            self.app.say(str(exc))
            await self._draw_features()
            return
        self._features[key] = feature
        # The strip behind this dialog is drawn from the same list; the
        # workspace asks again when this screen closes, rather than the
        # tabs shuffling under a dialog that is still open.
        self.app.say(
            f"{feature['label']} is back."
            if feature["enabled"]
            else f"{feature['label']} is off — its tab is gone from your clients."
        )

    def action_reload(self) -> None:
        self.reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "open-add-device":
            self.app.push_screen(AddDeviceModal())
            return
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
