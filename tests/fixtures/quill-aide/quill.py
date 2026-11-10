"""Aide: a fixture whose code has an assistant's tools, as the person."""

from cloudmorrow.quill import action, error, toast, ui, view

SETTINGS = "aide.settings"


@view("aide")
def aide(ctx):
    names = [t["name"] for t in ctx.assistant.tools()]
    return ui.stack(ui.text(f"{len(names)} tools"), ui.text(", ".join(names), style="muted"))


@action("tools")
def tools(ctx):
    return toast(", ".join(t["name"] for t in ctx.assistant.tools()))


@action("count")
def count(ctx, model):
    answer = ctx.assistant.call("list_records", {"model": model})
    if not answer["ok"]:
        return error(answer["text"])
    return toast(str(len(answer["data"]["records"])))


@action("build")
def build(ctx, manifest):
    answer = ctx.assistant.call("quill_dev_install", {"manifest": manifest, "mine": True})
    return error(answer["text"]) if not answer["ok"] else toast(answer["data"]["whose"])


@action("connect")
def connect(ctx, key):
    found = ctx.records.list(SETTINGS)
    if found:
        ctx.records.patch(SETTINGS, found[0].id, key=key, status="set")
    else:
        ctx.records.create(SETTINGS, scope="public", key=key, status="set")
    return toast("set")


@action("peek")
def peek(ctx):
    found = ctx.records.list(SETTINGS)
    if not found:
        return error("no key")
    return toast(str(ctx.records.get(SETTINGS, found[0].id).get("key")))
