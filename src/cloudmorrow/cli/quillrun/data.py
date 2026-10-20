"""The kit's `data` on the command line: the datamodels, the records of one, one record.

    cm data list                 every datamodel you may see, by domain
    cm data list deal            the records of one: id, title, where it is, what it is sorted by
    cm data show deal 1a2b       one record, every field
    cm data show snapshot 9f8e   a snapshot: its fields, then its digest and the attestations on it

Looking only: `add`, `set` and the rest are refused here, since every
datamodel on a data screen is marked read (server/dataview.py).
"""

from __future__ import annotations

import json

from rich.markup import escape
from rich.table import Table

from cloudmorrow.cli import quillrun
from cloudmorrow.cli.common import fail
from cloudmorrow.cli.quillrun.screen import _find, _short
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.console import TITLE

LOOKING = ("list", "show")
# How many fields beside the title a listing shows.
COLUMNS = 3


def _models(quill: dict, spec: dict) -> list[dict]:
    models = quill.get("models") or {}
    ids = spec.get("models") or sorted(models)
    return [models[i] for i in ids if i in models]


def _columns(model: dict) -> list[dict]:
    by_name = {f["name"]: f for f in model.get("fields") or []}
    chosen: list[dict] = []
    in_space = by_name.get(model.get("in_space") or "")
    if in_space:
        chosen.append(in_space)
    for f in model.get("fields") or []:
        if len(chosen) >= COLUMNS:
            break
        if f["name"] == model.get("title") or f in chosen or not f.get("indexed"):
            continue
        if f.get("kind") == "json" or f.get("secret"):
            continue
        chosen.append(f)
    return chosen


def _many(word: str) -> str:
    """A datamodel's label for all of its records: Deals, Activities, Journal entries."""
    if word.lower().endswith("s"):
        return word
    if word.lower().endswith("y") and word[-2:-1].lower() not in "aeiou":
        return f"{word[:-1]}ies"
    return f"{word}s"


def _said(field: dict, value: object) -> str:
    if value is None or value == "":
        return ""
    if field.get("kind") == "enum" and value in field.get("values", []):
        return str((field.get("labels") or field["values"])[field["values"].index(value)])
    return str(value)


async def _act_data(api: CloudmorrowClient, quill: dict, spec: dict, action: str, args: list[str], plain: bool) -> None:
    if action not in LOOKING:
        fail(f"{quill['id']} is for looking: `cm {quill['id']} list [datamodel]`, `show <datamodel> <id>`")
    models = _models(quill, spec)
    if action == "list" and not args:
        if plain:
            quillrun.emit(
                json.dumps([{k: m[k] for k in ("id", "label", "domain", "description")} for m in models]) + "\n"
            )
            return
        table = Table(title=spec.get("label") or quill["name"], title_style=TITLE)
        table.add_column("domain", style="dim")
        table.add_column("datamodel")
        table.add_column("what it is", overflow="fold")
        for model in sorted(models, key=lambda m: (m.get("domain") or "", m["id"])):
            table.add_row(
                model.get("domain") or "", f"[b]{escape(model['id'])}[/]", escape(model.get("description") or "")
            )
        quillrun.out.print(table)
        return
    model = next((m for m in models if m["id"] == args[0]), None)
    if model is None:
        fail(f"no datamodel {args[0]!r} you may see; `cm {quill['id']} list` names them")
    title = model.get("title") or ""
    records = await api.records(model["id"])
    if action == "list":
        if plain:
            quillrun.emit(json.dumps(records, indent=2) + "\n")
            return
        columns = _columns(model)
        table = Table(
            title=f"{model['label']}s" if not model["label"].endswith("s") else model["label"], title_style=TITLE
        )
        table.add_column("id", style="dim")
        table.add_column(title)
        for f in columns:
            table.add_column(f.get("label") or f["name"], style="dim")
        for record in records:
            fields = record.get("fields") or {}
            table.add_row(
                _short(record["id"]),
                escape(str(fields.get(title) or "")),
                *(escape(_said(f, fields.get(f["name"]))) for f in columns),
            )
        quillrun.out.print(table)
        return
    if len(args) < 2:
        fail(f"which one? cm {quill['id']} show {model['id']} <id>")
    record = _find(records, args[1], title)
    extra = await _snapshot(api, model, record)
    if plain:
        quillrun.emit(json.dumps(record | ({"snapshot": extra} if extra else {}), indent=2) + "\n")
        return
    table = Table(title=f"{model['label']} {record['id']}", title_style=TITLE, show_header=False)
    table.add_column("field", style="dim")
    table.add_column("value", overflow="fold")
    for f in model.get("fields") or []:
        value = (record.get("fields") or {}).get(f["name"])
        if f.get("secret"):
            table.add_row(f.get("label") or f["name"], "[dim]hidden[/]")
            continue
        if f.get("kind") == "json" and value is not None:
            value = json.dumps(value)
        table.add_row(f.get("label") or f["name"], escape(_said(f, value)))
    table.add_row("rev", str(record.get("rev", "")))
    quillrun.out.print(table)
    if extra:
        intact = "[green]intact[/]" if extra.get("intact") else "[red]DOES NOT MATCH ITS DIGEST[/]"
        quillrun.out.print(f"digest {escape(str(extra.get('digest') or ''))}  bundle {intact}")
        for a in extra.get("attestations") or []:
            f = a["fields"]
            who = f["signer_name"] + (f", {f['signer_organisation']}" if f.get("signer_organisation") else "")
            quillrun.out.print(
                f"  {f['verdict']} by {escape(who)}  [dim]{f['signed_at']}  key {f['signer_fingerprint']}[/]"
            )
        if not extra.get("attestations"):
            quillrun.out.print("  [dim]no attestations yet[/]")


async def _snapshot(api: CloudmorrowClient, model: dict, record: dict) -> dict | None:
    """A snapshot's digest, whether it is intact, and the attestations on it (docs/ATTESTATIONS.md)."""
    if model["id"] != "snapshot":
        return None
    try:
        return await api.snapshot(record["id"])
    except Exception:  # an older server, or one that keeps no bundle: the record still shows
        return None
