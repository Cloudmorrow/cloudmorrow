# Notes

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): your
notes, in Markdown, in folders, with pictures — on the phone, the web app,
the terminal and the command line.

- A note is a title and a page of Markdown. Folders hold notes and other
  folders.
- Pictures go in a note by pasting, dropping or picking them, and show where
  they are.
- Search finds a note by its name or by any line in it.
- Every note is a plain Markdown file in the Notes folder of your drive on
  the server — the same file My Files, WebDAV, `cm note`, your assistant's
  notes tools and any editor reach. Removing this Quill takes the tab away,
  never a note.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `note` (domain *Notes*), which the core serves from the Notes folder of your drive |
| Screens | one editor — folders and notes beside the page — on the phone, the web app, the terminal, `cm notes`, and to your assistant |
| Jobs | none |
| Datasets | `welcome`: a note on how the editor works, the first time somebody with no notes opens Notes |
| Actions | **Add to the end** of a note — on its sheet, `cm notes add-to-the-end <note> text=…`, and to your assistant |
| Services, webhooks, APIs | none |

Its code is [`quill.py`](quill.py): the one action, run in the sandbox as whoever presses it. Everything else is declared in [`quill.toml`](quill.toml).

## Working on it

See [CLAUDE.md](CLAUDE.md) and the skills in `.claude/skills/`. In short:

```
uv sync                  # .venv with Cloudmorrow and pytest
cm quill check           # the manifest, as a server would install it
cm quill test            # tests/, against the real record store and gate
cm quill test --sandbox  # the same, with the code in the sandbox
cm quill dev --local     # a throwaway server here, reinstalled as you save
```

## Licence

AGPL-3.0-or-later.
