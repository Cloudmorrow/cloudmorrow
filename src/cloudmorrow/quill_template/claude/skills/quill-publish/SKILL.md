---
name: quill-publish
description: Release a Quill and put it in the Quill Catalog — versions, tags, the release workflow, the README's "What it adds" table, and submitting the repository. Use when the person wants others (or their own server) to install it from the catalog.
---

# Publishing a Quill

1. Everything passes: `cm quill check`, `cm quill test`, `cm quill test --sandbox`.
2. README.md's "What it adds" table is true (`cm quill check` prints what it adds).
3. Bump `version` in quill.toml (major.minor.patch): a new field or action is
   minor; a change that breaks old records or removes something is major.
4. Commit, tag and push: `git tag v1.2.0 && git push --tags`. The release
   workflow checks the tag matches quill.toml, tests again in the sandbox,
   and publishes the release.
5. Open a pull request on Cloudmorrow/quill-catalog adding it to catalog.toml
   (and, if you like, list it at https://cloudmorrow.com/publish so people
   can find it while the pull request waits):
   ```toml
   [[quills]]
   id = "fleet"
   repo = "https://github.com/you/quill-fleet"
   ref = "v1.2.0"
   category = "business"
   ```
   An update is the same pull request with a new `ref`.

Start a Quill with GitHub's "Use this template" on Cloudmorrow/quill-template
(not a fork), or `cm quill new <id>`. The SDK is a dependency
(`pyproject.toml`, and `sdk = "1"` in the manifest), so a Quill made from an
older template gets new SDK features by updating the dependency.
