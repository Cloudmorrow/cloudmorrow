---
name: quill-automation
description: Make a Quill do things by itself — hooks when records change, jobs on a clock, webhooks from outside services, APIs for other programs, fetching from the internet and reading the person's secrets. Use for "when X happens, do Y", "every night", "when Stripe calls", "call this API".
---

# Code that runs by itself

All of it is declared in quill.toml and written in quill.py, and all of it
runs in the sandbox, reaching only what the manifest declares.

## Hooks: when a record changes

```toml
[[hooks]]
on = "fleet.visit"
when = "created"            # created, changed, deleted, or a list; all three by default
fields = ["km"]             # optional, for "changed": only when one of these changed
handler = "visit_logged"
```

```python
@hook
def visit_logged(ctx, change):
    visit = change.record               # change.action, change.before (old fields), change.changed
    van = ctx.records.get("vehicle", visit["vehicle"])
    ctx.records.patch("vehicle", van.id, {"fleet.odometer": visit["km"]})
```

A hook runs as whoever made the change, shortly after it, never in the way
of the write. It is not told about what its own hooks wrote, and chains stop
three deep: do not build ping-pong between two Quills.

## Jobs: on a clock

```toml
[[jobs]]
id = "nightly"
action = "call"
handler = "nightly"
every = "1d"                # 15m, 1h, 1d, 2w
```

A `call` job runs as the administrator who installed the Quill, never twice at once.
For plain expiry use the declarative `action = "expire"` instead — no code.

## Webhooks: something outside tells you something

```toml
[[webhooks]]
id = "stripe"
handler = "stripe_paid"     # or `model` + `map` to make a record with no code at all
signature = "Stripe-Signature"   # optional: an HMAC of the body instead of the token
```

```python
@webhook
def stripe_paid(ctx, request):          # request.json(), .text, .headers, .query
    ...
    return respond(json={"ok": True})   # or nothing: 204
```

It is at `POST /hooks/<quill>/<path>` with the webhook's secret, which an
administrator copies from Administration → Quills.

## APIs: for other programs

```toml
[[apis]]
id = "summary"
handler = "summary"         # GET/POST/… /api/q/<quill>/<path>, for anybody signed in
```

```python
@api
def summary(ctx, request):              # request.method, .path, .user (who asked)
    return {"vans": len(ctx.records.list("vehicle"))}   # a dict is sent as JSON
```

## The internet, and secrets

```toml
[[fetch]]
host = "api.example-tracker.com"        # or *.example.com; https only
why = "to read each van's odometer"

[[secrets]]
key = "TRACKER_KEY"
why = "to sign in to the tracker"
```

```python
answer = ctx.fetch("https://api.example-tracker.com/vans",
                   headers={"Authorization": "Bearer " + ctx.secret("TRACKER_KEY")})
if answer.ok:
    data = answer.json()
```

A secret comes from the person's own vault (`cm secret set TRACKER_KEY`),
and never when an assistant pressed the action.

## Test it

`q.run_job("nightly")`, `q.webhook("stripe", json={...})`, `q.api("summary")`,
`q.fetch.add("https://api.example-tracker.com/vans", json=[...])`, `q.secret("TRACKER_KEY", "x")`,
and `q.log` for what the code printed. A hook runs by itself in the harness
when a record changes (`q.seed`, `q.change`, `q.act`).
