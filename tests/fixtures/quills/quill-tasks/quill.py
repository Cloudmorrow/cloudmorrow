"""Tasks: what the lanes cannot do by dragging.

Everything else about Tasks is declared in quill.toml — the board, the
lanes, the week Done keeps a task, the first board. This is the code behind
its two actions, run as whoever presses them.
"""

from cloudmorrow.quill import action, open, toast

TASK = "task"


@action
def duplicate(ctx, task):
    copy = ctx.records.create(
        TASK, board=task["board"], title=task["title"], body=task.get("body") or "", lane="todo",
        due=task.get("due"),
    )
    return [toast(f"Duplicated {task['title']}"), open(copy)]


@action("clear_done")
def clear_done(ctx, board):
    gone = 0
    for task in ctx.records.list(TASK, board=board.id, lane="done"):
        gone += ctx.records.delete(TASK, task.id)
    if not gone:
        return toast("Nothing is done on this board yet")
    return toast(f"Cleared {gone} finished task{'s' if gone != 1 else ''}")
