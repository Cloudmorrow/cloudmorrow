"""Notes: the list on the left, the live markdown editor on the right.

The editor is the same one it always was — the line the cursor is on stays raw
source, everything else renders — and everything autosaves. The notes are
yours: nothing selected anywhere else has anything to do with them.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Static

from cloudmorrow.client.api import ApiError, AuthError, ConflictError
from cloudmorrow.tui.panes.base import Pane
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

WELCOME = """\
# Welcome to Cloudmorrow

This is a **live** markdown editor: the line your cursor is on stays raw so you
can edit the markers, and every other line renders as you leave it.

- [ ] click a note on the left to open it
- [ ] press `ctrl+t` on this line to tick it off
- [x] notes are plain `.md` files on your server

> Everything autosaves. `ctrl+s` if you are impatient.
"""


class NotesPane(Pane):
    """Note list, editor, and the file operations around them."""

    TAB_LABEL = "Notes"
    TAB_KEY = "f1"
    BINDINGS = [
        ("ctrl+s", "fire('save')", "Save"),
        ("ctrl+n", "fire('new_note')", "New note"),
        ("ctrl+o", "fire('new_folder')", "New folder"),
        ("ctrl+f", "fire('search')", "Search"),
        ("f6", "fire('import_file')", "Import"),
        ("f7", "fire('export_file')", "Export"),
        ("ctrl+p", "fire('insert_image')", "Photo"),
    ]
    ACTIONS = (
        Action("new_note", "New note", "^n", variant="primary"),
        Action("new_folder", "New folder", "^o"),
        Action("search", "Search", "^f"),
        Action("rename", "Rename", "r", hint="Rename or move — r in the list"),
        Action("import_file", "Import", "f6", hint="Read a markdown file on this machine"),
        Action("export_file", "Export", "f7", hint="Write the open note back out to a file"),
        Action("insert_image", "Photo", "^p", hint="Put a picture from this machine in the note"),
    )

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.current_path: str | None = None
        self.current_rev: str | None = None
        self.dirty = False
        self._autosave_timer: Timer | None = None
        self._seeded = False
        # Pictures already fetched, by name. A name never means another picture.
        self._pictures: dict[str, bytes] = {}

    def content(self) -> ComposeResult:
        with Horizontal(id="notes-body"):
            yield NoteTree(id="note-tree")
            with Vertical(id="editor-pane"):
                yield Static("no note open", id="note-path")
                with Horizontal(id="editor-row"):
                    yield LiveMarkdownEditor(id="editor")
                    yield Picture(id="picture")

    def on_show(self) -> None:
        self.reload()

    # -- tree --------------------------------------------------------------
    @work(exclusive=True, group="tree")
    async def reload(self, select: str | None = None) -> None:
        client = self.api
        if client is None:
            return
        try:
            payload = await client.tree()
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.query_one(NoteTree).load_tree(payload, select=select or self.current_path)
        empty = not payload.get("children")
        # Only a brand-new account gets the welcome note.
        if empty and self.current_path is None and not self._seeded:
            self._seeded = True
            self.seed_welcome_note()
            return
        self.status("" if not empty else "No notes here yet — New note starts one.")

    @work(group="ui")
    async def seed_welcome_note(self) -> None:
        """A brand-new account gets one note explaining how the editor works."""
        try:
            note = await self.api.create_note("welcome.md", WELCOME)
        except ApiError:
            self.status("No notes here yet — New note starts one.")
            return
        self.reload(select=note["path"])
        self.open_note(note["path"])

    def on_note_tree_reload_requested(self, _: NoteTree.ReloadRequested) -> None:
        self.reload()

    def on_note_tree_note_selected(self, event: NoteTree.NoteSelected) -> None:
        if event.path != self.current_path:
            self.open_note(event.path)

    # -- open / save -------------------------------------------------------
    @work(exclusive=True, group="io")
    async def open_note(self, path: str) -> None:
        if self.dirty and self.current_path:
            await self._save(self.current_path)
        try:
            note = await self.api.read(path)
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.current_path = note["path"]
        self.current_rev = note["rev"]
        self.dirty = False
        self.query_one(LiveMarkdownEditor).load_text(note["content"])
        self.query_one("#note-path", Static).update(f"[{SECOND}]{note['path']}[/]")
        self.status()
        self.query_one(NoteTree).select_path(note["path"])
        self.update_picture()

    def on_live_markdown_editor_changed(self, _: LiveMarkdownEditor.Changed) -> None:
        if self.current_path is None:
            return
        self.dirty = True
        self.status()
        self._schedule_autosave()

    def on_live_markdown_editor_cursor_moved(self, _: LiveMarkdownEditor.CursorMoved) -> None:
        self.status()
        self.update_picture()

    # -- pictures ----------------------------------------------------------
    def wanted_picture(self) -> tuple[str, str] | None:
        """Which picture the panel should show: the cursor line's, else the note's first."""
        editor = self.query_one(LiveMarkdownEditor)
        match = IMAGE_REF.search(editor.current_line)
        if match:
            return match.group("name"), match.group("alt")
        refs = image_refs(editor.text)
        return refs[0] if refs else None

    @work(exclusive=True, group="picture")
    async def update_picture(self) -> None:
        panel = self.query_one(Picture)
        wanted = self.wanted_picture() if self.current_path else None
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
                data = await self.api.image(name)
            except ApiError as exc:
                panel.say(f"{name}: {exc}")
                return
            self._pictures[name] = data
        await panel.show(name, alt, data)

    def act_insert_image(self) -> None:
        self.insert_image()

    @work(group="ui")
    async def insert_image(self) -> None:
        """A picture from this machine, kept with the notes and written into this one."""
        if self.current_path is None:
            self.status("Open a note first.", error=True)
            return
        answer = await self.app.push_screen_wait(
            PromptModal(
                "Add a photo",
                placeholder="~/Pictures/rack.jpg",
                detail="[dim]PNG, JPEG, GIF or WebP. It is kept with your notes on the server.[/]",
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
            info = await self.api.upload_image(data, filename=source.name)
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

    def on_live_markdown_editor_save_requested(self, _: LiveMarkdownEditor.SaveRequested) -> None:
        self.act_save()

    def _schedule_autosave(self) -> None:
        if self._autosave_timer is not None:
            self._autosave_timer.stop()
        delay = max(0.3, float(self.app.client_config.autosave_seconds))
        self._autosave_timer = self.set_timer(delay, self._autosave)

    def _autosave(self) -> None:
        self._autosave_timer = None
        if self.dirty and self.current_path:
            self.save_note()

    def act_save(self) -> None:
        if self.current_path is None:
            self.status("Nothing open.", error=True)
            return
        self.save_note()

    @work(exclusive=True, group="io")
    async def save_note(self) -> None:
        if self.current_path:
            await self._save(self.current_path)

    async def flush(self) -> None:
        """Save anything unsaved. The workspace calls this before it moves on."""
        if self.dirty and self.current_path:
            await self._save(self.current_path)

    async def _save(self, path: str, *, force: bool = False) -> None:
        editor = self.query_one(LiveMarkdownEditor)
        content = editor.text
        try:
            note = await self.api.write(path, content, rev=None if force else self.current_rev)
        except ConflictError:
            choice = await self.app.push_screen_wait(ConflictModal(path))
            if choice == "overwrite":
                await self._save(path, force=True)
            elif choice == "reload":
                self.current_rev = None
                self.dirty = False
                self.open_note(path)
            else:
                self.status("Save cancelled — the server copy is newer.", error=True)
            return
        except AuthError:
            await self.app.sign_out(message="Session expired — sign in again.")
            return
        except ApiError as exc:
            self.status(f"Save failed: {exc}", error=True)
            return
        self.current_rev = note["rev"]
        # Anything typed while the request was in flight keeps the note dirty.
        self.dirty = editor.text != content
        self.status("" if self.dirty else "saved")

    # -- create / rename / delete -----------------------------------------
    def act_new_note(self) -> None:
        self.new_note(self.query_one(NoteTree).selected_dir)

    def on_note_tree_new_note_requested(self, event: NoteTree.NewNoteRequested) -> None:
        self.new_note(event.parent)

    @work(group="ui")
    async def new_note(self, parent: str) -> None:
        name = await self.app.push_screen_wait(
            PromptModal("New note", placeholder="name, or folder/name")
        )
        if not name:
            return
        path = (PurePosixPath(parent) / name).as_posix() if parent else name
        try:
            note = await self.api.create_note(path, f"# {PurePosixPath(name).stem}\n\n")
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(select=note["path"])
        self.open_note(note["path"])
        self.query_one(LiveMarkdownEditor).focus()

    def act_new_folder(self) -> None:
        self.new_folder(self.query_one(NoteTree).selected_dir)

    def on_note_tree_new_folder_requested(self, event: NoteTree.NewFolderRequested) -> None:
        self.new_folder(event.parent)

    @work(group="ui")
    async def new_folder(self, parent: str) -> None:
        name = await self.app.push_screen_wait(PromptModal("New folder", placeholder="name"))
        if not name:
            return
        path = (PurePosixPath(parent) / name).as_posix() if parent else name
        try:
            await self.api.create_dir(path)
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
        new_path = await self.app.push_screen_wait(
            PromptModal("Rename / move", value=path, placeholder="new path")
        )
        if not new_path or new_path == path:
            return
        try:
            result = await self.api.move(path, new_path)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        if not is_dir and self.current_path == path:
            self.current_path = result["path"]
            self.query_one("#note-path", Static).update(f"[{SECOND}]{result['path']}[/]")
        self.reload(select=result["path"])

    def on_note_tree_delete_requested(self, event: NoteTree.DeleteRequested) -> None:
        self.delete(event.path, event.is_dir)

    @work(group="ui")
    async def delete(self, path: str, is_dir: bool) -> None:
        kind = "folder" if is_dir else "note"
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                f"Delete {kind}?",
                detail=f"[b]{path}[/]" + ("\nEverything inside it goes too." if is_dir else ""),
            )
        )
        if not confirmed:
            return
        try:
            await self.api.delete(path, recursive=is_dir)
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        open_path = self.current_path or ""
        if open_path == path or (is_dir and open_path.startswith(path + "/")):
            self.forget_open_note()
            self.query_one(Picture).hide()
        self.reload()
        self.status(f"Deleted {path}")

    # -- search ------------------------------------------------------------
    def act_search(self) -> None:
        self.search()

    def on_note_tree_search_requested(self, _: NoteTree.SearchRequested) -> None:
        self.search()

    @work(group="ui")
    async def search(self) -> None:
        path = await self.app.push_screen_wait(SearchModal(self.api.search))
        if path:
            self.open_note(path)
            self.query_one(LiveMarkdownEditor).focus()

    # -- files in and out --------------------------------------------------
    def act_import_file(self) -> None:
        self.import_file()

    @work(group="ui")
    async def import_file(self) -> None:
        """Read a markdown file on this machine into the notes tree."""
        answer = await self.app.push_screen_wait(
            PromptModal(
                "Import a markdown file",
                placeholder="~/notes/standup.md",
                detail="[dim]It lands in the folder selected in the list.[/]",
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
        path = (PurePosixPath(parent) / source.name).as_posix() if parent else source.name
        try:
            note = await self.api.create_note(path, content)
        except ApiError as exc:
            if exc.status_code != 409:
                self.status(str(exc), error=True)
                return
            overwrite = await self.app.push_screen_wait(
                ConfirmModal(
                    "That note already exists",
                    detail=f"[b]{path}[/]\nReplace it with {source.name}?",
                    confirm_label="Replace",
                )
            )
            if not overwrite:
                return
            try:
                note = await self.api.write(path, content)
            except ApiError as write_exc:
                self.status(str(write_exc), error=True)
                return
        self.reload(select=note["path"])
        # Opening the note clears the status bar, so the word about the import
        # goes there once the note is open.
        await self.open_note(note["path"]).wait()
        self.status(f"Imported {source.name}")

    def act_export_file(self) -> None:
        self.export_file()

    @work(group="ui")
    async def export_file(self) -> None:
        """Write the open note back out to a file on this machine."""
        if self.current_path is None:
            self.status("Nothing open to export.", error=True)
            return
        if self.dirty:
            await self._save(self.current_path)
        default = Path.cwd() / PurePosixPath(self.current_path).name
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

    # -- the status line the workspace shows for this pane ------------------
    def status_detail(self) -> str:
        if self.current_path is None:
            return f"[{MUTED}]no note open[/]"
        editor = self.query_one(LiveMarkdownEditor)
        state = "●  unsaved" if self.dirty else "✓  saved"
        return (
            f"[{MUTED}]{state}  ·  ln {editor.cursor_row + 1}/{editor.line_count}"
            f"  ·  {editor.word_count()} words[/]"
        )
