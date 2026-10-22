"""The sheet kit's arithmetic: one set of cases, two engines that must agree.

quill/cells.py works a sheet out for the terminal and the command line;
kit_cells_rules.js for the browser. The cases below go through both — the
JavaScript under node — and both must show every cell the same (docs/CELLS.md).
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from cloudmorrow.quill import cells
from cloudmorrow.server.routes.web import WEB

node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The cells of one sheet, as typed, and what each shows.
SHEET = {
    "A1": "Rent",
    "B1": "1200",
    "B2": "300",
    "B3": "=B1+B2",
    "B4": "=SUM(B1:B3)",
    "B5": "'0012",
    "B6": "40%",
    "B7": "true",
    "B8": "  12  ",
    "B9": "-3.50",
    "B10": "1e3",
    "C1": "=B1/0",
    "C2": "=C3",
    "C3": "=C2",
    "C4": "=FOO(1)",
    "C5": '="a" & B1',
    "C6": '=IF(B1>1000, "big", "small")',
    "C7": "=ROUND(2.345, 2)",
    "C8": '=COUNTIF(B1:B3, ">=300")',
    "C9": '=SUMIF(B1:B3, ">300")',
    "C10": "=0.1+0.2",
    "C11": "=10%",
    "C12": "=-B1^2",
    "C13": "=AVERAGE(B1:B2)",
    "C14": "=1/3",
    "C15": "='x",
    "C16": "=TRUE",
    "C17": "=B1=1200",
    "C18": '=A1="rent"',
    "C19": '=LEN(A1)&"!"',
    "C20": '=IFERROR(1/0, "oops")',
    "C21": '=SUM(B1:B3, "5")',
    "C22": "=(1+2)*3",
    "C23": "=2^3^2",
    "C24": '=CONCAT(A1, " ", B1)',
    "C25": "=D1",
    "C26": "=1e21",
    "C27": "=123456789012",
    "C28": "=1/1e7",
    "C29": "=ROUND(-2.5)",
    "C30": "=MOD(-7, 3)",
    "C31": "=INT(-2.5)",
    "C32": "=SQRT(-1)",
    "C33": "=MAX(B1:B2, 5000)",
    "C34": "=MIN(A1:A1)",
    "C35": "=COUNTA(A1:B3)",
    "C36": "=COUNT(A1:B3)",
    "C37": "=AND(B1>1, B2>1)",
    "C38": "=OR(B1<1, B2<1)",
    "C39": "=NOT(TRUE)",
    "C40": '=UPPER(A1) & LOWER("X") & TRIM("  a   b ")',
    "C41": "=A1 + 1",
    "C42": "=sum(b1:b2)",
    "C43": "=$B$1*2",
    "C44": "=B1<>1200",
    "C45": '=""',
    "C46": "=1 +",
    "C47": "=D1 = 0",
    "C48": '=D1 = ""',
    "C49": "=A1 > 5",
    "C50": "=PRODUCT(B1:B2)",
    "C51": '=COUNTIF(A1:B3, "rent")',
    "C52": '=SUMIF(A1:A3, "Rent", B1:B3)',
    "C53": "=POWER(2, 10)",
    "C54": "=ABS(-4.5)",
    "C55": '=CONCATENATE("x", 1, TRUE)',
    "C56": "=IF(B1)",
    "C57": '=IF("maybe", 1, 2)',
    "C58": "=1/3*3",
    "C59": "=B4:B4",
    "C60": "=2.50",
}

SHOWN = {
    "A1": "Rent",
    "B1": "1200",
    "B2": "300",
    "B3": "1500",
    "B4": "3000",
    "B5": "0012",
    "B6": "0.4",
    "B7": "TRUE",
    "B8": "12",
    "B9": "-3.5",
    "B10": "1000",
    "C1": "#DIV/0!",
    "C2": "#CIRC!",
    "C3": "#CIRC!",
    "C4": "#NAME?",
    "C5": "a1200",
    "C6": "big",
    "C7": "2.35",
    "C8": "3",
    "C9": "2700",
    "C10": "0.3",
    "C11": "0.1",
    "C12": "1440000",
    "C13": "750",
    "C14": "0.3333333333",
    "C15": "#VALUE!",
    "C16": "TRUE",
    "C17": "TRUE",
    "C18": "TRUE",
    "C19": "4!",
    "C20": "oops",
    "C21": "3005",
    "C22": "9",
    "C23": "64",
    "C24": "Rent 1200",
    "C25": "",
    "C26": "1e+21",
    "C27": "123456789012",
    "C28": "1e-7",
    "C29": "-3",
    "C30": "2",
    "C31": "-3",
    "C32": "#NUM!",
    "C33": "5000",
    "C34": "0",
    "C35": "4",
    "C36": "3",
    "C37": "TRUE",
    "C38": "FALSE",
    "C39": "FALSE",
    "C40": "RENTxa b",
    "C41": "#VALUE!",
    "C42": "1500",
    "C43": "2400",
    "C44": "FALSE",
    "C45": "",
    "C46": "#VALUE!",
    "C47": "TRUE",
    "C48": "TRUE",
    "C49": "TRUE",
    "C50": "360000",
    "C51": "1",
    "C52": "1200",
    "C53": "1024",
    "C54": "4.5",
    "C55": "x1TRUE",
    "C56": "TRUE",
    "C57": "#VALUE!",
    "C58": "1",
    "C59": "#VALUE!",
    "C60": "2.5",
}


def test_every_case_is_answered():
    assert set(SHEET) == set(SHOWN)


def test_python_shows_every_cell_as_the_cases_say():
    sheet = cells.Sheet(SHEET)
    shown = {name: sheet.shown(name) for name in SHEET}
    assert shown == SHOWN


RUNNER = """
import { shownCells } from "%s";
import { readFileSync } from "node:fs";
console.log(JSON.stringify(shownCells(JSON.parse(readFileSync(0, "utf8")))));
"""


@node
def test_javascript_shows_every_cell_the_same(tmp_path):
    script = tmp_path / "cells.mjs"
    script.write_text(RUNNER % (WEB / "kit_cells_rules.js").as_uri(), encoding="utf-8")
    done = subprocess.run(["node", str(script)], input=json.dumps(SHEET), capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == SHOWN


# -- the field ---------------------------------------------------------------------------
def test_the_cells_are_written_by_row_then_column():
    sheet = cells.Sheet({"B2": "=A1*2", "A10": "x", "A1": "3", "AA1": "wide", "C1": "  "})
    assert list(sheet.to_field().items()) == [("A1", "3"), ("AA1", "wide"), ("B2", "=A1*2"), ("A10", "x")]
    assert cells.parse_cells(sheet.to_field()) == {"A1": "3", "B2": "=A1*2", "AA1": "wide", "A10": "x"}
    for nothing in ("", "not json", "[1]", None, 3, []):
        assert cells.parse_cells(nothing) == {}
    # A key that is no cell, or an empty value, is left out; names are made proper.
    assert cells.parse_cells({"a1": "1", "nope": "2", "B2": "", "C3": None}) == {"A1": "1"}
    assert cells.parse_cells('{"a1": "1"}') == {"A1": "1"}, "the same as text, for a sheet typed by hand"


@node
def test_javascript_writes_the_same_cells(tmp_path):
    script = tmp_path / "dump.mjs"
    rules = (WEB / "kit_cells_rules.js").as_uri()
    script.write_text(
        f'import {{ Sheet }} from "{rules}";\nimport {{ readFileSync }} from "node:fs";\n'
        "process.stdout.write(JSON.stringify(Sheet.fromField(JSON.parse(readFileSync(0, 'utf8'))).toField()));\n",
        encoding="utf-8",
    )
    sheet = cells.Sheet({"B2": "=A1*2", "A10": "x", "a1": "3", "AA1": "wïde", "D4": 'say "hi"', "nope": "1"})
    done = subprocess.run(
        ["node", str(script)], input=json.dumps(sheet.cells), capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"A1": "3", "AA1": "wïde", "B2": "=A1*2", "D4": 'say "hi"', "A10": "x"}
    assert list(json.loads(done.stdout)) == list(
        cells.parse_cells(sheet.cells) and cells.ordered_cells(cells.parse_cells(sheet.cells))
    )


def test_names_and_places():
    assert [cells.col_name(i) for i in (0, 25, 26, 51, 52, 701, 702)] == ["A", "Z", "AA", "AZ", "BA", "ZZ", "AAA"]
    assert all(cells.col_index(cells.col_name(i)) == i for i in range(800))
    assert cells.parse_ref("$B$2") == (1, 1) and cells.parse_ref("b2") == (1, 1)
    assert cells.parse_ref("B0") is None and cells.parse_ref("2B") is None and cells.parse_ref("") is None
    assert cells.ref_name(0, 27) == "AB1"


def test_the_extent_is_what_is_used_with_room_and_never_less_than_the_least():
    assert cells.extent({}) == (cells.LEAST_ROWS, cells.LEAST_COLS)
    assert cells.extent({"K30": "x"}) == (35, 13)


def test_what_a_formula_reads():
    assert cells.references("=SUM(A1:B2)+C3*$D$4") == ["A1", "B1", "A2", "B2", "C3", "D4"]
    assert cells.references("12") == [] and cells.references("=1 +") == []


def test_setting_a_cell_and_clearing_it():
    sheet = cells.Sheet({"A1": "1"})
    sheet.set("b1", "=A1+1")
    assert sheet.shown("B1") == "2"
    sheet.set("A1", "5")
    assert sheet.shown("B1") == "6", "what was worked out before is worked out again"
    sheet.set("A1", "   ")
    assert sheet.cells == {"B1": "=A1+1"} and sheet.shown("B1") == "1"
    with pytest.raises(ValueError):
        sheet.set("nope", "1")


def test_the_table_is_what_is_used_headed_by_the_columns():
    sheet = cells.Sheet({"A1": "Rent", "B1": "1200", "B3": "=B1*2"})
    assert cells.table(sheet) == [["", "A", "B"], ["1", "Rent", "1200"], ["2", "", ""], ["3", "", "2400"]]
    assert cells.table(sheet, raw=True)[3] == ["3", "", "=B1*2"]
    assert cells.table(cells.Sheet()) == [[""]]
