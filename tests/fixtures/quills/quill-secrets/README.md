# Secrets

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): your
keys and passwords, in **vaults** (`default`, `home`, `work`) and in
**environments** inside each (`local`, `production`, whatever you call them),
on the phone, the web app and the terminal.

- A value is never on screen until you ask: every surface draws it hidden,
  and a tap, a click or a key reveals the one you want (and copies it, in the
  terminal).
- Add a key, change its value, move it to another vault or environment, or
  delete it, from any surface.
- Importing and exporting `.env` files, and `cm secret run` (a command with
  an environment's secrets in its environment), stay on the command line:
  they read and write files on your machine, which is where `cm secret` runs.
- No assistant ever reaches a secret. The `secret` datamodel is refused to
  every MCP tool, whatever else you let an assistant do.

The secrets themselves are part of Cloudmorrow's foundation, not this Quill:
they stay in the server's secrets store, sealed under the server's key, and
`cm secret` reaches them with or without it. This Quill is the screens.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `secret` (domain *Secrets*), kept by the core's `vaults` backend |
| Screens | one list, picked through by vault and then environment, on the phone, the web app, the terminal and `cm secrets`; never to an assistant |
| Jobs | none |
| Datasets | none |
| Services, webhooks, APIs | none |

It contains no code: everything above is declared in [`quill.toml`](quill.toml).

## Working on it

See [CLAUDE.md](CLAUDE.md). In short: `cm quill check`, then `cm quill dev`.

## Licence

AGPL-3.0-or-later.
