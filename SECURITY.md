# Security

Cloudmorrow holds people's notes, messages, files and passwords, so a hole
in it matters more than in most software. Reports are welcome and answered
quickly.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private report form:

**[Report a vulnerability](https://github.com/Cloudmorrow/cloudmorrow/security/advisories/new)**

You will get an answer within three days, usually sooner. If the report is
confirmed, a fix is released as soon as it is ready, the advisory is
published with credit to you unless you prefer otherwise, and the release
note says what was wrong in plain words so operators know whether they are
affected.

There is no bounty. There is a thank you, in public if you want it.

## What is in scope

Everything in this repository and the Quills under
[github.com/Cloudmorrow](https://github.com/Cloudmorrow): the server, the
web app, the terminal app, the command line, the agent, the installer and
the container. The interesting places are the ones
[docs/ENCRYPTION.md](docs/ENCRYPTION.md) describes: anything that lets one
person read what another sealed, anything that reaches a record across a
circle it is not in, anything a Quill's code can do that the sandbox says it
cannot, and anything the public installer does that its `--dry-run` did not
say.

Out of scope: the shared demo server, which is reset nightly and holds
nothing real, and denial of service against servers people run themselves.

## Supported versions

The latest release only. A release is a tag on `main`, there is one most
days, and the server updates itself when told to. Operators are expected to
stay current; the fix for a vulnerability is a new release, not a patch to
an old one.

## What the design does and does not protect

Encryption at rest, not end to end: the server holds the key and can read
what it stores, and so can anyone who has both a copy of the data and the
key file. A copied database, a stolen disk or an old backup alone holds
ciphertext. The whole threat model, including what stays plain, is in
[docs/ENCRYPTION.md](docs/ENCRYPTION.md). Please read it before reporting
"the server can decrypt the data": it can, by design, and the document says
why.
