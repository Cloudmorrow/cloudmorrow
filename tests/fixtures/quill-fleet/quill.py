"""Fleet: the vans, their services, and the odometer."""

import csv

from cloudmorrow.quill import action, api, hook, job, machine, respond, toast, ui, view, webhook


@view("garage")
def garage(ctx):
    vans = ctx.records.list("vehicle")
    return ui.stack(
        ui.text("Garage", style="title"),
        ui.row(ui.stat("Vans", len(vans))),
        ui.table(vans, columns=["name", ("Odometer", "fleet.odometer")], actions=["log-service"],
                 empty="No vans yet."),
        ui.button("Add a van", action="add-van", tone="primary"),
    )


@action("log_service")
def log_service(ctx, vehicle, date, km, note=None):
    ctx.records.create("fleet.visit", vehicle=vehicle.id, date=date, km=km, note=note or "")
    return toast(f"Logged {vehicle['name']} at {km} km")


@action("add_van")
def add_van(ctx, name, registration=None):
    van = ctx.records.create("vehicle", name=name, registration=registration or "")
    print("added", van.id, "for", ctx.user.username)
    return [toast(f"Added {name}"), {"effect": "open", "model": "vehicle", "id": van.id}]


@action
def peek(ctx):
    return toast(ctx.secret("TRACKER_KEY")[:3] + "…")


@action
def reach_out(ctx):
    ctx.records.list("contact")


@hook
def visit_logged(ctx, change):
    visit = change.record
    van = ctx.records.get("vehicle", visit["vehicle"])
    if (van.get("fleet.odometer") or 0) < visit["km"]:
        ctx.records.patch("vehicle", van.id, {"fleet.odometer": visit["km"]})


@job
def nightly(ctx):
    ctx.log("checked", len(ctx.records.list("vehicle")), "vans")


@webhook
def tracker_ping(ctx, request):
    body = request.json()
    for van in ctx.records.list("vehicle", registration=body["registration"]):
        ctx.records.patch("vehicle", van.id, {"fleet.odometer": body["km"]})
        return respond(json={"updated": van.id})
    return respond(json={"updated": None}, status=404)


@api
def summary(ctx, request):
    vans = ctx.records.list("vehicle")
    return {"vans": len(vans), "asked_by": request.user}


@machine
def import_exports(ctx):
    folder = ctx.folder("exports")
    made = 0
    for path in sorted(folder.glob("*.csv")):
        with open(path, newline="") as handle:
            for row in csv.DictReader(handle):
                vans = ctx.records.list("vehicle", registration=row["registration"])
                if vans:
                    ctx.records.create("fleet.visit", vehicle=vans[0].id, date=row["date"], km=int(row["km"]))
                    made += 1
    return {"made": made}
