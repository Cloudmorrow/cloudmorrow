# Tasks

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): boards,
and three lanes on each — **To Do**, **Doing**, **Done** — because that is
what a board is for.

- A task is a title and a Markdown body, which is where its detail and its
  subtasks (`- [ ]` lines) live.
- Done empties itself: a week after a task is finished, it goes.
- Everyone starts with a board named after them.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `board` and `task` (domain *Tasks*) |
| Screens | one board, on the phone, the web app, the terminal, `cm tasks`, and to your assistant |
| Jobs | `sweep_done`: deletes tasks that have been done for seven days |
| Datasets | `first_board`: one board for each person, the first time they open Tasks |
| Services, webhooks, APIs | none |

It contains no code: everything above is declared in [`quill.toml`](quill.toml).

## Working on it

See [CLAUDE.md](CLAUDE.md). In short: `cm quill check`, then `cm quill dev`.

## Licence

AGPL-3.0-or-later.
