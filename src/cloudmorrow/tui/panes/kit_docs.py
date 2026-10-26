"""The kit's `document` in the terminal: the editor's tree, and a document as Markdown.

A document screen is over `.docs` files — and Word's `.docx`, which the
server reads and writes as the same text (docs/DOCS.md). The terminal
cannot draw a page of blocks, so it edits the document as Markdown: a
heading is `# `, a bullet `- `, a numbered item `1. `, a quote `> `, a
table `| a | b |`, and `**bold**`, `*italic*`, `__underline__`,
`~~strike~~` and `[text](url)` in a line (quill/docs.py says the rest).
What is typed is kept as the document's file, never as Markdown; what
Markdown cannot say — how a paragraph is aligned — is lost on the way.

Import reads a Word, `.docs` or Markdown file on this machine in as a
document; Export writes the open one out as Word (`.docx`), PDF, `.docs`
or Markdown, by the name given. Open (f5) opens a document from anywhere
on the cloud — `share:folder/name.docx` — by its record, wherever it is.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from textual import work

from cloudmorrow.cli.quillrun.cells import anywhere
from cloudmorrow.cli.quillrun.docs import DocFileError, read_file, write_file
from cloudmorrow.client.api import ApiError
from cloudmorrow.quill import docs
from cloudmorrow.tui.panes.kit_editor import EditorPane
from cloudmorrow.tui.screens.modals import ConfirmModal, PromptModal
from cloudmorrow.tui.theme import MUTED
from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from cloudmorrow.tui.widgets.note_tree import NoteTree
from cloudmorrow.tui.widgets.toolbar import Action

IMPORTS = (".docx", ".docs", ".md", ".markdown", ".txt")


class DocsPane(EditorPane):
    """The editor over documents: Markdown in, the document's file out."""

    BINDINGS = [
        *EditorPane.BINDINGS,
        ("f5", "fire('open_anywhere')", "Open…"),
    ]

    def __init__(self, quill: dict, screen: dict, **kwargs) -> None:
        super().__init__(quill, screen, **kwargs)
        # A document keeps no pictures: the editor's photo button is not offered.
        self.attaches = False
        self.ACTIONS = self.offer(
            [a for a in self.ACTIONS if a.id != "insert_image"]
            + [Action("open_anywhere", "Open…", "f5", hint="A document anywhere on the cloud: share:folder/name")]
        )

    @property
    def noun(self) -> str:
        return "document"

    # -- the body: Markdown to edit, the file to keep ---------------------------------
    def body_to_show(self, body: str) -> str:
        return docs.to_markdown(docs.Doc.from_text(body))

    def body_to_keep(self, text: str) -> str:
        return docs.from_markdown(text).to_text()

    def new_body(self, stem: str) -> str:
        return docs.file_text([])

    def update_picture(self) -> None:
        """A document keeps no pictures; the panel stays empty."""

    # -- a document from anywhere on the cloud -------------------------------------------
    def act_open_anywhere(self) -> None:
        self.open_anywhere()

    @work(group="ui")
    async def open_anywhere(self) -> None:
        answer = await self.app.push_screen_wait(
            PromptModal(
                f"Open {self.noun} from anywhere",
                placeholder="my-files:Reports/Offer.docx",
                detail="[dim]A share's name, a colon, and the file's path in it.[/]",
            )
        )
        if not answer:
            return
        try:
            record = await anywhere(self.api, self.model_id, answer.strip(), self.noun)
        except SystemExit:
            record = None
        if record is None:
            self.status(f"No {self.noun} at {answer.strip()}", error=True)
            return
        self.open_page(str(record["id"]))

    # -- import and export: Word, PDF, .docs or Markdown files on this machine -----------
    @work(group="ui")
    async def import_file(self) -> None:
        answer = await self.app.push_screen_wait(
            PromptModal(
                "Import a document",
                placeholder="~/letters/offer.docx",
                detail="[dim]A Word, .docs or Markdown file; it lands in the folder selected in the tree.[/]",
            )
        )
        if not answer:
            return
        source = Path(answer).expanduser()
        if source.suffix.lower() not in IMPORTS:
            self.status(f"{source.name} is not a Word, .docs or Markdown file", error=True)
            return
        try:
            content = read_file(source).to_text()
        except DocFileError as exc:
            self.status(str(exc), error=True)
            return
        parent = self.query_one(NoteTree).selected_dir
        stem = source.stem
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
            call = self.api.create_record(self.model_id, {**self._fields_for(path), self.body_field: content})
        try:
            record = await call
        except ApiError as exc:
            self.status(str(exc), error=True)
            return
        self.reload(select=self.path_of(record))
        self._show(record)
        self.status(f"Imported {source.name}")

    @work(group="ui")
    async def export_file(self) -> None:
        if self.current_id is None:
            self.status("Nothing open to export.", error=True)
            return
        if self.dirty:
            await self._save()
        default = Path.cwd() / f"{PurePosixPath(self.current_path or 'document').name}.docx"
        answer = await self.app.push_screen_wait(
            PromptModal(
                f"Export {self.current_path}",
                value=str(default),
                detail="[dim]As Word (.docx), PDF, .docs or Markdown (.md), by the name. One there is replaced.[/]",
            )
        )
        if not answer:
            return
        target = Path(answer).expanduser()
        doc = docs.from_markdown(self.query_one(LiveMarkdownEditor).text)
        try:
            write_file(doc, target)
        except DocFileError as exc:
            self.status(str(exc), error=True)
            return
        self.status(f"Wrote {target}")

    # -- the status line the workspace shows for this pane ---------------------------------
    def status_detail(self) -> str:
        if self.current_id is None:
            return f"[{MUTED}]no {self.noun} open[/]"
        editor = self.query_one(LiveMarkdownEditor)
        state = "●  unsaved" if self.dirty else "✓  saved"
        word = " · Word" if (self.current_path or "") and self._is_word() else ""
        where = f"ln {editor.cursor_row + 1}/{editor.line_count}"
        return f"[{MUTED}]{state}  ·  {where}  ·  {editor.word_count()} words{word}[/]"

    def _is_word(self) -> bool:
        """Is the open document a Word file? Its record's name says."""
        for record in self.records:
            if str(record.get("id")) == self.current_id:
                return str((record.get("fields") or {}).get(self.title_field) or "").lower().endswith(".docx")
        return False
