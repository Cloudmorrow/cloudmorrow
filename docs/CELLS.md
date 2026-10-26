# The sheet kit

`kit = "sheet"` is a spreadsheet: cells in rows and columns, numbers and
text typed into them, and formulas that work the others out — `=SUM(B2:B9)`
— the way Excel's do, and nothing of the rest of Excel. Cloudmorrow draws
it on the web and the phone, in the terminal and on the command line
(`cm <quill> …`); a Quill declares it in TOML. A sheet is a file: a
`.cell` file in a folder of your drive, holding its cells exactly as
typed — in My Files, on WebDAV, in a backup of the folder, and open to
anything that reads JSON.

## The screen

```toml
[[screens]]
id = "sheets"
kit = "sheet"
label = "Cells"
model = "file"                                        # the foundational file
where = { share = "my-files", within = "Documents" }  # whose drive, which folder
suffix = ".cell"                                      # which files are sheets
title = "name"
cells = "text"                                        # the file's text: the sheet
path = "path"
```

It is an editor's kind of screen (docs/QUILLS.md): `where` is the filters
every listing is made with — a file's `share`, and `within`, the folder
the sheets are under — and `suffix` says which files are sheets and what a
new one is called. The sheets are listed newest first, by their path
under that folder and without the suffix; one opens as a grid. The record
sheet every screen has is not used for a sheet: the grid is its page.

A Quill that ships this screen ships a first sheet the same way Notes
ships its welcome note: a per-owner dataset of the `file` datamodel, with
the same `where` and the file's `text`.

## The file

A `.cell` file is UTF-8 text: one JSON object, with `cells` in it — one
entry per cell that has something in it, keyed by the cell's name, holding
what was typed, as typed:

```json
{
  "cells": {
    "A1": "Rent",
    "B1": "1200",
    "A2": "Food",
    "B2": "450",
    "A4": "Total",
    "B4": "=SUM(B1:B2)"
  }
}
```

Nothing else is kept: not what a formula came to, not that `1200` is a
number. All of that is worked out on reading, by the same rules on every
surface — `quill/cells.py` in Python, `kit_cells_rules.js` in the browser,
held together by one test (`tests/test_cells.py`). The file is written a
cell a line, by row then column, so two versions of a sheet diff well; a
key that is no cell, or an empty value, is dropped on writing; names are
made proper (`a1` → `A1`). Reading, a file holding the cells alone, with
no `cells` around them, is the same sheet; a file that is not JSON, or
not an object, is an empty sheet. Whatever else the object comes to hold
one day — a column's width — sits beside `cells` and is kept.

## What a cell says

| typed | it is |
| --- | --- |
| nothing, or spaces | blank |
| `=…` | a formula |
| `'…` | the rest, as text, even when it looks like a number: `'0012` |
| `12`, `-3.5`, `1e3`, `40%` | a number (`40%` is 0.4) |
| `TRUE`, `FALSE` (any case) | a boolean |
| anything else | text |

A number shows to ten significant figures without a trailing `.0`; a
boolean as `TRUE` or `FALSE`; blank as nothing.

## Formulas

A formula is `=` and an expression of:

- **cells** `B2`, `$B$2` (the `$` is allowed and means nothing yet); **ranges**
  `B2:B9`, `A1:C3`;
- **numbers**, **text** in double quotes (`""` inside for a quote), `TRUE`,
  `FALSE`;
- `+ - * /` and `^`, `-x`, `x%`, parentheses; `&` joins text;
- `= <> < > <= >=`, which give TRUE or FALSE. Numbers come before text,
  text before booleans; text compares letter by letter, case aside; a
  blank beside text is empty text, beside a number 0;
- functions, by name, any case:

| function | |
| --- | --- |
| `SUM(…)`, `AVERAGE(…)`, `MIN(…)`, `MAX(…)`, `PRODUCT(…)` | over numbers; in a range, text and blanks are passed over |
| `COUNT(…)` | how many numbers; `COUNTA(…)`: how many cells with anything |
| `COUNTIF(range, test)`, `SUMIF(range, test[, sum_range])` | `test` is a value, or `">=10"`, `"<>x"` |
| `IF(test, then[, else])`, `AND(…)`, `OR(…)`, `NOT(x)`, `IFERROR(x, instead)` | |
| `ROUND(x[, places])`, `ABS(x)`, `INT(x)`, `MOD(x, y)`, `SQRT(x)`, `POWER(x, y)` | `ROUND` rounds halves away from zero |
| `LEN(t)`, `CONCAT(…)` (or `CONCATENATE`), `UPPER(t)`, `LOWER(t)`, `TRIM(t)` | |

Where a number is wanted, blank is 0, TRUE is 1, and text counts only when
it reads as a number (`"5"`); otherwise `#VALUE!`. A range where one value
is wanted (`=B1:B3`, `=B1:B3+1`) is `#VALUE!` too.

What goes wrong is a value, shown in the cell, and passed on by whatever
reads it:

| | |
| --- | --- |
| `#DIV/0!` | division by zero; `AVERAGE` of nothing |
| `#REF!` | a cell that is no cell |
| `#NAME?` | a function nobody has, or a word that is no cell |
| `#VALUE!` | text where a number was wanted; a formula that cannot be read |
| `#CIRC!` | a formula that needs itself, by any way round |
| `#NUM!` | a number that is none: `SQRT(-1)`, too big |

## On each surface

**Web and phone** (`kit_cells.js`): the sheets, newest first, with a
search box and the pen; a sheet is its title — the file's name — the
formula bar (the cell's name and what is typed in it) and the grid, as
many rows and columns as are used with room beyond, scrolling both ways
with the headings held. A tap or click selects a cell; typing, Enter or a
double tap edits it; Enter commits and moves down, Tab across, Escape
leaves it as it was, Delete clears it; the arrows move. While a formula
wants a reference — after `=`, an operator, `(`, a comma or a colon — the
arrows point one out instead, as in Excel: the cell's name is written
where the caret is and follows as they move, Shift and an arrow make it a
range, a click on a cell points the same way, and Enter keeps the name and
typing goes on. Numbers stand to the right, errors are red.
The sheet saves as you type; changing the title renames the file. One
changed elsewhere since it was opened is not written over. On a computer
the list and the sheet are side by side, and the list folds away.
Read-only, the grid shows and nothing types into it.

**Terminal** (`tui/panes/kit_cells.py`): the sheets down the left, the
grid on the right with the cell's name and what is typed in it over it.
Arrows move, Enter or typing edits on the line above the grid, Enter
commits and moves down, Tab across, Escape leaves it, Delete clears; a
formula wanting a reference is pointed out with the arrows as on the web,
`ctrl+s` saves (it saves on its own too); `ctrl+n` a new sheet, `f2`
rename or move (`2026/Costs` puts it in a folder that is there), `del` delete.

**Command line** (`cli/quillrun/cells.py`):

```
cm cells list                          # every sheet, newest first
cm cells add Budget                    # a new, empty sheet: Documents/Budget.cell
cm cells show Budget                   # the sheet, worked out, as a table
cm cells show Budget --raw             # as typed: the formulas
cm cells get Budget B4                 # one cell, worked out (--raw: as typed)
cm cells set Budget B4 "=SUM(B1:B3)"   # one cell; set Budget B4 "" clears it
cm cells set Budget name=Costs         # renames the file; path=2026/Costs moves it to a folder that is there
cm cells delete Budget
cm cells show Budget --plain           # {"A1": {"raw": …, "value": …, "shown": …}}
```

**An assistant** reads and writes the file's `text` through the record
tools, like any text file's — and so does anything else that can read a
file from your drive.
