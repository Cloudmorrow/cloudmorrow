"""Notes: what the editor cannot do without opening the note.

A note is a Markdown file in the Notes folder of the person's drive, served
as a `file` record by the core; the editor on every surface is declared in
quill.toml. This is the code behind its one action, run as whoever presses it.
"""

from cloudmorrow.quill import action, toast

FILE = "file"


@action("add_to_the_end")
def add_to_the_end(ctx, note, text):
    body = note.get("text") or ""
    if body and not body.endswith("\n"):
        body += "\n"
    ctx.records.patch(FILE, note.id, {"text": body + text.rstrip("\n") + "\n"}, rev=note.rev)
    return toast(f"Added to {note['name'].removesuffix('.md')}")
