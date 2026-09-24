"""Secrets: your vaults on the left, and the picked vault's world on the right.

Laid out like notes — a list you pick from, and what you picked beside it.
A vault's environments run across the top of the right-hand side and that
environment's keys are below them. Nothing is on screen until it is asked
for — a listing shows lengths, and one value at a time is revealed or
copied. Import and export read and write `.env` files on this machine,
which is where the TUI is running.

Picking a vault here means "show me this vault". It is not a mode the rest
of the app is in: nothing outside this pane knows or cares which one it is.
"""

from __future__ import annotations

import os
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Static

from cloudmorrow import dotenv
from cloudmorrow.client.api import ApiError
from cloudmorrow.dotenv import DEFAULT_VAULT, KNOWN_ENVIRONMENTS
from cloudmorrow.tui.panes.base import Pane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.toolbar import Action
from cloudmorrow.tui.widgets.vault_list import VaultList


def _mask(secret: dict) -> str:
    return "•" * min(secret.get("length", 0), 12) or "empty"


class EnvironmentBar(Horizontal):
    """The environments, as buttons. Clicking one switches to it."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_class("env-bar")

    async def show(self, environments: list[dict], current: str) -> None:
        # Awaited: removal is scheduled, and remounting the same ids before it
        # lands is a duplicate-id error.
        await self.remove_children()
        for environment in environments:
            name = environment["environment"]
            button = Button(
                f"{name}  {environment['secrets']}",
                id=f"env-{name}",
                compact=True,
                variant="primary" if name == current else "default",
            )
            button.tooltip = f"{environment['secrets']} secrets in {name}"
            await self.mount(button)
        add = Button("＋", id="env-new", compact=True)
        add.tooltip = "Work in another environment"
        await self.mount(add)


class SecretsPane(Pane):
    """Your vaults, and one vault's keys beside them."""

    TAB_LABEL = "Secrets"
    TAB_KEY = "f3"
    BINDINGS = [
        ("ctrl+n", "fire('new_vault')", "New vault"),
        ("a", "fire('add')", "Add / edit"),
        ("v", "fire('reveal')", "Reveal"),
        ("c", "fire('copy')", "Copy"),
        ("d", "fire('remove')", "Delete"),
        ("i", "fire('import_file')", "Import .env"),
        ("x", "fire('export_file')", "Export .env"),
        ("e", "fire('environment')", "Environment"),
        ("r", "fire('refresh')", "Refresh"),
    ]
    ACTIONS = (
        Action("new_vault", "New vault", "^n", hint="A named place for a set of secrets"),
        Action("add", "Add", "a", variant="primary", hint="Store a value for a key"),
        Action("reveal", "Reveal", "v", hint="Show the selected value, or hide it again"),
        Action("copy", "Copy", "c", hint="Copy the value without showing it"),
        Action("remove", "Delete", "d", variant="error"),
        Action("import_file", "Import", "i", hint="Read a .env file on this machine"),
        Action("export_file", "Export", "x", hint="Write this environment out as a .env"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.environment = ""
        # Which vault the right-hand side is showing. Nothing else in the
        # app reads it.
        self.selected_vault: str | None = None
        self._vaults: list[dict] = []
        self._environments: list[dict] = []
        self._secrets: list[dict] = []
        self._revealed: dict[str, str] = {}

    def content(self) -> ComposeResult:
        with Horizontal(id="secrets-body"):
            yield VaultList(id="vault-list")
            with Vertical(id="secret-detail"):
                yield Static("", id="vault-name")
                yield EnvironmentBar(id="environment-bar")
                with Vertical(id="secret-body"):
                    yield DataTable(id="secret-table", cursor_type="row", zebra_stripes=True)
                    yield Static("", id="secret-empty")

    def on_mount(self) -> None:
        table = self.query_one("#secret-table", DataTable)
        table.add_columns("key", "value", "len", "updated")
        self.environment = self.app.client_config.environment or "local"
        self.selected_vault = self.app.client_config.vault or DEFAULT_VAULT

    def on_show(self) -> None:
        self.reload()
        # Focus lands in the pane so its keys are in the footer before you
        # touch anything. Not stolen back if you are already working inside it.
        focused = self.screen.focused
        if focused is None or self not in focused.ancestors:
            self.query_one(VaultList).focus()

    # -- the vaults --------------------------------------------------------
    @property
    def vault(self) -> str:
        return self.selected_vault or DEFAULT_VAULT

    def select(self, vault: str) -> None:
        """Show another vault on the right. Nothing outside this pane moves."""
        self.selected_vault = vault
        self._revealed.clear()
        self.reload()

    def on_vault_list_vault_chosen(self, event: VaultList.VaultChosen) -> None:
        event.stop()
        if event.vault != self.selected_vault:
            self.select(event.vault)

    def on_vault_list_new_vault_requested(self, _: VaultList.NewVaultRequested) -> None:
        self.new_vault()

    def act_new_vault(self) -> None:
        self.new_vault()

    @work(group="ui")
    async def new_vault(self) -> None:
        name = await self.app.push_screen_wait(
            PromptModal(
                "New vault",
                placeholder="home",
                detail="[dim]A vault exists once it holds a secret: add one next.[/]",
            )
        )
        if not name:
            return
        self.select(name.strip().lower())

    def _draw_vaults(self) -> None:
        rows = list(self._vaults)
        # A vault picked but not yet holding anything — just made, or the
        # default on a fresh account — is still a row, or there is nothing
        # to be standing in.
        if self.vault not in {row["vault"] for row in rows}:
            rows.append({"vault": self.vault, "secrets": 0, "environments": 0})
        rows.sort(key=lambda row: row["vault"])
        self.query_one(VaultList).show(rows, self.vault)
        self.query_one("#vault-name", Static).update(f"[b]{self.vault}[/]")

    @property
    def selected(self) -> dict | None:
        table = self.query_one("#secret-table", DataTable)
        if not self._secrets or not 0 <= table.cursor_row < len(self._secrets):
            return None
        return self._secrets[table.cursor_row]

    @work(exclusive=True, group="secrets")
    async def reload(self, message: str = "") -> None:
        client = self.api
        if client is None:
            return
        try:
            self._vaults = await client.secret_vaults()
            self._environments = await client.secret_environments(vault=self.vault)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._draw_vaults()
        names = [row["environment"] for row in self._environments]
        # Landing on an environment this vault has never used shows an empty
        # table and no hint that the others exist. Land on a real one instead.
        if names and self.environment not in names:
            self.environment = names[0]
        rows = list(self._environments)
        if self.environment not in names:
            rows.append({"environment": self.environment, "secrets": 0})
        rows.sort(key=lambda row: row["environment"])
        self._environments = rows
        await self.query_one(EnvironmentBar).show(rows, self.environment)
        await self._load_secrets(message)

    async def _load_secrets(self, message: str = "") -> None:
        try:
            self._secrets = await self.api.secrets(self.environment, vault=self.vault)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        table = self.query_one("#secret-table", DataTable)
        row = table.cursor_row
        table.clear()
        for secret in self._secrets:
            revealed = self._revealed.get(secret["key"])
            table.add_row(
                secret["key"],
                revealed if revealed is not None else f"[{MUTED}]{_mask(secret)}[/]",
                str(secret["length"]),
                secret["updated_at"].replace("T", " ")[:16],
            )
        empty = self.query_one("#secret-empty", Static)
        if self._secrets:
            table.move_cursor(row=min(max(row, 0), len(self._secrets) - 1))
            table.display = True
            empty.display = False
            self.status(message)
        else:
            table.display = False
            empty.display = True
            empty.update(
                f"[{MUTED}]Nothing in [/][b]{self.vault} · {self.environment}[/]"
                f"[{MUTED}] yet.\n\nAdd one above, or import a .env file:[/]\n"
                f"  [dim]cloudmorrow secret import -f .env -v {self.vault}[/]"
            )
            self.status(message)

    def use_environment(self, environment: str) -> None:
        self.environment = environment
        # Revealed values belong to the environment they came from.
        self._revealed.clear()
        self.reload()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not (event.button.id or "").startswith("env-"):
            return
        event.stop()
        if event.button.id == "env-new":
            self.pick_environment()
            return
        self.use_environment(event.button.id[len("env-") :])

    @work(group="ui")
    async def pick_environment(self) -> None:
        known = ", ".join(KNOWN_ENVIRONMENTS)
        name = await self.app.push_screen_wait(
            PromptModal(
                "Environment",
                value=self.environment,
                placeholder="production",
                detail=f"[dim]{known} — or any name you like.[/]",
            )
        )
        if name:
            self.use_environment(name.strip().lower())

    # -- actions -----------------------------------------------------------
    def act_refresh(self) -> None:
        self.reload()

    def act_environment(self) -> None:
        self.pick_environment()

    def act_reveal(self) -> None:
        self.reveal()

    @work(group="ui")
    async def reveal(self) -> None:
        secret = self.selected
        if secret is None:
            return
        if secret["key"] in self._revealed:
            del self._revealed[secret["key"]]
            await self._load_secrets()
            return
        value = await self._value_of(secret["key"])
        if value is None:
            return
        self._revealed[secret["key"]] = value
        await self._load_secrets(f"{secret['key']} is on screen — reveal again to hide it.")

    def act_copy(self) -> None:
        self.copy_secret()

    @work(group="ui")
    async def copy_secret(self) -> None:
        secret = self.selected
        if secret is None:
            return
        value = self._revealed.get(secret["key"]) or await self._value_of(secret["key"])
        if value is None:
            return
        # Textual copies via OSC 52, so this works over SSH in most terminals.
        self.app.copy_to_clipboard(value)
        self.status(f"Copied {secret['key']} to the clipboard.")

    async def _value_of(self, key: str) -> str | None:
        try:
            return (
                await self.api.read_secret(key, self.environment, vault=self.vault)
            )["value"]
        except ApiError as exc:
            self.status(str(exc), error=True)
            return None

    def act_add(self) -> None:
        self.add_secret()

    @work(group="ui")
    async def add_secret(self) -> None:
        selected = self.selected
        key = await self.app.push_screen_wait(
            PromptModal(
                f"Secret in {self.vault} · {self.environment}",
                value=selected["key"] if selected else "",
                placeholder="DATABASE_URL",
                detail="[dim]An existing key is replaced.[/]",
            )
        )
        if not key:
            return
        value = await self.app.push_screen_wait(
            PromptModal(f"Value for {key}", placeholder="not shown as you type", password=True)
        )
        if value is None:
            return
        try:
            await self.api.write_secret(key, value, self.environment, vault=self.vault)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._revealed.pop(key, None)
        self.reload(f"Saved {key} in {self.environment}")

    def act_remove(self) -> None:
        self.remove_secret()

    @work(group="ui")
    async def remove_secret(self) -> None:
        secret = self.selected
        if secret is None:
            return
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                "Delete this secret?",
                detail=f"[b]{secret['key']}[/] in {self.environment}\nThe value is gone for good.",
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete_secret(secret["key"], self.environment, vault=self.vault)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._revealed.pop(secret["key"], None)
        self.reload(f"Deleted {secret['key']}")

    # -- files on this machine ---------------------------------------------
    def act_import_file(self) -> None:
        self.import_file()

    @work(group="ui")
    async def import_file(self) -> None:
        raw = await self.app.push_screen_wait(
            PromptModal(
                f"Import a .env into {self.environment}",
                value=str(Path.cwd() / ".env"),
                placeholder="~/code/app/.env",
                detail="[dim]Existing keys are replaced; nothing else is touched.[/]",
            )
        )
        if not raw:
            return
        path = Path(raw).expanduser()
        try:
            entries = dotenv.parse(path.read_text(encoding="utf-8"))
        except (OSError, dotenv.DotenvError) as exc:
            self.status(str(exc), error=True)
            return
        if not entries:
            self.status(f"{path} holds no assignments", error=True)
            return
        try:
            result = await self.api.import_secrets(entries, self.environment, vault=self.vault)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(
            f"{len(result['added'])} added, {len(result['updated'])} updated "
            f"from {path.name}"
        )

    def act_export_file(self) -> None:
        self.export_file()

    @work(group="ui")
    async def export_file(self) -> None:
        raw = await self.app.push_screen_wait(
            PromptModal(
                f"Write {self.environment} to a .env",
                value=str(Path.cwd() / ".env"),
                placeholder="~/code/app/.env",
                detail="[dim]Written at mode 600. An existing file is replaced.[/]",
            )
        )
        if not raw:
            return
        path = Path(raw).expanduser()
        try:
            entries = await self.api.export_secrets(self.environment, vault=self.vault)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if not entries:
            self.status(f"nothing in {self.environment} to write", error=True)
            return
        header = (
            f"{self.vault} · {self.environment}\n"
            "Written by cloudmorrow. Keep it out of version control."
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(dotenv.dump(entries, header=header))
            os.chmod(path, 0o600)
        except OSError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Wrote {len(entries)} secrets to {path} (mode 600)")
