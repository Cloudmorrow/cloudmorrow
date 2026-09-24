# Cloudmorrow: the concept

Cloudmorrow is your personal platform for everything. For a person, a
household, or a company. It is the place your data lives, in standard
shapes every app agrees on, and the apps are things that sit around that
data with clearly drawn access to it. You fetch apps from the store at
cloudmorrow.com, tweak them, or build your own by dragging in the data
elements they need and describing the rest to an assistant. Notes, tasks,
calendar, chat, files and secrets come in the box. Everything else is an
app, and every app runs on the phone, in the browser, in the terminal and
as tools an assistant can use, without anyone writing it four times.

You own the data. Not the app, not us.

## What that means

**The data is the person's.** An app reads and writes what it was let at.
Delete the app, and nothing is lost. Move to another server, and
everything comes with you in formats other software already reads.

**Data has standard shapes.** A contact is a contact whichever app made
it. A task, an event, a message, an expense, a secret: each is an
*element* with standard fields, published at cloudmorrow.com, versioned,
and few. An app that needs more adds fields under its own name; it never
invents a second kind of contact. An app that needs something new
introduces an element, and from that moment every other app may ask for
it. That is how one app's data becomes the next app's.

**Access is visible.** Every app and every assistant is on one screen with
what it may see and change, and a switch to cut it. Installing an app
shows what it asks for, in plain words, and waits for a yes. One gate
checks every read and write.

**Everything is on every device.** An app is a manifest: the elements it
uses, the access it asks for, its screens built from a small kit — list,
detail, form, board, calendar, thread, grid, editor. The phone app, the
desktop browser, the terminal app and the command line each render the
kit, and the assistant gets the elements as tools. One description, five
surfaces.

**Building is a conversation.** Say what you want. The assistant writes
the manifest, drags in the elements, and the app is on your phone before
you have finished the sentence. Or start from the store: fetch an app,
open its manifest, change it. Publishing is a git push and a form, with a
donate link if you want one.

**Secrets are part of the foundation.** Keys and passwords live in vaults
of your own, encrypted. An app is given a secret by name when you say so.
An assistant is never given one.

**Encrypted, and yours to run.** Everything you write is ciphertext on
disk under a key the server holds. Run it on a Raspberry Pi, an old
laptop, a container, or a tenant we host with the assistant included.
Sign in with a password; never handle a key.

## The data, in short

Every record is of an element and carries the same envelope: an id, an
owner, a scope, a revision, which app wrote it (a fact, not ownership),
tags, links to other records, and attachments. The element's standard
fields and the extensions apps added sit side by side in it, are drawn
together on every screen, and are exported together.

Three scopes: **personal** (one owner), **shared** (a named circle: the
family, the sales team), **public** (everybody on the server). An element
says which it allows; contacts are never public, messages never personal.

One sealed table holds every record of every element, with the seal bound
to the element and the scope so nothing can be moved by editing the
database. Links live in their own table so "everything about this
contact" is one query. Deleting goes to a bin. Every write bumps a
revision and lands on a change feed, which is what clients, automations,
connectors and the audit line read.

Every element names an export: vCard, iCal, Markdown, `.env`, CSV, JSON at
worst. A whole server exports to a directory that imports into an empty
server and compares equal, and a test says so.

The full concept is [docs/DATA.md](docs/DATA.md).

## The registry and the store

**cloudmorrow.com/elements** publishes element definitions: the standard
ones under `com.cloudmorrow`, and anyone's under their own domain.
Versions are immutable. A server keeps a copy of every element it holds
records of, so it never depends on the registry to run.

**cloudmorrow.com/apps** publishes apps: a manifest, a page, a git URL, a
donate link. The page says which elements the app uses, extends and
introduces, and what it asks for. The store and the registry are a
Cloudmorrow of their own: elements and apps are records, which is the
platform hosting its own catalogue and the best test it could have.

## Three ways to have one

- **Your own machine.** One command, three questions.
- **A Raspberry Pi image.** Burn a card, plug it in, open
  `cloudmorrow.local` on a phone. Public access and a certificate through
  a cloudmorrow.com tunnel that never sees your traffic.
- **A tenant we host**, cheap, with the assistant included.

The delivery plan is [docs/HOSTING.md](docs/HOSTING.md).

## Where the code is, against this

Nothing is in production, so nothing is constrained by what is stored
today. What exists: the six included apps, each keeping its own tables;
encryption at rest with seals bound to scope; the three scopes in chat
and calendar; secrets in vaults; a first-boot page; the MCP server with
OAuth and per-assistant revocation; a catalogue of the kinds of data on
the server at `/api/types`, with which app uses each; the installer, the
container, the phone app, the terminal app and the command line.

What is next, in order: element definitions as files; the record store
with its generic API and the gate; the included apps moved onto it, Tasks
first; extensions and grants with the consent page and the Apps screen;
export and import with the round-trip test; the kit rendered from
manifests; the registry and the store. The plan with its phases and
costs is [docs/PLATFORM.md](docs/PLATFORM.md).
