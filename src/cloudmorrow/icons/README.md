# The icon library

Pixel icons, the kind Cloudmorrow draws its tabs with: a square of dots,
one colour, drawn by every surface from the same rows. Hundreds of them, in
themes, and all of them **CC0**: public domain, free to use anywhere, in
anything, with no attribution owed (`LICENSE`). They are listed, with every
theme, at [cloudmorrow.com/resources/icons](https://cloudmorrow.com/resources/icons).

## The format

`themes.toml` lists the themes in display order:

```toml
[[themes]]
id = "animals"
name = "Animals"
description = "Pets, farm, wild and small."
file = "animals.toml"
```

Each theme is one file of icons:

```toml
[[icons]]
id = "hedgehog"                       # lowercase letters, digits, dashes; unique across every theme
name = "Hedgehog"
tags = ["animal", "pet", "morrow"]    # for searching
rows = [                              # 12 rows of 12: X is a dot, . is not
  "............",
  "...X.X.X.X..",
  "..XXXXXXXX..",
  ".XXXXXXXXXX.",
  "XXXXXXXXXXX.",
  "XXXXXXXXXXXX",
  "XXXXXXXXXX.X",
  "XXXXXXXXXXXX",
  ".XXXXXXXXXXX",
  ".XXXXXXXXX..",
  "..XX...XX...",
  "............",
]
```

An icon is 12×12; 8×8 is allowed for one that reads well that small. Strokes
are one dot wide, shapes are bold enough to read at 20 pixels.

## Adding one

Add an `[[icons]]` block to its theme's file (or a theme: a file, and a line
in `themes.toml`), then `python -m cloudmorrow.icons check` says whether the
files are sound, and `python -m cloudmorrow.icons sheet out.html` writes a
contact sheet to look at every icon at 48 and 20 pixels.

## Naming one

A Quill's manifest names its tab icon: `icon = "hedgehog"` in `quill.toml`.
The app draws the library's icon, or one of its own nine, and the quill
mark for a name it does not know (`cm quill check` says so). The web app
reads the whole library once from `GET /icons.json` on the server; in
Python, `cloudmorrow.icons.get("hedgehog").rows`, and `svg(rows)` draws it.
