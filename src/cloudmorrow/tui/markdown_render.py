"""Render a single markdown line as styled text.

The editor shows the line the cursor is on as raw markdown and every other line
rendered, so rendering has to work one line at a time. Block context that spans
lines (fenced code) is passed in by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rich.text import Text

BULLETS = ("•", "◦", "▪", "‣")


@dataclass(frozen=True, slots=True)
class Theme:
    """Every colour the renderer can use, in one place."""

    text: str = "#d7dbe4"
    heading: tuple[str, ...] = (
        "bold #7dd3fc",
        "bold #67e8f9",
        "bold #a5b4fc",
        "bold #c4b5fd",
        "bold #cbd5f5",
        "bold #cbd5f5",
    )
    heading_mark: str = "#3f5266"
    bold: str = "bold #f1f5f9"
    italic: str = "italic #cbd5f5"
    strike: str = "strike #7b8494"
    code: str = "#f9a8d4 on #26262f"
    code_block: str = "#dbe4f0 on #1b1b23"
    fence: str = "dim #5a6472"
    link: str = "underline #7dd3fc"
    link_url: str = "dim #5a6472"
    bullet: str = "bold #22d3ee"
    number: str = "bold #38bdf8"
    quote_bar: str = "#3f5266"
    quote: str = "italic #94a3b8"
    rule: str = "#3f5266"
    tag: str = "#fbbf24"
    task_open: str = "#38bdf8"
    task_done: str = "#4ade80"
    task_done_text: str = "strike #6b7280"
    table_pipe: str = "dim #3f5266"
    raw: str = "#e7ebf3"


DEFAULT_THEME = Theme()

_FENCE_RE = re.compile(r"^(\s*)(```|~~~)\s*([\w+-]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_RULE_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_RE = re.compile(r"^(\s*)((?:>\s?)+)(.*)$")
_UL_RE = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)(\d+)([.)])\s+(.*)$")
_TASK_RE = re.compile(r"^\[([ xX])\]\s*(.*)$")
_TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

_INLINE_RE = re.compile(
    r"""
      (?P<esc>\\[\\`*_{}\[\]()#+\-.!~>|])
    | (?P<code>`+)(?P<code_body>.+?)(?P=code)
    | !\[(?P<img_alt>[^\]]*)\]\((?P<img_url>[^)]*)\)
    | \[\[(?P<wiki>[^\]]+)\]\]
    | \[(?P<link_text>[^\]]*)\]\((?P<link_url>[^)]*)\)
    | (?P<bold>\*\*|__)(?P<bold_body>.+?)(?P=bold)
    | ~~(?P<strike_body>.+?)~~
    | (?P<em>[*_])(?P<em_body>[^\s*_](?:.*?[^\s*_])?)(?P=em)
    | (?P<autolink><(?P<autolink_url>[a-z][a-z0-9+.-]*://[^>\s]+)>)
    | (?<![\w#])(?P<tag>\#[A-Za-z][\w/-]*)
    """,
    re.VERBOSE,
)


def code_fence_states(lines: list[str]) -> list[bool]:
    """For each line, whether it sits *inside* a fenced code block.

    The fence markers themselves are reported as outside, so the caller can
    style them as fences rather than as code.
    """
    states: list[bool] = []
    inside = False
    for line in lines:
        match = _FENCE_RE.match(line)
        if match:
            states.append(False)
            inside = not inside
            continue
        states.append(inside)
    return states


def render_inline(raw: str, theme: Theme = DEFAULT_THEME, base: str | None = None) -> Text:
    """Render inline markdown, hiding the markers themselves."""
    base_style = base or theme.text
    text = Text(no_wrap=True)
    pos = 0
    while pos < len(raw):
        match = _INLINE_RE.search(raw, pos)
        if match is None:
            text.append(raw[pos:], base_style)
            break
        if match.start() > pos:
            text.append(raw[pos : match.start()], base_style)
        text.append_text(_render_match(match, theme, base_style))
        pos = max(match.end(), match.start() + 1)
    return text


def _styled(body: str, theme: Theme, base: str, style: str) -> Text:
    inner = render_inline(body, theme, base)
    inner.stylize(style)
    return inner


def _render_match(match: re.Match[str], theme: Theme, base: str) -> Text:
    groups = match.groupdict()
    if groups["esc"]:
        return Text(groups["esc"][1], base)
    if groups["code"]:
        return Text(groups["code_body"], theme.code)
    if groups["img_alt"] is not None:
        label = groups["img_alt"] or groups["img_url"]
        return Text(f"🖼 {label}", theme.link)
    if groups["wiki"]:
        return Text(groups["wiki"], theme.link)
    if groups["link_text"] is not None:
        out = _styled(groups["link_text"], theme, base, theme.link)
        out.append(" ↗", theme.link_url)
        return out
    if groups["bold"]:
        return _styled(groups["bold_body"], theme, base, theme.bold)
    if groups["strike_body"]:
        return _styled(groups["strike_body"], theme, base, theme.strike)
    if groups["em"]:
        return _styled(groups["em_body"], theme, base, theme.italic)
    if groups["autolink"]:
        return Text(groups["autolink_url"], theme.link)
    if groups["tag"]:
        return Text(groups["tag"], theme.tag)
    return Text(match.group(0), base)


def render_line(
    raw: str,
    *,
    in_code_block: bool = False,
    width: int = 80,
    theme: Theme = DEFAULT_THEME,
) -> Text:
    """Render one markdown line to styled text."""
    if in_code_block:
        return Text(raw or " ", theme.code_block, no_wrap=True)

    fence = _FENCE_RE.match(raw)
    if fence:
        indent, _, lang = fence.groups()
        label = f" {lang} " if lang else ""
        bar = "─" * max(4, min(width, 40) - len(label) - len(indent) - 2)
        return Text(f"{indent}╌╌{label}{bar}", theme.fence, no_wrap=True)

    heading = _HEADING_RE.match(raw)
    if heading:
        hashes, body = heading.groups()
        level = len(hashes)
        text = Text(no_wrap=True)
        text.append("▎" * min(level, 2) + " ", theme.heading_mark)
        text.append_text(_styled(body, theme, theme.text, theme.heading[level - 1]))
        return text

    if _RULE_RE.match(raw) and raw.strip():
        return Text("─" * max(4, width - 2), theme.rule, no_wrap=True)

    quote = _QUOTE_RE.match(raw)
    if quote:
        indent, markers, body = quote.groups()
        depth = markers.count(">")
        text = Text(indent, theme.text, no_wrap=True)
        text.append("▏" * depth + " ", theme.quote_bar)
        text.append_text(render_inline(body, theme, theme.quote))
        return text

    if _TABLE_RE.match(raw):
        if _TABLE_SEP_RE.match(raw):
            ruled = re.sub(r"[^|]", "─", raw).replace("|", "│")
            return Text(ruled, theme.table_pipe, no_wrap=True)
        text = Text(no_wrap=True)
        for index, cell in enumerate(raw.split("|")):
            if index:
                text.append("│", theme.table_pipe)
            text.append_text(render_inline(cell, theme))
        return text

    unordered = _UL_RE.match(raw)
    if unordered:
        indent, _, body = unordered.groups()
        level = len(indent) // 2
        text = Text(indent, theme.text, no_wrap=True)
        task = _TASK_RE.match(body)
        if task:
            mark, task_body = task.groups()
            done = mark.lower() == "x"
            text.append(
                ("☑" if done else "☐") + " ", theme.task_done if done else theme.task_open
            )
            text.append_text(
                render_inline(task_body, theme, theme.task_done_text if done else theme.text)
            )
            return text
        text.append(BULLETS[level % len(BULLETS)] + " ", theme.bullet)
        text.append_text(render_inline(body, theme))
        return text

    ordered = _OL_RE.match(raw)
    if ordered:
        indent, number, _, body = ordered.groups()
        text = Text(indent, theme.text, no_wrap=True)
        text.append(f"{number}. ", theme.number)
        text.append_text(render_inline(body, theme))
        return text

    return render_inline(raw, theme)


def render_raw_line(raw: str, theme: Theme = DEFAULT_THEME) -> Text:
    """The line under the cursor: markdown source, markers and all."""
    return Text(raw, theme.raw, no_wrap=True)
