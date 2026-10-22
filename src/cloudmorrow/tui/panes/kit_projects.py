"""Projects and their .env files, in the terminal.

A `list` that binds `vault` is a list of projects (docs/QUILLS.md), and the
terminal is on your machine, so it does what `cm <quill> init`, `update`,
`clone` and `secrets import` do, on the project under the cursor: the work
is cloudmorrow/checkout.py's, the same as the command line's.

- `i` makes a folder a project (this one, or the one you type) and reads
  its .env files into the project's vault.
- `u` pulls the project's folder and writes its .env files from the vault.
- `c` clones the project's repository and writes them there.
- `m` reads the folder's .env files into the vault again.

A list of the foundational `secret` datamodel gets `m` and `x` as well
(kit_grouped.py): the environment on screen in from a .env file, or out to
one.
"""

from __future__ import annotations

from pathlib import Path

from textual import work

from cloudmorrow.checkout import (
    CheckoutError,
    Imported,
    Projects,
    Written,
    clone,
    env_files,
    environment_of,
    export_file,
    file_for,
    import_file,
    init,
    pull,
    remembered,
    remote,
    write_all,
)
from cloudmorrow.client.api import ApiError
from cloudmorrow.tui.panes.kit import KitPane, ListPane
from cloudmorrow.tui.screens.modals import PromptModal
from cloudmorrow.tui.widgets.toolbar import Action


def said_written(written: list[Written]) -> str:
    """What writing the files did, in a line."""
    if not written:
        return "no secrets in its vault yet"
    parts = []
    for state, verb in (("written", "wrote"), ("unchanged", "unchanged")):
        names = [w.file for w in written if w.state == state]
        if names:
            parts.append(f"{verb} {', '.join(names)}")
    for one in written:
        if one.state == "kept":
            parts.append(f"kept {one.file} (only it has {', '.join(one.only_here)}: import it first)")
    return "; ".join(parts)


def said_imported(done: list[Imported]) -> str:
    if not done:
        return "no .env files there"
    return ", ".join(
        f"{one.file} → {one.environment} ({len(one.result['added'])} new, {len(one.result['updated'])} changed)"
        for one in done
    )


class ProjectsPane(ListPane):
    """A list of projects, with their folders on this machine."""

    BINDINGS = [
        *ListPane.BINDINGS,
        ("i", "fire('init')", "Init a folder"),
        ("u", "fire('update')", "Update"),
        ("c", "fire('clone')", "Clone"),
        ("m", "fire('import_env')", "Import .env"),
    ]
    WRITING = ListPane.WRITING | {"init"}

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.projects = Projects.of(screen, self.models)
        actions = list(self.ACTIONS)
        actions[1:1] = [
            Action("init", "Init", "i", hint="Make a folder a project, its .env files into its vault"),
            Action("update", "Update", "u", hint="git pull, then its .env files from the vault"),
            Action("clone", "Clone", "c", hint="Its repository into a folder, then its .env files"),
            Action("import_env", "Import .env", "m", hint="Its folder's .env files into the vault"),
        ]
        self.ACTIONS = self.offer(actions)

    @property
    def server(self) -> str:
        return self.api.config.api_url

    async def ask_folder(self, title: str, value: Path, detail: str = "") -> Path | None:
        text = await self.app.push_screen_wait(PromptModal(title, value=str(value), detail=detail))
        text = (text or "").strip()
        return Path(text).expanduser().resolve() if text else None

    def act_init(self) -> None:
        self.init_folder()

    @work(group="ui")
    async def init_folder(self) -> None:
        folder = await self.ask_folder(
            "Init a project",
            Path.cwd(),
            "[dim]The folder: a project is made for it (or found), and its .env files go into its vault.[/]",
        )
        if folder is None:
            return
        try:
            record, made, done = await init(self.api, self.projects, folder)
        except CheckoutError as exc:
            self.status(str(exc), error=True)
            return
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        name = self.projects.name(record)
        self.status(f"{'Made' if made else 'Found'} {name}: {said_imported(done)}.")
        self.reload()

    def _folder_of(self, record: dict) -> Path:
        return remembered(self.server, self.projects.vault_of(record)) or Path.cwd()

    def act_update(self) -> None:
        self.update_project()

    @work(group="ui")
    async def update_project(self) -> None:
        record = self.selected
        if record is None:
            return
        name = self.projects.name(record)
        folder = await self.ask_folder(f"Update {name}", self._folder_of(record), "[dim]Its folder on this machine.[/]")
        if folder is None:
            return
        if not folder.is_dir():
            self.status(f"{folder} is not there: clone it (c) first", error=True)
            return
        try:
            head = await pull(folder) if remote(folder) else ""
            written = await write_all(self.api, self.projects, record, folder)
        except CheckoutError as exc:
            self.status(str(exc), error=True)
            return
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        pulled = f"pulled ({head}); " if head else ""
        self.status(f"{name}: {pulled}{said_written(written)}.")

    def act_clone(self) -> None:
        self.clone_project()

    @work(group="ui")
    async def clone_project(self) -> None:
        record = self.selected
        if record is None:
            return
        name = self.projects.name(record)
        url = self.projects.repo_of(record)
        if not url:
            self.status(f"{name} has no repository: open it and fill one in", error=True)
            return
        folder = await self.ask_folder(
            f"Clone {name}", Path.cwd() / self.projects.vault_of(record), f"[dim]{url} goes into this folder.[/]"
        )
        if folder is None:
            return
        try:
            await clone(url, folder)
            written = await write_all(self.api, self.projects, record, folder)
        except CheckoutError as exc:
            self.status(str(exc), error=True)
            return
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.status(f"Cloned {name} into {folder}: {said_written(written)}.")

    def act_import_env(self) -> None:
        self.import_project_env()

    @work(group="ui")
    async def import_project_env(self) -> None:
        record = self.selected
        if record is None:
            return
        name = self.projects.name(record)
        folder = await self.ask_folder(
            f"Import {name}'s .env files", self._folder_of(record), "[dim]Every .env file in it, into its vault.[/]"
        )
        if folder is None:
            return
        try:
            found = env_files(folder)
            vault = self.projects.vault_of(record)
            done = [await import_file(self.api, vault, env, folder / file) for env, file in found.items()]
            if self.projects.files and found:
                files = {**self.projects.files_of(record), **found}
                await self.api.update_record(self.projects.model, record["id"], {self.projects.files: files})
        except CheckoutError as exc:
            self.status(str(exc), error=True)
            return
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.status(f"{name}: {said_imported(done)}.")
        self.reload()


class SecretFiles:
    """`m` and `x` on a list of the foundational `secret`: the environment on screen, in from a file or out to one.

    Mixed into kit_grouped.py's pane, which knows nothing of secrets: the
    vault and environment are two of its levels, read here by name.
    """

    @property
    def secrets(self) -> bool:
        return self.model_id == "secret"

    def file_actions(self) -> list[Action]:
        if not self.secrets:
            return []
        actions = [Action("export_env", "Export .env", "x", hint="The environment on screen into a .env file")]
        if self.writes:
            actions.insert(
                0, Action("import_env", "Import .env", "m", hint="A .env file into the environment on screen")
            )
        return actions

    def place(self) -> tuple[str, str]:
        """The vault and environment on screen."""
        chosen = {f["name"]: v for f, v in zip(self.levels, self.chosen, strict=False) if v}
        return chosen.get("vault") or "default", chosen.get("environment") or "local"

    def act_import_env(self) -> None:
        if self.secrets and self.writes:
            self.run_worker(self.import_env_file(), group="ui")

    def act_export_env(self) -> None:
        if self.secrets:
            self.run_worker(self.export_env_file(), group="ui")

    async def import_env_file(self: KitPane) -> None:
        vault, environment = self.place()
        text = await self.app.push_screen_wait(
            PromptModal(
                f"Import into {vault} · {environment}",
                value=str(Path.cwd() / file_for(environment, {})),
                detail="[dim]A .env file on this machine.[/]",
            )
        )
        path = Path((text or "").strip()).expanduser()
        if not (text or "").strip():
            return
        if not path.is_file():
            self.status(f"no such file: {path}", error=True)
            return
        into = environment or environment_of(path.name) or "local"
        try:
            done = await import_file(self.api, vault, into, path)
        except CheckoutError as exc:
            self.status(str(exc), error=True)
            return
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.status(f"{said_imported([done])}.")
        self.reload()

    async def export_env_file(self: KitPane) -> None:
        vault, environment = self.place()
        text = await self.app.push_screen_wait(
            PromptModal(
                f"Export {vault} · {environment}",
                value=str(Path.cwd() / file_for(environment, {})),
                detail="[dim]Written private (mode 600). A file with keys the vault lacks is left alone.[/]",
            )
        )
        if not (text or "").strip():
            return
        path = Path(text.strip()).expanduser()
        try:
            written = await export_file(self.api, vault, environment, path)
        except CheckoutError as exc:
            self.status(str(exc), error=True)
            return
        except ApiError as exc:
            await self.went_wrong(exc)
            return
        self.status(f"{said_written([written])}.")
