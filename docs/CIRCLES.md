# Circles: who may use which data

A server is one household, one company or one institution, and not
everybody on it should reach everything. The children may read the family
calendar but not change it, and never see the budget. The warehouse uses
the fleet but not the customers. A **circle** is how that is said: a named
set of people — Parents, Kids, Sales, Warehouse — and, for each kind of
data, what they may do with it.

Access is about data, and only data. A Quill has no rights of its own to
give or withhold: it does what the data under it lets the person do. A
tasks board over tasks you may only read is a board you look at. A screen
over data you may not reach is not there. A Quill with nothing left is
not on your phone at all.

## Two questions, kept apart

1. **Which kinds of data may you use?** Your circles decide: `write`,
   `read`, or nothing, per datamodel.
2. **Which records of them are yours to see?** The scope decides, as it
   always has: your own, the spaces you are in, and what is public.

A circle sets the ceiling and the scope picks the records beneath it. A
Parents circle with `write` on `expense` does not let a parent read a
child's personal expenses: personal is personal, for administrators too.
Nothing here widens what anybody sees; everything here narrows it.

## The words

| word | what it is |
| --- | --- |
| **circle** | A named set of people on the server, and what they may do with each datamodel. `Parents`, `Kids`, `Sales`. |
| **access** | What a circle gives on a datamodel: `write` (see, make, change, delete), `read` (see), or nothing. |
| **rule** | One line of a circle: a datamodel and an access. `*` is every datamodel, including ones installed later. |
| **own rules** | Rules one person has beside their circles, the same three words: the one person who needs the budget without a circle made for them. |
| **your access** | The most any of your circles, or your own rules, gives, per datamodel. |
| **default circle** | Where a new account goes. |

## The rules

1. **Circles only ever give.** Your access to a datamodel is the most any
   of your circles, or your own rules, gives. There is no deny: children
   are not given less, parents are given more. "Why can't I see this?"
   always has one answer — nothing of yours has it.
2. **A named rule beats `*`.** Inside one circle, `task = read` and
   `* = write` means read on tasks and write on everything else. Between
   circles, rule 1 holds.
3. **In no circle is no data.** Somebody in no circle can sign in and
   reaches nothing. The administration screens say so beside their name.
4. **Everybody, administrators too.** Being an administrator is about
   running the server — accounts, Quills, circles — not about data. An
   administrator who wants the budget is in a circle that has it, which
   they can arrange, visibly.
5. **One gate.** The check every read and write already passes — this
   principal, this action, this datamodel — asks the person's access first.
   A Quill's service and an assistant acting for somebody reach at most
   what that person may; an assistant never reaches `secret`, whatever the
   circles say.
6. **Refused looks like absent.** A datamodel you may not read answers 404
   on its records and is missing from `GET /api/datamodels`, the way a
   record you cannot see is missing today. Writing where you may only read
   answers 403, because you can see it is there.

## What a Quill does with it

The client asks `GET /api/quills` and draws what it gets. The server has
already fitted every Quill to the person asking:

- **Each datamodel carries your `access`**: `"write"` or `"read"`. A
  datamodel you have no access to is left out of `models`.
- **Fields go with their data.** A link field to a datamodel you cannot
  read is left out of the datamodel as you are sent it, so a task's
  *assignee* is not a picker of contacts you may not see. The value stays
  on the record, untouched, for whoever may.
- **Screens go with their data.** A screen is left out when you cannot read
  its datamodel, or the space or group it is drawn within (the calendars of
  a calendar screen, the boards of a board).
- **Read is drawn as read.** On a datamodel you may only read, every
  surface draws the screen without its writing: no new, no edit, no
  delete, no dragging between lanes, no ticking, no composer in a thread,
  no uploads in a grid, and the editor opens its pages read-only. It is
  the same screen, looked at.
- **A Quill with no screens left is not yours.** It comes as
  `"available": false` and draws no tab, the same as one you switched off.
  Its commands on the command line and its tools for an assistant go with
  it.

Access on a space is managing spaces: making a calendar, adding people
to a channel. Access on what is in it is writing there. `calendar = read`
with `event = write` is somebody who puts events on the family calendar
but does not make calendars.

## Setting it up

A fresh server has one circle, **Members**, with `* = write`, and it is the
default: everybody is in it and everybody has everything, which is what a
server without circles has always been. An upgraded server gets the same,
with every existing account in it, so nothing changes until an
administrator changes it.

A family, then:

| circle | rules | people |
| --- | --- | --- |
| Parents | `* = write` | mum, dad |
| Kids | `task = write`, `board = read`, `event = read`, `calendar = read`, `thread = write`, `message = write` | the children |

…and Members deleted, or kept for the parents and emptied of the children.
A company: `Everyone` with the shared things, `Sales` with `contact` and
`deal`, `Warehouse` with `vehicle` and `service_visit`.

The screens set rules by **domain** — Tasks, Calendars, Messaging, Customers,
Fleet — because that is how people think of their data, and store them per
datamodel, because that is what the gate checks. A Quill that introduces a
datamodel asks on its install sheet which circles get it; `*` rules get it
anyway.

## The API

| call | what it does |
| --- | --- |
| `GET /api/me/access` | your access: `{"task": "write", "event": "read", …}`, every datamodel you reach, your circles, and your own rules |
| `GET /api/access/{username}` | one person's access, their circles and their own rules (administrators) |
| `PUT /api/access/{username}` | `{"rules": {…}}`: their own rules, replaced whole |
| `PUT /api/access/{username}/{model}` | `{"access": "read"}`: one rule of their own, the others kept; `none` on `*` removes the `*` line |
| `DELETE /api/access/{username}/{model}` | take one of their own rules away: the datamodel follows their circles again |
| `GET /api/circles` | every circle, with its rules and its people (administrators) |
| `POST /api/circles` | `{"name": …, "rules": {…}, "members": […]}`: make one (administrators) |
| `PATCH /api/circles/{id}` | change its name, its rules (replaced whole), or make it the default |
| `PUT /api/circles/{id}/rules/{model}` | `{"access": "write"}`: set one rule, the others kept; `none` on `*` removes the `*` line |
| `DELETE /api/circles/{id}` | delete it; its people keep their other circles |
| `PUT /api/circles/{id}/members/{username}` | put somebody in it |
| `DELETE /api/circles/{id}/members/{username}` | take them out |

On the command line: `cm circle list`, `cm circle add Kids`, `cm circle
rule Kids task write`, `cm circle rule Kids expense none`, `cm circle
join Kids alice`, `cm circle leave Kids alice`, `cm circle default Kids`,
`cm circle delete Kids`, and `cm access` for your own. An administrator's
`cm access alice` is hers, `cm access alice expense read` gives her a rule
of her own, and `cm access alice expense -` takes it away. On the screens,
a person's own rules are on their account, under *Data of their own*.

## Storage

In the accounts database, beside `users`:

```
circles(id, name, is_default, created_at)
circle_members(circle_id, username)
circle_rules(circle_id, model, access)   -- model is a datamodel id or '*'
person_rules(username, model, access)    -- one person's own, the same shape
```

Plain, not sealed: who is in which circle is what the server needs to
answer every request, and it is no more secret than the list of accounts.

## Not yet

- **Sharing a space with a circle.** A shared space's people are named one
  by one today. Sharing the family calendar with *Kids*, so the next child
  is in it the day they get an account, is next. Fileshares do this
  already: a share is shared with circles as well as people, and follows
  the circle as it changes (MANUAL.md, *Fileshares*).
- **Guardians.** A parent seeing a child's personal records is a real
  wish, and it must be a visible link the child can see — never a power an
  administrator has quietly. Not in this.
- **Fields.** Access is per datamodel. Hiding a contact's phone number
  from some people but not the contact is a later, finer rule.
- **Time.** No screen time, no "until Friday". Rules are about data.
- **Circle managers.** Only administrators change circles, for now.
