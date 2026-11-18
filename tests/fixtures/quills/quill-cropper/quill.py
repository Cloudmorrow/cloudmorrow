"""Cropper: the one button the photo kit does not draw by itself."""

from cloudmorrow.quill import action, toast


@action("export")
def export(ctx, edit, format="jpeg"):
    ctx.records.patch("cropper.edit", edit.id, {"status": "queued", "message": f"as {format}"})
    return toast("Queued")
