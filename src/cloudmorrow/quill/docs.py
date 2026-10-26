"""The document kit's model: a document's blocks, and their runs of text.

A document is a `.docs` file: a text file in a folder of somebody's drive —
`Documents/Letter.docs` — holding one JSON object with `blocks` in it:

    {"blocks": [
      {"kind": "heading", "level": 1, "runs": [{"text": "A letter"}]},
      {"kind": "paragraph", "runs": [{"text": "Dear "}, {"text": "you", "bold": true}]},
      {"kind": "bullet", "runs": [{"text": "one thing"}]},
      {"kind": "table", "rows": [[{"runs": [{"text": "a"}]}, {"runs": [{"text": "b"}]}]]}
    ]}

A block is a paragraph, a heading (level 1 to 3), a bullet or a numbered
list item (with a level, 0 at the margin), a quote, or a table (rows of
cells, each a run of text); a paragraph, heading, item or quote may say
how it is aligned (`center`, `right`, `justify`; nothing means left). A
run is text and what is true of it: `bold`, `italic`, `underline`,
`strike`, or a `link`. Nothing else is kept — not fonts, not sizes, not
pictures — which is what makes a document the same on every surface.

The web app draws a document from the same rules in kit_docs_rules.js;
the terminal and the command line edit it as Markdown through
`to_markdown` and `from_markdown` here, and a Word file comes and goes
through quill/docx.py. Nothing here draws or fetches.
"""

from __future__ import annotations

import json
import re
from typing import Any

KINDS = ("paragraph", "heading", "bullet", "numbered", "quote", "table")
FLAGS = ("bold", "italic", "underline", "strike")
ALIGNS = ("center", "right", "justify")


# -- runs ---------------------------------------------------------------------------------
def run(text: str, **what: Any) -> dict:
    """One run: its text, and only what is true of it, in a fixed order."""
    out: dict = {"text": str(text)}
    for flag in FLAGS:
        if what.get(flag):
            out[flag] = True
    if what.get("link"):
        out["link"] = str(what["link"])
    return out


def _clean_run(value: Any) -> dict | None:
    if isinstance(value, str):
        return run(value) if value else None
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    if not isinstance(text, str) or not text:
        return None
    return run(text, **{k: value.get(k) for k in (*FLAGS, "link")})


def _same_style(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in (*FLAGS, "link"))


def merge_runs(runs: list) -> list[dict]:
    """Runs cleaned, and neighbours alike joined: `Hel` + `lo` bold is one run."""
    out: list[dict] = []
    for raw in runs or []:
        one = _clean_run(raw)
        if one is None:
            continue
        if out and _same_style(out[-1], one):
            out[-1]["text"] += one["text"]
        else:
            out.append(one)
    return out


def runs_text(runs: list) -> str:
    return "".join(r.get("text", "") for r in runs or [])


# -- blocks -------------------------------------------------------------------------------
def block(kind: str, runs: list | None = None, *, level: int = 0, align: str = "", rows: list | None = None) -> dict:
    """One block, in a fixed order of keys: kind, level, align, then runs or rows."""
    out: dict = {"kind": kind}
    if kind == "heading":
        out["level"] = min(3, max(1, int(level or 1)))
    elif kind in ("bullet", "numbered") and level:
        out["level"] = max(0, int(level))
    if align in ALIGNS and kind != "table":
        out["align"] = align
    if kind == "table":
        out["rows"] = [
            [{"runs": merge_runs(cell.get("runs") if isinstance(cell, dict) else cell)} for cell in row]
            for row in (rows or [])
        ]
    else:
        out["runs"] = merge_runs(runs or [])
    return out


def _clean_block(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind = value.get("kind")
    if kind not in KINDS:
        return None
    if kind == "table":
        rows = [row for row in value.get("rows") or [] if isinstance(row, list)]
        if not rows:
            return None
        width = max(len(row) for row in rows)
        rows = [row + [{"runs": []}] * (width - len(row)) for row in rows]
        return block("table", rows=rows)
    level = value.get("level") or 0
    if not isinstance(level, int) or isinstance(level, bool):
        level = 0
    align = value.get("align") if isinstance(value.get("align"), str) else ""
    runs = value.get("runs") if isinstance(value.get("runs"), list) else []
    return block(kind, runs, level=level, align=align)


def block_text(one: dict) -> str:
    """A block's words alone; a table's cells by tabs, its rows by lines."""
    if one["kind"] == "table":
        return "\n".join("\t".join(runs_text(cell["runs"]) for cell in row) for row in one["rows"])
    return runs_text(one["runs"])


# -- the file -----------------------------------------------------------------------------
class Doc:
    """One document: its blocks, in order."""

    def __init__(self, blocks: list | None = None) -> None:
        self.blocks: list[dict] = [b for b in (_clean_block(x) for x in blocks or []) if b is not None]

    @classmethod
    def from_text(cls, value: Any) -> Doc:
        """From a `.docs` file's text (a file record's `text` field): the JSON
        object, or the same already parsed. Anything else is an empty document."""
        return cls(parse_blocks(value))

    def to_text(self) -> str:
        """The `.docs` file's text, for writing back."""
        return file_text(self.blocks)

    @property
    def text(self) -> str:
        """The words alone, a block a line."""
        return "\n".join(block_text(b) for b in self.blocks)

    @property
    def words(self) -> int:
        return len(self.text.split())


def parse_blocks(value: Any) -> list[dict]:
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value) if value.strip() else {}
        except ValueError:
            return []
    if isinstance(data, dict) and isinstance(data.get("blocks"), list):
        data = data["blocks"]
    if not isinstance(data, list):
        return []
    return [b for b in (_clean_block(x) for x in data) if b is not None]


def file_text(blocks: list[dict]) -> str:
    """A `.docs` file's text: one JSON object with the blocks in it — the
    same bytes kit_docs_rules.js writes."""
    return json.dumps({"blocks": blocks}, indent=2, ensure_ascii=False) + "\n"


def preview(doc: Doc, chars: int = 120) -> str:
    """The first words after the title: what a list shows under a document's name."""
    lines = [block_text(b).strip() for b in doc.blocks]
    lines = [ln for ln in lines if ln]
    if lines and doc.blocks and doc.blocks[0]["kind"] == "heading" and len(lines) > 1:
        lines = lines[1:]
    text = " ".join(lines)
    return text[: chars - 1] + "…" if len(text) > chars else text


# -- Markdown: how the terminal and the command line edit a document -----------------------
# A heading is `# `, a bullet `- ` (indented two spaces a level), a numbered
# item `1. `, a quote `> `, a table `| a | b |` with a `| --- |` line after
# its first row; a paragraph is the lines up to a blank one. In a line,
# `**bold**`, `*italic*`, `__underline__`, `~~strike~~` and `[text](url)`.
# Alignment has no Markdown, and is lost on the way through.

_ESCAPED = re.compile(r"([\\*_~\[\]])")


def _mark(text: str) -> str:
    return _ESCAPED.sub(r"\\\1", text)


def runs_markdown(runs: list) -> str:
    out = []
    for r in runs:
        text = _mark(r["text"])
        if r.get("bold"):
            text = f"**{text}**"
        if r.get("italic"):
            text = f"*{text}*"
        if r.get("underline"):
            text = f"__{text}__"
        if r.get("strike"):
            text = f"~~{text}~~"
        if r.get("link"):
            text = f"[{text}]({r['link']})"
        out.append(text)
    return "".join(out)


def to_markdown(doc: Doc) -> str:
    lines: list[str] = []
    number = 0
    blocks = doc.blocks
    for i, b in enumerate(blocks):
        kind = b["kind"]
        if kind != "numbered":
            number = 0
        # A list's items stand together; a blank line parts everything else.
        if lines and not (kind in ("bullet", "numbered") and blocks[i - 1]["kind"] == kind):
            lines.append("")
        if kind == "heading":
            lines.append("#" * b["level"] + " " + runs_markdown(b["runs"]))
        elif kind == "bullet":
            lines.append("  " * b.get("level", 0) + "- " + runs_markdown(b["runs"]))
        elif kind == "numbered":
            number += 1
            lines.append("  " * b.get("level", 0) + f"{number}. " + runs_markdown(b["runs"]))
        elif kind == "quote":
            lines.append("> " + runs_markdown(b["runs"]).replace("\n", "\n> "))
        elif kind == "table":
            for i, row in enumerate(b["rows"]):
                lines.append("| " + " | ".join(runs_markdown(c["runs"]).replace("|", "\\|") for c in row) + " |")
                if i == 0:
                    lines.append("|" + " --- |" * len(row))
        else:
            lines.append(runs_markdown(b["runs"]))
    return "\n".join(lines) + ("\n" if lines else "")


_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_RULE = re.compile(r"^\|?(\s*:?-{3,}:?\s*\|)+\s*$")


def parse_runs(text: str) -> list[dict]:
    """Runs from a line of Markdown: the marks toggle what is true of the
    text, a backslash keeps the character after it, `[text](url)` is a link."""
    runs: list[dict] = []
    state = {"bold": False, "italic": False, "underline": False, "strike": False}
    link = ""
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            runs.append(run("".join(buffer), **state, link=link))
            buffer.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        two = text[i : i + 2]
        if ch == "\\" and i + 1 < n:
            buffer.append(text[i + 1])
            i += 2
            continue
        if two == "**":
            flush()
            state["bold"] = not state["bold"]
            i += 2
            continue
        if two == "__":
            flush()
            state["underline"] = not state["underline"]
            i += 2
            continue
        if two == "~~":
            flush()
            state["strike"] = not state["strike"]
            i += 2
            continue
        if ch == "*":
            flush()
            state["italic"] = not state["italic"]
            i += 1
            continue
        if ch == "[" and not link:
            close = text.find("](", i)
            end = text.find(")", close + 2) if close >= 0 else -1
            if close >= 0 and end >= 0:
                flush()
                link = text[close + 2 : end].strip()
                inner = parse_runs(text[i + 1 : close])
                for r in inner:
                    runs.append(run(r["text"], **{k: r.get(k) or state[k] for k in FLAGS}, link=link))
                link = ""
                i = end + 1
                continue
        buffer.append(ch)
        i += 1
    flush()
    return merge_runs(runs)


def from_markdown(text: str) -> Doc:
    blocks: list[dict] = []
    paragraph: list[str] = []
    table: list[list[dict]] = []
    quoting = False

    def end_paragraph() -> None:
        if paragraph:
            blocks.append(block("paragraph", parse_runs("\n".join(paragraph))))
            paragraph.clear()

    def end_table() -> None:
        if table:
            blocks.append(block("table", rows=[[{"runs": c} for c in row] for row in table]))
            table.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            end_paragraph()
            end_table()
            quoting = False
            continue
        if line.lstrip().startswith("|") and line.endswith("|"):
            end_paragraph()
            quoting = False
            if _RULE.match(line.strip()):
                continue
            cells = re.split(r"(?<!\\)\|", line.strip()[1:-1])
            table.append([parse_runs(c.strip().replace("\\|", "|")) for c in cells])
            continue
        end_table()
        if (m := _HEADING.match(line)) is not None:
            end_paragraph()
            blocks.append(block("heading", parse_runs(m.group(2)), level=len(m.group(1))))
        elif (m := _BULLET.match(line)) is not None:
            end_paragraph()
            blocks.append(block("bullet", parse_runs(m.group(2)), level=len(m.group(1)) // 2))
        elif (m := _NUMBERED.match(line)) is not None:
            end_paragraph()
            blocks.append(block("numbered", parse_runs(m.group(2)), level=len(m.group(1)) // 2))
        elif line.startswith(">"):
            end_paragraph()
            said = parse_runs(line[1:].lstrip())
            if quoting:
                # The quote goes on: another line of the same.
                blocks[-1] = block("quote", blocks[-1]["runs"] + [run("\n")] + said)
            else:
                blocks.append(block("quote", said))
            quoting = True
            continue
        else:
            paragraph.append(line)
        quoting = False
    end_paragraph()
    end_table()
    return Doc(blocks)
