# Chat

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): the
people on your server, talking.

- **Public channels** are everybody's: everybody is in them, anybody writes
  in them, and nobody leaves.
- **Private channels** are the people added to them. Nobody accepts an
  invitation — you are added, you are told, and you can leave.
- **Direct messages** are between two people. Pick somebody and the
  conversation is there, whether or not it was a moment ago, from either side.
- Everybody starts with `#general`.
- What you have not read is counted beside each channel and on the app's
  icon, and everybody else in a channel gets a push when somebody writes.
- A channel's topic and every message are sealed at rest; a message is its
  author's to change or delete.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `channel` (a space: shared or public) and `message` (in a channel, authored, notifies with push and unread) — domain *Messaging* |
| Screens | one `thread`: the channels, and the conversation — on the phone, the web app, the terminal, `cm chat`, and to your assistant |
| Jobs | none |
| Datasets | `general`: one public channel for the whole server, the first time anybody opens Chat |
| Services, webhooks, APIs | none |

It contains no code: everything above is declared in [`quill.toml`](quill.toml).

On the command line:

```
cm chat list                     # the channels, with what is unread in each
cm chat show general             # the conversation, newest at the bottom
cm chat say general "on my way"
```

## Working on it

See [CLAUDE.md](CLAUDE.md). In short: `cm quill check`, then `cm quill dev`.

## Licence

AGPL-3.0-or-later.
