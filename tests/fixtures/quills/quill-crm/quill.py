"""CRM: what the lists and the pipeline cannot do by being dragged.

The data, the board, the lists and the first pipeline are declared in
quill.toml. This is the code behind the sales page, the buttons on a deal,
an organisation, a person, an activity and a stage, and the hook that keeps
a deal's status in step with the stage it is in.
"""

import datetime as dt

from cloudmorrow.quill import action, error, hook, open, toast, ui, view

DEAL, STAGE, BOOK, ACTIVITY = "deal", "stage", "book", "activity"
KINDS = {"todo": "To-do", "call": "Call", "meeting": "Meeting", "email": "Email"}


# -- the stages of a book ------------------------------------------------------------
def stages_of(ctx, book_id):
    """A book's stages, in the pipeline's order."""
    return sorted(ctx.records.list(STAGE, book=book_id), key=lambda s: s.position)


def first_open(stages):
    return next((s for s in stages if s.get("outcome") == "open"), stages[0] if stages else None)


def stage_for(ctx, book_id, outcome):
    return next((s for s in stages_of(ctx, book_id) if s.get("outcome") == outcome), None)


def _moment(ctx):
    return ctx.now().replace(microsecond=0).isoformat()


# -- a deal follows its stage ----------------------------------------------------------
@hook
def deal_moved(ctx, change):
    """Open, won or lost, and when it closed: read off the stage.

    Set the other way round — Won pressed on the deal's sheet — it goes to
    the book's stage for that, and the two never disagree.
    """
    deal = change.record
    if change.action == "changed" and "stage" not in change.changed:
        if "status" in change.changed:
            _to_status(ctx, deal)
        return
    fields = {}
    stage = None
    if deal.get("stage"):
        try:
            stage = ctx.records.get(STAGE, deal["stage"])
        except Exception:  # a stage since deleted: the deal is back where it starts
            stage = None
    if stage is None and change.action == "created":
        stage = first_open(stages_of(ctx, deal["book"]))
        if stage is not None:
            fields["stage"] = stage.id
    outcome = stage.get("outcome") if stage is not None else "open"
    if deal.get("status") != outcome:
        fields["status"] = outcome
    if outcome == "open" and deal.get("closed_at"):
        fields["closed_at"] = None
    elif outcome != "open" and (deal.get("status") != outcome or not deal.get("closed_at")):
        fields["closed_at"] = _moment(ctx)
    if change.action == "created" and not deal.get("currency"):
        book = ctx.records.get(BOOK, deal["book"])
        if book.get("currency"):
            fields["currency"] = book["currency"]
    if fields:
        ctx.records.patch(DEAL, deal.id, fields)


def _to_status(ctx, deal):
    status = deal.get("status") or "open"
    stages = stages_of(ctx, deal["book"])
    current = next((s for s in stages if s.id == deal.get("stage")), None)
    if current is not None and current.get("outcome") == status:
        return
    target = (
        first_open(stages)
        if status == "open"
        else next((s for s in stages if s.get("outcome") == status), None)
    )
    fields = {"closed_at": None if status == "open" else _moment(ctx)}
    if target is not None:
        fields["stage"] = target.id
    ctx.records.move(DEAL, deal.id, fields)


# -- deals ----------------------------------------------------------------------------
@action("new_deal")
def new_deal(ctx, organisation, title, value=None, expected_close=None):
    book = organisation.get("book")
    if not book:
        return error("Put the organisation in a book first; a pipeline belongs to a book")
    stage = first_open(stages_of(ctx, book))
    deal = ctx.records.create(
        DEAL,
        book=book,
        title=title,
        organisation=organisation.id,
        stage=stage.id if stage else None,
        value=value,
        expected_close=expected_close,
    )
    return [toast(f"New deal: {title}"), open(deal)]


def _close(ctx, deal, outcome, note=""):
    stage = stage_for(ctx, deal["book"], outcome)
    if stage is None:
        return error(f"This book's pipeline has no {outcome} stage; add one with outcome {outcome}")
    fields = {"stage": stage.id}
    if note:
        fields["notes"] = (
            (deal.get("notes") or "").rstrip() + f"\n\n**{stage['name']}:** {note}"
        ).strip()
    ctx.records.move(DEAL, deal.id, fields)
    return toast(f"{deal['title']}: {stage['name']}")


@action
def won(ctx, deal):
    return _close(ctx, deal, "won")


@action
def lost(ctx, deal, reason=None):
    return _close(ctx, deal, "lost", (reason or "").strip())


# -- activities -----------------------------------------------------------------------
@action("follow_up")
def follow_up(ctx, record, title, kind="call", due=None):
    """Planned from a deal, an organisation or a person: linked to it, and to what it is linked to."""
    links = {}
    if record.model == DEAL:
        links = {
            "deal": record.id,
            "organisation": record.get("organisation"),
            "contact": record.get("contact"),
        }
    elif record.model == "organisation":
        links = {"organisation": record.id}
    elif record.model == "contact":
        links = {"contact": record.id, "organisation": record.get("organisation")}
    made = ctx.records.create(
        ACTIVITY,
        book=record.get("book"),
        title=title,
        kind=kind,
        due=due,
        **{k: v for k, v in links.items() if v},
    )
    return [toast(f"{KINDS.get(kind, 'To-do')} planned: {title}"), open(made)]


@action
def complete(ctx, activity):
    ctx.records.patch(ACTIVITY, activity.id, {"done": True})
    return toast(f"Done: {activity['title']}")


# -- the pipeline's stages --------------------------------------------------------------
@action("add_stage")
def add_stage(ctx, book, name, probability=None):
    """A new open stage goes after the last open one, so Won and Lost stay at the end."""
    stages = stages_of(ctx, book.id)
    open_ones = [s for s in stages if s.get("outcome") == "open"]
    index = (stages.index(open_ones[-1]) + 1) if open_ones else 0
    ctx.records.create(STAGE, book=book.id, name=name, probability=probability, index=index)
    return toast(f"Added the stage {name}")


def _shift(ctx, stage, delta):
    stages = stages_of(ctx, stage["book"])
    where = next(i for i, s in enumerate(stages) if s.id == stage.id)
    to = max(0, min(len(stages) - 1, where + delta))
    if to == where:
        return toast(f"{stage['name']} is already {'first' if delta < 0 else 'last'}")
    ctx.records.move(STAGE, stage.id, {}, index=to)
    return toast(f"Moved {stage['name']} {'earlier' if delta < 0 else 'later'}")


@action("stage_earlier")
def stage_earlier(ctx, stage):
    return _shift(ctx, stage, -1)


@action("stage_later")
def stage_later(ctx, stage):
    return _shift(ctx, stage, 1)


# -- the sales page ---------------------------------------------------------------------
def _number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def money(amounts):
    """{"EUR": 1200.0, "USD": 50.0} -> "EUR 1,200 · USD 50"."""
    said = [f"{cur} {amount:,.0f}".strip() for cur, amount in sorted(amounts.items()) if amount]
    return " · ".join(said) or "0"


def _add(amounts, currency, amount):
    amounts[currency or ""] = amounts.get(currency or "", 0.0) + amount


def _day(value):
    return str(value or "")[:10]


@view("sales")
def sales(ctx):
    now = ctx.now()
    today = now.date().isoformat()
    week = (now.date() + dt.timedelta(days=7)).isoformat()
    month = today[:7]
    books = ctx.records.list(BOOK)
    stages = {s.id: s for s in ctx.records.list(STAGE)}
    deals = ctx.records.list(DEAL)

    open_deals = [d for d in deals if d.get("status", "open") == "open"]
    pipeline, weighted, won = {}, {}, {}
    for deal in open_deals:
        value = _number(deal.get("value"))
        chance = _number((stages.get(deal.get("stage")) or {}).get("probability"))
        _add(pipeline, deal.get("currency"), value)
        _add(weighted, deal.get("currency"), value * chance / 100)
    won_now = [
        d for d in deals if d.get("status") == "won" and _day(d.get("closed_at"))[:7] == month
    ]
    for deal in won_now:
        _add(won, deal.get("currency"), _number(deal.get("value")))

    todo = [a for a in ctx.records.list(ACTIVITY) if not a.get("done")]
    overdue = [a for a in todo if a.get("due") and _day(a["due"]) < today]
    next_up = sorted(
        (a for a in todo if not a.get("due") or _day(a["due"]) <= week),
        key=lambda a: (not a.get("due"), str(a.get("due") or "")),
    )[:10]
    closing = sorted(
        (d for d in open_deals if d.get("expected_close")),
        key=lambda d: str(d["expected_close"]),
    )[:10]

    return ui.stack(
        ui.row(
            ui.stat("Open deals", len(open_deals)),
            ui.stat("In the pipeline", money(pipeline), hint=f"weighted {money(weighted)}"),
            ui.stat(
                "Won this month",
                money(won),
                hint=f"{len(won_now)} deal{'s' if len(won_now) != 1 else ''}",
                tone="good" if won_now else "neutral",
            ),
            ui.stat("Overdue", len(overdue), tone="warn" if overdue else "neutral"),
        ),
        ui.text("Next up", style="title"),
        ui.table(
            next_up,
            columns=[
                "title",
                ("Kind", "kind"),
                ("Due", "due"),
                ("With", "organisation"),
                ("Deal", "deal"),
            ],
            actions=["complete"],
            empty="Nothing planned for the coming week. Plan a follow-up from a deal, an organisation or a person.",
        ),
        ui.text("Closing soon", style="title"),
        ui.table(
            closing,
            columns=[
                "title",
                ("With", "organisation"),
                ("Stage", "stage"),
                ("Value", "value"),
                ("Closes", "expected_close"),
            ],
            actions=["won", "lost", "follow-up"],
            empty="No open deal has a date it is expected to close.",
        ),
        ui.text("Pipelines", style="title"),
        ui.text(
            "Each book has its own stages, in order. Open one to rename it, weigh it or delete it.",
            style="muted",
        ),
        [
            ui.stack(
                ui.text(book["name"], style="subtitle"),
                ui.table(
                    [
                        s
                        for s in sorted(stages.values(), key=lambda s: s.position)
                        if s.get("book") == book.id
                    ],
                    columns=["name", ("Chance (%)", "probability"), ("Outcome", "outcome")],
                    actions=["stage-earlier", "stage-later"],
                    empty="No stages yet.",
                ),
                ui.button("Add a stage", action="add-stage", record=book),
                gap="small",
            )
            for book in books
        ]
        or ui.empty("No book yet. Start one from the chips on Organisations or Pipeline."),
    )
