"""A `document`: documents in `.docs` files and Word's, edited as Markdown (docs/DOCS.md)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.markup import escape
from rich.table import Table

# quillrun.out, .console and .emit, looked up as they print: see screen.py.
from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import edit_text, fail, stdin_is_a_terminal
from cloudmorrow.cli.quillrun.cells import _moved_fields, anywhere
from cloudmorrow.cli.quillrun.screen import Screen
from cloudmorrow.client.api import ApiError, CloudmorrowClient
from cloudmorrow.console import TITLE
from cloudmorrow.quill import convert, docs, docx
from cloudmorrow.quill.screens import document_fields, listing_filters, page_fields, page_path, page_title

WORD = ".docx"


def _bound(screen: Screen) -> dict:
    return document_fields(screen.spec, screen.models[screen.model])


def _key(bound: dict, record: dict) -> str:
    """What a document is called on the command line: its path under the
    root, without the suffix, else its title."""
    return page_path(bound, record) or page_title(bound, record)


def _find_doc(bound: dict, records: list[dict], key: str) -> dict:
    """A document by its path, its title, or its id — whole, or the start of one."""
    wanted = key.strip().strip("/")
    for suffix in bound["suffixes"]:
        if wanted.lower().endswith(suffix.lower()):
            wanted = wanted[: -len(suffix)]
    for test in (
        lambda r: _key(bound, r) == wanted,
        lambda r: r["id"] == key,
        lambda r: _key(bound, r).casefold() == wanted.casefold(),
        lambda r: (page_title(bound, r) or "").casefold() == wanted.casefold(),
    ):
        matches = [r for r in records if test(r)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            fail(f"more than one document matches {key!r}: {', '.join(_key(bound, r) for r in matches)}")
    fail(f"no document matches {key!r}")


def _doc_of(bound: dict, record: dict) -> docs.Doc:
    return docs.Doc.from_text(record["fields"].get(bound["body"]))


def _markdown(initial: str, *, what: str) -> str:
    """The new Markdown: what is piped in, else what $EDITOR saves."""
    if not stdin_is_a_terminal():
        return sys.stdin.read()
    text = edit_text(initial)
    if not text.strip():
        fail(f"{what} is empty — nothing was saved")
    return text


class DocFileError(ValueError):
    """A file on this machine that cannot be read or written as a document."""


def read_file(source: Path) -> docs.Doc:
    """A document from a file on this machine: Word's, a `.docs` file, or Markdown."""
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise DocFileError(f"cannot read {source}: {exc.strerror or exc}") from None
    suffix = source.suffix.lower()
    if suffix == WORD or (suffix not in (".md", ".markdown", ".txt", ".docs") and docx.is_docx(data)):
        try:
            return docx.read_docx(data)
        except docx.DocxError:
            raise DocFileError(f"{source} is not a Word file") from None
    text = data.decode("utf-8", errors="replace")
    if suffix == ".docs":
        return docs.Doc.from_text(text)
    return docs.from_markdown(text)


def write_file(doc: docs.Doc, target: Path) -> None:
    """A document to a file on this machine, by its name: Word's, PDF,
    `.docs`, or Markdown (quill/convert.py), Markdown for a name that says
    nothing."""
    suffix = target.suffix.lower() if target.suffix.lower() in convert.DOCUMENT_FORMATS else ".md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(convert.document_bytes(doc, suffix, target.stem))
    except OSError as exc:
        raise DocFileError(f"cannot write {target}: {exc.strerror or exc}") from None


async def _act_docs(
    api: CloudmorrowClient, screen: Screen, action: str, args: list[str], plain: bool, raw: bool
) -> None:
    bound = _bound(screen)
    body = bound["body"]
    filters = listing_filters(bound)
    if action == "search":
        if not args:
            fail(f"search for what? cm {screen.quill['id']} search <text>")
        found = await api.records(screen.model, q=" ".join(args), **filters)
        if plain:
            quillrun.emit(json.dumps(found, indent=2) + "\n")
            return
        for record in found:
            quillrun.out.print(f"{escape(_key(bound, record))}  [dim]{escape(record.get('preview') or '')}[/]")
        if not found:
            quillrun.console.print("[dim]nothing matches[/]")
        return
    records = await api.records(screen.model, **filters)
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(records, indent=2) + "\n")
            return
        table = Table(title=screen.spec.get("label") or screen.quill["name"], title_style=TITLE)
        table.add_column("Document")
        table.add_column("File", style="dim")
        table.add_column("Changed", style="dim")
        for record in sorted(records, key=lambda r: _key(bound, r).casefold()):
            name = str(record["fields"].get(bound["title"]) or "")
            table.add_row(
                escape(_key(bound, record)),
                "Word" if name.lower().endswith(WORD) else "",
                str(record.get("updated_at") or "")[:16].replace("T", " "),
            )
        quillrun.out.print(table)
        if not records:
            quillrun.console.print(f"[dim]nothing yet — cm {screen.quill['id']} add <name> starts one[/]")
        return
    if not args:
        fail(f"which document? cm {screen.quill['id']} {action} <name or path>")
    if action in ("add", "import"):
        if action == "import":
            source = Path(args[0]).expanduser()
            try:
                doc = read_file(source)
            except DocFileError as exc:
                fail(str(exc))
            path = args[1].strip("/") if len(args) > 1 else source.stem
        else:
            path = args[0].strip("/")
            # Each word given is a line of Markdown; none, and stdin or $EDITOR says.
            doc = docs.from_markdown("\n".join(args[1:]) if len(args) > 1 else _markdown("", what="the document"))
        if any(_key(bound, r).casefold() == path.casefold() for r in records):
            fail(f"there is already a document {path!r}; edit it instead")
        made = await api.create_record(screen.model, {**page_fields(bound, path), body: doc.to_text()})
        quillrun.console.print(f"[green]{'Imported' if action == 'import' else 'Added'}[/] {escape(_key(bound, made))}")
        return
    elsewhere = await anywhere(api, screen.model, args[0], "document")
    found = await api.record(screen.model, (elsewhere or _find_doc(bound, records, args[0]))["id"])
    doc = _doc_of(bound, found)
    if action == "show":
        if plain:
            quillrun.emit(json.dumps(found, indent=2) + "\n")
        elif raw:
            quillrun.emit(str(found["fields"].get(body) or ""))
        else:
            quillrun.emit(docs.to_markdown(doc))
    elif action == "edit":
        before = docs.to_markdown(doc)
        text = "\n".join(args[1:]) if len(args) > 1 else _markdown(before, what="the document")
        if text == before:
            quillrun.console.print("[dim]unchanged[/]")
            return
        try:
            await api.update_record(
                screen.model, found["id"], {body: docs.from_markdown(text).to_text()}, rev=found["rev"]
            )
        except ApiError as exc:
            if exc.status_code == 409:
                fail("it changed somewhere else while you were editing; nothing was saved")
            raise
        quillrun.console.print(f"[green]Saved[/] {escape(_key(bound, found))}")
    elif action == "export":
        target = Path(args[1]).expanduser() if len(args) > 1 else Path.cwd() / f"{Path(_key(bound, found)).name}{WORD}"
        try:
            write_file(doc, target)
        except DocFileError as exc:
            fail(str(exc))
        quillrun.console.print(f"[green]Wrote[/] {escape(str(target))}")
    elif action == "delete":
        await api.delete_record(screen.model, found["id"])
        quillrun.console.print(f"[green]Deleted[/] {escape(_key(bound, found))}")
    elif action == "set":
        changed = await api.update_record(screen.model, found["id"], _moved_fields(bound, screen, found, args[1:]))
        quillrun.console.print(f"[green]Saved[/] {escape(_key(bound, changed))}")
    else:
        fail(f"a document has list, show, add, edit, set, delete, search, export and import, not {action}")
