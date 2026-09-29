"""The workspace's Quill cards: one card and pane per screen of every installed Quill.

The workspace asks the server which Quills there are after sign-in and
again whenever the features are asked for (after an install or a removal
in Administration, after Settings), and this is what keeps its sidebar and
its switcher in step with the answer: a card and a pane for each screen,
drawn from the kit by tui/panes/kit.py, each with a function key of its
own, the ones that changed drawn again, and the ones whose Quill went taken
out. A Quill's `go`, and its actions on ctrl+e, come through here too.

`QuillCards` is mixed into the WorkspaceScreen, whose sidebar (`#sidebar`,
`#nav-section-quills`), switcher (`#panes`) and ways of showing a pane
(`action_show_pane`, `_mark_active`, `set_status`, `active_pane`,
`admin_showing`, `first_builtin`) it works with.
"""

from __future__ import annotations

import json

from textual import work
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher

from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.kitdata import loose_actions
from cloudmorrow.tui.panes.kit import pane_for, screen_key
from cloudmorrow.tui.quill_actions import QuillCommands, run_action
from cloudmorrow.tui.widgets.sidebar import NavCard, SectionLabel

# The function keys no built-in card has, handed to Quill cards in the order
# they appear, which is the catalog's.
QUILL_KEYS: tuple[str, ...] = ("f1", "f2", "f5", "f7", "f4", "f10", "f11", "f12", "f3")
# The keys the built-in cards had before each became a Quill, kept for the
# card of the same name wherever it comes in the order, so nobody's fingers
# have to learn them again. Chat's f6 is not one: in Notes it was Import as
# well, so Chat takes the next key free, f4.
FORMER_KEYS: dict[str, str] = {
    "notes": "f1", "tasks": "f2", "files": "f5", "calendar": "f7", "secrets": "f3",
}


class QuillCards:
    """The part of the workspace that is its Quills' cards and panes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The Quill cards there are now, by key, with what they were drawn
        # from — so a refresh only touches the ones that changed — and the
        # function key and the feature switch of each.
        self._quill_panes: dict[str, str] = {}
        self._quill_keys: dict[str, str] = {}
        self._feature_of: dict[str, str] = {}

    # -- Quill cards -------------------------------------------------------
    async def sync_quills(self) -> None:
        """One card and pane per screen of every installed Quill.

        Asked on sign-in and again whenever the features are (after an
        install or a removal in Administration, after Settings). A pane whose
        screen or datamodels did not change is left exactly as it is, cards
        and all; one that changed is drawn again, and one whose Quill went is
        taken out.
        """
        client = self.app.client
        if client is None:
            return
        try:
            quills = await client.quills()
        except ApiError:
            # Keep what is there: a Quill is not worth losing to a blip.
            return
        # Their actions, for the record sheet and the palette.
        self.app.quills = [q for q in quills if q.get("available") is not False]
        wanted: dict[str, tuple[dict, dict, str]] = {}
        for quill in quills:
            if quill.get("available") is False:
                # Nothing in it this account may use (docs/CIRCLES.md): not
                # theirs, so no card, the same as one switched off.
                continue
            for screen in quill.get("screens") or []:

                signature = json.dumps(
                    [quill.get("version"), quill.get("jobs"), screen, quill.get("models")],
                    sort_keys=True,
                    default=str,
                )
                wanted[screen_key(quill, screen)] = (quill, screen, signature)
        for key, signature in list(self._quill_panes.items()):
            if key not in wanted or wanted[key][2] != signature:
                await self._drop_quill_pane(key)
        anchor: NavCard | SectionLabel = self.query_one("#nav-section-quills", SectionLabel)
        for key, (quill, screen, signature) in wanted.items():
            if key in self._quill_panes:
                anchor = self.query_one(f"#nav-{key}", NavCard)
                continue
            card = await self._add_quill_pane(key, quill, screen, after=anchor)
            if card is not None:
                self._quill_panes[key] = signature
                anchor = card

    def _free_key(self, key: str) -> str:
        """This card's function key: the one it had, or the first nobody has."""
        if key in self._quill_keys:
            return self._quill_keys[key]
        taken = set(self._quill_keys.values())
        former = FORMER_KEYS.get(key)
        if former and former not in taken:
            free = former
        else:
            # A key another Quill had before is kept for it, even before it comes.
            spoken_for = set(FORMER_KEYS.values()) - {former}
            free = next((k for k in QUILL_KEYS if k not in taken and k not in spoken_for), "")
        if free:
            self._quill_keys[key] = free
        return free

    async def _add_quill_pane(
        self, key: str, quill: dict, screen: dict, *, after
    ) -> NavCard | None:
        if self.query(f"#pane-{key}") or self.query(f"#nav-{key}"):
            # Half there from a sync that was cut short by the next one.
            await self._drop_quill_pane(key)
        pane = pane_for(quill, screen, tab_key=self._free_key(key), id=f"pane-{key}")
        if pane is None:
            # A kit this terminal does not draw yet: no card, and no key held.
            self._quill_keys.pop(key, None)
            return None
        self._feature_of[key] = str(quill["id"])
        # Mounted hidden: the switcher only hides what it had at the start.
        pane.display = False
        await self.query_one("#panes", ContentSwitcher).mount(pane)
        card = NavCard(key, pane.TAB_LABEL, tag=pane.TAB_KEY, id=f"nav-{key}")
        card.set_class(self.has_class("-narrow"), "-line")
        card.set_status("none", str(quill.get("summary") or quill.get("name") or ""))
        await self.query_one("#sidebar", VerticalScroll).mount(card, after=after)
        # Its card says how it is from the start, not only once visited.
        pane.reload()
        return card

    async def _drop_quill_pane(self, key: str) -> None:
        switcher = self.query_one("#panes", ContentSwitcher)
        if switcher.current == f"pane-{key}":
            # Standing on it: step onto another card before the floor goes.
            other = next((k for k in self._quill_panes if k != key), None)
            if other is None:
                other = self.first_builtin()
            switcher.current = f"pane-{other}" if other else None
            self._mark_active(other or "")
        for widget in [*self.query(f"#nav-{key}"), *switcher.query(f"#pane-{key}")]:
            await widget.remove()
        self._quill_panes.pop(key, None)
        self._feature_of.pop(key, None)
        self._quill_keys.pop(key, None)

    def go_to(self, quill_id: str, screen_id: str, params: dict | None = None) -> None:
        """A Quill's `go`: to one of its screens, a view asked again with *params*."""
        quill = next((q for q in self.app.quills if q.get("id") == quill_id), None)
        screen = next(
            (s for s in (quill or {}).get("screens") or [] if s.get("id") == screen_id), None
        )
        if quill is None or screen is None:
            self.set_status(f"{quill_id} has no screen called {screen_id}.", error=True)
            return
        key = screen_key(quill, screen)
        found = self.query(f"#pane-{key}")
        if not found:
            return
        pane = found.first()
        if hasattr(pane, "params"):
            pane.params = dict(params or {})
        if self.query_one("#panes", ContentSwitcher).current == f"pane-{key}":
            pane.reload()
        self.action_show_pane(key)

    # -- a Quill's actions -------------------------------------------------
    def action_quill_actions(self) -> None:
        """ctrl+e: the palette of every action not on a record."""
        from textual.command import CommandPalette

        if not loose_actions([q for q in self.app.quills if q.get("enabled", True)]):
            self.set_status("No Quill here has an action of its own.", error=True)
            return
        self.app.push_screen(
            CommandPalette(providers=[QuillCommands], placeholder="Run a Quill action…")
        )

    def run_quill_action(self, quill: dict, action: dict) -> None:
        """One chosen in the palette: run it, then draw the pane you are on again."""
        self._run_quill_action(quill, action)

    @work(group="quill-action")
    async def _run_quill_action(self, quill: dict, action: dict) -> None:
        if await run_action(self.app, quill, action):
            pane = self.active_pane
            if pane is not None and not self.admin_showing:
                pane.reload()

    def action_quill_key(self, function_key: str) -> None:
        """One of the free function keys: the Quill card that holds it, if any."""
        key = next((k for k, f in self._quill_keys.items() if f == function_key), None)
        if key is not None and key in self._quill_panes:
            self.action_show_pane(key)
