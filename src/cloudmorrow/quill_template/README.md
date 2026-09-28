# {{name}}

{{summary}}

A [Quill](https://github.com/Cloudmorrow/cloudmorrow/blob/main/docs/QUILLS.md)
for Cloudmorrow: install it from the Quill Catalog, or from this repository
with `cm quill add --source https://github.com/<you>/quill-{{id}} --ref v0.1.0`.

## What it adds to your Cloudmorrow

`cm quill check` prints this for you; keep it here for the catalog page.

| | |
| --- | --- |
| Datamodels | introduces `{{id}}.item` |
| Screens | an overview and a list, on the phone, the web app, the terminal, `cm {{id}}`, and to your assistant |
| Actions | Add an item; Clear what is done |
| Code | `quill.py`, in the sandbox, as whoever uses it; reaches nothing outside |

## Working on it

```
uv sync                  # .venv with Cloudmorrow and pytest
cm quill check           # the manifest, as a server would install it
cm quill test            # tests/, against the real record store and gate
cm quill test --sandbox  # the same, with quill.py in the sandbox
cm quill dev --local     # a throwaway server here, reinstalled as you save
```
