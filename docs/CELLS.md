# The sheet kit

`kit = "sheet"` is a spreadsheet: cells in rows and columns, numbers and
text typed into them, and formulas that work the others out — `=SUM(B2:B9)`
— the way Excel's do, and nothing of the rest of Excel. Cloudmorrow draws
it on the web and the phone, in the terminal and on the command line
(`cm <quill> …`); a Quill declares it in TOML. A sheet is a record: a name
and its cells, kept exactly as typed.

## The screen

```toml
[[screens]]
id = "sheets"
kit = "sheet"
label = "Cells"
model = "sheet"       # the foundational sheet: name, cells, notes
title = "name"
cells = "cells"       # a json field: what is typed in each cell, by name
```

Any datamodel with a string title and a json field for the cells will do;
the foundational `sheet` (domain Sheets) is the one every Quill should
agree on. The sheets are listed newest first, like any records; one opens
as a grid. The record sheet every screen has is not used for a sheet: the
grid is its page.

## The cells

The `cells` field is a JSON object with one entry per cell that has
something in it, keyed by the cell's name, holding what was typed, as
typed:

```json
{
  "A1": "Rent",
  "B1": "1200",
  "A2": "Food",
  "B2": "450",
  "A4": "Total",
  "B4": "=SUM(B1:B2)"
}
```

Nothing else is kept: not what a formula came to, not that `1200` is a
number. All of that is worked out on reading, by the same rules on every
surface — `quill/cells.py` in Python, `kit_cells_rules.js` in the browser,
held together by one test (`tests/test_cells.py`). The cells are written
in row order, then column, so two versions of a sheet diff well; a key
that is no cell, or an empty value, is dropped on writing; names are made
proper (`a1` → `A1`). A field that is not an object is an empty sheet.

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
search box and the pen; a sheet is its title, the formula bar — the cell's
name and what is typed in it — and the grid, as many rows and columns as
are used with room beyond, scrolling both ways with the headings held. A
tap or click selects a cell; typing, Enter or a double tap edits it; Enter
commits and moves down, Tab across, Escape leaves it as it was, Delete
clears it; the arrows move. Numbers stand to the right, errors are red.
The sheet saves as you type, and one changed elsewhere since it was opened
is not written over. On a computer the list and the sheet are side by
side, and the list folds away. Read-only, the grid shows and nothing types
into it.

**Terminal** (`tui/panes/kit_cells.py`): the sheets down the left, the
grid on the right with the cell's name and what is typed in it over it.
Arrows move, Enter or typing edits on the line above the grid, Enter
commits and moves down, Tab across, Escape leaves it, Delete clears,
`ctrl+s` saves (it saves on its own too); `ctrl+n` a new sheet, `f2`
rename, `del` delete.

**Command line** (`cli/quillrun/cells.py`):

```
cm cells list                          # every sheet, newest first
cm cells add "Budget"                  # a new, empty sheet
cm cells show Budget                   # the sheet, worked out, as a table
cm cells show Budget --raw             # as typed: the formulas
cm cells get Budget B4                 # one cell, worked out (--raw: as typed)
cm cells set Budget B4 "=SUM(B1:B3)"   # one cell; set Budget B4 "" clears it
cm cells set Budget name=Costs         # the record's fields
cm cells delete Budget
cm cells show Budget --plain           # {"A1": {"raw": …, "value": …, "shown": …}}
```

**An assistant** reads and writes the `cells` field through the record
tools, like any record's field.
