"""The kit's `document` in the terminal: the editor's tree, a document as Markdown (docs/DOCS.md).

Drawn from a Docs Quill as the server sends it, over the fake notes client
pointed at the Documents folder: a document opens as Markdown, what is
typed is saved as the document's file, a new one is an empty document, a
Word file on this machine is imported, the open one is exported as Word.
"""

from __future__ import annotations

import copy

from cloudmorrow.quill import docs, docx
from cloudmorrow.tui.panes.kit import pane_for
from cloudmorrow.tui.panes.kit_docs import DocsPane
from cloudmorrow.tui.widgets.editor import LiveMarkdownEditor
from tests.tui_harness import feature_row, settle, start
from tests.tui_notes import FILE_MODEL, NOTES_QUILL, note_id

DOCS_QUILL = {
    **copy.deepcopy(NOTES_QUILL),
    "id": "docs",
    "name": "Docs",
    "summary": "Documents.",
    "category": "productivity",
    "icon": "document",
    "screens": [
        {
            "id": "docs",
            "kit": "document",
            "label": "Docs",
            "model": "file",
            "where": {"share": "my-files", "within": "Notes"},
            "suffix": [".md", ".docx"],
            "title": "name",
            "body": "text",
            "path": "path",
        },
    ],
    "models": {"file": FILE_MODEL},
}

LETTER = docs.Doc(
    [
        {"kind": "heading", "level": 1, "runs": [{"text": "Letter"}]},
        {"kind": "paragraph", "runs": [{"text": "Dear "}, {"text": "you", "bold": True}]},
    ]
)


def with_docs(app):
    """The fake notes client's files, read as documents: the Docs screen is
    pointed at the same folder and suffix the fake serves."""
    app.client.quill_list = [q for q in app.client.quill_list if q["id"] != "notes"]
    app.client.quill_list.insert(0, copy.deepcopy(DOCS_QUILL))
    app.client.feature_list.append(feature_row("docs", "Docs"))
    app.client.note_files = {"letter": [LETTER.to_text(), 1]}


async def _open(app, pilot):
    screen = await start(app, pilot)
    screen.action_show_pane("docs")
    await settle(app, pilot)
    assert screen.query_one("#panes").current == "pane-docs"
    return screen


def test_the_docs_screen_is_a_docs_pane():
    pane = pane_for(DOCS_QUILL, DOCS_QUILL["screens"][0], tab_key="f1", id="pane-docs")
    assert isinstance(pane, DocsPane)
    assert pane.filters == {"share": "my-files", "within": "Notes", "suffix": ".md,.docx"}
    assert pane.bound["suffix"] == ".md" and pane.bound["suffixes"] == [".md", ".docx"]
    assert [a.id for a in pane.ACTIONS] == ["new_page", "new_folder", "search", "rename", "import_file", "export_file"]
    assert pane.noun == "document"


async def test_a_document_opens_as_markdown_and_is_saved_as_its_file(app):
    with_docs(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await _open(app, pilot)
        pane = screen.query_one(DocsPane)
        pane.open_page(note_id("letter"))
        await settle(app, pilot)
        editor = pane.query_one(LiveMarkdownEditor)
        assert editor.text == "# Letter\n\nDear **you**\n"
        editor.load_text(editor.text + "\n- a thing\n")
        pane.dirty = True
        await pane.flush()
        await settle(app, pilot)
        kept = docs.Doc.from_text(app.client.note_files["letter"][0])
        assert kept.blocks == LETTER.blocks + [{"kind": "bullet", "runs": [{"text": "a thing"}]}]
        assert app.client.note_calls[-1][2]["text"].startswith('{\n  "blocks": ['), "the file, never Markdown"


async def test_a_new_document_is_empty_and_import_and_export_go_through_word(app, tmp_path):
    with_docs(app)
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await _open(app, pilot)
        pane = screen.query_one(DocsPane)
        pane.new_page("")
        await pilot.pause()
        await pilot.pause()
        await pilot.press(*"Offer", "enter")
        await settle(app, pilot)
        assert app.client.note_files["Offer"][0] == docs.file_text([])
        # A Word file on this machine comes in as a document.
        source = tmp_path / "Deal.docx"
        source.write_bytes(docx.write_docx(LETTER))
        pane.import_file()
        await pilot.pause()
        await pilot.pause()
        await pilot.press(*str(source), "enter")
        await settle(app, pilot)
        assert docs.Doc.from_text(app.client.note_files["Deal"][0]).blocks == LETTER.blocks
        assert pane.query_one(LiveMarkdownEditor).text == "# Letter\n\nDear **you**\n"
        # And the open one goes out as Word.
        target = tmp_path / "out" / "Deal.docx"
        pane.export_file()
        await pilot.pause()
        await pilot.pause()
        modal_input = app.screen.query_one("Input")
        modal_input.value = str(target)
        await pilot.press("enter")
        await settle(app, pilot)
        assert docx.read_docx(target.read_bytes()).blocks == LETTER.blocks
