"""Budget: envelopes, and what went into each. Written against its own names."""

from cloudmorrow.quill import action, api, hook, job, machine, respond, toast, ui, view, webhook


@view("overview")
def overview(ctx):
    envelopes = ctx.records.list("budget.envelope")
    return ui.stack(
        ui.text(f"{ctx.user.username}'s budget", style="title"),
        ui.row(ui.stat("Envelopes", len(envelopes))),
        ui.table(envelopes, columns=["name", "total"], actions=["spend"], empty="No envelopes yet."),
        ui.button("Add an envelope", action="add-envelope", tone="primary"),
    )


@action("add_envelope")
def add_envelope(ctx, name):
    made = ctx.records.create("budget.envelope", name=name, total=0)
    assert made.model == "budget.envelope", made.model
    return [toast(f"Added {name}"), {"effect": "open", "model": "budget.envelope", "id": made.id}]


@action
def spend(ctx, envelope, amount, note=None):
    ctx.records.create("budget.entry", envelope=envelope.id, amount=amount, note=note or "")
    return toast(f"Spent {amount} from {envelope['name']}")


@hook
def entry_made(ctx, change):
    entry = change.record
    assert entry.model == "budget.entry", entry.model
    pot = ctx.records.get("budget.envelope", entry["envelope"])
    ctx.records.patch("budget.envelope", pot.id, {"total": (pot.get("total") or 0) + entry["amount"]})


@job
def nightly(ctx):
    ctx.log("envelopes:", len(ctx.records.list("budget.envelope")))


@webhook
def bank_ping(ctx, request):
    body = request.json()
    pots = ctx.records.list("budget.envelope", name=body["envelope"])
    if not pots:
        return respond(json={"updated": None}, status=404)
    ctx.records.create("budget.entry", envelope=pots[0].id, amount=body["amount"], note="from the bank")
    return respond(json={"updated": pots[0].id})


@api
def summary(ctx, request):
    return {"envelopes": len(ctx.records.list("budget.envelope")), "asked_by": request.user}


@machine
def import_statements(ctx):
    return {"files": len(list(ctx.folder("statements").glob("*.csv")))}
