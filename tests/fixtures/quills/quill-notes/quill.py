"""Notes: what the editor cannot do without opening the note.

The notes, their folders and pictures, and the editor on every surface are
declared in quill.toml and kept by the core's notes store. This is the code
behind its one action, run as whoever presses it.
"""

from cloudmorrow.quill import action, toast

NOTE = "note"


@action("add_to_the_end")
def add_to_the_end(ctx, note, text):
    body = note.get("body") or ""
    if body and not body.endswith("\n"):
        body += "\n"
    ctx.records.patch(NOTE, note.id, {"body": body + text.rstrip("\n") + "\n"}, rev=note.rev)
    return toast(f"Added to {note['title']}")
