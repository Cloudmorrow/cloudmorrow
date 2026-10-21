"""`cloudmorrow snapshot` — a frozen copy of a space's records, for somebody to validate.

The books at year end: copy the ledger's records into a sealed snapshot
with a digest, hand the bundle to the accountant, and keep their signed
word beside it. See docs/ATTESTATIONS.md.

    cloudmorrow snapshot take ledger r_1a2b3c --series "Books 2025" --period on:2025-01-01:2025-12-31
    cloudmorrow snapshot list
    cloudmorrow snapshot show r_9f8e7d
    cloudmorrow snapshot bundle r_9f8e7d books-2025.json      # the file to send
    cloudmorrow snapshot guest r_9f8e7d --label "Acme Accounting" --days 60
    cloudmorrow snapshot attest r_9f8e7d books-2025.attestation.json
    cloudmorrow snapshot verify books-2025.json books-2025.attestation.json
    cloudmorrow snapshot withdraw r_9f8e7d
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from cloudmorrow.cli.common import client, console, emit, fail, from_server, out, plural, run
from cloudmorrow.console import TITLE

app = typer.Typer(help="Snapshots: a frozen copy of a space's records, with a digest.", no_args_is_help=True)

SnapshotArg = Annotated[str, typer.Argument(help="The snapshot's id.")]


def _period(text: str | None) -> dict | None:
    """`field:from:to`, either date blank: `on:2025-01-01:2025-12-31`, `on::2025-12-31`."""
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3 or not parts[0]:
        fail("--period is field:from:to, with either date left blank: on:2025-01-01:2025-12-31")
    return {"field": parts[0], "from": parts[1] or None, "to": parts[2] or None}


def _line(told: dict) -> str:
    snap = told["snapshot"]
    fields = snap["fields"]
    status = fields.get("status", "")
    colour = "green" if status == "sealed" else "yellow"
    series = f" [dim]{fields['series']} v{fields.get('version', 1)}[/]" if fields.get("series") else ""
    return (
        f"[b]{fields.get('title', '')}[/]{series}  [{colour}]{status}[/]  "
        f"{plural(int(fields.get('records') or 0), 'record')} of {fields.get('of_model')} "
        f"[dim]{fields.get('of_title', '')}[/]\n  {snap['id']}  {fields.get('digest', '')}"
    )


@app.command("take")
def take(
    space_model: Annotated[str, typer.Argument(help="The datamodel of the space: ledger, book, association.")],
    space_id: Annotated[str, typer.Argument(help="The space's id.")],
    title: Annotated[
        str, typer.Option("--title", help="What to call it; the space's name and the date unless said.")
    ] = (""),
    series: Annotated[str, typer.Option("--series", help="What this is one version of: 'Books 2025'.")] = "",
    models: Annotated[list[str] | None, typer.Option("--model", help="A datamodel to copy; every one unless said.")] = (
        None
    ),
    period: Annotated[
        str | None, typer.Option("--period", help="field:from:to: that range, and what hangs off it.")
    ] = (None),
    notes: Annotated[str, typer.Option("--notes", help="A word on it.")] = "",
    shared: Annotated[list[str] | None, typer.Option("--with", help="Somebody on the server to share it with.")] = None,
) -> None:
    """Copy a space's records into a sealed snapshot."""

    async def _take() -> None:
        _, api = client()
        async with api:
            told = await api.take_snapshot(
                space_model,
                space_id,
                title=title,
                series=series,
                models=models or [],
                period=_period(period),
                notes=notes,
                scope="shared" if shared else None,
                members=shared or [],
            )
        console.print(f"[green]Sealed.[/] {_line(told)}")
        console.print(
            "[dim]`cm snapshot bundle <id> <file>` writes the bundle to send; `cm snapshot guest <id>` makes a link.[/]"
        )

    run(_take())


@app.command("list")
def list_snapshots(
    of: Annotated[str | None, typer.Option("--of", help="Only the snapshots of this space, by its id.")] = None,
) -> None:
    """Every snapshot you may see."""

    async def _list() -> None:
        _, api = client()
        async with api:
            rows = await api.records("snapshot", **({"of_space": of} if of else {}))
        if not rows:
            console.print("[dim]No snapshots yet.[/] `cm snapshot take <space-datamodel> <space-id>` makes one.")
            return
        table = Table(title="snapshots", title_style=TITLE)
        for column in ("id", "title", "series", "of", "records", "status", "sealed", "digest"):
            table.add_column(column, overflow="fold")
        for row in rows:
            f = row["fields"]
            series = f"{f['series']} v{f.get('version', 1)}" if f.get("series") else ""
            table.add_row(
                row["id"],
                f.get("title", ""),
                series,
                f"{f.get('of_model', '')} {f.get('of_title', '')}".strip(),
                str(f.get("records", 0)),
                f.get("status", ""),
                (f.get("sealed_at") or "")[:10],
                (f.get("digest") or "")[:23] + "…",
            )
        out.print(table)

    run(_list())


@app.command("show")
def show(snapshot_id: SnapshotArg) -> None:
    """One snapshot: its digest, whether its bundle is intact, its attestations and its links."""

    async def _show() -> None:
        _, api = client()
        async with api:
            told = await api.snapshot(snapshot_id)
        console.print(_line(told))
        intact = "[green]intact[/]" if told["intact"] else "[red]DOES NOT MATCH ITS DIGEST[/]"
        console.print(f"  bundle: {told['size']} bytes, {intact}")
        if not told["attestations"]:
            console.print("  [dim]no attestations yet[/]")
        for a in told["attestations"]:
            f = a["fields"]
            colour = {"validated": "green", "qualified": "yellow", "rejected": "red"}.get(f["verdict"], "")
            who = f["signer_name"] + (f", {f['signer_organisation']}" if f.get("signer_organisation") else "")
            console.print(
                f"  [{colour}]{f['verdict']}[/] by {who}  [dim]{f['signed_at']}  key {f['signer_fingerprint']}[/]"
            )
            if f.get("statement"):
                console.print(f"    [dim]{f['statement']}[/]")
        for g in told.get("guests", []):
            state = "live" if g["live"] else ("revoked" if g["revoked_at"] else "expired")
            console.print(f"  link {g['id']} [dim]{g['label']}[/] {state} until {g['expires_at'][:10]}")

    run(_show())


@app.command("bundle")
def bundle(
    snapshot_id: SnapshotArg,
    path: Annotated[Path | None, typer.Argument(help="Where to write it; stdout when left out.")] = None,
) -> None:
    """Write the bundle: the file to send to whoever validates it."""

    async def _bundle() -> None:
        snapshots = from_server("snapshots")
        _, api = client()
        async with api:
            data, digest = await api.snapshot_bundle(snapshot_id)
        if snapshots.digest_of(data) != digest:
            fail("the bundle does not hash to the digest the server sent with it")
        if path is None:
            emit(data.decode("utf-8"))
            return
        path.write_bytes(data)
        console.print(f"[green]Wrote[/] {path} ({len(data)} bytes), digest {digest}")

    run(_bundle())


@app.command("attest")
def attest(
    snapshot_id: SnapshotArg,
    path: Annotated[Path, typer.Argument(help="The attestation file that came back.")],
) -> None:
    """Bring an attestation back to its snapshot. The server checks it before keeping it."""
    document = _read_json(path)

    async def _attest() -> None:
        _, api = client()
        async with api:
            kept = await api.attest_snapshot(snapshot_id, document)
        f = kept["fields"]
        console.print(f"[green]Kept.[/] {f['verdict']} by {f['signer_name']}, key {f['signer_fingerprint']}")

    run(_attest())


@app.command("guest")
def guest(
    snapshot_id: SnapshotArg,
    label: Annotated[str, typer.Option("--label", help="Who it is for: 'Acme Accounting'.")] = "",
    days: Annotated[int | None, typer.Option("--days", help="How long it works; thirty unless said.")] = None,
) -> None:
    """A link that opens this one snapshot to somebody outside. Shown once: send it to them."""

    async def _guest() -> None:
        _, api = client()
        async with api:
            made = await api.invite_snapshot_guest(snapshot_id, label=label, days=days)
        console.print(f"[green]Link {made['id']}[/] for {made['label'] or 'a guest'}, until {made['expires_at'][:10]}:")
        emit(made["url"] + "\n")
        console.print("[dim]They run `cm attest sign <that link> --verdict validated`, and need no account here.[/]")

    run(_guest())


@app.command("guests")
def guests(snapshot_id: SnapshotArg) -> None:
    """The links given out to a snapshot."""

    async def _guests() -> None:
        _, api = client()
        async with api:
            rows = await api.snapshot_guests(snapshot_id)
        if not rows:
            console.print("[dim]No links given out.[/]")
            return
        table = Table(title="guest links", title_style=TITLE)
        for column in ("id", "for", "made by", "expires", "used", "state"):
            table.add_column(column, overflow="fold")
        for g in rows:
            state = "live" if g["live"] else ("revoked" if g["revoked_at"] else "expired")
            table.add_row(
                str(g["id"]), g["label"], g["made_by"], g["expires_at"][:10], (g["used_at"] or "")[:16], state
            )
        out.print(table)

    run(_guests())


@app.command("revoke")
def revoke(snapshot_id: SnapshotArg, guest_id: Annotated[int, typer.Argument(help="The link's number.")]) -> None:
    """Take a link back."""

    async def _revoke() -> None:
        _, api = client()
        async with api:
            await api.revoke_snapshot_guest(snapshot_id, guest_id)
        console.print(f"[green]Revoked[/] link {guest_id}.")

    run(_revoke())


@app.command("withdraw")
def withdraw(snapshot_id: SnapshotArg) -> None:
    """Mark a snapshot as not to be relied on. It stays, with its attestations."""

    async def _withdraw() -> None:
        _, api = client()
        async with api:
            told = await api.withdraw_snapshot(snapshot_id)
        console.print(f"[yellow]Withdrawn.[/] {_line(told)}")

    run(_withdraw())


@app.command("verify")
def verify(
    bundle_path: Annotated[Path, typer.Argument(help="The bundle file.")],
    attestations: Annotated[list[Path] | None, typer.Argument(help="Attestation files on it.")] = None,
) -> None:
    """Check a bundle and the attestations on it, with no server at all.

    The bundle hashes to a digest; each attestation is checked to be its
    signer's signature over that very digest.
    """
    snapshots = from_server("snapshots")
    data = bundle_path.read_bytes()
    try:
        document = snapshots.verify_bundle(data)
    except ValueError as exc:
        fail(str(exc))
    digest = snapshots.digest_of(data)
    space = document.get("space", {})
    count = sum(len(rows) for rows in document.get("records", {}).values())
    console.print(
        f"[green]Bundle[/] of {space.get('model')} [b]{space.get('fields', {}).get('name', space.get('id'))}[/], "
        f"{plural(count, 'record')}, taken {document.get('taken_at', '')[:10]}"
    )
    emit(digest + "\n")
    bad = 0
    for path in attestations or []:
        try:
            checked = snapshots.verify_attestation(_read_json(path), digest=digest)
        except ValueError as exc:
            bad += 1
            console.print(f"[red]{path.name}: {exc}[/]")
            continue
        signer = checked["signer"]
        who = signer["name"] + (f", {signer['organisation']}" if signer.get("organisation") else "")
        console.print(
            f"[green]{path.name}[/]: {checked['verdict']} by {who}, {checked['signed_at']}, key {signer['key'][:20]}…"
        )
    if bad:
        raise typer.Exit(code=1)


def _read_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"{path}: {exc}")
    if not isinstance(document, dict):
        fail(f"{path}: not an attestation")
    return document
