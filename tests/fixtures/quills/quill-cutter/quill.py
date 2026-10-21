"""Cutter: the one button the timeline kit does not draw by itself."""

from cloudmorrow.quill import action, toast


@action("export")
def export(ctx, project, format="mp4"):
    ctx.records.patch("cutter.project", project.id, {"status": "queued", "message": f"as {format}"})
    return toast("Queued")
