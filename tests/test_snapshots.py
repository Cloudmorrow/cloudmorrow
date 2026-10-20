"""Snapshots and attestations: a frozen copy of a space, locked, and the signed word on it."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import typer
from typer.testing import CliRunner

from cloudmorrow.cli import attest as attest_cli
from cloudmorrow.cli import snapshot as snapshot_cli
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from cloudmorrow.server import crypto
from cloudmorrow.server.database import connect
from cloudmorrow.server.datamodels import DatamodelError, Lock, parse_datamodel
from cloudmorrow.server.snapshots import (
    NotSigned,
    canonical,
    digest_of,
    sign_attestation,
    verify_attestation,
    verify_bundle,
)
from tests.conftest import ADMIN, GUEST, token_for


# -- the lock rule, on its own ----------------------------------------------------------
def _model(**head):
    data = {
        "datamodel": {"id": "thing", "label": "Thing", **head},
        "fields": {
            "name": {"kind": "string", "required": True},
            "status": {"kind": "enum", "values": ["draft", "final", "void"], "default": "draft"},
        },
    }
    return parse_datamodel(data)


def test_a_datamodel_is_not_locked_unless_it_says_so():
    assert _model().lock is None and _model().server_made is False
    assert _model(locked=True).lock == Lock()
    lock = _model(locked={"field": "status", "value": "final", "allow": ["void"]}).lock
    assert lock == Lock("status", "final", ("void",))
    assert not lock.holds({"status": "draft"})
    assert lock.holds({"status": "final"}) and lock.holds({"status": "void"})
    assert _model(locked=True).to_dict()["locked"] is True
    assert _model().to_dict()["locked"] is False


@pytest.mark.parametrize(
    "locked, said",
    [
        ({"field": "name", "value": "x"}, "must be an enum"),
        ({"field": "status", "value": "gone"}, "never has"),
        ({"field": "status", "value": "final", "allow": ["final"]}, "allows the value it locks on"),
        ("yes", "locked is true, false"),
    ],
)
def test_a_lock_that_does_not_hold_together_is_refused(locked, said):
    with pytest.raises(DatamodelError, match=said):
        _model(locked=locked)


# -- a server with a book to copy ------------------------------------------------------------
@pytest.fixture()
def api(client):
    """The CRM Quill installed, so there is a space (a book) with records in it."""
    client.app.state.cloudmorrow.quills.install_from_catalog("crm")
    tokens = {who[0]: token_for(client, *who) for who in (ADMIN, GUEST)}

    def call(method: str, path: str, body=None, *, expect: int = 200, who: str = ADMIN[0], raw: bool = False):
        headers = {"Authorization": f"Bearer {tokens[who]}"} if who else {}
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code == expect, f"{method} {path}: {response.status_code} {response.text}"
        if raw:
            return response
        return response.json() if response.content else None

    call.client = client
    call.state = client.app.state.cloudmorrow
    return call


def _book(api, name: str = "Customers", **more) -> dict:
    return api("POST", "/api/records/book", {"fields": {"name": name}, **more}, expect=201)


def _deal(api, book: str, title: str, closes: str, value: str = "100") -> dict:
    fields = {"book": book, "title": title, "expected_close": closes, "value": value}
    return api("POST", "/api/records/deal", {"fields": fields}, expect=201)


def _activity(api, book: str, title: str, deal: str | None = None) -> dict:
    fields = {"book": book, "title": title, "deal": deal}
    return api("POST", "/api/records/activity", {"fields": fields}, expect=201)


def _take(api, book: str, **more) -> dict:
    return api("POST", "/api/snapshots", {"space_model": "book", "space_id": book, **more}, expect=201)


def test_the_two_datamodels_come_with_the_core(api, config):
    ids = {m["id"] for m in api("GET", "/api/datamodels")}
    assert {"snapshot", "attestation"} <= ids
    assert (config.datamodels_dir / "snapshot.toml").exists()
    snapshot = next(m for m in api("GET", "/api/datamodels") if m["id"] == "snapshot")
    assert snapshot["locked"] == {"field": "status", "value": "sealed", "allow": ["withdrawn"]}
    assert snapshot["server_made"] is True and snapshot["space"] is True


def test_a_snapshot_copies_the_space_and_does_not_move_when_the_space_does(api):
    book = _book(api)["id"]
    deal = _deal(api, book, "Roof", "2025-03-01")
    _activity(api, book, "Call them", deal["id"])
    told = _take(api, book, title="Books 2025", series="Books", notes="Year end.")
    snap = told["snapshot"]
    assert snap["model"] == "snapshot" and snap["fields"]["status"] == "sealed"
    assert snap["fields"]["of_model"] == "book" and snap["fields"]["of_title"] == "Customers"
    assert snap["fields"]["version"] == 1 and snap["fields"]["supersedes"] is None
    assert snap["fields"]["sealed_at"] and snap["fields"]["digest"].startswith("sha256:")
    assert told["intact"] is True and told["attestations"] == [] and told["guests"] == []
    # Stages are seeded per book by the CRM, so they are in the copy too.
    assert set(snap["fields"]["datamodels"]) == {"activity", "contact", "deal", "organisation", "stage"}
    assert snap["fields"]["records"] >= 2 and told["size"] > 100

    response = api("GET", f"/api/snapshots/{snap['id']}/bundle", raw=True)
    data = response.content
    assert response.headers["X-Snapshot-Digest"] == digest_of(data) == snap["fields"]["digest"]
    assert response.headers["Content-Disposition"].endswith(f'snapshot-{snap["id"]}.json"')
    bundle = verify_bundle(data)
    assert bundle["space"] == {
        "model": "book",
        "id": book,
        "fields": {"name": "Customers", "currency": "EUR", "notes": None},
    }
    assert [d["fields"]["title"] for d in bundle["records"]["deal"]] == ["Roof"]
    assert bundle["records"]["deal"][0]["rev"] == 1
    assert bundle["datamodels"]["deal"]["version"] == 1
    assert canonical(bundle) == data

    # The live book moves on; the snapshot is what it was.
    api("PATCH", f"/api/records/deal/{deal['id']}", {"fields": {"title": "Roof and gutters"}})
    api("DELETE", f"/api/records/activity/{_activity(api, book, 'Later')['id']}", expect=204)
    again = api("GET", f"/api/snapshots/{snap['id']}/bundle", raw=True).content
    assert again == data
    assert api("GET", f"/api/snapshots/{snap['id']}")["intact"] is True


def test_the_same_content_is_the_same_bytes_and_any_change_is_another_digest(api):
    book = _book(api)["id"]
    _deal(api, book, "Roof", "2025-03-01")
    first = _take(api, book)["snapshot"]
    second = _take(api, book)["snapshot"]
    one = verify_bundle(api("GET", f"/api/snapshots/{first['id']}/bundle", raw=True).content)
    two = verify_bundle(api("GET", f"/api/snapshots/{second['id']}/bundle", raw=True).content)
    # Taken twice with nothing changed: the records are the same bytes, so
    # only when it was taken can tell the two bundles apart.
    assert canonical(one["records"]) == canonical(two["records"])
    assert {k for k in one if one[k] != two[k]} <= {"taken_at"}
    _deal(api, book, "Windows", "2025-04-01")
    third = _take(api, book)["snapshot"]
    assert third["fields"]["digest"] != first["fields"]["digest"]


def test_a_period_keeps_the_range_and_what_hangs_off_it(api):
    book = _book(api)["id"]
    inside = _deal(api, book, "In the year", "2025-06-01")
    outside = _deal(api, book, "Next year", "2026-02-01")
    _activity(api, book, "On the one inside", inside["id"])
    _activity(api, book, "On the one outside", outside["id"])
    _activity(api, book, "On no deal")
    told = _take(
        api,
        book,
        models=["deal", "activity"],
        period={"field": "expected_close", "from": "2025-01-01", "to": "2025-12-31"},
    )
    bundle = verify_bundle(api("GET", f"/api/snapshots/{told['snapshot']['id']}/bundle", raw=True).content)
    assert bundle["period"] == {"field": "expected_close", "from": "2025-01-01", "to": "2025-12-31"}
    assert [d["fields"]["title"] for d in bundle["records"]["deal"]] == ["In the year"]
    assert sorted(a["fields"]["title"] for a in bundle["records"]["activity"]) == ["On no deal", "On the one inside"]
    assert set(bundle["records"]) == {"deal", "activity"}
    assert told["snapshot"]["fields"]["records"] == 3


@pytest.mark.parametrize(
    "body, said",
    [
        ({"space_model": "deal", "space_id": "r_x"}, "not a space"),
        ({"space_model": "book", "space_id": "r_nothere"}, "no such record"),
        ({"models": ["task"]}, "not a datamodel in a book"),
        ({"period": {"field": "title", "from": "2025-01-01"}}, "not an indexed date"),
        ({"period": {"field": "expected_close"}}, "from, to, or both"),
        ({"period": {"field": "expected_close", "from": "yesterday"}}, "YYYY-MM-DD"),
    ],
)
def test_what_cannot_be_taken_says_why(api, body, said):
    book = _book(api)["id"]
    asked = {"space_model": "book", "space_id": book} | body
    expect = 404 if "no such" in said else 400
    answer = api("POST", "/api/snapshots", asked, expect=expect)
    assert said in str(answer["detail"])


def test_a_series_counts_versions_and_links_each_to_the_one_before(api):
    book = _book(api)["id"]
    first = _take(api, book, series="Books 2025")["snapshot"]
    _deal(api, book, "Fixed", "2025-01-01")
    second = _take(api, book, series="Books 2025")["snapshot"]
    other = _take(api, book, series="Members")["snapshot"]
    assert (first["fields"]["version"], second["fields"]["version"], other["fields"]["version"]) == (1, 2, 1)
    assert second["fields"]["supersedes"] == first["id"] and other["fields"]["supersedes"] is None
    listed = api("GET", "/api/records/snapshot?series=Books 2025")
    assert [s["fields"]["version"] for s in listed] == [1, 2]


def test_a_sealed_snapshot_is_never_changed_or_deleted_only_withdrawn(api):
    book = _book(api)["id"]
    snap = _take(api, book, title="Year end")["snapshot"]
    locked = api("PATCH", f"/api/records/snapshot/{snap['id']}", {"fields": {"title": "Edited"}}, expect=423)
    assert "locked" in locked["detail"]
    api("PATCH", f"/api/records/snapshot/{snap['id']}", {"fields": {"digest": "sha256:0"}}, expect=423)
    api("DELETE", f"/api/records/snapshot/{snap['id']}", expect=423)
    # Withdrawing, and nothing with it.
    api("PATCH", f"/api/records/snapshot/{snap['id']}", {"fields": {"status": "withdrawn", "title": "x"}}, expect=423)
    told = api("POST", f"/api/snapshots/{snap['id']}/withdraw")
    assert told["snapshot"]["fields"]["status"] == "withdrawn" and told["snapshot"]["fields"]["withdrawn_at"]
    assert told["snapshot"]["fields"]["sealed_at"] == snap["fields"]["sealed_at"]
    # And withdrawn is locked too: not back to sealed, not deleted.
    api("PATCH", f"/api/records/snapshot/{snap['id']}", {"fields": {"status": "sealed"}}, expect=423)
    api("DELETE", f"/api/records/snapshot/{snap['id']}", expect=423)
    assert api("GET", f"/api/snapshots/{snap['id']}")["snapshot"]["fields"]["title"] == "Year end"


def test_a_snapshot_is_made_by_the_server_not_by_hand(api):
    refused = api("POST", "/api/records/snapshot", {"fields": {"title": "Fake", "digest": "sha256:0"}}, expect=403)
    assert "made by the server" in refused["detail"]
    book = _book(api)["id"]
    snap = _take(api, book)["snapshot"]
    fields = {"snapshot": snap["id"], "digest": "sha256:0", "verdict": "validated", "signer_name": "x"}
    fields |= {"signer_key": "ed25519:x", "signed_at": "2026-01-01T00:00:00+00:00", "signature": "x"}
    api("POST", "/api/records/attestation", {"fields": fields}, expect=403)


def test_the_bundle_is_ciphertext_in_the_database_and_the_digest_is_over_the_plain_bytes(api, config):
    book = _book(api)["id"]
    _deal(api, book, "Roof", "2025-03-01")
    snap = _take(api, book)["snapshot"]
    with connect(config.db_path) as conn:
        row = conn.execute("SELECT * FROM snapshot_bundles WHERE snapshot_id = ?", (snap["id"],)).fetchone()
    assert row["bundle"].startswith("s1:") and "Roof" not in row["bundle"]
    assert row["digest"] == snap["fields"]["digest"]
    data = api("GET", f"/api/snapshots/{snap['id']}/bundle", raw=True).content
    assert digest_of(data) == row["digest"] and b"Roof" in data


def test_a_tampered_bundle_is_not_intact(api, config):
    book = _book(api)["id"]
    snap = _take(api, book)["snapshot"]
    data = api("GET", f"/api/snapshots/{snap['id']}/bundle", raw=True).content
    forged = data.replace(b"Customers", b"Customerz")
    state = api.state
    with state.db.connect() as conn:
        sealed = conn.seal("snapshot_bundles", "bundle", (snap["id"],), forged.decode())
        conn.execute("UPDATE snapshot_bundles SET bundle = ? WHERE snapshot_id = ?", (sealed, snap["id"]))
        conn.commit()
    assert api("GET", f"/api/snapshots/{snap['id']}")["intact"] is False


# -- attestations ---------------------------------------------------------------------------
@pytest.fixture()
def accountant(tmp_path):
    """Somebody outside, with a key of their own."""
    return crypto.load_or_create_signing_key(tmp_path / "accountant.key")


def _signed(key, snap: dict, verdict: str = "validated", **more) -> dict:
    return sign_attestation(
        key,
        digest=snap["fields"]["digest"],
        snapshot=snap["id"],
        verdict=verdict,
        statement=more.pop("statement", "Reviewed."),
        signer_name=more.pop("signer_name", "Jane Doe"),
        signer_organisation=more.pop("signer_organisation", "Acme Accounting"),
        **more,
    )


def test_an_attestation_is_a_signature_over_the_digest_and_is_checked_before_it_is_kept(api, accountant):
    book = _book(api)["id"]
    snap = _take(api, book, series="Books 2025")["snapshot"]
    document = _signed(accountant, snap)
    assert verify_attestation(document) == document
    kept = api("POST", f"/api/snapshots/{snap['id']}/attestations", document, expect=201)
    f = kept["fields"]
    assert f["verdict"] == "validated" and f["signer_name"] == "Jane Doe"
    assert f["signer_key"] == crypto.public_key_text(accountant)
    assert f["signer_fingerprint"] == crypto.key_fingerprint(f["signer_key"])
    assert f["digest"] == snap["fields"]["digest"] and f["signature"] == document["signature"]
    told = api("GET", f"/api/snapshots/{snap['id']}")
    assert [a["id"] for a in told["attestations"]] == [kept["id"]]
    # Locked from the moment it is made.
    api("PATCH", f"/api/records/attestation/{kept['id']}", {"fields": {"verdict": "rejected"}}, expect=423)
    api("DELETE", f"/api/records/attestation/{kept['id']}", expect=423)


def test_a_wrong_attestation_is_refused_and_says_why(api, accountant, tmp_path):
    book = _book(api)["id"]
    snap = _take(api, book)["snapshot"]
    _deal(api, book, "Another", "2025-01-01")
    other = _take(api, book)["snapshot"]
    assert other["fields"]["digest"] != snap["fields"]["digest"]
    good = _signed(accountant, snap)

    def refused(document, said):
        answer = api("POST", f"/api/snapshots/{snap['id']}/attestations", document, expect=400)
        assert said in answer["detail"], answer

    refused(good | {"statement": "Changed after signing."}, "signature is not the signer's")
    refused(good | {"signature": good["signature"][:-4] + "AAAA"}, "signature is not the signer's")
    refused(_signed(accountant, other), "another digest")
    on_other = sign_attestation(
        accountant, digest=snap["fields"]["digest"], snapshot=other["id"], verdict="validated", signer_name="Jane"
    )
    refused(on_other, "another snapshot")
    refused(good | {"snapshot": other["id"]}, "signature is not")
    refused({"cloudmorrow_attestation": 1}, "no signer")
    refused({"hello": 1}, "not a Cloudmorrow attestation")
    stranger = crypto.load_or_create_signing_key(tmp_path / "stranger.key")
    swapped = good | {"signer": good["signer"] | {"key": crypto.public_key_text(stranger)}}
    refused(swapped, "signature is not the signer's")
    with pytest.raises(NotSigned, match="verdict"):
        verify_attestation(_signed(accountant, snap) | {"verdict": "maybe"})
    # A withdrawn snapshot takes none.
    api("POST", f"/api/snapshots/{snap['id']}/withdraw")
    refused(good, "withdrawn")


def test_the_server_signs_for_its_own_people_with_its_identity(api, config):
    book = _book(api)["id"]
    snap = _take(api, book)["snapshot"]
    identity = api("GET", "/api/identity")
    assert identity["key"].startswith("ed25519:") and identity["fingerprint"] == crypto.key_fingerprint(identity["key"])
    assert (config.data_dir / "identity.key").exists()
    document = api(
        "POST",
        "/api/attest",
        {"digest": snap["fields"]["digest"], "snapshot": snap["id"], "verdict": "qualified", "statement": "One thing."},
    )
    assert document["signer"]["key"] == identity["key"] and document["signer"]["name"] == ADMIN[0]
    assert verify_attestation(document, digest=snap["fields"]["digest"])
    kept = api("POST", f"/api/snapshots/{snap['id']}/attestations", document, expect=201)
    assert kept["fields"]["verdict"] == "qualified"
    api("POST", "/api/attest", {"digest": "md5:x", "verdict": "validated"}, expect=400)
    api("POST", "/api/attest", {"digest": snap["fields"]["digest"], "verdict": "maybe"}, expect=400)


# -- guests ---------------------------------------------------------------------------------
def test_a_guest_link_opens_one_snapshot_and_nothing_else(api, accountant):
    book = _book(api)["id"]
    _deal(api, book, "Roof", "2025-03-01")
    snap = _take(api, book)["snapshot"]
    other = _take(api, book)["snapshot"]
    made = api("POST", f"/api/snapshots/{snap['id']}/guests", {"label": "Acme Accounting", "days": 10}, expect=201)
    assert made["token"].startswith("cmg_") and made["url"].endswith(
        f"/api/guest/snapshots/{snap['id']}?token={made['token']}"
    )
    listed = api("GET", f"/api/snapshots/{snap['id']}/guests")
    assert [(g["label"], g["live"], g["used_at"]) for g in listed] == [("Acme Accounting", True, None)]
    assert "token" not in listed[0]

    client = api.client
    token = made["token"]
    # With no account at all: the snapshot, its bundle, and the attestation door.
    told = client.get(f"/api/guest/snapshots/{snap['id']}", params={"token": token}).json()
    assert told["snapshot"]["id"] == snap["id"] and "guests" not in told
    data = client.get(f"/api/guest/snapshots/{snap['id']}/bundle", params={"token": token}).content
    assert digest_of(data) == snap["fields"]["digest"]
    # As a bearer token, too.
    assert (
        client.get(f"/api/guest/snapshots/{snap['id']}", headers={"Authorization": f"Bearer {token}"}).status_code
        == 200
    )
    posted = client.post(
        f"/api/guest/snapshots/{snap['id']}/attestations", params={"token": token}, json=_signed(accountant, snap)
    )
    assert posted.status_code == 201, posted.text
    assert posted.json()["written_by"] == "guest:Acme Accounting"
    assert api("GET", f"/api/snapshots/{snap['id']}/guests")[0]["used_at"]
    # Not the other snapshot, not the records API, not without the token.
    assert client.get(f"/api/guest/snapshots/{other['id']}", params={"token": token}).status_code == 404
    assert client.get(f"/api/guest/snapshots/{snap['id']}").status_code == 404
    assert client.get(f"/api/guest/snapshots/{snap['id']}", params={"token": "cmg_nope"}).status_code == 404
    assert client.get("/api/records/snapshot", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/records/deal", params={"token": token}).status_code == 401
    # Revoked, it is spent.
    api("DELETE", f"/api/snapshots/{snap['id']}/guests/{made['id']}", expect=204)
    assert client.get(f"/api/guest/snapshots/{snap['id']}", params={"token": token}).status_code == 404
    assert api("GET", f"/api/snapshots/{snap['id']}/guests")[0]["live"] is False


def test_a_link_lasts_as_long_as_said_and_only_its_maker_gives_them_out(api):
    book = _book(api, scope="shared", members=[GUEST[0]])["id"]
    snap = _take(api, book, scope="shared", members=[GUEST[0]])["snapshot"]
    api("POST", f"/api/snapshots/{snap['id']}/guests", {"days": 0}, expect=400)
    api("POST", f"/api/snapshots/{snap['id']}/guests", {"days": 400}, expect=400)
    # A member sees the snapshot and may not hand out links to it.
    assert api("GET", f"/api/snapshots/{snap['id']}", who=GUEST[0])["snapshot"]["id"] == snap["id"]
    api("POST", f"/api/snapshots/{snap['id']}/guests", {"days": 5}, who=GUEST[0], expect=400)
    made = api("POST", f"/api/snapshots/{snap['id']}/guests", {"days": 5}, expect=201)
    with connect(api.state.config.db_path) as conn:
        conn.execute("UPDATE snapshot_guests SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (made["id"],))
        conn.commit()
    assert api.client.get(f"/api/guest/snapshots/{snap['id']}", params={"token": made["token"]}).status_code == 404


# -- who sees what -----------------------------------------------------------------------------
def test_a_snapshot_is_its_takers_unless_shared_and_the_circles_rule_it(api):
    book = _book(api)["id"]
    mine = _take(api, book)["snapshot"]
    api("GET", f"/api/snapshots/{mine['id']}", who=GUEST[0], expect=404)
    assert api("GET", "/api/records/snapshot", who=GUEST[0]) == []
    shared = _take(api, book, scope="shared", members=[GUEST[0]])["snapshot"]
    seen = api("GET", f"/api/snapshots/{shared['id']}", who=GUEST[0])
    assert seen["snapshot"]["members"] == [GUEST[0]] and seen["intact"] is True
    # A circle that does not give snapshots: not there at all.
    circles = api.state.circles
    circles.set_rule("members", "snapshot", "none")
    circles.set_rule("members", "attestation", "none")
    api("GET", f"/api/snapshots/{shared['id']}", who=GUEST[0], expect=404)
    api("POST", "/api/snapshots", {"space_model": "book", "space_id": book}, who=GUEST[0], expect=404)


# -- the command line --------------------------------------------------------------------------
runner = CliRunner()


@pytest.fixture()
def cm(api, monkeypatch, tmp_path):
    """`cm snapshot …` and `cm attest …` against the server, the accountant's key in a config dir of its own."""
    client = api.client
    token = token_for(client, *ADMIN)

    def api_for():
        api_client = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
        api_client._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        )
        return None, api_client

    monkeypatch.setattr(snapshot_cli, "client", api_for)
    monkeypatch.setattr(attest_cli, "client", api_for)
    monkeypatch.setattr(attest_cli, "key_path", lambda: tmp_path / "keys" / "identity.key")
    app = typer.Typer()
    app.add_typer(snapshot_cli.app, name="snapshot")
    app.add_typer(attest_cli.app, name="attest")

    def invoke(*argv: str):
        return runner.invoke(app, list(argv))

    invoke.dir = tmp_path
    return invoke


def test_the_whole_offline_round_trip_on_the_command_line(api, cm):
    book = _book(api)["id"]
    _deal(api, book, "Roof", "2025-03-01")
    taken = cm("snapshot", "take", "book", book, "--series", "Books 2025", "--period", "expected_close:2025-01-01:")
    assert taken.exit_code == 0, taken.output
    assert "Sealed." in taken.output
    listed = cm("snapshot", "list")
    assert listed.exit_code == 0 and "Books" in listed.output and "sealed" in listed.output
    snap_id = api("GET", "/api/records/snapshot")[0]["id"]

    bundle = cm.dir / "books-2025.json"
    wrote = cm("snapshot", "bundle", snap_id, str(bundle))
    assert wrote.exit_code == 0, wrote.output
    assert digest_of(bundle.read_bytes()) == api("GET", f"/api/snapshots/{snap_id}")["digest"]

    # The accountant, on their machine: a key of their own, made on first use.
    signed = cm(
        "attest", "sign", str(bundle), "--verdict", "validated", "--statement", "Checked.", "--name", "Jane Doe"
    )
    assert signed.exit_code == 0, signed.output
    attestation = cm.dir / "books-2025.attestation.json"
    assert attestation.exists() and (cm.dir / "keys" / "identity.key").exists()
    document = json.loads(attestation.read_text())
    assert document["signer"]["name"] == "Jane Doe" and document["snapshot"] == ""
    shown = cm("attest", "key")
    assert shown.exit_code == 0 and document["signer"]["key"] in shown.output
    # Checked with no server at all, and a changed bundle fails it.
    assert cm("attest", "verify", str(bundle), str(attestation)).exit_code == 0
    verified = cm("snapshot", "verify", str(bundle), str(attestation))
    assert verified.exit_code == 0 and "validated by Jane Doe" in verified.output
    forged = cm.dir / "forged.json"
    forged.write_bytes(bundle.read_bytes().replace(b"Roof", b"Roo"))
    assert cm("snapshot", "verify", str(forged), str(attestation)).exit_code == 1

    # Back at the company: kept, and shown.
    kept = cm("snapshot", "attest", snap_id, str(attestation))
    assert kept.exit_code == 0, kept.output
    shown = cm("snapshot", "show", snap_id)
    assert shown.exit_code == 0 and "validated by Jane Doe" in shown.output
    assert "intact" in shown.output
    # The name is remembered for next time.
    again = cm("attest", "sign", str(bundle), "--verdict", "qualified", "--out", str(cm.dir / "again.json"))
    assert again.exit_code == 0, again.output
    assert json.loads((cm.dir / "again.json").read_text())["signer"]["name"] == "Jane Doe"


def test_signing_through_a_guest_link_on_the_command_line(api, cm, monkeypatch):
    book = _book(api)["id"]
    snap = _take(api, book, series="Books 2025")["snapshot"]
    made = api("POST", f"/api/snapshots/{snap['id']}/guests", {"label": "Acme"}, expect=201)
    # The accountant's `httpx` reaches the test server.
    monkeypatch.setattr(attest_cli.httpx, "get", lambda url, **kw: api.client.get(url, follow_redirects=True))
    monkeypatch.setattr(attest_cli.httpx, "post", lambda url, **kw: api.client.post(url, json=kw.get("json")))
    link = "http://testserver" + made["url"][made["url"].index("/api/guest") :]
    sent = cm("attest", "sign", link, "--verdict", "validated", "--name", "Jane Doe", "--organisation", "Acme")
    assert sent.exit_code == 0, sent.output
    assert "Sent." in sent.output
    told = api("GET", f"/api/snapshots/{snap['id']}")
    assert [(a["fields"]["verdict"], a["fields"]["signer_organisation"]) for a in told["attestations"]] == [
        ("validated", "Acme")
    ]
    assert told["attestations"][0]["written_by"] == "guest:Acme"


def test_signing_via_your_own_server_on_the_command_line(api, cm):
    book = _book(api)["id"]
    snap = _take(api, book)["snapshot"]
    bundle = cm.dir / "b.json"
    bundle.write_bytes(api("GET", f"/api/snapshots/{snap['id']}/bundle", raw=True).content)
    signed = cm("attest", "sign", str(bundle), "--verdict", "rejected", "--via-server")
    assert signed.exit_code == 0, signed.output
    document = json.loads((cm.dir / "b.attestation.json").read_text())
    assert document["signer"]["key"] == api("GET", "/api/identity")["key"]
    assert not (cm.dir / "keys" / "identity.key").exists()
    kept = api("POST", f"/api/snapshots/{snap['id']}/attestations", document, expect=201)
    assert kept["fields"]["verdict"] == "rejected"


def test_a_bundle_that_is_not_one_is_said_so(cm):
    bad = cm.dir / "bad.json"
    bad.write_text('{"hello": 1}')
    assert cm("snapshot", "verify", str(bad)).exit_code == 1
    bad.write_text("not json")
    assert cm("snapshot", "verify", str(bad)).exit_code == 1
    Path(cm.dir / "x.json").write_text("{}")
    assert cm("attest", "sign", str(cm.dir / "x.json"), "--verdict", "validated").exit_code == 1
