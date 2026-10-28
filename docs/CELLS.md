# The sheet kit

`kit = "sheet"` is a spreadsheet: cells in rows and columns, numbers and
text typed into them, and formulas that work the others out — `=SUM(B2:B9)`
— the way Excel's do, and nothing of the rest of Excel. Cloudmorrow draws
it on the web and the phone, in the terminal and on the command line
(`cm <quill> …`); a Quill declares it in TOML. A sheet is a file: a
`.cell` file in a folder of your drive, holding its cells exactly as
typed — in My Files, on WebDAV, in a backup of the folder, and open to
anything that reads JSON. An Excel file (`.xlsx`) in the same folder is a
sheet too: the server reads it as the same cells and writes it back as
Excel, so Excel's files are edited here and nothing else, and any sheet
can be exported as one — or as a PDF, or as CSV.

## The screen

```toml
[[screens]]
id = "sheets"
kit = "sheet"
label = "Cells"
model = "file"                                        # the foundational file
where = { share = "my-files", within = "Documents" }  # whose drive, which folder
suffix = [".cell", ".xlsx"]                           # which files are sheets; a new one is the first
title = "name"
cells = "text"                                        # the file's text: the sheet
path = "path"
```

It is an editor's kind of screen (docs/QUILLS.md): `where` is the filters
every listing is made with — a file's `share`, and `within`, the folder
the sheets are under — and `suffix` says which files are sheets, one or
a list, the first being what a new one is called. The list is the
editor's: the folders under that folder, every sheet newest first, or one
folder's, each with its first cells under its name; one opens as a grid. The record sheet every screen has is not used for a
sheet: the grid is its page.

A Quill that ships this screen ships a first sheet the same way Notes
ships its welcome note: a per-owner dataset of the `file` datamodel, with
the same `where` (the suffixes by commas) and the file's `text`.

## Excel, PDF and CSV

An `.xlsx` is a zip of XML; `quill/xlsx.py` reads its first worksheet
into a sheet — each cell's text, number or formula, and the borders its
style gives it — and writes a sheet back as a small, plain package Excel
opens as it is: the same cells, a formula with the value it came to, the
borders. Other sheets, fonts, colours, number formats and charts are
passed over; a percentage comes back as the number Excel keeps. The
server treats an Excel file as a text file: reading its `text` gives the
sheet as a `.cell` file would hold it, writing `text` writes Excel's
package, so an Excel file in the folder is listed, opened, edited and
saved like any sheet, on every surface. A file up to 25 MB is read.

**Export** hands a sheet over in another shape through the record API —
`GET /api/records/file/<id>/export?as=xlsx` — as Excel, as a PDF
(`quill/pdf.py`: a ruled grid of what the cells come to, headings in
grey, the borders in black, landscape when wide, more pages when wider)
or as CSV of the values; `as=cell` is the file itself. The same shapes
come out of the terminal's and the command line's `export`
(`quill/convert.py`). Nothing is written beside the sheet.

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

Nothing else is kept of a cell's value: not what a formula came to, not
that `1200` is a number. All of that is worked out on reading, by the
same rules on every surface — `quill/cells.py` in Python,
`kit_cells_rules.js` in the browser, held together by one test
(`tests/test_cells.py`). The file is written a cell a line, by row then
column, so two versions of a sheet diff well; a key that is no cell, or an
empty value, is dropped on writing; names are made proper (`a1` → `A1`).
Reading, a file holding the cells alone, with no `cells` around them, is
the same sheet; a file that is not JSON, or not an object, is an empty
sheet.

Beside `cells`, a `format` says how a cell looks — for now, which of its
sides have a border — for the cells that have anything to say:

```json
{
  "cells": { "A1": "Rent", "B1": "1200" },
  "format": {
    "A1": { "border": "bottom" },
    "B1": { "border": "top right bottom left" }
  }
}
```

`border` is the sides with a line, as words, written in the order top,
right, bottom, left and read in any order (`all` reads as the four). A
key beside `border` that this version does not know is kept as it was
found, as is whatever else the file holds beside `cells` and `format` —
a column's width, one day.

## Rows and columns

A row or a column can be put in or taken out, and the sheet moves with
it: the cells past it shift, their borders with them, and every
formula's references follow, as Excel's do.

| before | after | |
| --- | --- | --- |
| `=A1+A3` | `=A1+A4` | a row put in at 2 |
| `=SUM(A1:A3)` | `=SUM(A1:A4)` | a row put in inside the range |
| `=SUM(A1:A3)` | `=SUM(A1:A3)` | a row put in just after it |
| `=SUM(A1:A3)` | `=SUM(A1:A2)` | row 2 taken out |
| `=A2*2` | `=#REF!*2` | row 2 taken out |
| `=SUM(A1:A3)` | `=SUM(#REF!)` | rows 1 to 3 taken out |
| `=$A$3` | `=$A$2` | row 1 taken out: the `$`s stay |

`#REF!` written in a formula is that error, so a cell whose row is gone
says so. Text in quotes is never touched, nor a function's name
(`LOG10(`). Python: `Sheet.insert_rows(at, count)`, `delete_rows`,
`insert_cols`, `delete_cols`, `at` counted from zero; the browser the
same in camel case.

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

**Web and phone** (`kit_cells.js`): the sheets, newest first, each
saying where its file is as Files says it (`My Files/Documents/Budget.cell`,
cut at the start when the line is too short), with a search box and the
pen, an Excel file saying so; a sheet is its title — the file's name — the
formula bar (the cell's name and what is typed in it) and the grid, as
many rows and columns as are used with room beyond, scrolling both ways
with the headings held. A tap or click selects a cell, a drag or Shift
with a click or an arrow a block of them, a row's or a column's heading
the whole row or column (dragging down the headings, more); typing,
Enter or a double tap edits the cell; Enter commits and moves down, Tab
across, Escape leaves it as it was — or, with a block selected, selects
the one cell again; Delete or Backspace clears everything selected; the
arrows move. Over the formula bar, the border buttons: a side of the
selection, all four around it, every side of every cell, or none — a
border that is there already comes off again. On a row's or a column's
heading the right button (on a phone, a second tap) opens a menu to put
rows or columns in before or after the selection, as many as are
selected, or take them out; the right button on a cell offers both, and
Clear. Taking out rows or columns that hold something asks first, there
being no undo. While a formula
wants a reference — after `=`, an operator, `(`, a comma or a colon — the
arrows point one out instead, as in Excel: the cell's name is written
where the caret is and follows as they move, Shift and an arrow make it a
range, a click on a cell points the same way, and Enter keeps the name and
typing goes on. Numbers stand to the right, errors are red.
The sheet saves as you type; changing the title renames the file, and an
Excel file stays an Excel file. One changed elsewhere since it was opened
is not written over. **Open** (the folder in the bar) picks a sheet from
anywhere on the cloud — another folder of your drive, a fileshare —
through the picker every file screen shares (`filepick.js`: the shares,
then the folders, then the files that are sheets); it opens by its record,
the file staying where it is, and the stamp says where. **Export** offers
Excel, PDF and CSV, and hands the file over to save. On a computer the
list and the sheet are side by side, and the list folds away. Read-only,
the grid shows and nothing types into it; Open and Export are still there.

**Terminal** (`tui/panes/kit_cells.py`): the sheets down the left, the
grid on the right with the cell's name and what is typed in it over it.
Arrows move, Enter or typing edits on the line above the grid, Enter
commits and moves down, Tab across, Escape leaves it, Delete clears; a
formula wanting a reference is pointed out with the arrows as on the web,
`ctrl+s` saves (it saves on its own too); `ctrl+n` a new sheet, `f2`
rename or move (`2026/Costs` puts it in a folder that is there), `del`
delete; `f5` opens a sheet from anywhere on the cloud by `share:path`
(`my-files:Reports/Q3.xlsx`), `f7` exports the open one by the name
given (`.xlsx`, `.pdf`, `.csv` or `.cell`).

**Command line** (`cli/quillrun/cells.py`):

```
cm cells list                          # every sheet, newest first
cm cells add Budget                    # a new, empty sheet: Documents/Budget.cell
cm cells show Budget                   # the sheet, worked out, as a table
cm cells show Budget --raw             # as typed: the formulas
cm cells get Budget B4                 # one cell, worked out (--raw: as typed)
cm cells set Budget B4 "=SUM(B1:B3)"   # one cell; set Budget B4 "" clears it
cm cells set Budget name=Costs         # renames the file; path=2026/Costs moves it to a folder that is there
cm cells export Budget [./Budget.xlsx] # an Excel file on this machine; or a name ending .pdf, .csv or .cell
cm cells show my-files:Reports/Q3.xlsx # a sheet anywhere on the cloud: share:path, Excel or .cell
cm cells delete Budget
cm cells show Budget --plain           # {"A1": {"raw": …, "value": …, "shown": …}}
```

**An assistant** reads and writes the file's `text` through the record
tools, like any text file's — and so does anything else that can read a
file from your drive.
