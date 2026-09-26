"""The kit's `editor`: the tree on the left, the live Markdown editor on the right.

A screen binds a `model`, its `title`, a Markdown `body`, and — when its
records sit in folders — a `path` field, `folder/sub/title`, whose folders
are the tree. The datamodel's `can` says the rest: `folders` when its
backend keeps folders that exist empty (made, renamed and deleted here),
`attachments` when it keeps pictures beside the pages, `search` when a
listing answers `?q=`. Nothing here knows what a note is; Notes is simply
the first Quill to draw one.

The editor is the one notes always had — the line the cursor is on stays
raw source, everything else renders — and it saves as you type. A page
changed somewhere else since it was opened is not written over: you are
asked.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Static

from cloudmorrow.client.api import ApiError, AuthError
from cloudmorrow.tui.panes.kit import KitPane
from cloudmorrow.tui.screens.modals import (
    ConfirmModal,
    ConflictModal,
    PromptModal,
    SearchModal,
)
from cloudmorrow.tui.theme import MUTED, SECOND
from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from cloudmorrow.tui.widgets.note_tree import NoteTree
from cloudmorrow.tui.widgets.picture import IMAGE_REF, Picture, image_refs
from cloudmorrow.tui.widgets.toolbar import Action


def _folder_of(path: str) -> str:
    return path.rpartition("/")[0]


class EditorPane(KitPane):
    """The tree, the page, and what you can do to either."""

    BINDINGS = [
        ("ctrl+s", "fire('save')", "Save"),
        ("ctrl+n", "fire('new_page')", "New"),
        ("ctrl+o", "fire('new_folder')", "New folder"),
        ("ctrl+f", "fire('search')", "Search"),
        ("f6", "fire('import_file')", "Import"),
        ("f7", "fire('export_file')", "Export"),
        ("ctrl+p", "fire('insert_image')", "Photo"),
    ]

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        self.title_field: str = screen.get("title") or self.model.get("title") or "title"
        self.body_field: str = screen.get("body") or "body"
        self.path_field: str = screen.get("path") or ""
        can = set(self.model.get("can") or [])
        self.keeps_folders = bool(self.path_field) and "folders" in can
        self.searches = "search" in can
        self.attaches = "attachments" in can
        actions = [
            Action("new_page", f"New {self.noun}", "^n", variant="primary"),
        ]
        if self.keeps_folders:
            actions.append(Action("new_folder", "New folder", "^o"))
        if self.searches:
            actions.append(Action("search", "Search", "^f"))
        actions += [
            Action("rename", "Rename", "r", hint="Rename or move — r in the tree"),
            Action("import_file", "Import", "f6", hint="Read a markdown file on this machine"),
            Action("export_file", "Export", "f7", hint="Write the open page back out to a file"),
        ]
        if self.attaches:
            actions.append(
                Action("insert_image", "Photo", "^p", hint="Put a picture from this machine in the page")
            )
        self.ACTIONS = tuple(actions)
        # The page that is open: its id, its path in the tree, and its rev.
        self.current_id: str | None = None
        self.current_path: str | None = None
        self.current_rev: object = None
        self.dirty = False
        self._autosave_timer: Timer | None = None
        # The tree's paths, by the id of the record each one is.
        self._ids: dict[str, str] = {}
        # Pictures already fetched, by name. A name never means another picture.
        self._pictures: dict[str, bytes] = {}

    def content(self) -> ComposeResult:
        with Horizontal(id="editor-body"):
            yield NoteTree(id="editor-tree", label=self.TAB_LABEL.lower())
            with Vertical(id="editor-pane"):
                yield Static(f"no {self.noun} open", id="editor-path")
                with Horizontal(id="editor-row"):
                    yield LiveMarkdownEditor(id="editor")
                    yield Picture(id="picture")

    def card_status(self) -> tuple[str, str] | None:
        if self.current_path:
            return "news", f"open: {self.current_path.rsplit('/', 1)[-1]}"
        if not self.loaded:
            return None
        count = len(self.records)
        return "ok", f"{count} {self.noun}{'' if count == 1 else 's'}"

    # -- what a record is called here -------------------------------------------
    def path_of(self, record: dict) -> str:
        fields = record.get("fields") or {}
        return str(fields.get(self.path_field or self.title_field) or "")

    def title_of(self, record: dict) -> str:
        fields = record.get("fields") or {}
        return str(fields.get(self.title_field) or "") or self.path_of(record).rsplit("/", 1)[-1]

    def _fields_for(self, path: str) -> dict:
        """What a record at *path* is written as: its path, or its title alone."""
        if self.path_field:
            return {self.path_field: path}
        return {self.title_field: path.rsplit("/", 1)[-1]}

    # -- the tree ----------------------------------------------------------------
    def _tree(self, records: list[dict], folders: list[str]) -> dict:
        """The records and folders as the tree widget draws them: folders first."""
        root: dict = {"name": "", "path": "", "is_dir": True, "children": []}
        dirs: dict[str, dict] = {"": root}

        def folder(path: str) -> dict:
            if path in dirs:
                return dirs[path]
            node = {"name": path.rsplit("/", 1)[-1], "path": path, "is_dir": True, "children": []}
            folder(_folder_of(path))["children"].append(node)
            dirs[path] = node
            return node

        for path in folders:
            folder(path)
        self._ids = {}
        for record in records:
            path = self.path_of(record)
            self._ids[path] = str(record["id"])
            parent = folder(_folder_of(path)) if self.path_field else root
            parent["children"].append(
                {"name": self.title_of(record), "path": path, "is_dir": False, "id": record["id"]}
            )

        def order(node: dict) -> None:
            node["children"].sort(key=lambda c: (not c["is_dir"], c["name"].casefold()))
            for child in node["children"]:
                if child["is_dir"]:
                    order(child)

        order(root)
        return root

    @work(exclusive=True, group="tree")
    async def reload(self, select: str | None = None) -> None:
        client = self.api
        if client is None:
            return
        try:
            self.records = await client.records(self.model_id)
            folders: list[str] = []
            if self.keeps_folders:
                folders = [f["path"] for f in await client.record_folders(self.model_id)]
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.loaded = True
        self.query_one(NoteTree).load_tree(
            self._tree(self.records, folders), select=select or self.current_path
        )
        # Opened again after a rename elsewhere: what is open may have moved.
        if self.current_path and self.current_path in self._ids:
            self.current_id = self._ids[self.current_path]
        self.status(
            "" if self.records or folders else f"Nothing here yet — New {self.noun} starts one.",
            note=True,
        )

    def on_note_tree_reload_requested(self, _: NoteTree.ReloadRequested) -> None:
        self.reload()

    def on_note_tree_note_selected(self, event: NoteTree.NoteSelected) -> None:
        if event.path != self.current_path and event.path in self._ids:
            self.open_page(self._ids[event.path])

    # -- open / save -------------------------------------------------------------
    @work(exclusive=True, group="io")
    async def open_page(self, record_id: str) -> None:
        if self.dirty and self.current_id:
            await self._save()
        try:
            record = await self.api.record(self.model_id, record_id)
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self._show(record)

    def _show(self, record: dict) -> None:
        self.current_id = str(record["id"])
        self.current_path = self.path_of(record)
        self.current_rev = record.get("rev")
        self.dirty = False
        body = str((record.get("fields") or {}).get(self.body_field) or "")
        self.query_one(LiveMarkdownEditor).load_text(body)
        self.query_one("#editor-path", Static).update(f"[{SECOND}]{self.current_path}[/]")
        self.status()
        self.query_one(NoteTree).select_path(self.current_path)
        self.update_picture()

    def forget_open_page(self) -> None:
        self.current_id = self.current_path = None
        self.current_rev = None
        self.dirty = False
        self.query_one(LiveMarkdownEditor).load_text("")
        self.query_one("#editor-path", Static).update(f"no {self.noun} open")

    def on_live_markdown_editor_changed(self, _: LiveMarkdownEditor.Changed) -> None:
        if self.current_id is None:
            return
        self.dirty = True
        self.status()
        self._schedule_autosave()

    def on_live_markdown_editor_cursor_moved(self, _: LiveMarkdownEditor.CursorMoved) -> None:
        self.status()
        self.update_picture()

    def on_live_markdown_editor_save_requested(self, _: LiveMarkdownEditor.SaveRequested) -> None:
        self.act_save()

    def _schedule_autosave(self) -> None:
        if self._autosave_timer is not None:
            self._autosave_timer.stop()
        delay = max(0.3, float(self.app.client_config.autosave_seconds))
        self._autosave_timer = self.set_timer(delay, self._autosave)

    def _autosave(self) -> None:
        self._autosave_timer = None
        if self.dirty and self.current_id:
            self.save_page()

    def act_save(self) -> None:
        if self.current_id is None:
            self.status("Nothing open.", error=True)
            return
        self.save_page()

    @work(exclusive=True, group="io")
    async def save_page(self) -> None:
        if self.current_id:
            await self._save()

    async def flush(self) -> None:
        """Save anything unsaved. The workspace calls this before it moves on."""
        if self.dirty and self.current_id:
            await self._save()

    async def _save(self, *, force: bool = False) -> None:
        editor = self.query_one(LiveMarkdownEditor)
        content = editor.text
        record_id = self.current_id
        try:
            saved = await self.api.update_record(
                self.model_id, record_id, {self.body_field: content},
                rev=None if force else self.current_rev,
            )
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            if exc.status_code != 409:
                self.status(f"Save failed: {exc}", error=True)
                return
            choice = await self.app.push_screen_wait(ConflictModal(self.current_path or ""))
            if choice == "overwrite":
                await self._save(force=True)
            elif choice == "reload":
                self.dirty = False
                self.open_page(record_id)
            else:
                self.status("Save cancelled — the server copy is newer.", error=True)
            return
        self.current_rev = saved.get("rev")
        # Anything typed while the request was in flight keeps the page dirty.
        self.dirty = editor.text != content
        self.status("" if self.dirty else "saved")

    # -- pictures ------------------------------------------------------------------
    def wanted_picture(self) -> tuple[str, str] | None:
        """Which picture the panel should show: the cursor line's, else the page's first."""
        editor = self.query_one(LiveMarkdownEditor)
        match = IMAGE_REF.search(editor.current_line)
        if match:
            return match.group("name"), match.group("alt")
        refs = image_refs(editor.text)
        return refs[0] if refs else None

    @work(exclusive=True, group="picture")
    async def update_picture(self) -> None:
        panel = self.query_one(Picture)
        wanted = self.wanted_picture() if self.current_id and self.attaches else None
        if wanted is None:
            panel.hide()
            return
        name, alt = wanted
        if panel.shown == name:
            return
        data = self._pictures.get(name)
        if data is None:
            panel.say(f"fetching {name}…")
            try:
                data = await self.api.attachment(self.model_id, name)
            except ApiError as exc:
                panel.say(f"{name}: {exc}")
                return
            self._pictures[name] = data
        await panel.show(name, alt, data)

    def act_insert_image(self) -> None:
        self.insert_image()

    @work(group="ui")
    async def insert_image(self) -> None:
        """A picture from this machine, kept beside the pages and written into this one."""
        if self.current_id is None:
            self.status(f"Open a {self.noun} first.", error=True)
            return
        answer = await self.app.push_screen_wait(
            PromptModal(
                "Add a photo",
                placeholder="~/Pictures/rack.jpg",
                detail="[dim]PNG, JPEG, GIF or WebP. It is kept beside the pages on the server.[/]",
            )
        )
        if not answer:
            return
        source = Path(answer).expanduser()
        try:
            data = source.read_bytes()
        except OSError as exc:
            self.status(f"cannot read {source}: {exc}", error=True)
            return
        try:
            info = await self.api.attach(self.model_id, data, filename=source.name)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        editor = self.query_one(LiveMarkdownEditor)
        line = f"![{source.stem}]({info['path']})"
        # On a line of its own, whatever the cursor was in the middle of.
        prefix = "" if editor.cursor_col == 0 else "\n"
        editor.insert_text(f"{prefix}{line}\n")
        editor.focus()
        self._pictures[info["name"]] = data
        self.update_picture()

    # -- new, rename, delete ----------------------------------------------------------
    def act_new_page(self) -> None:
        self.new_page(self.query_one(NoteTree).selected_dir)

    def on_note_tree_new_note_requested(self, event: NoteTree.NewNoteRequested) -> None:
        self.new_page(event.parent)

    @work(group="ui")
    async def new_page(self, parent: str) -> None:
        hint = "name, or folder/name" if self.path_field else "name"
        name = await self.app.push_screen_wait(PromptModal(f"New {self.noun}", placeholder=hint))
        if not name:
            return
        path = (PurePosixPath(parent) / name).as_posix() if parent else name
        stem = PurePosixPath(name).name
        try:
            record = await self.api.create_record(
                self.model_id, {**self._fields_for(path), self.body_field: f"# {stem}\n\n"}
            )
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(select=self.path_of(record))
        self._show(record)
        self.query_one(LiveMarkdownEditor).focus()

    def act_new_folder(self) -> None:
        self.new_folder(self.query_one(NoteTree).selected_dir)

    def on_note_tree_new_folder_requested(self, event: NoteTree.NewFolderRequested) -> None:
        self.new_folder(event.parent)

    @work(group="ui")
    async def new_folder(self, parent: str) -> None:
        if not self.keeps_folders:
            self.status(f"A folder here is made by a {self.noun} in it.", error=True)
            return
        name = await self.app.push_screen_wait(PromptModal("New folder", placeholder="name"))
        if not name:
            return
        path = (PurePosixPath(parent) / name).as_posix() if parent else name
        try:
            await self.api.make_record_folder(self.model_id, path)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(select=path)

    def act_rename(self) -> None:
        data = self.query_one(NoteTree).selected
        if data["path"]:
            self.rename(data["path"], data["is_dir"])

    def on_note_tree_rename_requested(self, event: NoteTree.RenameRequested) -> None:
        self.rename(event.path, event.is_dir)

    @work(group="ui")
    async def rename(self, path: str, is_dir: bool) -> None:
        if is_dir and not self.keeps_folders:
            self.status("A folder here is renamed by moving what is in it.", error=True)
            return
        new_path = await self.app.push_screen_wait(
            PromptModal("Rename / move", value=path, placeholder="new path")
        )
        if not new_path or new_path == path:
            return
        try:
            if is_dir:
                result = await self.api.move_record_folder(self.model_id, path, new_path)
                moved_to = result["path"]
                open_path = self.current_path or ""
                if open_path.startswith(path + "/"):
                    self.current_path = moved_to + open_path[len(path):]
            else:
                record = await self.api.update_record(
                    self.model_id, self._ids[path], self._fields_for(new_path)
                )
                moved_to = self.path_of(record)
                if self.current_path == path:
                    self.current_id = str(record["id"])
                    self.current_path = moved_to
                    self.current_rev = record.get("rev")
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if self.current_path:
            self.query_one("#editor-path", Static).update(f"[{SECOND}]{self.current_path}[/]")
        self.reload(select=moved_to)

    def act_delete_record(self) -> None:
        data = self.query_one(NoteTree).selected
        if data["path"]:
            self.delete(data["path"], data["is_dir"])

    def on_note_tree_delete_requested(self, event: NoteTree.DeleteRequested) -> None:
        self.delete(event.path, event.is_dir)

    @work(group="ui")
    async def delete(self, path: str, is_dir: bool) -> None:
        if is_dir and not self.keeps_folders:
            self.status("A folder here goes when what is in it does.", error=True)
            return
        kind = "folder" if is_dir else self.noun
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete {kind}?",
                detail=f"[b]{path}[/]" + ("\nEverything inside it goes too." if is_dir else ""),
            )
        )
        if not confirmed:
            return
        try:
            if is_dir:
                await self.api.delete_record_folder(self.model_id, path)
            else:
                await self.api.delete_record(self.model_id, self._ids[path])
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        open_path = self.current_path or ""
        if open_path == path or (is_dir and open_path.startswith(path + "/")):
            self.forget_open_page()
            self.query_one(Picture).hide()
        self.reload()
        self.status(f"Deleted {path}")

    # -- search ------------------------------------------------------------------------
    def act_search(self) -> None:
        if self.searches:
            self.search()

    def on_note_tree_search_requested(self, _: NoteTree.SearchRequested) -> None:
        self.act_search()

    async def _search(self, query: str) -> dict:
        """The record API's `?q=`, in the shape the search box lists."""
        found = await self.api.records(self.model_id, q=query)
        return {
            "results": [
                {"path": self.path_of(r), "matches": [{"text": r.get("preview") or ""}]}
                for r in found
            ]
        }

    @work(group="ui")
    async def search(self) -> None:
        path = await self.app.push_screen_wait(
            SearchModal(self._search, title=f"Search {self.TAB_LABEL.lower()}")
        )
        if not path:
            return
        found = next((r for r in self.records if self.path_of(r) == path), None)
        record_id = self._ids.get(path) or (found and found["id"])
        if record_id:
            self.open_page(record_id)
            self.query_one(LiveMarkdownEditor).focus()

    # -- files in and out -----------------------------------------------------------------
    def act_import_file(self) -> None:
        self.import_file()

    @work(group="ui")
    async def import_file(self) -> None:
        """Read a markdown file on this machine in, as a page."""
        answer = await self.app.push_screen_wait(
            PromptModal(
                "Import a markdown file",
                placeholder="~/notes/standup.md",
                detail="[dim]It lands in the folder selected in the tree.[/]",
            )
        )
        if not answer:
            return
        source = Path(answer).expanduser()
        try:
            content = source.read_text(encoding="utf-8")
        except OSError as exc:
            self.status(f"cannot read {source}: {exc}", error=True)
            return
        parent = self.query_one(NoteTree).selected_dir
        stem = source.name.removesuffix(".md")
        path = (PurePosixPath(parent) / stem).as_posix() if parent else stem
        if path in self._ids:
            overwrite = await self.app.push_screen_wait(
                ConfirmModal(
                    f"That {self.noun} already exists",
                    detail=f"[b]{path}[/]\nReplace it with {source.name}?",
                    confirm_label="Replace",
                )
            )
            if not overwrite:
                return
            call = self.api.update_record(self.model_id, self._ids[path], {self.body_field: content})
        else:
            call = self.api.create_record(
                self.model_id, {**self._fields_for(path), self.body_field: content}
            )
        try:
            record = await call
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(select=self.path_of(record))
        self._show(record)
        self.status(f"Imported {source.name}")

    def act_export_file(self) -> None:
        self.export_file()

    @work(group="ui")
    async def export_file(self) -> None:
        """Write the open page back out to a file on this machine."""
        if self.current_id is None:
            self.status("Nothing open to export.", error=True)
            return
        if self.dirty:
            await self._save()
        default = Path.cwd() / f"{PurePosixPath(self.current_path or 'page').name}.md"
        answer = await self.app.push_screen_wait(
            PromptModal(
                f"Export {self.current_path}",
                value=str(default),
                detail="[dim]An existing file is replaced.[/]",
            )
        )
        if not answer:
            return
        target = Path(answer).expanduser()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.query_one(LiveMarkdownEditor).text, encoding="utf-8")
        except OSError as exc:
            self.status(f"cannot write {target}: {exc}", error=True)
            return
        self.status(f"Wrote {target}")

    # -- the status line the workspace shows for this pane ---------------------------------
    def status_detail(self) -> str:
        if self.current_id is None:
            return f"[{MUTED}]no {self.noun} open[/]"
        editor = self.query_one(LiveMarkdownEditor)
        state = "●  unsaved" if self.dirty else "✓  saved"
        return (
            f"[{MUTED}]{state}  ·  ln {editor.cursor_row + 1}/{editor.line_count}"
            f"  ·  {editor.word_count()} words[/]"
        )
