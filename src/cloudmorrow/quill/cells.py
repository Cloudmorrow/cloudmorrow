"""The sheet kit's arithmetic: a sheet's cells, and their formulas.

A sheet is a `.cell` file: a text file in a folder of somebody's drive —
`Documents/Budget.cell` — holding one JSON object with `cells` in it, one
entry per cell that has something in it, keyed by the cell's name:
`{"cells": {"A1": "Rent", "B1": "1200", "B4": "=SUM(B1:B3)"}}`. What is
kept is what was typed, as typed; everything else — that `1200` is a
number, that `=SUM(B1:B3)` is a formula and what it comes to — is worked
out on reading, here, and in kit_cells_rules.js for the web app, by the
same rules (docs/CELLS.md). The terminal app and the command line both ask
here, so no two surfaces can disagree about what a cell says. Beside the
cells the file may hold a `format`: per cell, how it looks — for now its
borders, `{"B5": {"border": "top bottom"}}` — and whatever else sits beside
those is kept as it was found.

A row or a column can be put in or taken out (Sheet.insert_rows and the
rest): the cells move, and every formula's references follow, as in Excel
— a reference to a cell that is taken out becomes `#REF!`, a range that
loses a row shrinks, one that gains a row grows.

A cell's text means:

- nothing, or only spaces: blank;
- `=` first: a formula;
- `'` first: the rest, as text, even when it looks like a number;
- a number (`12`, `-3.5`, `1e3`, `40%`): a number; `TRUE` or `FALSE`: that;
- anything else: text.

A formula is Excel's: cells (`B2`, `$B$2`), ranges (`B2:B9`), numbers,
`"text"`, TRUE and FALSE, `+ - * / ^`, `&` to join text, `= <> < > <= >=`,
`%`, parentheses, and the functions in FUNCTIONS. What goes wrong is an
error value: `#DIV/0!`, `#REF!` (a cell that is no cell), `#NAME?` (a
function nobody has), `#VALUE!` (text where a number was wanted),
`#CIRC!` (a formula that needs itself), `#N/A`.

Nothing here draws or fetches: a Sheet is made from a file's text, asked
what its cells come to, and gives the text back for writing.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

# -- the cells --------------------------------------------------------------------------

REF = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]+)$")
NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?%?$")

# What a sheet may be asked to draw at the least: a sheet with nothing in
# it still has room to type in.
LEAST_ROWS = 20
LEAST_COLS = 8


def col_name(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA."""
    name = ""
    index += 1
    while index > 0:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def col_index(name: str) -> int:
    """A → 0, Z → 25, AA → 26."""
    index = 0
    for ch in name.upper():
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def parse_ref(text: str) -> tuple[int, int] | None:
    """`B2` (or `$B$2`) → (row 1, col 1), counted from zero; None for no cell."""
    match = REF.match(str(text or "").strip())
    if not match:
        return None
    row = int(match.group(2)) - 1
    if row < 0:
        return None
    return row, col_index(match.group(1))


def ref_name(row: int, col: int) -> str:
    return f"{col_name(col)}{row + 1}"


def parse_cells(value: Any) -> dict[str, str]:
    """The cells of a `.cell` file, by name, as typed: the file's text, or
    the object it holds — `{"cells": {…}}`, or the cells alone. Anything
    else is an empty sheet: there is nothing in it to lose. Names are made
    proper (`a1` → `A1`); a key that is no cell, or an empty value, is left
    out."""
    cells = value
    if isinstance(value, str):
        try:
            cells = json.loads(value) if value.strip() else {}
        except ValueError:
            return {}
    if isinstance(cells, dict) and isinstance(cells.get("cells"), dict):
        cells = cells["cells"]
    if not isinstance(cells, dict):
        return {}
    found: dict[str, str] = {}
    for key, raw in cells.items():
        at = parse_ref(key)
        if at is None or raw is None:
            continue
        value = str(raw)
        if value.strip():
            found[ref_name(*at)] = value
    return found


def sort_key(name: str) -> tuple[int, int]:
    at = parse_ref(name)
    return at if at is not None else (0, 0)


def ordered_cells(cells: dict[str, str]) -> dict[str, str]:
    """The cells as they are written: those with something, by row then column."""
    return {name: cells[name] for name in sorted(cells, key=sort_key) if str(cells[name]).strip()}


# -- the format --------------------------------------------------------------------------
# Beside the cells, how a cell looks: for now its borders. Written only for
# the cells that have any, {"B5": {"border": "top bottom"}}, the sides in
# SIDES' order; a key that is not known is kept as it is, for whoever wrote it.

SIDES = ("top", "right", "bottom", "left")


def parse_sides(value: Any) -> list[str]:
    """`"bottom top"` → ["top", "bottom"], in SIDES' order; `all` is the
    four; a word that is no side is passed over."""
    words = str(value or "").replace(",", " ").lower().split()
    if "all" in words:
        return list(SIDES)
    return [side for side in SIDES if side in words]


def parse_format(value: Any) -> dict[str, dict]:
    """The `format` object of a `.cell` file: per cell, how it looks. Names
    are made proper; a cell with nothing to say is left out."""
    if not isinstance(value, dict):
        return {}
    found: dict[str, dict] = {}
    for key, entry in value.items():
        at = parse_ref(key)
        if at is None or not isinstance(entry, dict):
            continue
        kept = {k: v for k, v in entry.items() if k != "border"}
        sides = parse_sides(entry.get("border"))
        if sides:
            kept = {"border": " ".join(sides), **kept}
        if kept:
            found[ref_name(*at)] = kept
    return found


def ordered_format(format: dict[str, dict]) -> dict[str, dict]:
    return {name: format[name] for name in sorted(format, key=sort_key) if format[name]}


def parse_file(value: Any) -> tuple[dict[str, str], dict[str, dict], dict[str, Any]]:
    """A `.cell` file's text, or the object it holds, taken apart: the cells,
    the format, and whatever else sits beside them, kept for writing back."""
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value) if value.strip() else {}
        except ValueError:
            return {}, {}, {}
    if not isinstance(data, dict):
        return {}, {}, {}
    if not isinstance(data.get("cells"), dict):
        # The cells alone, with nothing around them, are a sheet too.
        return parse_cells(data), {}, {}
    extra = {k: v for k, v in data.items() if k not in ("cells", "format")}
    return parse_cells(data["cells"]), parse_format(data.get("format")), extra


def file_text(cells: dict[str, str], format: dict[str, dict] | None = None, extra: dict[str, Any] | None = None) -> str:
    """A `.cell` file's text: one JSON object with the cells in it, a cell
    a line, by row then column, then the format of the cells that have
    one, then whatever else was found beside them — the same bytes
    kit_cells_rules.js writes."""
    data: dict[str, Any] = {"cells": ordered_cells(cells)}
    kept = ordered_format(format or {})
    if kept:
        data["format"] = kept
    for key, value in (extra or {}).items():
        if key not in data:
            data[key] = value
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# -- rows and columns ------------------------------------------------------------------
# Putting rows (or columns) in, or taking them out, moves what is past them,
# and every formula's references follow, as Excel's do.


def shift_index(index: int, at: int, count: int) -> int | None:
    """Where row (or column) `index` goes when `count` are put in at `at`
    (count > 0), or that many taken out there (count < 0): None for one
    that is taken out."""
    if count > 0:
        return index + count if index >= at else index
    if index >= at - count:
        return index + count
    return None if index >= at else index


def shift_place(place: tuple[int, int] | None, axis: int, at: int, count: int) -> tuple[int, int] | None:
    if place is None:
        return None
    moved = shift_index(place[axis], at, count)
    if moved is None:
        return None
    return (moved, place[1]) if axis == 0 else (place[0], moved)


# A reference in a formula, or a range of two, outside a string: not a
# function's name (`LOG10(`), not part of a longer word.
REF_IN_FORMULA = re.compile(
    r'(?P<string>"(?:[^"]|"")*")'
    r"|(?<![A-Za-z0-9_.$])(?P<a>\$?[A-Za-z]{1,3}\$?[0-9]+)"
    r"(?:(?P<colon>\s*:\s*)(?P<b>\$?[A-Za-z]{1,3}\$?[0-9]+))?(?![A-Za-z0-9_.(])"
)


def _ref_text(like: str, place: tuple[int, int]) -> str:
    """`place` named the way `like` was: its `$`s kept, its letters proper."""
    col_dollar = "$" if like.startswith("$") else ""
    row_dollar = "$" if "$" in like[1:] else ""
    return f"{col_dollar}{col_name(place[1])}{row_dollar}{place[0] + 1}"


def shift_formula(raw: str, axis: int, at: int, count: int) -> str:
    """A formula with its references moved along: `count` rows (axis 0) or
    columns (axis 1) put in at `at`, or taken out there when count < 0. A
    reference to a cell taken out becomes `#REF!`; a range that loses rows
    shrinks, one with rows put in grows, one wholly taken out is `#REF!`.
    What is not a formula is as it was."""
    if not is_formula(raw) or count == 0:
        return raw

    def with_axis(place: tuple[int, int], index: int) -> tuple[int, int]:
        return (index, place[1]) if axis == 0 else (place[0], index)

    def fix(match: re.Match) -> str:
        whole = match.group(0)
        if match.group("string"):
            return whole
        a, b = match.group("a"), match.group("b")
        pa = parse_ref(a)
        if pa is None:
            return whole
        if b is None:
            moved = shift_index(pa[axis], at, count)
            if moved is None:
                return "#REF!"
            return whole if moved == pa[axis] else _ref_text(a, with_axis(pa, moved))
        pb = parse_ref(b)
        if pb is None:
            return whole
        lo, hi = sorted((pa[axis], pb[axis]))
        if count > 0:
            lo2 = lo + count if lo >= at else lo
            hi2 = hi + count if hi >= at else hi
        else:
            n = -count
            lo2 = lo if lo < at else (lo - n if lo >= at + n else at)
            hi2 = hi if hi < at else (hi - n if hi >= at + n else at - 1)
            if lo2 > hi2:
                return "#REF!"
        if (lo2, hi2) == (lo, hi):
            return whole
        a_is_lo = pa[axis] <= pb[axis]
        pa2 = with_axis(pa, lo2 if a_is_lo else hi2)
        pb2 = with_axis(pb, hi2 if a_is_lo else lo2)
        return _ref_text(a, pa2) + match.group("colon") + _ref_text(b, pb2)

    return "=" + REF_IN_FORMULA.sub(fix, raw[1:])


def extent(cells: dict[str, str]) -> tuple[int, int]:
    """How many rows and columns the sheet is drawn with: what is used, with
    room beyond it, and never less than LEAST_ROWS × LEAST_COLS."""
    rows, cols = 0, 0
    for name in cells:
        at = parse_ref(name)
        if at is not None:
            rows, cols = max(rows, at[0] + 1), max(cols, at[1] + 1)
    return max(LEAST_ROWS, rows + 5), max(LEAST_COLS, cols + 2)


# -- values -----------------------------------------------------------------------------
# A value is a float, a str, a bool, None (blank) or an Error.


class Error:
    """What a cell comes to when it cannot: `#DIV/0!`, `#REF!`, …"""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code

    def __repr__(self) -> str:
        return self.code

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Error) and other.code == self.code

    def __hash__(self) -> int:
        return hash(self.code)


DIV0 = Error("#DIV/0!")
REF_ERR = Error("#REF!")
NAME_ERR = Error("#NAME?")
VALUE_ERR = Error("#VALUE!")
CIRC = Error("#CIRC!")
NA = Error("#N/A")

ERRORS = {e.code: e for e in (DIV0, REF_ERR, NAME_ERR, VALUE_ERR, CIRC, NA)}


def literal(raw: str) -> Any:
    """What a cell's text is, when it is not a formula."""
    text = str(raw or "")
    if not text.strip():
        return None
    if text.startswith("'"):
        return text[1:]
    stripped = text.strip()
    upper = stripped.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    if NUMBER.match(stripped):
        if stripped.endswith("%"):
            return float(stripped[:-1]) / 100
        return float(stripped)
    return text


def is_formula(raw: str) -> bool:
    return str(raw or "").startswith("=")


# What a formula may end in and still want a reference: `=`, an operator,
# `(`, a comma, a colon. There the arrows point one out (the surfaces'
# point mode, docs/CELLS.md).
WANTS_REF = frozenset("=+-*/^&<>(,;:")


def wants_ref(text: str) -> bool:
    """Whether a cell's name may go where this (typed so far) ends."""
    text = text.rstrip()
    return is_formula(text) and text[-1] in WANTS_REF


def range_name(one: tuple[int, int], other: tuple[int, int]) -> str:
    """`B1` for one cell; `B1:C3` for two corners, whichever way round."""
    top, bottom = sorted((one[0], other[0]))
    left, right = sorted((one[1], other[1]))
    first = ref_name(top, left)
    return first if (top, left) == (bottom, right) else f"{first}:{ref_name(bottom, right)}"


def display(value: Any) -> str:
    """A value as a cell shows it: numbers short, booleans TRUE/FALSE, blank empty."""
    if value is None:
        return ""
    if isinstance(value, Error):
        return value.code
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return number_text(float(value))
    return str(value)


def number_text(x: float) -> str:
    """A number to ten significant figures, without a trailing `.0` — the
    same text the web app shows (kit_cells_rules.js)."""
    if math.isnan(x):
        return "#NUM!"
    if math.isinf(x):
        return "#NUM!"
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    rounded = float(f"{x:.10g}")
    if rounded == 0:
        return "0"
    if rounded == int(rounded) and abs(rounded) < 1e21:
        return str(int(rounded))
    text = repr(rounded)
    # JavaScript writes 1e-7, not 1e-07.
    return re.sub(r"e([+-])0*(\d)", r"e\1\2", text)


def to_number(value: Any) -> float | Error:
    """A value where a number is wanted: blank is 0, a boolean 1 or 0, text
    only when it reads as one."""
    if value is None:
        return 0.0
    if isinstance(value, Error):
        return value
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    got = literal(str(value).strip()) if str(value).strip() else None
    if isinstance(got, float):
        return got
    return VALUE_ERR


def to_text(value: Any) -> str:
    return display(value)


def truth(value: Any) -> bool | Error:
    if isinstance(value, Error):
        return value
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    upper = str(value).strip().upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    return VALUE_ERR


# -- the tokens -------------------------------------------------------------------------

TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<string>\"(?:[^\"]|\"\")*\")"
    r"|(?P<error>#(?:REF!|DIV/0!|NAME\?|VALUE!|NUM!|CIRC!|N/A))"
    r"|(?P<name>\$?[A-Za-z_][A-Za-z0-9_.]*\$?[0-9]*)"
    r"|(?P<op><>|<=|>=|[-+*/^&=<>%(),:])"
    r")"
)


class FormulaError(Exception):
    """A formula that cannot be read; what it comes to is #NAME? or #VALUE!."""

    def __init__(self, error: Error) -> None:
        super().__init__(error.code)
        self.error = error


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = TOKEN.match(text, pos)
        if not match:
            raise FormulaError(VALUE_ERR)
        pos = match.end()
        kind = match.lastgroup or "op"
        tokens.append((kind, match.group(kind)))
    return tokens


# -- the tree ---------------------------------------------------------------------------
# A node is a tuple: ("num", 1.0), ("str", "x"), ("bool", True), ("ref", row, col),
# ("range", r0, c0, r1, c1), ("call", NAME, [args]), ("neg", node), ("pct", node),
# ("op", symbol, left, right).


class Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.pos = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, kind: str | None = None, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (kind and token[0] != kind) or (value is not None and token[1] != value):
            raise FormulaError(VALUE_ERR)
        self.pos += 1
        return token

    def is_op(self, *symbols: str) -> bool:
        token = self.peek()
        return token is not None and token[0] == "op" and token[1] in symbols

    def parse(self) -> tuple:
        node = self.comparison()
        if self.peek() is not None:
            raise FormulaError(VALUE_ERR)
        return node

    def comparison(self) -> tuple:
        node = self.concat()
        while self.is_op("=", "<>", "<", ">", "<=", ">="):
            symbol = self.take()[1]
            node = ("op", symbol, node, self.concat())
        return node

    def concat(self) -> tuple:
        node = self.additive()
        while self.is_op("&"):
            self.take()
            node = ("op", "&", node, self.additive())
        return node

    def additive(self) -> tuple:
        node = self.term()
        while self.is_op("+", "-"):
            symbol = self.take()[1]
            node = ("op", symbol, node, self.term())
        return node

    def term(self) -> tuple:
        node = self.power()
        while self.is_op("*", "/"):
            symbol = self.take()[1]
            node = ("op", symbol, node, self.power())
        return node

    def power(self) -> tuple:
        node = self.unary()
        while self.is_op("^"):
            self.take()
            node = ("op", "^", node, self.unary())
        return node

    def unary(self) -> tuple:
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        if self.is_op("+"):
            self.take()
            return self.unary()
        return self.postfix()

    def postfix(self) -> tuple:
        node = self.primary()
        while self.is_op("%"):
            self.take()
            node = ("pct", node)
        return node

    def primary(self) -> tuple:
        token = self.peek()
        if token is None:
            raise FormulaError(VALUE_ERR)
        kind, text = token
        if kind == "number":
            self.take()
            return ("num", float(text))
        if kind == "string":
            self.take()
            return ("str", text[1:-1].replace('""', '"'))
        if kind == "error":
            # `#REF!` written in a formula — left by a row taken out — is that error.
            self.take()
            return ("err", text)
        if kind == "op" and text == "(":
            self.take()
            node = self.comparison()
            self.take("op", ")")
            return node
        if kind == "name":
            self.take()
            upper = text.upper()
            if upper == "TRUE":
                return ("bool", True)
            if upper == "FALSE":
                return ("bool", False)
            if self.is_op("("):
                self.take()
                args: list[tuple] = []
                if not self.is_op(")"):
                    args.append(self.comparison())
                    while self.is_op(","):
                        self.take()
                        args.append(self.comparison())
                self.take("op", ")")
                return ("call", upper.replace("$", ""), args)
            at = parse_ref(text)
            if at is None:
                # A word that is no cell and no function: #NAME?, as Excel says.
                raise FormulaError(NAME_ERR)
            if self.is_op(":"):
                self.take()
                other = parse_ref(self.take("name")[1])
                if other is None:
                    raise FormulaError(REF_ERR)
                r0, c0 = min(at[0], other[0]), min(at[1], other[1])
                r1, c1 = max(at[0], other[0]), max(at[1], other[1])
                return ("range", r0, c0, r1, c1)
            return ("ref", at[0], at[1])
        raise FormulaError(VALUE_ERR)


def parse_formula(raw: str) -> tuple:
    """The tree of a formula (`=…`); FormulaError when it cannot be read."""
    return Parser(str(raw)[1:]).parse()


def references(raw: str) -> list[str]:
    """Every cell a formula reads, by name, for whoever wants to know."""
    if not is_formula(raw):
        return []
    try:
        tree = parse_formula(raw)
    except FormulaError:
        return []
    found: list[str] = []

    def walk(node: tuple) -> None:
        kind = node[0]
        if kind == "ref":
            found.append(ref_name(node[1], node[2]))
        elif kind == "range":
            for r in range(node[1], node[3] + 1):
                for c in range(node[2], node[4] + 1):
                    found.append(ref_name(r, c))
        elif kind == "call":
            for arg in node[2]:
                walk(arg)
        elif kind in ("neg", "pct"):
            walk(node[1])
        elif kind == "op":
            walk(node[2])
            walk(node[3])

    walk(tree)
    return found


# -- the functions ------------------------------------------------------------------------
# Each takes the evaluated arguments: a value, or a list of values for a
# range (row by row, blanks included). Ranges given where one value is
# wanted are a #VALUE!.


def _flat(args: list[Any]) -> list[Any]:
    """Every value in the arguments, ranges opened up."""
    out: list[Any] = []
    for arg in args:
        if isinstance(arg, list):
            out.extend(arg)
        else:
            out.append(arg)
    return out


def _numbers(args: list[Any], *, loose: bool) -> list[float] | Error:
    """The numbers among the arguments: a range's text and blanks are passed
    over, as Excel does; a value given straight must read as one."""
    out: list[float] = []
    for arg in args:
        if isinstance(arg, list):
            for v in arg:
                if isinstance(v, Error):
                    return v
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)):
                    out.append(float(v))
        else:
            if isinstance(arg, Error):
                return arg
            if arg is None and loose:
                continue
            n = to_number(arg)
            if isinstance(n, Error):
                return n
            out.append(n)
    return out


def _one(args: list[Any], index: int, default: Any = None) -> Any:
    if index >= len(args):
        return default
    value = args[index]
    if isinstance(value, list):
        return VALUE_ERR
    return value


def _first_error(values: list[Any]) -> Error | None:
    return next((v for v in values if isinstance(v, Error)), None)


def _criterion(crit: Any):
    """A COUNTIF/SUMIF criterion: `">=10"`, `"<>x"`, `10`, `"x"` → a test on a value."""
    if isinstance(crit, Error):
        return crit
    text = display(crit) if not isinstance(crit, str) else crit
    match = re.match(r"^(<>|<=|>=|=|<|>)(.*)$", text)
    symbol, rest = (match.group(1), match.group(2)) if match else ("=", text)
    target = literal(rest.strip()) if rest.strip() else None

    def test(value: Any) -> bool:
        if symbol in ("=", "<>"):
            if target is None:
                same = value is None or value == ""
            elif isinstance(target, float):
                n = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
                same = n is not None and float(n) == target
            elif isinstance(target, bool):
                same = isinstance(value, bool) and value == target
            else:
                same = isinstance(value, str) and value.casefold() == str(target).casefold()
            return same if symbol == "=" else not same
        if not isinstance(target, float) or not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        v = float(value)
        return {"<": v < target, ">": v > target, "<=": v <= target, ">=": v >= target}[symbol]

    return test


def _round(x: float, places: int) -> float:
    """Excel's ROUND: halves away from zero."""
    factor = 10.0**places
    shifted = abs(x) * factor
    rounded = math.floor(shifted + 0.5 + 1e-9)
    return math.copysign(rounded / factor, x)


def fn_sum(args):
    nums = _numbers(args, loose=True)
    return nums if isinstance(nums, Error) else float(sum(nums))


def fn_average(args):
    nums = _numbers(args, loose=True)
    if isinstance(nums, Error):
        return nums
    return DIV0 if not nums else sum(nums) / len(nums)


def fn_min(args):
    nums = _numbers(args, loose=True)
    return nums if isinstance(nums, Error) else (min(nums) if nums else 0.0)


def fn_max(args):
    nums = _numbers(args, loose=True)
    return nums if isinstance(nums, Error) else (max(nums) if nums else 0.0)


def fn_product(args):
    nums = _numbers(args, loose=True)
    if isinstance(nums, Error):
        return nums
    if not nums:
        return 0.0
    out = 1.0
    for n in nums:
        out *= n
    return out


def fn_count(args):
    values = _flat(args)
    return float(sum(1 for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)))


def fn_counta(args):
    values = _flat(args)
    return float(sum(1 for v in values if v is not None and v != ""))


def fn_if(args):
    if not args:
        return VALUE_ERR
    cond = truth(_one(args, 0))
    if isinstance(cond, Error):
        return cond
    return _one(args, 1, True) if cond else _one(args, 2, False)


def fn_and(args):
    values = _flat(args)
    err = _first_error(values)
    if err:
        return err
    tests = [truth(v) for v in values if v is not None and not isinstance(v, str)]
    return all(tests) if tests else VALUE_ERR


def fn_or(args):
    values = _flat(args)
    err = _first_error(values)
    if err:
        return err
    tests = [truth(v) for v in values if v is not None and not isinstance(v, str)]
    return any(tests) if tests else VALUE_ERR


def fn_not(args):
    cond = truth(_one(args, 0))
    return cond if isinstance(cond, Error) else not cond


def fn_round(args):
    x = to_number(_one(args, 0))
    places = to_number(_one(args, 1, 0.0))
    if isinstance(x, Error):
        return x
    if isinstance(places, Error):
        return places
    return _round(x, int(places))


def fn_abs(args):
    x = to_number(_one(args, 0))
    return x if isinstance(x, Error) else abs(x)


def fn_int(args):
    x = to_number(_one(args, 0))
    return x if isinstance(x, Error) else float(math.floor(x))


def fn_mod(args):
    x = to_number(_one(args, 0))
    y = to_number(_one(args, 1))
    if isinstance(x, Error):
        return x
    if isinstance(y, Error):
        return y
    if y == 0:
        return DIV0
    return x - y * math.floor(x / y)


def fn_sqrt(args):
    x = to_number(_one(args, 0))
    if isinstance(x, Error):
        return x
    return Error("#NUM!") if x < 0 else math.sqrt(x)


def fn_power(args):
    x = to_number(_one(args, 0))
    y = to_number(_one(args, 1))
    if isinstance(x, Error):
        return x
    if isinstance(y, Error):
        return y
    return _power(x, y)


def _power(x: float, y: float) -> Any:
    try:
        out = x**y
    except (OverflowError, ZeroDivisionError, ValueError):
        return Error("#NUM!")
    if isinstance(out, complex):
        return Error("#NUM!")
    return float(out)


def fn_len(args):
    v = _one(args, 0)
    return v if isinstance(v, Error) else float(len(to_text(v)))


def fn_concat(args):
    values = _flat(args)
    err = _first_error(values)
    return err if err else "".join(to_text(v) for v in values)


def fn_upper(args):
    v = _one(args, 0)
    return v if isinstance(v, Error) else to_text(v).upper()


def fn_lower(args):
    v = _one(args, 0)
    return v if isinstance(v, Error) else to_text(v).lower()


def fn_trim(args):
    v = _one(args, 0)
    return v if isinstance(v, Error) else " ".join(to_text(v).split())


def fn_iferror(args):
    v = _one(args, 0)
    return _one(args, 1, "") if isinstance(v, Error) else v


def fn_countif(args):
    if len(args) < 2:
        return VALUE_ERR
    values = args[0] if isinstance(args[0], list) else [args[0]]
    test = _criterion(args[1])
    if isinstance(test, Error):
        return test
    return float(sum(1 for v in values if test(v)))


def fn_sumif(args):
    if len(args) < 2:
        return VALUE_ERR
    values = args[0] if isinstance(args[0], list) else [args[0]]
    summed = args[2] if len(args) > 2 and isinstance(args[2], list) else values
    test = _criterion(args[1])
    if isinstance(test, Error):
        return test
    total = 0.0
    for i, v in enumerate(values):
        if test(v) and i < len(summed):
            s = summed[i]
            if isinstance(s, (int, float)) and not isinstance(s, bool):
                total += float(s)
    return total


FUNCTIONS = {
    "SUM": fn_sum,
    "AVERAGE": fn_average,
    "MIN": fn_min,
    "MAX": fn_max,
    "PRODUCT": fn_product,
    "COUNT": fn_count,
    "COUNTA": fn_counta,
    "IF": fn_if,
    "AND": fn_and,
    "OR": fn_or,
    "NOT": fn_not,
    "ROUND": fn_round,
    "ABS": fn_abs,
    "INT": fn_int,
    "MOD": fn_mod,
    "SQRT": fn_sqrt,
    "POWER": fn_power,
    "LEN": fn_len,
    "CONCAT": fn_concat,
    "CONCATENATE": fn_concat,
    "UPPER": fn_upper,
    "LOWER": fn_lower,
    "TRIM": fn_trim,
    "IFERROR": fn_iferror,
    "COUNTIF": fn_countif,
    "SUMIF": fn_sumif,
}


# -- the sheet ----------------------------------------------------------------------------


class Sheet:
    """The cells of one `.cell` file, and what each comes to."""

    def __init__(
        self,
        cells: dict[str, str] | None = None,
        format: dict[str, dict] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.cells: dict[str, str] = dict(cells or {})
        # How a cell looks, by name, for the cells that say: {"B5": {"border": "top"}}.
        self.format: dict[str, dict] = {name: dict(entry) for name, entry in (format or {}).items()}
        # Whatever else the file held beside the cells and the format, kept as found.
        self.extra: dict[str, Any] = dict(extra or {})
        self._values: dict[str, Any] = {}
        self._busy: set[str] = set()

    @classmethod
    def from_text(cls, value: Any) -> Sheet:
        """From a `.cell` file's text (a file record's `text` field)."""
        return cls(*parse_file(value))

    def to_text(self) -> str:
        """The `.cell` file's text, for writing back."""
        return file_text(self.cells, self.format, self.extra)

    # -- how a cell looks

    def border(self, name: str) -> list[str]:
        """The sides of a cell that have a border, in SIDES' order."""
        at = parse_ref(name)
        if at is None:
            return []
        return parse_sides((self.format.get(ref_name(*at)) or {}).get("border"))

    def set_border(self, name: str, sides: Any) -> None:
        """Which sides of a cell have a border; none clears them."""
        at = parse_ref(name)
        if at is None:
            raise ValueError(f"{name!r} is no cell")
        key = ref_name(*at)
        words = parse_sides(" ".join(sides))
        entry = {k: v for k, v in (self.format.get(key) or {}).items() if k != "border"}
        if words:
            entry = {"border": " ".join(words), **entry}
        if entry:
            self.format[key] = entry
        else:
            self.format.pop(key, None)

    # -- rows and columns

    def insert_rows(self, at: int, count: int = 1) -> None:
        """`count` empty rows put in before row `at` (counted from zero)."""
        self._shift(0, at, count)

    def delete_rows(self, at: int, count: int = 1) -> None:
        """Rows `at` to `at + count - 1` taken out."""
        self._shift(0, at, -count)

    def insert_cols(self, at: int, count: int = 1) -> None:
        self._shift(1, at, count)

    def delete_cols(self, at: int, count: int = 1) -> None:
        self._shift(1, at, -count)

    def _shift(self, axis: int, at: int, count: int) -> None:
        if at < 0 or count == 0:
            return
        cells: dict[str, str] = {}
        for name, raw in self.cells.items():
            place = shift_place(parse_ref(name), axis, at, count)
            if place is not None:
                cells[ref_name(*place)] = shift_formula(raw, axis, at, count)
        format: dict[str, dict] = {}
        for name, entry in self.format.items():
            place = shift_place(parse_ref(name), axis, at, count)
            if place is not None:
                format[ref_name(*place)] = entry
        self.cells, self.format = cells, format
        self._values.clear()

    def raw(self, name: str) -> str:
        return self.cells.get(name, "")

    def set(self, name: str, raw: str) -> None:
        """What is typed into a cell; nothing clears it."""
        at = parse_ref(name)
        if at is None:
            raise ValueError(f"{name!r} is no cell")
        name = ref_name(*at)
        if str(raw or "").strip():
            self.cells[name] = str(raw)
        else:
            self.cells.pop(name, None)
        self._values.clear()

    @property
    def extent(self) -> tuple[int, int]:
        return extent(self.cells)

    def value(self, name: str) -> Any:
        """What a cell comes to: its literal, or its formula worked out."""
        at = parse_ref(name)
        if at is None:
            return REF_ERR
        name = ref_name(*at)
        if name in self._values:
            return self._values[name]
        raw = self.cells.get(name, "")
        if not is_formula(raw):
            value = literal(raw)
        elif name in self._busy:
            return CIRC
        else:
            self._busy.add(name)
            try:
                value = self._single(self.evaluate(parse_formula(raw)))
            except FormulaError as exc:
                value = exc.error
            finally:
                self._busy.discard(name)
        self._values[name] = value
        return value

    def shown(self, name: str) -> str:
        return display(self.value(name))

    def values(self) -> dict[str, Any]:
        return {name: self.value(name) for name in sorted(self.cells, key=sort_key)}

    def evaluate(self, node: tuple) -> Any:
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "str":
            return node[1]
        if kind == "bool":
            return node[1]
        if kind == "err":
            return Error(node[1])
        if kind == "ref":
            return self.value(ref_name(node[1], node[2]))
        if kind == "range":
            # A range where one value is wanted is its values; the functions
            # take them as a list, the operators say #VALUE!.
            return [
                self.value(ref_name(r, c)) for r in range(node[1], node[3] + 1) for c in range(node[2], node[4] + 1)
            ]
        if kind == "neg":
            x = to_number(self._single(self.evaluate(node[1])))
            return x if isinstance(x, Error) else -x
        if kind == "pct":
            x = to_number(self._single(self.evaluate(node[1])))
            return x if isinstance(x, Error) else x / 100
        if kind == "call":
            fn = FUNCTIONS.get(node[1])
            if fn is None:
                return NAME_ERR
            return fn([self.evaluate(arg) for arg in node[2]])
        if kind == "op":
            return self._operate(node[1], self._single(self.evaluate(node[2])), self._single(self.evaluate(node[3])))
        return VALUE_ERR

    @staticmethod
    def _single(value: Any) -> Any:
        return VALUE_ERR if isinstance(value, list) else value

    @staticmethod
    def _operate(symbol: str, left: Any, right: Any) -> Any:
        if isinstance(left, Error):
            return left
        if isinstance(right, Error):
            return right
        if symbol == "&":
            return to_text(left) + to_text(right)
        if symbol in ("=", "<>", "<", ">", "<=", ">="):
            return compare(symbol, left, right)
        x = to_number(left)
        y = to_number(right)
        if isinstance(x, Error):
            return x
        if isinstance(y, Error):
            return y
        if symbol == "+":
            return x + y
        if symbol == "-":
            return x - y
        if symbol == "*":
            return x * y
        if symbol == "/":
            return DIV0 if y == 0 else x / y
        if symbol == "^":
            return _power(x, y)
        return VALUE_ERR


def _rank(value: Any) -> tuple[int, Any]:
    """Excel's order: numbers, then text (by letters, case aside), then booleans."""
    if value is None:
        return (0, 0.0)
    if isinstance(value, bool):
        return (2, 1 if value else 0)
    if isinstance(value, (int, float)):
        return (0, float(value))
    return (1, str(value).casefold())


def _blank_like(other: Any) -> Any:
    """A blank beside text is empty text, beside a boolean FALSE, else 0, as in Excel."""
    if isinstance(other, str):
        return ""
    if isinstance(other, bool):
        return False
    return 0.0


def compare(symbol: str, left: Any, right: Any) -> bool:
    if left is None:
        left = _blank_like(right)
    if right is None:
        right = _blank_like(left)
    a, b = _rank(left), _rank(right)
    if symbol == "=":
        return a == b
    if symbol == "<>":
        return a != b
    if symbol == "<":
        return a < b
    if symbol == ">":
        return a > b
    if symbol == "<=":
        return a <= b
    return a >= b


# -- a sheet as text -----------------------------------------------------------------------


def table(sheet: Sheet, *, raw: bool = False) -> list[list[str]]:
    """The sheet as rows of text, headed by the column names: what the
    command line prints, and the terminal draws."""
    places = [parse_ref(n) for n in sheet.cells]
    used_rows = max((at[0] + 1 for at in places if at), default=0)
    used_cols = max((at[1] + 1 for at in places if at), default=0)
    head = [""] + [col_name(c) for c in range(used_cols)]
    out = [head]
    for r in range(used_rows):
        line = [str(r + 1)]
        for c in range(used_cols):
            name = ref_name(r, c)
            line.append(sheet.raw(name) if raw else sheet.shown(name))
        out.append(line)
    return out
