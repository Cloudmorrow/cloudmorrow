"""{{name}}: the code behind quill.toml's views and actions.

Every handler here is named in quill.toml, and runs in a sandbox on the
person's server, as the person using it: `ctx.records` reaches only the
datamodels the manifest declares, and only the records they may see.
"""

from cloudmorrow.quill import action, toast, ui, view

ITEM = "{{id}}.item"


@view("overview")
def overview(ctx):
    items = ctx.records.list(ITEM)
    left = [item for item in items if not item.get("done")]
    return ui.stack(
        ui.row(
            ui.stat("To do", len(left)),
            ui.stat("Done", len(items) - len(left), tone="good"),
        ),
        ui.table(left, columns=["name"], empty="Nothing to do."),
        ui.row(
            ui.button("Add an item", action="add", tone="primary"),
            len(items) > len(left) and ui.button("Clear what is done", action="clear-done"),
        ),
    )


@action("add")
def add(ctx, name):
    ctx.records.create(ITEM, name=name)
    return toast(f"Added {name}")


@action("clear_done")
def clear_done(ctx):
    gone = 0
    for item in ctx.records.list(ITEM, done=True):
        gone += ctx.records.delete(ITEM, item.id)
    return toast(f"Cleared {gone}" if gone else "Nothing was done yet")
