"""Leave: asked for, asked of the team lead, answered on the record."""

from cloudmorrow.quill import action, hook, result, toast


@action
def request(ctx, employment, what, starts, ends):
    leave = ctx.records.create("leave", employment=employment, what=what, starts=starts, ends=ends)
    asked = ctx.approvals.ask(leave, role="team_lead", question=f"Approve {what} ({starts} to {ends})?")
    return [toast(f"Asked the team lead about {what}"), result(leave=leave.id, approval=asked.id)]


@action("who_approves")
def who_approves(ctx, leave):
    people = ctx.people(role="team_lead")
    return [toast(", ".join(people) or "nobody yet"), result(people=people, mine=ctx.user.roles)]


@hook
def answered(ctx, change):
    approval = change.record
    if approval["about_model"] != "leave" or approval["status"] not in ("approved", "declined"):
        return
    ctx.records.patch("leave", approval["about"], {"status": approval["status"]})
