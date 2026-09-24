"""Settings: this machine, and which of the app you want.

Two things, and they are the two that are yours rather than the server's.
The machine you happen to be sitting at — what it is called, whether the
server has heard from it lately, and whether its Omarchy config is one of
the copies being kept in step. And the tabs: a tick box per feature, so an
account that never opens Projects can stop being offered them. What the
machines have actually been doing is not here: that is the bell in the top
bar.

The feature boxes are only ever the ones this server offers. One an
administrator has switched off is not listed at all — it is not a thing you
can have an opinion about, and a tick box that did nothing would be worse
than no tick box. Switching one off here hides its tab for you, on every
machine you sign in from; it does not close the API, because this is a
preference and a preference that locked you out would be a mistake with no
way back from the phone you made it on.

The Omarchy tick box is the whole of that feature's user interface. Ticking
it tells the server this machine syncs `omarchy`; the agent finds out on its
next heartbeat and does the rest. If nobody has claimed the bundle yet, this
machine's copy becomes the one everybody else adopts — so the box says so
before you tick it, rather than after.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Label, Static

from cloudmorrow.agent.omarchy import BUNDLE, PATHS, describe, is_omarchy
from cloudmorrow.agent.setup import machine_name
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.screens.modals import Modal
from cloudmorrow.tui.theme import ACCENT, BAD, GOOD, MUTED, SECOND, WARN


def _short(value: str | None, width: int = 16) -> str:
    return (value or "—")[:width].replace("T", " ")


class SettingsScreen(Modal[None]):
    """This machine, and its Omarchy config."""

    BINDINGS = [("escape", "close", "Close"), ("ctrl+r", "reload", "Refresh")]

    def __init__(self) -> None:
        super().__init__()
        # The agent record for this machine, once we have found it.
        self._agent: dict | None = None
        self._bundle: dict = {}
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

                yield Static(f"[{MUTED}]omarchy config[/]", classes="pane-title")
                yield Static("Looking for this machine…", id="settings-omarchy")
                yield Checkbox(
                    "Keep Omarchy config in sync", value=False, id="sync-omarchy", disabled=True
                )
                yield Static("", id="settings-bundle")

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

    def on_mount(self) -> None:
        # The tick box and the buttons are what there is to reach, so the
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
        client = getattr(self.app, "client", None)
        if client is None:
            return
        name = machine_name()
        try:
            agents = await client.agents()
            self._bundle = await client.config_bundle(BUNDLE)
        except ApiError as exc:
            self.query_one("#settings-omarchy", Static).update(f"[{BAD}]{exc}[/]")
            return
        self._agent = next((agent for agent in agents if agent["name"] == name), None)
        self._draw_omarchy()
        await self._draw_features()

    def _draw_omarchy(self) -> None:
        """Say what this machine is, and switch the box on only if it can sync."""
        box = self.query_one("#sync-omarchy", Checkbox)
        line = self.query_one("#settings-omarchy", Static)
        agent = self._agent

        if agent is None:
            box.disabled = True
            line.update(
                f"[{WARN}]No agent enrolled for this machine.[/]\n"
                f"[{MUTED}]`cloudmorrow login` here enrols it and starts it.[/]"
            )
            self._draw_bundle()
            return

        # The agent on the machine is the one that knows; local detection is
        # the fallback for a machine whose agent has not reported in yet.
        capable = "omarchy" in agent["capabilities"] or is_omarchy()
        dot = f"[{GOOD}]●[/]" if agent["online"] else f"[{MUTED}]○[/]"
        seen = "online" if agent["online"] else f"last seen {_short(agent['last_seen'])}"
        if not capable:
            box.disabled = True
            line.update(
                f"{dot} [{MUTED}]{seen}[/]\n"
                f"[{MUTED}]{describe()} — nothing to sync from here.[/]"
            )
            self._draw_bundle()
            return

        box.disabled = False
        box.value = BUNDLE in (agent.get("sync_bundles") or [])
        line.update(
            f"{dot} [{MUTED}]{seen}[/]\n"
            f"[{MUTED}]{describe()}[/]\n"
            f"[{MUTED}]syncing ~/.config/{', ~/.config/'.join(PATHS)}[/]"
        )
        self._draw_bundle()

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

    def _draw_bundle(self) -> None:
        """The bundle's own story: who claimed it, when it last moved, who keeps it."""
        bundle = self._bundle
        target = self.query_one("#settings-bundle", Static)
        if not bundle or not bundle.get("revision"):
            target.update(
                f"[{MUTED}]Nobody is syncing this yet. The first machine to tick the box "
                f"decides the configuration every other machine adopts.[/]"
            )
            return
        machines = bundle.get("machines") or []
        here = machine_name()
        listed = ", ".join(
            f"[b]{name}[/]" if name == here else name for name in machines
        )
        target.update(
            f"[{ACCENT}]revision {bundle['revision']}[/] "
            f"[{MUTED}]from[/] {bundle.get('origin') or '?'} "
            f"[{MUTED}]at {_short(bundle.get('updated_at'), 19)}[/]\n"
            f"[{MUTED}]claimed by[/] {bundle.get('claimed_by') or '?'}"
            f"[{MUTED}] · {len(bundle.get('files') or [])} files ·"
            f" kept by[/] {listed or '—'}"
        )

    # -- acting ------------------------------------------------------------
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """A tick from you goes to the server; one from `_draw_omarchy` does not.

        Setting `value` to draw the state we just read fires this too, and the
        message arrives after the assignment has returned — so the two are told
        apart by what they say, not by a flag: a tick that already agrees with
        the server is one of ours.
        """
        event.stop()
        box_id = event.checkbox.id or ""
        if box_id.startswith("myfeature-"):
            key = box_id[len("myfeature-") :]
            known = self._features.get(key)
            if known is not None and event.value != known["enabled"]:
                self.set_feature(key, event.value)
            return
        if box_id != "sync-omarchy" or self._agent is None:
            return
        if event.value == (BUNDLE in (self._agent.get("sync_bundles") or [])):
            return
        self.set_sync(event.value)

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

    @work(group="settings-write")
    async def set_sync(self, wanted: bool) -> None:
        agent = self._agent
        client = getattr(self.app, "client", None)
        if agent is None or client is None:
            return
        bundles = [BUNDLE] if wanted else []
        box = self.query_one("#sync-omarchy", Checkbox)
        box.disabled = True
        try:
            self._agent = await client.set_agent_sync(agent["id"], bundles)
        except ApiError as exc:
            self.query_one("#settings-bundle", Static).update(f"[{BAD}]{exc}[/]")
            box.disabled = False
            return
        box.disabled = False
        claimed = bool(self._bundle.get("revision"))
        # Said in the status bar under this screen, and read when it closes.
        if wanted and not claimed:
            self.app.say(
                "This machine will claim the config on its next check-in — "
                "its copy becomes the one the others adopt."
            )
        elif wanted:
            self.app.say(
                f"Syncing with revision {self._bundle['revision']} from "
                f"{self._bundle.get('origin') or 'the server'}."
            )
        else:
            self.app.say("This machine keeps its files, and stops following the others.")
        self.reload()

    def action_reload(self) -> None:
        self.reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
