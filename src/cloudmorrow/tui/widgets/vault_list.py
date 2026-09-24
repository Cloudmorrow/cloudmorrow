"""The vault list: what the note tree is for notes, for your secrets.

A vault is a row in a list, the way a note is a leaf in a tree. Click one
and its environments and keys open beside it. Nothing outside the Secrets
tab knows which one is picked.
"""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len, set_cell_size
from rich.text import Text
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from cloudmorrow.tui.theme import ACCENT, MUTED, SECOND, TEXT

# How wide a row is before the list has been laid out: the vault column
# is 32 columns, less the one of padding on each side of a row.
ROW_WIDTH = 30


class VaultRow(ListItem):
    """One vault in the list. Holds its name so a click can say which."""

    def __init__(self, vault: str, label: Text) -> None:
        super().__init__(Static(label))
        self.vault = vault


class VaultList(ListView):
    """Your vaults, one row each, alphabetically."""

    BINDINGS = [
        ("n", "new_vault", "New vault"),
    ]

    class VaultChosen(Message):
        def __init__(self, vault: str) -> None:
            self.vault = vault
            super().__init__()

    class NewVaultRequested(Message):
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.vaults: list[dict] = []
        self.current: str | None = None
        # The width the rows were cut to last time, so a resize that changes
        # nothing does not rebuild the list under you.
        self._drawn_width = 0

    def show(self, vaults: list[dict], current: str | None) -> None:
        """Redraw the list. Keeps the selection on *current*."""
        self.vaults = vaults
        self.current = current
        self.clear()
        width = self.row_width()
        self._drawn_width = width
        rows = [
            VaultRow(
                vault["vault"],
                self._label(
                    vault["vault"],
                    vault["vault"] == current,
                    count=int(vault.get("secrets", 0)),
                    width=width,
                ),
            )
            for vault in vaults
        ]
        for row in rows:
            self.append(row)
        self.index = next(
            (index for index, row in enumerate(rows) if row.vault == current), 0
        )

    def row_width(self) -> int:
        """How many columns a row has, once the padding is taken off."""
        return self.size.width - 2 if self.size.width > 2 else ROW_WIDTH

    def on_resize(self) -> None:
        """A narrower column is a shorter name, so cut them again."""
        if self.vaults and self.row_width() != self._drawn_width:
            self.show(self.vaults, self.current)

    @staticmethod
    def _label(name: str, selected: bool, count: int = 0, width: int = ROW_WIDTH) -> Text:
        """One row, one line: the name, and how many secrets it holds, to the right."""
        tail = str(count) if count else ""
        marker = "▎" if selected else " "
        text = Text(marker, style=ACCENT if selected else "")
        room = max(1, width - 2 - (cell_len(tail) + 2 if tail else 0))
        shown = (
            name
            if cell_len(name) <= room
            else set_cell_size(name, room - 1).rstrip() + "…"
        )
        text.append(f" {shown}", style=f"bold {SECOND}" if selected else TEXT)
        if tail:
            text.append(" " * max(2, width - 2 - cell_len(shown) - cell_len(tail)))
            text.append(tail, style=MUTED)
        return text

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        if isinstance(event.item, VaultRow):
            self.post_message(self.VaultChosen(event.item.vault))

    def action_new_vault(self) -> None:
        self.post_message(self.NewVaultRequested())
