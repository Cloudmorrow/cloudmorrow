"""`cloudmorrow <quill> ACTION` — every installed Quill, on the command line.

The command-line surface of the kit. Nobody writes it per Quill: the words
come from the Quill's first screen (or `--screen`) and its datamodel.

    cm tasks list                      # the board, lane by lane
    cm tasks add "Repot the fig"       # into the first lane
    cm tasks move 8f2c doing           # a record by the start of its id
    cm tasks done 8f2c
    cm tasks show 8f2c
    cm tasks set 8f2c due=2026-10-01
    cm tasks delete 8f2c
    cm tasks groups                    # the boards, for a board with groups
    cm tasks list --group Garden       # another board, by name or id
    cm secrets list -g work/production # a list's group and subgroup, by value
    cm secrets show API_KEY --reveal   # a secret field is dots until asked for

A `calendar` screen lists a range of days, and adds with its two moments:

    cm calendar list --from 2026-10-01 --to 2026-10-31
    cm calendar add "Dentist" starts=2026-10-01T10:00 ends=2026-10-01T11:00
    cm calendar add "Holiday" starts=2026-10-12 ends=2026-10-16 calendar=House

A field may be named by what the screen binds it as (`starts=` for the
calendar's `starts_at`), and a link field (`calendar=House`) takes the
linked record's name or id.

Every screen's records have a history — who did what, which fields, never
a value: `cm <quill> history <id or title>`.

An `editor` screen is pages of Markdown, found by their path:

    cm notes list                      # every page, folders and all
    cm notes show ideas/garden         # the Markdown, as it is: pipe it on
    cm notes add ideas/garden          # from stdin, or $EDITOR
    cm notes edit ideas/garden         # $EDITOR, or the new text from stdin
    cm notes search tomatoes           # names and every line

A `sheet` screen is sheets of cells, `.cell` files worked out here (docs/CELLS.md):

    cm cells add Budget                # a new, empty sheet: Documents/Budget.cell
    cm cells show Budget               # the sheet as a table; --raw for the formulas
    cm cells get Budget B4             # one cell, worked out
    cm cells set Budget B4 "=SUM(B1:B3)"
    cm cells set Budget name=Costs     # renames the file
A `document` screen is documents, `.docs` files and Word's, edited as Markdown (docs/DOCS.md):

    cm docs list                       # every document, folders and all
    cm docs show Letter                # as Markdown; --raw for the .docs file; --plain for JSON
    cm docs add Letter                 # from stdin, or $EDITOR, as Markdown
    cm docs edit Letter                # $EDITOR, or the new Markdown from stdin
    cm docs export Letter ./Letter.docx   # a Word file on this machine (or .md, .docs)
    cm docs import ./Letter.docx       # a Word (or Markdown) file from this machine, as a document

A `grid` (files) takes its group and folder as words instead:

    cm files list                      # the groups: My Files, the shares
    cm files list my-files Photos      # a folder in one
    cm files get my-files Photos/cat.jpg [out]
    cm files put my-files Photos ./dog.jpg [more…]
    cm files add my-files Photos/2026  # a new folder
    cm files delete my-files Photos/old.jpg
A `thread` screen is spaces and what is said in them:

    cm chat list                       # the channels, with what is unread

    cm data list                       # every datamodel you may see, by domain
    cm data list deal                  # the records of one, to look at
    cm data show snapshot 9f8e         # one record; a snapshot with its attestations
    cm chat show general               # the conversation, newest at the bottom
    cm chat say general "on my way"    # a channel by name, id, or the person

A `timeline` is projects of pieces on tracks; a piece is named by the start
of its id or its name, a time is seconds or m:ss:

    cm cutter list                     # the projects, newest first
    cm cutter add "Holiday"            # a new project
    cm cutter show Holiday             # its tracks, and the pieces with their times
    cm cutter add Holiday beach.mp4 --track V1 --at 0   # --length without a frames API
    cm cutter cut Holiday 8f2c 4.5     # split at 4.5 s; its blurs go with each half
    cm cutter trim Holiday 8f2c --start 1 | --end 0:12
    cm cutter move Holiday 8f2c --at 20 [--track V2]
    cm cutter rm Holiday 8f2c
    cm cutter frame Holiday --at 3 -o frame.jpg   # the cut at 3 s, from the frames API
    cm cutter export Holiday format=webm          # the screen's export action

A `list` that binds `vault` is projects: folders on your machines, each
with a git repository and .env files kept in its vault (checkout.py):

    cm devproject init [name] [--path DIR]     # here: a project, and every .env* into its vault
    cm devproject update [project]             # git pull, then the .env files from the vault
    cm devproject clone myapp [DIR]            # another machine: the repository, then its .env files
    cm devproject secrets [project]            # its environments, and the file each is
    cm devproject secrets import [project] [-e local] [-f .env]
    cm devproject secrets export [project] [-e prod] [-f .env.prod] [--force]

A Quill with code has actions of its own, each a command, and views, which
print as text:

    cm fleet actions                   # what it can do, and what each takes
    cm fleet add-van name=Transit registration="AB 12 345"
    cm fleet log-service Transit date=2026-09-28 km=1200   # on a record: which one first
    cm fleet                           # its first screen; a view prints as text
    cm fleet --screen garage --plain   # the view's tree, as JSON

`main` sends a first word that is not one of the built-in commands here, so
`cm tasks` works without the CLI knowing, when it starts, what is installed.

Each kind of screen is a module of its own, as the TUI's are panes/kit_*:
board, grouped (a list), calendar, editor, cells (a sheet), grid, thread and timeline, with records
for what a board, a list and a calendar share, screen for what they all do,
and actions for a Quill's own code.
"""

from __future__ import annotations

from typing import Annotated

import typer

# `out`, `console` and `emit` are where every kind of screen prints, looked up
# here as it prints. The other names without a use here are what was reached
# for when quillrun was one file, and still is.
from cloudmorrow.cli.common import client, console, emit, fail, out, run  # noqa: F401
from cloudmorrow.cli.quillrun.actions import _list_actions, _press, _view
from cloudmorrow.cli.quillrun.board import _lane_named, _lanes  # noqa: F401
from cloudmorrow.cli.quillrun.cells import _act_cells
from cloudmorrow.cli.quillrun.data import _act_data
from cloudmorrow.cli.quillrun.docs import _act_docs
from cloudmorrow.cli.quillrun.editor import _act_editor
from cloudmorrow.cli.quillrun.grid import _act_grid
from cloudmorrow.cli.quillrun.history import _history
from cloudmorrow.cli.quillrun.projects import WORDS as PROJECT_WORDS
from cloudmorrow.cli.quillrun.projects import _act_projects
from cloudmorrow.cli.quillrun.records import _act_records
from cloudmorrow.cli.quillrun.screen import (  # noqa: F401
    MASK,
    Screen,
    _quill,
    _screen,
    _screen_spec,
)
from cloudmorrow.cli.quillrun.thread import _thread, space_name  # noqa: F401
from cloudmorrow.cli.quillrun.timeline import _act_timeline
from cloudmorrow.client.api import CloudmorrowClient

# A timeline's words that no other screen has; a document's export is its too.
TIMELINE_ONLY = ("cut", "trim", "rm", "frame", "export")
# A document's word that no other screen has.
DOCUMENT_ONLY = ("import",)
ACTIONS = (
    "list",
    "add",
    "show",
    "set",
    "move",
    "done",
    "undone",
    "delete",
    "groups",
    "get",
    "put",
    "edit",
    "search",
    "say",
    "history",
    *TIMELINE_ONLY,
    *DOCUMENT_ONLY,
    *PROJECT_WORDS,
)


def route(argv: list[str], commands: set[str]) -> list[str]:
    """`tasks list` → `run-quill tasks list`, when `tasks` is not a command of ours."""
    if argv and not argv[0].startswith("-") and argv[0] not in commands:
        return ["run-quill", *argv]
    return argv


def main(
    quill: Annotated[str, typer.Argument(help="The Quill's id.")],
    action: Annotated[str, typer.Argument(help=" | ".join(ACTIONS) + " | actions | one of the Quill's own")] = "list",
    args: Annotated[list[str] | None, typer.Argument(help="What the action needs.")] = None,
    screen_id: Annotated[str, typer.Option("--screen", help="Another of the Quill's screens.")] = "",
    group: Annotated[str, typer.Option("--group", "-g", help="Which board (or other group), by name or id.")] = "",
    index: Annotated[int | None, typer.Option("--index", help="Where in the lane, 0 for the top.")] = None,
    plain: Annotated[bool, typer.Option("--plain", help="JSON, for scripts.")] = False,
    reveal: Annotated[bool, typer.Option("--reveal", help="show: include a hidden field's value.")] = False,
    raw: Annotated[bool, typer.Option("--raw", help="A sheet: the cells as typed, formulas and all.")] = False,
    first: Annotated[str, typer.Option("--from", help="A calendar: the first day, as 2026-10-01 (today).")] = "",
    last: Annotated[str, typer.Option("--to", help="A calendar: the last day (a week after --from).")] = "",
    track: Annotated[str, typer.Option("--track", help="A timeline: the track, as V1.")] = "",
    at: Annotated[str | None, typer.Option("--at", help="A timeline: when, in seconds or m:ss.")] = None,
    length: Annotated[str | None, typer.Option("--length", help="A timeline: how long the file is.")] = None,
    start: Annotated[str | None, typer.Option("--start", help="A timeline's trim: the new start.")] = None,
    end: Annotated[str | None, typer.Option("--end", help="A timeline's trim: the new end.")] = None,
    out_file: Annotated[str, typer.Option("--out", "-o", help="A timeline's frame: where to save it.")] = "",
    path: Annotated[str, typer.Option("--path", help="Projects: the folder, instead of this one.")] = "",
    env: Annotated[str, typer.Option("--env", "-e", help="Projects' secrets: the environment, as local or prod.")] = "",
    file: Annotated[str, typer.Option("--file", "-f", help="Projects' secrets: the .env file.")] = "",
    force: Annotated[bool, typer.Option("--force", help="Projects: write over keys only a .env file has.")] = False,
) -> None:
    """Run ACTION on an installed Quill: one of the kit's, or one the Quill declares."""
    args = list(args or [])

    async def _run() -> None:
        _, api = client()
        async with api:
            await dispatch(
                api,
                quill,
                action,
                args,
                screen_id=screen_id,
                group=group,
                index=index,
                plain=plain,
                days=(first, last),
                reveal=reveal,
                raw=raw,
                timing={"track": track, "at": at, "length": length, "start": start, "end": end, "out": out_file},
                local={"path": path, "env": env, "file": file, "force": force, "plain": plain},
            )

    run(_run())


async def dispatch(
    api: CloudmorrowClient,
    quill: str,
    action: str,
    args: list[str],
    *,
    screen_id: str = "",
    group: str = "",
    index: int | None = None,
    plain: bool = False,
    days: tuple[str, str] = ("", ""),
    reveal: bool = False,
    raw: bool = False,
    timing: dict | None = None,
    local: dict | None = None,
) -> None:
    """One `cm <quill> …`: a Quill's own action, its view, or the kit's words for its screen."""
    found = _quill(await api.quills(), quill)
    declared = {a["id"]: a for a in found.get("actions", [])}
    shown = next((s for s in found.get("screens") or [] if s["id"] == screen_id or not screen_id), {})
    # A timeline's or a document's `export` is its screen's, whatever the action is called.
    exports = shown.get("kit") in ("timeline", "document") and action == "export"
    if action in declared and not exports:
        await _press(api, found, declared[action], args, plain)
        return
    if action == "actions":
        _list_actions(found, plain)
        return
    if action not in ACTIONS:
        words = [*ACTIONS, "actions", *declared]
        fail(f"{action!r}: {found['id']} does {', '.join(words)}")
    spec = _screen_spec(found, screen_id)
    if spec["kit"] == "data":
        # Over every datamodel the Quill has, to look at: data.py.
        await _act_data(api, found, spec, action, args, plain)
        return
    if spec["kit"] == "view":
        if action not in ("list", "show"):
            fail(f"{spec['id']} is a view: `cm {found['id']} --screen {spec['id']}` prints it")
        await _view(api, found, spec, args, plain)
        return
    screen = Screen(found, spec)
    if action in PROJECT_WORDS:
        await _act_projects(api, screen, action, args, local or {})
        return
    await _act(api, screen, action, args, group, index, plain, days, reveal, timing, raw=raw)


async def _act(
    api: CloudmorrowClient,
    screen: Screen,
    action: str,
    args: list[str],
    group: str,
    index: int | None,
    plain: bool,
    days: tuple[str, str] = ("", ""),
    reveal: bool = False,
    timing: dict | None = None,
    raw: bool = False,
) -> None:
    if action == "history":
        await _history(api, screen, args, plain)
        return
    if screen.kit == "editor":
        await _act_editor(api, screen, action, args, plain)
        return
    if screen.kit == "sheet":
        await _act_cells(api, screen, action, args, plain, raw)
        return
    if screen.kit == "document":
        await _act_docs(api, screen, action, args, plain, raw)
        return
    if screen.kit == "grid":
        await _act_grid(api, screen, action, args, plain)
        return
    if screen.kit == "thread":
        await _thread(api, screen, action, args, plain)
        return
    if screen.kit == "timeline":
        await _act_timeline(api, screen, action, args, plain, timing or {})
        return
    if action in TIMELINE_ONLY:
        fail(f"{action} is a timeline's; {screen.quill['id']} is a {screen.kit}")
    if action in DOCUMENT_ONLY:
        fail(f"{action} is a document's; {screen.quill['id']} is a {screen.kit}")
    await _act_records(api, screen, action, args, group, index, plain, days, reveal)
