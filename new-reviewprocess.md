# The new review process for Quills

A note from 11 October 2026, before the work starts. What is decided, how it
will work, and what is needed to finish it. Delete it when it is built and
the docs say all of this.

## Decided

- **Our team is the Cloudmorrow GitHub organisation.** A Quill whose
  repository is `github.com/Cloudmorrow/quill-*` is ours. A release of it
  reaches the catalog with no review and no further step. The template
  (`quill-template`) is excluded.
- **Everybody else's Quills are reviewed on GitHub**, once per release, as a
  pull request on `Cloudmorrow/quill-catalog`. Not on cloudmorrow.com: the
  site's own review queue (`reviews.py`, `/cmadmin/reviews`) stays dormant
  behind the publishing switch and nothing new is built on it.
- **`catalog.toml` on GitHub stays the one thing servers read**, and one
  workflow is its only writer. Nobody edits refs by hand any more. The
  `foundation` flag and the categories stay hand edits, since they are
  product decisions.

## Why GitHub, not the website

- The catalog repository is already the audit trail: every release a server
  can install is a commit there. Reviewing elsewhere and copying the result
  in gives two histories, and makes the website a dependency for other
  people's releases.
- The reviewer needs the Quill, not a form. On GitHub they are already in
  the repository at the tag, and the catalog's check can post the install
  sheet as a comment, because it computes it anyway.
- Everyone submitting has a GitHub account: their Quill is a GitHub
  repository made from the template.
- Less to maintain. The website keeps pages, stars and listings mirrored
  from the catalog, as it does today.

## How it works

One scheduled workflow in `quill-catalog`, every 15 minutes and on demand
(Run workflow), does the same job for every Quill and differs only in the
last step:

1. It finds the newest release of every `Cloudmorrow/quill-*` repository,
   of `Cloudmorrow/datamodels`, and of every other repository listed in
   `catalog.toml`.
2. For each release newer than the pin, it works out the catalog as it
   should be — a new Cloudmorrow Quill is added, with its name and summary
   from `quill.toml` at that release; an existing one is bumped — and runs
   the existing check (every Quill fetched at its pin, planned against the
   pinned datamodels, as a server would before installing).
3. **Cloudmorrow Quills and the datamodels:** checked out, committed to
   `main`. The datamodels are bumped only when every Quill still checks out
   against the new release; otherwise the pin stays and the run names the
   Quill that breaks.
4. **Everyone else's listed Quills:** a pull request, opened by the
   workflow, with the check result and the install sheet in its body. One
   of us merges it, or closes it. Submitters may open that pull request
   themselves; the result is the same.
5. **A new Quill from someone else:** a pull request from its author adding
   one `[[quills]]` block to `catalog.toml`, with a pull request template
   that carries the block. The check runs on it as it does today.

A `CODEOWNERS` file names the team, so every pull request that is not the
workflow's own commit asks us for a review. No branch protection is needed
for the gating: outsiders have no write access to the catalog, and only
the team can merge. (If `main` is ever protected, the workflow's commits
need a bypass, which is a repository setting.)

Pull requests opened with the workflow's own token do not trigger the pull
request check, so the workflow runs the check itself and puts the result in
the body. Pull requests opened by people run the check as now.

The catalog's check parses a Quill's Python with `ast` and never runs it, so
running it on a stranger's release in CI is safe.

## The same release flow in every Quill

Every Cloudmorrow Quill and the template get the release workflow
`quill-files` has: a pushed tag, a release made on github.com, or Run
workflow in the Actions tab, which checks and tests `main`, tags it with
`quill.toml`'s version and publishes. The template carries it, so every new
Quill, ours or someone else's, releases the same way. The only difference
for others is that the catalog waits for a review.

The core and the datamodels already release from the Actions tab too
(`Release` in `Cloudmorrow/cloudmorrow`, `release` in
`Cloudmorrow/datamodels`).

## What changes where

| where | what |
| --- | --- |
| `Cloudmorrow/quill-catalog` | the scheduled workflow (the only writer of `catalog.toml`), `CODEOWNERS`, a pull request template with the `[[quills]]` block, and a README that says how to submit and what happens then |
| `Cloudmorrow/quill-notes`, `-tasks`, `-calendar`, `-chat`, `-secrets`, `-crm`, `-template` | the same `release.yml` as `quill-files`, and the publishing skill text |
| `Cloudmorrow/cloudmorrow` | `docs/QUILLS.md` and the Quill reference: how a Quill is released and how the catalog follows |
| `Cloudmorrow/cloudmorrow-web` | the publish page says how to submit on GitHub and what the review is; the listings keep following the catalog |

## What is needed to finish

- The six Quill repositories above attached to the session that does the
  work (a prompt to approve for each). The catalog automation does not
  depend on this; it reads their releases from GitHub either way.
- A deploy of cloudmorrow.com after its pull request is merged
  (`make deploy WHAT=website` from a machine with the SSH key), or a deploy
  workflow in `cloudmorrow-web` with the key in a repository secret, after
  which the deploy can run from Actions too.

Nothing else: no tokens, no branch protection, no website code beyond the
page text.

## Order of work

1. The catalog workflow, `CODEOWNERS`, the template and the README; run the
   workflow and read its log before calling it done.
2. The core docs and the website page.
3. The release workflow in each Quill and the template.
