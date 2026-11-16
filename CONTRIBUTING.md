# Contributing to Cloudmorrow

Thank you for looking. Cloudmorrow is one person's project in the open, and
every issue, question and pull request from outside is read the same day.

## The quickest ways to help

- **Install it and say what happened.** A fresh Raspberry Pi, an old laptop,
  a VPS: run the installer, time it, and open an issue with the snags, even
  the small ones. "It took eleven minutes and step 4 was unclear" is a
  useful report.
- **Write a Quill.** The whole point of the project is apps that are small
  enough to write in an afternoon. Start from
  [quill-template](https://github.com/Cloudmorrow/quill-template), read
  [docs/QUILLS.md](docs/QUILLS.md), and show it in
  [Discussions](https://github.com/Cloudmorrow/cloudmorrow/discussions)
  under *Show your Quill*. To list it for everyone, open a pull request on
  [quill-catalog](https://github.com/Cloudmorrow/quill-catalog).
- **Fix the words.** The docs are long and written by the same person who
  wrote the code. If a sentence made you stop, it is wrong; a pull request
  that fixes one sentence is welcome.
- **Report a bug.** Use the bug template; it asks for the version
  (`cm --version`, or the server's `/api/health`) and the surface (phone,
  browser, terminal, command line).

## Working on the code

```bash
git clone https://github.com/Cloudmorrow/cloudmorrow
cd cloudmorrow
uv venv && uv pip install -e '.[tui,server,dev]'
pytest                       # a quarter of an hour; -n 0 for one process
ruff check src tests scripts
ruff format --check src tests scripts
```

`cloudmorrow --dev` runs the checkout you are standing in against your real
server, so a change to the terminal app or the web app needs no deploy to
try. The web app is plain HTML, CSS and JavaScript with no build step.

What the layout is and why it is that way is in
[docs/MANUAL.md](docs/MANUAL.md); the data shapes are in
[docs/DATAMODELS.md](docs/DATAMODELS.md); what a Quill may and may not do is
in [docs/QUILLS.md](docs/QUILLS.md) and [docs/QUILLCODE.md](docs/QUILLCODE.md).

## Pull requests

- One change per pull request, with a title that says what changed for a
  person using it, not which file moved.
- CI must be green: lint, format and the test suite.
- If you add something that stores what a person wrote, seal it. The last
  section of [docs/ENCRYPTION.md](docs/ENCRYPTION.md) says how, and a test
  that reads the raw row and finds ciphertext is the proof.
- If you change behaviour, change the words that describe it in the same
  pull request: the manual, the on-screen text, the README. Docs that lag
  the code are a bug here.
- No new dependency without a sentence on why the standard library or what
  is already installed would not do. The server has to run on a Raspberry Pi.
- Every question a screen asks is an on-page sheet, never a browser popup.

A maintainer reviews within a few days. A release is a tag on main, and
there is one most days, so a merged fix is usually installed on servers
the same week.

## Licensing of contributions

The core is [AGPL-3.0-or-later](LICENSE). By opening a pull request you
agree that your contribution is licensed the same way. The Quill SDK, the
template and the Quills you write are yours to license as you like; MIT is
the default in the template.

## Where to talk

- Bugs and concrete proposals: [Issues](https://github.com/Cloudmorrow/cloudmorrow/issues).
- Questions, ideas, showing a Quill: [Discussions](https://github.com/Cloudmorrow/cloudmorrow/discussions).
- Security: see [SECURITY.md](SECURITY.md). Please do not open a public
  issue for a vulnerability.

Everyone here follows the [code of conduct](CODE_OF_CONDUCT.md).
