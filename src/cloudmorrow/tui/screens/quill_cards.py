"""The workspace's Quill cards: one card per installed Quill, a pane per screen.

The workspace asks the server which Quills there are after sign-in and
again whenever the features are asked for (after an install or a removal
in Administration, after Settings), and this is what keeps its sidebar and
its switcher in step with the answer: a pane for each screen, drawn from
the kit by tui/panes/kit.py, the ones that changed drawn again, and the
ones whose Quill went taken out. A Quill's `go`, and its actions on
ctrl+e, come through here too.

A Quill is one card, with one function key: a CRM is CRM in the sidebar,
not Sales, Pipeline, Organisations, People and Activities side by side
with everything else. A Quill with one screen is that screen's card
(`#nav-<quill>`, its pane `#pane-<quill>`), as the built-in cards were. A
Quill with several has a card of its own (`#nav-<quill>`, no pane: chosen,
it opens the first screen) and under it an item per screen (`#nav-<quill>-
<screen>`, one line each), shown only while one of its screens is the pane
on show — the card is lit, and its items are listed under it.

The cards stand on shelves, one per category of the catalog's — PERSONAL,
HOME, BUSINESS, DEVELOPER — in the catalog's order, each a section label
(`#nav-shelf-<category>`) with its Quills' cards under it. The server says
the label and the order (`category_label`, `category_rank`, from
quills/registry.py); from a server that does not, the category's own name
stands in, shelved in the order the Quills came.

`QuillCards` is mixed into the WorkspaceScreen, whose sidebar (`#sidebar`,
`#nav-section-cloud`), switcher (`#panes`) and ways of showing a pane
(`action_show_pane`, `_mark_active`, `set_status`, `active_pane`,
`admin_showing`, `first_builtin`) it works with.
"""

from __future__ import annotations

import json
import re

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
    "notes": "f1",
    "tasks": "f2",
    "files": "f5",
    "calendar": "f7",
    "secrets": "f3",
}


def shelf_of(quill: dict) -> tuple[str, int | None]:
    """The shelf a Quill's cards stand on, and where that shelf comes: the
    catalog's label and rank when the server says them, else the category's
    own name (`home` reads Home) and no rank; QUILLS for one with neither."""
    label = str(quill.get("category_label") or "")
    rank = quill.get("category_rank")
    if not label:
        words = str(quill.get("category") or "").replace("_", " ").replace("-", " ").split()
        label = " ".join(words).capitalize() if words else "Quills"
    return label, rank if isinstance(rank, int) and not isinstance(rank, bool) else None


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-") or "other"


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
        # The ones the server composes for whoever asks rather than anybody
        # installed — Data (server/dataview.py) — whose cards stand under
        # YOUR CLOUD rather than among the Quills.
        self._cloud_panes: set[str] = set()
        # The shelves the Quills' cards stand on, by label, and which shelf
        # each card is on.
        self._shelves: dict[str, SectionLabel] = {}
        self._shelf_of: dict[str, str] = {}
        # The Quills with several screens: the Quill's own card (by its id)
        # and the key of its first screen, which the card opens; the keys of
        # its screens' items, in order; and which Quill each item is under.
        self._quill_cards: dict[str, str] = {}
        self._screens_of: dict[str, list[str]] = {}
        self._sub_of: dict[str, str] = {}
        # Panes with no card: a screen the Quill marked admin, its settings,
        # reached from Administration › Quills alone (admin_quills.py). By
        # key, the feature each is switched by.
        self._hidden_panes: dict[str, str] = {}

    # -- Quill cards -------------------------------------------------------
    async def sync_quills(self) -> None:
        """A pane per screen of every installed Quill, and a card per Quill.

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
        cloud = self.query_one("#nav-section-cloud", SectionLabel)
        # Which screens are under one card: a Quill's, when it has several.
        screens_of: dict[str, list[str]] = {}
        for key, (quill, screen, _) in wanted.items():
            if not screen.get("admin"):
                screens_of.setdefault(str(quill["id"]), []).append(key)
        for key, (quill, screen, signature) in wanted.items():
            if key in self._quill_panes:
                continue
            quill_id = str(quill["id"])
            if screen.get("admin"):
                # The Quill's settings: a pane with no card, opened from
                # Administration › Quills.
                if await self._add_quill_pane(key, quill, screen, first=False, hidden=True):
                    self._quill_panes[key] = signature
                continue
            keys = screens_of[quill_id]
            under = quill_id if len(keys) > 1 else ""
            first = key == keys[0]
            if quill.get("composed"):
                # Under YOUR CLOUD: after whatever is there already, which is
                # everything up to the Administration label.
                card = await self._add_quill_pane(
                    key,
                    quill,
                    screen,
                    before=self.query_one("#nav-section-admin", SectionLabel),
                    under=under,
                    first=first,
                )
                if card:
                    self._quill_panes[key] = signature
                    self._cloud_panes.add(key)
                continue
            # Among the Quills, anywhere for now: `shelve` puts it in place.
            card = await self._add_quill_pane(key, quill, screen, before=cloud, under=under, first=first)
            if card:
                self._quill_panes[key] = signature
        await self.shelve(
            [
                (key, quill)
                for key, (quill, screen, _) in wanted.items()
                if not (quill.get("composed") or screen.get("admin"))
            ]
        )
        current = self.query_one("#panes", ContentSwitcher).current or ""
        self.reveal_screens(current[len("pane-") :])
        self.show_sections()

    def admin_screens(self, quill_id: str) -> list[dict]:
        """The screens a Quill marked admin — its settings — that have a pane here."""
        quill = next((q for q in self.app.quills if q.get("id") == quill_id), None)
        return [
            s
            for s in (quill or {}).get("screens") or []
            if s.get("admin") and screen_key(quill, s) in self._hidden_panes
        ]

    def pane_key(self, key: str) -> str:
        """The pane a card opens: its own, or a Quill's first screen's."""
        return self._quill_cards.get(key, key)

    def reveal_screens(self, key: str) -> None:
        """The items under a Quill's card are there while one of its screens
        is on show — *key* names the pane — and the card is lit with it."""
        showing = getattr(self, "_showing", None)
        for quill_id, keys in self._screens_of.items():
            open_ = key in keys
            for card in self.query(f"#nav-{quill_id}"):
                if isinstance(card, NavCard):
                    card.set_active(open_)
            last = None
            for sub in keys:
                for card in self.query(f"#nav-{sub}"):
                    card.display = open_ and (showing is None or sub in showing)
                    card.set_class(False, "-last")
                    if card.display:
                        last = card
            if last is not None:
                last.set_class(True, "-last")

    async def shelve(self, quills: list[tuple[str, dict]]) -> None:
        """Stand the Quills' cards on their shelves: a section label per category,
        in the catalog's order, and under each its cards in the order they came.

        *quills* is every (card key, Quill) among the Quills, in the server's
        order. A card is moved, never drawn again; a shelf with nothing left
        on it goes.
        """
        sidebar = self.query_one("#sidebar", VerticalScroll)
        shelves: dict[str, tuple[float, list[str]]] = {}
        for key, quill in quills:
            if key not in self._quill_panes:
                continue
            label, rank = shelf_of(quill)
            rank = rank if rank is not None else len(shelves)
            rank, keys = shelves.setdefault(label, (rank, []))
            # A Quill's own card stands before the items under it.
            under = self._sub_of.get(key)
            if under and under not in keys:
                keys.append(under)
                self._shelf_of[under] = label
            keys.append(key)
            self._shelf_of[key] = label
        for label, heading in list(self._shelves.items()):
            if label not in shelves:
                await heading.remove()
                del self._shelves[label]
        anchor: SectionLabel | NavCard | None = None
        for label, (_, keys) in sorted(shelves.items(), key=lambda item: (item[1][0], item[0].casefold())):
            heading = self._shelves.get(label)
            if heading is None:
                heading = SectionLabel(label, id=f"nav-shelf-{_slug(label)}")
                self._shelves[label] = heading
                await sidebar.mount(heading, before=self.query_one("#nav-section-cloud", SectionLabel))
            # The first shelf stands at the top of the sidebar, with no air above it.
            heading.set_class(anchor is None, "-first")
            if anchor is None:
                sidebar.move_child(heading, before=0)
            else:
                sidebar.move_child(heading, after=anchor)
            anchor = heading
            for key in keys:
                card = self.query_one(f"#nav-{key}", NavCard)
                sidebar.move_child(card, after=anchor)
                anchor = card

    def show_sections(self) -> None:
        """The shelves and YOUR CLOUD, each shown while a card of its own is."""
        showing = {card.nav_key for card in self._place_cards() if card.display}
        quills = (showing & (set(self._quill_panes) | set(self._quill_cards))) - self._cloud_panes
        for label, heading in self._shelves.items():
            heading.display = any(self._shelf_of.get(key) == label for key in quills)
        # The rest are its: the built-in cards, and the composed ones.
        self.query_one("#nav-section-cloud").display = bool(showing - quills)

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
        self,
        key: str,
        quill: dict,
        screen: dict,
        *,
        after=None,
        before=None,
        under: str = "",
        first: bool = True,
        hidden: bool = False,
    ) -> NavCard | bool | None:
        """A pane for the screen, and its card: the Quill's own when it is the
        Quill's only screen, else an item under the Quill's card (*under*
        names the Quill), which is made with the first of them, and holds
        the function key for them all. *hidden*: the pane alone, no card —
        the Quill's settings, which Administration opens — and True for it."""
        if self.query(f"#pane-{key}") or self.query(f"#nav-{key}"):
            # Half there from a sync that was cut short by the next one.
            await self._drop_quill_pane(key)
        # One key per Quill: the first screen's, which its card opens.
        pane = pane_for(quill, screen, tab_key=self._free_key(key) if first else "", id=f"pane-{key}")
        if pane is None:
            # A kit this terminal does not draw yet: no card, and no key held.
            self._quill_keys.pop(key, None)
            return None
        # A Quill of somebody's own is switched by its key, `~alice.budget`.
        feature = str(quill.get("key") or quill["id"])
        self._feature_of[key] = feature
        # Mounted hidden: the switcher only hides what it had at the start.
        pane.display = False
        await self.query_one("#panes", ContentSwitcher).mount(pane)
        if hidden:
            self._hidden_panes[key] = feature
            return True
        sidebar = self.query_one("#sidebar", VerticalScroll)
        summary = str(quill.get("summary") or quill.get("name") or "")
        if under and under not in self._quill_cards:
            own = NavCard(under, str(quill.get("name") or under), tag=pane.TAB_KEY, id=f"nav-{under}")
            own.add_class("-parent")
            own.set_class(self.has_class("-narrow"), "-line")
            own.set_status("none", summary)
            await sidebar.mount(own, after=after, before=before)
            self._quill_cards[under] = key
            self._screens_of[under] = []
            self._feature_of[under] = feature
            after, before = own, None
        if under:
            card = NavCard(key, pane.TAB_LABEL, sub=True, id=f"nav-{key}")
            card.display = False
            self._screens_of[under].append(key)
            self._sub_of[key] = under
        else:
            card = NavCard(key, pane.TAB_LABEL, tag=pane.TAB_KEY, id=f"nav-{key}")
            card.set_status("none", summary)
        card.set_class(self.has_class("-narrow"), "-line")
        await sidebar.mount(card, after=after, before=before)
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
        self._cloud_panes.discard(key)
        self._hidden_panes.pop(key, None)
        self._shelf_of.pop(key, None)
        self._feature_of.pop(key, None)
        self._quill_keys.pop(key, None)
        # An item under a Quill's card: the card goes with its last item.
        under = self._sub_of.pop(key, None)
        if under is not None:
            keys = self._screens_of.get(under, [])
            if key in keys:
                keys.remove(key)
            if keys:
                if self._quill_cards.get(under) == key:
                    self._quill_cards[under] = keys[0]
            else:
                for widget in self.query(f"#nav-{under}"):
                    await widget.remove()
                self._quill_cards.pop(under, None)
                self._screens_of.pop(under, None)
                self._shelf_of.pop(under, None)
                self._feature_of.pop(under, None)

    def go_to(self, quill_id: str, screen_id: str, params: dict | None = None) -> None:
        """A Quill's `go`: to one of its screens, a view asked again with *params*."""
        quill = next((q for q in self.app.quills if q.get("id") == quill_id), None)
        screen = next((s for s in (quill or {}).get("screens") or [] if s.get("id") == screen_id), None)
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
        self.app.push_screen(CommandPalette(providers=[QuillCommands], placeholder="Run a Quill action…"))

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
