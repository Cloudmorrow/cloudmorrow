"""`cloudmorrow attest` — put your signed word on a snapshot somebody sent you.

An accountant, an auditor, a board member: given a snapshot's bundle, or a
guest link to one, they read it and sign a verdict over its digest with a
key of their own. The company's server never holds that key, so it cannot
forge the stamp. See docs/ATTESTATIONS.md.

    cloudmorrow attest sign books-2025.json --verdict validated --statement "Reviewed against the bank statements."
    cloudmorrow attest sign https://cloud.example/api/guest/snapshots/r_9f8e7d?token=cmg_… --verdict validated
    cloudmorrow attest sign books-2025.json --verdict qualified --via-server     # your own Cloudmorrow signs
    cloudmorrow attest key                                                      # your public key, to give out

With a file, the attestation is written beside it as `<name>.attestation.json`,
to send back. With a link, it is sent through the link at once. The key is
made on first use at `<config dir>/identity.key`; `--via-server` uses your
own Cloudmorrow's key instead, in your name, so no key is on this machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer

from cloudmorrow.cli.common import client, console, emit, fail, run
from cloudmorrow.client.config import config_path
from cloudmorrow.server import crypto
from cloudmorrow.server.snapshots import VERDICTS, digest_of, sign_attestation, verify_attestation, verify_bundle

app = typer.Typer(help="Sign your word on a snapshot: validated, qualified or rejected.", no_args_is_help=True)


def key_path() -> Path:
    return config_path().parent / "identity.key"


def _bundle_from(what: str) -> tuple[bytes, dict, str]:
    """The bundle's bytes and document, and where to put the attestation: a path, or a link to post to."""
    if what.startswith(("http://", "https://")):
        try:
            response = httpx.get(_bundle_url(what), timeout=60, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            fail(f"cannot fetch the snapshot through that link: {exc}")
        return response.content, verify_bundle(response.content), what
    path = Path(what)
    try:
        data = path.read_bytes()
    except OSError as exc:
        fail(f"{path}: {exc}")
    return data, verify_bundle(data), ""


def _bundle_url(link: str) -> str:
    base, _, query = link.partition("?")
    return f"{base.rstrip('/')}/bundle?{query}"


def _attestations_url(link: str) -> str:
    base, _, query = link.partition("?")
    return f"{base.rstrip('/')}/attestations?{query}"


@app.command("sign")
def sign(
    what: Annotated[str, typer.Argument(help="The bundle file, or the guest link you were sent.")],
    verdict: Annotated[str, typer.Option("--verdict", help="validated, qualified or rejected.")],
    statement: Annotated[str, typer.Option("--statement", help="Your word on it, in a sentence or two.")] = "",
    name: Annotated[
        str, typer.Option("--name", help="Who signs; the name last used, or your login, unless said.")
    ] = "",
    organisation: Annotated[str, typer.Option("--organisation", help="On whose behalf.")] = "",
    via_server: Annotated[bool, typer.Option("--via-server", help="Have your own Cloudmorrow sign, in your name.")] = (
        False
    ),
    out_path: Annotated[Path | None, typer.Option("--out", help="Where to write the attestation, with a file.")] = None,
) -> None:
    """Sign a verdict over a snapshot's digest, and write it beside the bundle or send it through the link."""
    verdict = verdict.strip().lower()
    if verdict not in VERDICTS:
        fail(f"--verdict is one of {', '.join(VERDICTS)}")
    data, bundle, link = _bundle_from(what)
    digest = digest_of(data)
    snapshot_id = str(bundle.get("snapshot_id") or _snapshot_in(link))
    series = ""
    version = 0
    if link:
        told = _describe(link)
        snapshot_id = told["snapshot"]["id"]
        series = str(told["snapshot"]["fields"].get("series") or "")
        version = int(told["snapshot"]["fields"].get("version") or 0)
        if told["digest"] != digest:
            fail("the bundle fetched does not hash to the digest the server states")
    if via_server:
        document = _sign_via_server(
            digest=digest, snapshot=snapshot_id, series=series, version=version, verdict=verdict, statement=statement
        )
    else:
        key = crypto.load_or_create_signing_key(key_path())
        who = name.strip() or _remembered_name() or _login_name()
        if not who:
            fail("say who signs: --name 'Jane Doe'")
        document = sign_attestation(
            key,
            digest=digest,
            snapshot=snapshot_id,
            series=series,
            version=version,
            verdict=verdict,
            statement=statement,
            signer_name=who,
            signer_organisation=organisation,
        )
        _remember_name(who)
    verify_attestation(document, digest=digest)
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if link:
        try:
            response = httpx.post(_attestations_url(link), json=document, timeout=60)
        except httpx.HTTPError as exc:
            fail(f"cannot send the attestation through that link: {exc}")
        if response.status_code >= 400:
            fail(f"the server refused it: {response.text}")
        console.print(f"[green]Sent.[/] {verdict} by {document['signer']['name']} on {digest}")
        return
    target = out_path or Path(what).with_suffix("").with_suffix(".attestation.json")
    target.write_text(text, encoding="utf-8")
    console.print(f"[green]Signed.[/] {verdict} by {document['signer']['name']} on {digest}")
    console.print(f"[dim]Wrote {target}: send it back, to be kept with the snapshot (`cm snapshot attest`).[/]")


def _snapshot_in(link: str) -> str:
    base = link.partition("?")[0].rstrip("/")
    return base.rsplit("/", 1)[-1] if "/api/guest/snapshots/" in base else ""


def _describe(link: str) -> dict:
    try:
        response = httpx.get(link, timeout=60, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        fail(f"cannot read the snapshot through that link: {exc}")


def _sign_via_server(**what) -> dict:
    async def _sign() -> dict:
        _, api = client()
        async with api:
            return await api.sign_attestation(**what)

    return run(_sign())


def _login_name() -> str:
    from cloudmorrow.client.config import StoredCredentials

    stored = StoredCredentials.load()
    return stored.username if stored else ""


def _name_path() -> Path:
    return key_path().with_suffix(".name")


def _remembered_name() -> str:
    try:
        return _name_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _remember_name(name: str) -> None:
    try:
        _name_path().write_text(name + "\n", encoding="utf-8")
    except OSError:
        pass


@app.command("key")
def key() -> None:
    """Your public key and its fingerprint: give them to whoever will check your stamps."""
    signing = crypto.load_or_create_signing_key(key_path())
    public = crypto.public_key_text(signing)
    console.print(f"[dim]fingerprint[/] {crypto.key_fingerprint(public)}  [dim]at {key_path()}[/]")
    emit(public + "\n")


@app.command("verify")
def verify(
    bundle_path: Annotated[Path, typer.Argument(help="The bundle file.")],
    attestation_path: Annotated[Path, typer.Argument(help="The attestation file.")],
) -> None:
    """Check that an attestation is its signer's word over this very bundle."""
    data = bundle_path.read_bytes()
    verify_bundle(data)
    digest = digest_of(data)
    try:
        checked = verify_attestation(json.loads(attestation_path.read_text(encoding="utf-8")), digest=digest)
    except (OSError, ValueError) as exc:
        fail(f"{attestation_path.name}: {exc}")
    signer = checked["signer"]
    console.print(
        f"[green]Good.[/] {checked['verdict']} by {signer['name']}"
        f"{', ' + signer['organisation'] if signer.get('organisation') else ''}, {checked['signed_at']}"
    )
    emit(digest + "\n")
