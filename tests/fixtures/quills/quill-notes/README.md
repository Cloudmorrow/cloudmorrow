# Notes

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): your
notes, in Markdown, in folders, with pictures — on the phone, the web app,
the terminal and the command line.

- A note is a title and a page of Markdown. Folders hold notes and other
  folders.
- Pictures go in a note by pasting, dropping or picking them, and show where
  they are.
- Search finds a note by its name or by any line in it.
- Every note is a real file in your notes folder on the server, sealed at
  rest — the same file WebDAV, `cm note` and your assistant's notes tools
  reach. Removing this Quill takes the tab away, never a note.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `note` (domain *Notes*), which the core serves from your notes folder |
| Screens | one editor — folders and notes beside the page — on the phone, the web app, the terminal, `cm notes`, and to your assistant |
| Jobs | none |
| Datasets | `welcome`: a note on how the editor works, the first time somebody with no notes opens Notes |
| Services, webhooks, APIs | none |

It contains no code: everything above is declared in [`quill.toml`](quill.toml).

## Working on it

See [CLAUDE.md](CLAUDE.md). In short: `cm quill check`, then `cm quill dev`.

## Licence

AGPL-3.0-or-later.
