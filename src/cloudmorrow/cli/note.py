"""`cloudmorrow note` — markdown, by title.

A note is a title and some text. Titles may contain slashes, which makes them
folders on the server, so `cloudmorrow note add "hetzner/firewall"` sorts itself.

Text comes from stdin when there is any, and from `$EDITOR` when there is not:

    cat architecture.md | cloudmorrow note add "Architecture"
    cloudmorrow note add "Hetzner setup"          # opens $EDITOR
    cloudmorrow note show "Architecture" > architecture.md

Notes are yours, not a project's: one set per account, wherever you are
standing when you write them.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from cloudmorrow.cli.common import (
    client,
    console,
    edit_text,
    emit,
    fail,
    out,
    plural,
    run,
    stdin_is_a_terminal,
)
from cloudmorrow.client.api import ApiError
from cloudmorrow.console import TITLE

app = typer.Typer(help="Notes: markdown, by title.", no_args_is_help=True)

TitleArgument = Annotated[str, typer.Argument(help="The note's title.")]


def _title(path: str) -> str:
    """A stored path back as a title: `hetzner/firewall.md` → `hetzner/firewall`."""
    return path[:-3] if path.endswith(".md") else path


def _walk(node: dict):
    for child in node.get("children", []):
        if child["is_dir"]:
            yield from _walk(child)
        else:
            yield child


def _text_from_stdin_or_editor(initial: str = "", *, what: str) -> str:
    if not stdin_is_a_terminal():
        return sys.stdin.read()
    text = edit_text(initial)
    if not text.strip():
        fail(f"{what} is empty — nothing was saved")
    return text


@app.command("list")
def list_notes(
    plain: Annotated[
        bool, typer.Option("--plain", help="One title per line, for scripts.")
    ] = False,
) -> None:
    """List your notes."""

    async def _list() -> None:
        config, api = client()
        try:
            tree = await api.tree()
        finally:
            await api.aclose()
        notes = sorted(_walk(tree), key=lambda note: note["path"].lower())
        if plain:
            emit("".join(f"{_title(note['path'])}\n" for note in notes))
            return
        if not notes:
            console.print("[dim]No notes.[/]")
            return
        table = Table(title="notes", title_style=TITLE)
        table.add_column("title")
        table.add_column("size", justify="right", style="dim")
        for note in notes:
            table.add_row(_title(note["path"]), f"{note['size']:,}")
        out.print(table)

    run(_list())


@app.command("show")
def show(title: TitleArgument) -> None:
    """Print a note's raw text, for redirecting or piping."""

    async def _show() -> None:
        config, api = client()
        try:
            note = await api.read(title)
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            fail(f"no such note: {title}")
        finally:
            await api.aclose()
        emit(note["content"])

    run(_show())


@app.command("add")
def add(
    title: TitleArgument,
    force: Annotated[
        bool, typer.Option("--force", help="Replace a note that is already there.")
    ] = False,
) -> None:
    """Write a new note, from stdin or from $EDITOR."""
    text = _text_from_stdin_or_editor(f"# {title}\n\n", what="the note")

    async def _add() -> None:
        config, api = client()
        try:
            try:
                note = await api.create_note(title, text)
            except ApiError as exc:
                if exc.status_code != 409:
                    raise
                if not force:
                    fail(f"{title} already exists — --force replaces it")
                note = await api.write(title, text)
        finally:
            await api.aclose()
        console.print(
            f"[green]Saved[/] {_title(note['path'])} "
            f"[dim]({plural(len(text), 'byte')})[/]"
        )

    run(_add())


@app.command("edit")
def edit(title: TitleArgument) -> None:
    """Open a note in $EDITOR, or replace its text from stdin."""

    async def _edit() -> None:
        config, api = client()
        try:
            try:
                note = await api.read(title)
            except ApiError as exc:
                if exc.status_code != 404:
                    raise
                fail(f"no such note: {title} — `note add` makes one")
            text = _text_from_stdin_or_editor(note["content"], what="the note")
            if text == note["content"]:
                console.print(f"[dim]{title} is unchanged.[/]")
                return
            # The rev we read is what stops a TUI save landing on top of this.
            saved = await api.write(title, text, note["rev"])
        finally:
            await api.aclose()
        console.print(f"[green]Saved[/] {_title(saved['path'])}")

    run(_edit())


@app.command("remove")
def remove(
    title: TitleArgument,
    recursive: Annotated[
        bool, typer.Option("--recursive", "-r", help="Delete a folder of notes.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Delete a note."""

    async def _remove() -> None:
        config, api = client()
        if not yes:
            typer.confirm(f"Delete {title}?", abort=True)
        try:
            await api.delete(title, recursive=recursive)
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            fail(f"no such note: {title}")
        finally:
            await api.aclose()
        console.print(f"[green]Deleted[/] {title}")

    run(_remove())


@app.command("rename")
def rename(
    title: TitleArgument,
    new_title: Annotated[str, typer.Argument(help="What to call it instead.")],
) -> None:
    """Rename a note, or move it into a folder."""

    async def _rename() -> None:
        config, api = client()
        try:
            result = await api.move(title, new_title)
        finally:
            await api.aclose()
        console.print(f"[green]Renamed[/] {title} → {_title(result['path'])}")

    run(_rename())


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Text to look for.")],
) -> None:
    """Search your note titles and bodies."""

    async def _search() -> None:
        config, api = client()
        try:
            payload = await api.search(query)
        finally:
            await api.aclose()
        results = payload.get("results", [])
        if not results:
            console.print(f"[dim]No notes match {query!r}.[/]")
            return
        for result in results:
            console.print(f"[b #7dd3fc]{_title(result['path'])}[/]")
            for match in result["matches"]:
                where = f"{match['line']:>4}" if match["line"] else "title"
                # The hit is note text: escape it rather than let it be markup.
                console.print(f"  [dim]{where}[/] {escape(match['text'])}", highlight=False)

    run(_search())


app.command("cat", hidden=True)(show)
app.command("rm", hidden=True)(remove)
app.command("mv", hidden=True)(rename)
