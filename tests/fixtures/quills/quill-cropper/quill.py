"""Cropper: the buttons the photo kit does not draw by itself."""

from cloudmorrow.quill import action, toast


@action("export")
def export(ctx, edit, format="jpeg"):
    ctx.records.patch("cropper.edit", edit.id, {"status": "queued", "message": f"as {format}"})
    return toast("Queued")


@action("save")
def save(ctx, edit, overwrite=False, name=""):
    how = "over the photo" if overwrite else f"as {name or edit['name']}"
    ctx.records.patch("cropper.edit", edit.id, {"status": "queued", "message": how})
    return toast("Saving")
