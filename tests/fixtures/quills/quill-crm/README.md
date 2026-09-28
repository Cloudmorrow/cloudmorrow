# CRM

A Quill for [Cloudmorrow](https://github.com/Cloudmorrow/cloudmorrow): the
customers a company keeps — organisations, the people at them, a pipeline
of deals, and what to do next — shared by everybody who works with them.

- **Books.** Everything is kept in a book. There is one everybody on the
  server shares from the start, *Customers*; make more for a team (shared,
  with the people you add) or for yourself.
- **Organisations and people**, with how to reach them, what they do and
  where each organisation is on its way to being a customer (Lead,
  Prospect, Customer, Partner, Former customer).
- **A pipeline of deals.** Every book starts with Lead, Qualified,
  Proposal, Negotiation, Won and Lost. Drag a deal from stage to stage; the
  circle on a card wins it. Add, rename, reorder and weigh the stages by the
  chance of winning — each book has its own.
- **Activities**: calls, meetings, emails and to-dos, with when they are
  due, linked to the deal, organisation or person they are about, and
  ticked off when done.
- **Sales**, the first tab: open deals, what the pipeline is worth (and
  worth weighted by each stage's chance), what was won this month, what is
  overdue, what is next and what is closing soon.

## What it adds to your Cloudmorrow

| | |
| --- | --- |
| Datamodels | uses the foundational `book`, `organisation`, `contact`, `stage`, `deal` and `activity` (domain *Customers (CRM)*); extends `organisation` with `crm.status` |
| Screens | Sales (a view), Pipeline (a board), Organisations, People and Activities (lists) — on the phone, the web app, the terminal, `cm crm`, and to your assistant |
| Actions | New deal, Won, Lost, Plan a follow-up, Done, Add a stage, Move earlier, Move later |
| Hooks | `deal_moved`: a deal's status (open, won, lost) and when it closed follow its stage, and the other way round |
| Datasets | `customers`: one book for everybody, once; `pipeline`: the six stages, in every book that has none |
| Services, webhooks, APIs | none |

## Working on it

See [CLAUDE.md](CLAUDE.md). In short: `cm quill check`, `cm quill test`
(and `--sandbox`), then `cm quill dev --local`.

## Licence

AGPL-3.0-or-later.
