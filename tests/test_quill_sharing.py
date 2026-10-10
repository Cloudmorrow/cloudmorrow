"""Quills of people's own: installed for one person, shared, promoted, exported (docs/SHARING.md).

Installs `fixtures/quill-budget`, a Quill somebody wrote for themselves, as
alice's own, and walks it the whole way: on her shelf and nobody else's, run
as her, over her data; offered to bob and on his shelf over his; asked for,
approved, promoted for everyone with every record moved; exported in the
shape a repository wants. The code runs in the server's own interpreter
(`quill_code = "trusted"`), as the code tests do.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloudmorrow.server.app import create_app
from cloudmorrow.server.datamodels import ID_RE
from cloudmorrow.server.quills import QuillError, load_manifest
from cloudmorrow.server.quills.manifest import personalise
from cloudmorrow.server.quills.registry import check_personal
from cloudmorrow.server.security import hash_password
from tests.conftest import ADMIN, token_for
from tests.test_quills import FLEET, VISIT, write_quill

BUDGET = Path(__file__).parent / "fixtures" / "quill-budget"
PASSWORD = "a-password-long-enough"


def _tarball(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.add(path, arcname=str(path.relative_to(folder)))
    return buffer.getvalue()


def state_of(client: TestClient):
    return client.app.state.cloudmorrow


@pytest.fixture()
def server(config, users):
    """A server with alice and bob on it besides the administrator, and alice's Budget uploaded."""
    config.quill_code = "trusted"
    users.create("alice", hash_password(PASSWORD))
    users.create("bob", hash_password(PASSWORD))
    client = TestClient(create_app(config))
    who = {
        name: {"Authorization": "Bearer " + token_for(client, name, PASSWORD if name != ADMIN[0] else ADMIN[1])}
        for name in ("alice", "bob", ADMIN[0])
    }
    return client, who


@pytest.fixture()
def budget(server):
    client, who = server
    answer = client.post("/api/quills/mine/upload", content=_tarball(BUDGET), headers=who["alice"])
    assert answer.status_code == 201, answer.text
    return client, who


def add_envelope(client, headers, name="Food"):
    answer = client.post("/api/quills/budget/actions/add-envelope", json={"fields": {"name": name}}, headers=headers)
    assert answer.status_code == 200, answer.text
    return answer.json()["effects"][1]["id"]


# -- the manifest, read as somebody's own ------------------------------------------------------------
def test_a_datamodel_id_may_carry_its_owners_name():
    assert ID_RE.match("~alice.budget.envelope") and ID_RE.match("budget.envelope") and ID_RE.match("task")
    assert not ID_RE.match("~alice.budget.envelope.more") and not ID_RE.match("alice.budget.envelope")


def test_personalising_renames_what_the_quill_introduces_and_nothing_else():
    manifest = personalise(load_manifest(BUDGET), "alice")
    assert manifest.owner == "alice" and manifest.key == "~alice.budget" and manifest.id == "budget"
    assert {m.id for m in manifest.introduces} == {"~alice.budget.envelope", "~alice.budget.entry"}
    entry = next(m for m in manifest.introduces if m.id.endswith("entry"))
    assert entry.by_name["envelope"].to == "~alice.budget.envelope"
    assert [s["model"] for s in manifest.screens] == ["~alice.budget.envelope", "~alice.budget.envelope", "contact"]
    assert manifest.hooks[0]["on"] == "~alice.budget.entry"
    assert next(a for a in manifest.actions if a["id"] == "spend")["on"] == "~alice.budget.envelope"
    assert (
        manifest.resolve("budget.entry") == "~alice.budget.entry"
        and manifest.plain("~alice.budget.entry") == "budget.entry"
    )
    assert manifest.resolve("contact") == "contact"
    assert "~alice.budget.envelope" in manifest.models and "contact" in manifest.models


EXTENDS = '[[extends]]\nmodel = "vehicle"\n[extends.fields]\nodometer = { kind = "int", indexed = true }\n'
SHARED_VISIT = VISIT.replace('title = "what"', 'title = "what"\nscopes = ["personal", "shared"]')


@pytest.mark.parametrize(
    ("manifest", "datamodels", "says"),
    [
        (FLEET, {"visit": VISIT}, "adds no fields"),
        (FLEET.replace(EXTENDS, ""), {"visit": VISIT}, "runs no \\[\\[services\\]\\]"),
        (FLEET.split("[[services]]")[0].replace(EXTENDS, ""), {"visit": SHARED_VISIT}, "personal only"),
    ],
)
def test_what_a_quill_of_ones_own_may_not_do_is_refused_in_words(tmp_path, manifest, datamodels, says):
    folder = write_quill(tmp_path / "fleet", manifest, **datamodels)
    with pytest.raises(QuillError, match=says):
        check_personal(load_manifest(folder, owner="alice"))


# -- on one shelf, over one person's data ------------------------------------------------------------
def test_a_quill_of_your_own_is_on_your_shelf_and_nobody_elses(budget):
    client, who = budget
    mine = {q["id"]: q for q in client.get("/api/quills", headers=who["alice"]).json()}
    assert mine["budget"]["mine"] is True and mine["budget"]["key"] == "~alice.budget"
    assert mine["budget"]["owner"] == "alice" and mine["budget"]["personal"] is True
    assert set(mine["budget"]["models"]) >= {"~alice.budget.envelope", "~alice.budget.entry", "contact"}
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who[ADMIN[0]]).json()}
    # Nor is its datamodel: not listed, and refused as if it were not there.
    bobs = {m["id"] for m in client.get("/api/datamodels", headers=who["bob"]).json()}
    assert "~alice.budget.envelope" not in bobs
    assert client.get("/api/records/~alice.budget.envelope", headers=who["bob"]).status_code == 404
    assert client.post(
        "/api/records/~alice.budget.envelope", json={"fields": {"name": "x"}}, headers=who["bob"]
    ).status_code in (403, 404)
    assert "~alice.budget.envelope" in {m["id"] for m in client.get("/api/datamodels", headers=who["alice"]).json()}
    # The switch for it is hers, under its key; bob has none.
    assert "~alice.budget" in {f["key"] for f in client.get("/api/me/features", headers=who["alice"]).json()}
    assert "~alice.budget" not in {f["key"] for f in client.get("/api/me/features", headers=who["bob"]).json()}


def test_its_code_runs_as_the_owner_under_the_quills_own_names(budget):
    client, who = budget
    pot = add_envelope(client, who["alice"])
    rows = client.get("/api/records/~alice.budget.envelope", headers=who["alice"]).json()
    assert [r["fields"]["name"] for r in rows] == ["Food"] and rows[0]["owner"] == "alice"
    spent = client.post(
        "/api/quills/budget/actions/spend", json={"record": pot, "fields": {"amount": 12}}, headers=who["alice"]
    )
    assert spent.status_code == 200, spent.text
    # The hook ran, as her, and kept the total.
    state_of(client).code.drain()
    assert (
        client.get(f"/api/records/~alice.budget.envelope/{pot}", headers=who["alice"]).json()["fields"]["total"] == 12
    )
    view = client.get("/api/quills/budget/views/overview", headers=who["alice"]).json()
    assert "alice's budget" in str(view["tree"])
    assert client.get("/api/quills/budget/views/overview", headers=who["bob"]).status_code == 404


def test_its_jobs_webhooks_and_apis_run_as_its_owner(budget):
    client, who = budget
    add_envelope(client, who["alice"], "Rent")
    state = state_of(client)
    state.code.run_job("~alice.budget", "nightly")
    assert any("envelopes: 1" in line for line in state.code.tail("~alice.budget"))
    secret = state.quill_tokens.webhook_secret("~alice.budget", "bank")
    assert client.post("/hooks/~alice.budget/bank", json={"envelope": "Rent", "amount": 5}).status_code == 401
    answer = client.post(f"/hooks/~alice.budget/bank?token={secret}", json={"envelope": "Rent", "amount": 5})
    assert answer.status_code == 200, answer.text
    state.code.drain()
    rows = client.get("/api/records/~alice.budget.envelope", headers=who["alice"]).json()
    assert rows[0]["fields"]["total"] == 5
    # Her webhook's address is on her own page, with its secret.
    page = client.get("/api/quills/mine/budget", headers=who["alice"]).json()
    assert page["webhook_urls"][0]["url"].endswith("/hooks/~alice.budget/bank")
    assert page["webhook_urls"][0]["secret"] == secret
    # The API answers as her, told who asked.
    assert client.get("/api/q/~alice.budget/summary", headers=who["bob"]).json() == {"envelopes": 1, "asked_by": "bob"}


def test_an_assistant_gets_its_actions_as_tools_only_on_the_shelf_they_stand_on(budget):
    from cloudmorrow.server import mcptools

    client, _ = budget
    state = state_of(client)
    alice, bob = state.users.get("alice"), state.users.get("bob")
    assert "budget_add_envelope" in {t.name for t in mcptools.available(state, alice)}
    assert "budget_add_envelope" not in {t.name for t in mcptools.available(state, bob)}
    made = mcptools.call(state, alice, "budget_add_envelope", {"name": "Via assistant"})
    assert not made.get("isError"), made


# -- shared --------------------------------------------------------------------------------------------
def share_with_bob(client, who):
    offered = client.put("/api/quills/mine/budget/share", json={"people": ["bob"]}, headers=who["alice"])
    assert offered.status_code == 200, offered.text
    assert offered.json()[0] == offered.json()[0] | {"username": "bob", "state": "offered"}
    accepted = client.post("/api/quills/offers/alice/budget/accept", headers=who["bob"])
    assert accepted.status_code == 200, accepted.text


def test_sharing_is_an_offer_bob_says_yes_to_and_then_it_is_over_his_own_data(budget):
    client, who = budget
    add_envelope(client, who["alice"], "Food")
    offered = client.put("/api/quills/mine/budget/share", json={"people": ["bob"]}, headers=who["alice"])
    assert offered.status_code == 200, offered.text
    # Told, and not yet his.
    assert any(n["kind"] == "quill.offered" for n in client.get("/api/notifications", headers=who["bob"]).json())
    mine = client.get("/api/quills/mine", headers=who["bob"]).json()
    assert mine["offers"][0]["state"] == "offered" and mine["offers"][0]["name"] == "Budget"
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert client.post("/api/quills/offers/alice/budget/accept", headers=who["bob"]).status_code == 200
    shelf = {q["id"]: q for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert shelf["budget"]["shared_by"] == "alice" and shelf["budget"]["mine"] is False
    # His envelopes are his; hers stay hers.
    assert client.get("/api/records/~alice.budget.envelope", headers=who["bob"]).json() == []
    pot = add_envelope(client, who["bob"], "Beer")
    assert [
        r["fields"]["name"] for r in client.get("/api/records/~alice.budget.envelope", headers=who["alice"]).json()
    ] == ["Food"]
    assert client.get("/api/records/~alice.budget.envelope", headers=who["bob"]).json()[0]["owner"] == "bob"
    # Her hook runs for his write, as him, on his record.
    client.post("/api/quills/budget/actions/spend", json={"record": pot, "fields": {"amount": 3}}, headers=who["bob"])
    state_of(client).code.drain()
    assert client.get(f"/api/records/~alice.budget.envelope/{pot}", headers=who["bob"]).json()["fields"]["total"] == 3
    # Alice sees who has it; bob may leave, and then it is gone from his shelf, his records kept.
    assert client.get("/api/quills/mine/budget", headers=who["alice"]).json()["shared_with"][0]["state"] == "accepted"
    assert client.delete("/api/quills/offers/alice/budget", headers=who["bob"]).status_code == 200
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert state_of(client).records.count_all("~alice.budget.envelope") == 2


def test_a_shared_quill_is_narrowed_by_the_other_persons_circles(budget):
    client, who = budget
    share_with_bob(client, who)
    state = state_of(client)
    thrifty = state.circles.create("Thrifty", rules={"*": "write", "contact": "none"})
    for circle in state.circles.circles_of("bob"):
        state.circles.leave(circle.id, "bob")
    state.circles.join(thrifty.id, "bob")
    bobs = next(q for q in client.get("/api/quills", headers=who["bob"]).json() if q["id"] == "budget")
    assert [s["id"] for s in bobs["screens"]] == ["overview", "envelopes"]
    alices = next(q for q in client.get("/api/quills", headers=who["alice"]).json() if q["id"] == "budget")
    assert [s["id"] for s in alices["screens"]] == ["overview", "envelopes", "people"]


def test_taking_it_back_and_removing_it_leave_everybodys_records(budget):
    client, who = budget
    share_with_bob(client, who)
    add_envelope(client, who["bob"], "Beer")
    client.delete("/api/quills/mine/budget/share/bob", headers=who["alice"])
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who["bob"]).json()}
    brought = client.get("/api/quills/mine/budget/brought", headers=who["alice"]).json()
    assert {b["id"]: b["records"] for b in brought} == {"~alice.budget.envelope": 1, "~alice.budget.entry": 0}
    assert client.delete("/api/quills/mine/budget", headers=who["alice"]).status_code == 200
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who["alice"]).json()}
    assert state_of(client).records.count_all("~alice.budget.envelope") == 1
    # Dropping takes them.
    client.post("/api/quills/mine/upload", content=_tarball(BUDGET), headers=who["alice"])
    client.delete("/api/quills/mine/budget?drop=~alice.budget.envelope", headers=who["alice"])
    assert state_of(client).records.count_all("~alice.budget.envelope") == 0


# -- the policy ----------------------------------------------------------------------------------------
def test_an_administrator_switches_quills_of_peoples_own_off_on_or_to_asking(budget):
    client, who = budget
    admin = who[ADMIN[0]]
    assert client.put("/api/quills/policy", json={"personal_quills": "off"}, headers=who["alice"]).status_code == 403
    assert client.put("/api/quills/policy", json={"personal_quills": "off"}, headers=admin).status_code == 200
    assert "budget" not in {q["id"] for q in client.get("/api/quills", headers=who["alice"]).json()}
    assert client.post("/api/quills/mine/upload", content=_tarball(BUDGET), headers=who["alice"]).status_code == 403
    client.put("/api/quills/policy", json={"personal_quills": "ask"}, headers=admin)
    refused = client.post("/api/quills/mine/upload", content=_tarball(BUDGET), headers=who["alice"])
    assert refused.status_code == 403 and "request" in refused.json()["detail"]
    client.put("/api/quills/policy", json={"personal_quills": "on", "personal_quill_code": "off"}, headers=admin)
    refused = client.post("/api/quills/mine/upload", content=_tarball(BUDGET), headers=who["alice"])
    assert refused.status_code == 403 and "code" in refused.json()["detail"]
    assert client.put("/api/quills/policy", json={"personal_quills": "sometimes"}, headers=admin).status_code == 400
    policy = client.get("/api/quills/policy", headers=who["alice"]).json()
    assert (
        policy["personal_quill_code"] == "off" and policy["may"]["code"] is False and policy["may"]["install"] is True
    )


def test_sharing_can_be_switched_off(budget):
    client, who = budget
    client.put("/api/quills/policy", json={"personal_quill_sharing": "off"}, headers=who[ADMIN[0]])
    assert (
        client.put("/api/quills/mine/budget/share", json={"people": ["bob"]}, headers=who["alice"]).status_code == 403
    )


# -- asked for, and approved ---------------------------------------------------------------------------
def test_a_request_is_asked_approved_for_an_audience_and_told_of(server):
    client, who = server
    admin = who[ADMIN[0]]
    asked = client.post("/api/quills/requests", json={"id": "tasks", "note": "for my chores"}, headers=who["bob"])
    assert asked.status_code == 201, asked.text
    assert client.post("/api/quills/requests", json={"id": "tasks"}, headers=who["bob"]).status_code == 400
    assert any(n["kind"] == "quill.requested" for n in client.get("/api/notifications", headers=admin).json())
    assert client.get("/api/quills/requests", headers=who["alice"]).json() == []
    assert [r["id"] for r in client.get("/api/quills/requests", headers=admin).json()] == [asked.json()["id"]]
    assert (
        client.post(f"/api/quills/requests/{asked.json()['id']}/approve", json={}, headers=who["bob"]).status_code
        == 403
    )
    approved = client.post(
        f"/api/quills/requests/{asked.json()['id']}/approve",
        json={"audience": {"people": ["bob"]}, "note": "yours alone for now"},
        headers=admin,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "approved" and approved.json()["installed"] == "tasks"
    assert "tasks" in {q["id"] for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert "tasks" not in {q["id"] for q in client.get("/api/quills", headers=who["alice"]).json()}
    assert any(n["kind"] == "quill.approved" for n in client.get("/api/notifications", headers=who["bob"]).json())
    # The audience is the administrator's to widen later: to a circle, or to everyone.
    widened = client.put("/api/quills/tasks/audience", json={"circles": ["Members"]}, headers=admin)
    assert widened.status_code == 200, widened.text
    assert "tasks" in {q["id"] for q in client.get("/api/quills", headers=who["alice"]).json()}
    everything = client.get("/api/quills/all", headers=admin).json()
    assert next(q for q in everything["server"] if q["id"] == "tasks")["audience"] == {
        "circles": ["Members"],
        "people": [],
    }


def test_a_request_may_be_declined_or_withdrawn(server):
    client, who = server
    admin = who[ADMIN[0]]
    first = client.post("/api/quills/requests", json={"id": "tasks"}, headers=who["bob"]).json()
    declined = client.post(f"/api/quills/requests/{first['id']}/decline", json={"note": "not yet"}, headers=admin)
    assert declined.json()["state"] == "declined"
    second = client.post("/api/quills/requests", json={"id": "chat"}, headers=who["bob"]).json()
    assert client.delete(f"/api/quills/requests/{second['id']}", headers=who["alice"]).status_code == 403
    assert client.delete(f"/api/quills/requests/{second['id']}", headers=who["bob"]).json()["state"] == "withdrawn"
    assert client.get("/api/quills/requests", headers=admin).json() == []
    assert len(client.get("/api/quills/requests?all=true", headers=who["bob"]).json()) == 2


# -- promoted --------------------------------------------------------------------------------------------
def test_promotion_makes_it_the_servers_and_moves_everybodys_records(budget):
    client, who = budget
    admin = who[ADMIN[0]]
    share_with_bob(client, who)
    food = add_envelope(client, who["alice"], "Food")
    add_envelope(client, who["bob"], "Beer")
    client.post(
        "/api/quills/budget/actions/spend", json={"record": food, "fields": {"amount": 7}}, headers=who["alice"]
    )
    state_of(client).code.drain()
    promoted = client.post("/api/quills/promote", json={"owner": "alice", "id": "budget"}, headers=admin)
    assert promoted.status_code == 201, promoted.text
    assert promoted.json()["moved"] == {"budget.envelope": 2, "budget.entry": 1}
    state = state_of(client)
    assert state.quills.personal == {} and "budget" in state.quills.quills
    assert state.records.count_all("~alice.budget.envelope") == 0
    for person in ("alice", "bob", ADMIN[0]):
        shelf = {q["id"]: q for q in client.get("/api/quills", headers=who[person]).json()}
        assert shelf["budget"]["key"] == "budget" and shelf["budget"]["personal"] is False, person
    # Everybody's records came with it, still their own, sealed again under the new name.
    alices = client.get("/api/records/budget.envelope", headers=who["alice"]).json()
    assert [(r["fields"]["name"], r["fields"]["total"]) for r in alices] == [("Food", 7)]
    assert [r["fields"]["name"] for r in client.get("/api/records/budget.envelope", headers=who["bob"]).json()] == [
        "Beer"
    ]
    assert client.get(f"/api/records/budget.envelope/{food}/history", headers=who["alice"]).status_code == 200
    # And the code runs on, as the server's, for anybody.
    add_envelope(client, who[ADMIN[0]], "Tools")
    assert state.quills.quills["budget"].origin["promoted_from"] == "alice"
    assert any(n["kind"] == "quill.promoted" for n in client.get("/api/notifications", headers=who["alice"]).json())


def test_a_promotion_may_be_asked_for(budget):
    client, who = budget
    asked = client.post("/api/quills/requests", json={"kind": "promote", "id": "budget"}, headers=who["alice"])
    assert asked.status_code == 201, asked.text
    assert (
        client.post("/api/quills/requests", json={"kind": "promote", "id": "nope"}, headers=who["alice"]).status_code
        == 404
    )
    approved = client.post(
        f"/api/quills/requests/{asked.json()['id']}/approve",
        json={"audience": {"circles": ["Members"]}},
        headers=who[ADMIN[0]],
    )
    assert approved.status_code == 200, approved.text
    assert "budget" in state_of(client).quills.quills


def test_a_server_quill_of_the_same_id_adopts_somebodys_own_on_the_install_sheet(budget, tmp_path):
    client, who = budget
    admin = who[ADMIN[0]]
    add_envelope(client, who["alice"], "Food")
    plan = client.post("/api/quills/plan", json={"source": str(BUDGET)}, headers=admin).json()
    assert plan["adopt"] == [{"owner": "alice", "version": "0.2.0", "records": ["budget.entry", "budget.envelope"]}]
    installed = client.post("/api/quills", json={"source": str(BUDGET), "adopt": ["alice"]}, headers=admin)
    assert installed.status_code == 201, installed.text
    assert installed.json()["adopted"] == {"alice": {"budget.envelope": 1, "budget.entry": 0}}
    assert [r["fields"]["name"] for r in client.get("/api/records/budget.envelope", headers=who["alice"]).json()] == [
        "Food"
    ]
    assert state_of(client).quills.personal == {}


# -- exported, and forked ------------------------------------------------------------------------------------
def test_exporting_writes_the_templates_shape_around_it_and_only_the_datasets_chosen(budget):
    client, who = budget
    pot = add_envelope(client, who["alice"], "Food")
    client.post("/api/quills/budget/actions/spend", json={"record": pot, "fields": {"amount": 7}}, headers=who["alice"])
    answer = client.get("/api/quills/mine/budget/export", headers=who["alice"])
    assert answer.status_code == 200 and answer.headers["content-type"] == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(answer.content), mode="r:gz") as archive:
        names = set(archive.getnames())
        manifest = archive.extractfile("quill-budget/quill.toml").read().decode()
        claude = archive.extractfile("quill-budget/CLAUDE.md").read().decode()
    assert {"quill-budget/quill.py", "quill-budget/tests/test_quill.py", "quill-budget/pyproject.toml"} <= names
    assert (
        "quill-budget/.github/workflows/check.yml" in names
        and "quill-budget/.claude/skills/quill-data/SKILL.md" in names
    )
    assert "quill-budget/.origin.json" not in names and "quill-budget/datasets/envelope.toml" not in names
    assert "~alice" not in manifest and "Working on this Quill" in claude
    chosen = client.get("/api/quills/mine/budget/export?datasets=budget.envelope", headers=who["alice"])
    with tarfile.open(fileobj=io.BytesIO(chosen.content), mode="r:gz") as archive:
        dataset = archive.extractfile("quill-budget/datasets/envelope.toml").read().decode()
        manifest = archive.extractfile("quill-budget/quill.toml").read().decode()
    assert 'name = "Food"' in dataset and "total = 7" in dataset
    assert 'model = "budget.envelope"' in manifest and 'seed = "per-owner"' in manifest
    assert client.get("/api/quills/mine/budget/export?datasets=contact", headers=who["alice"]).status_code == 400


def test_forking_makes_a_quill_of_your_own_under_a_new_id(budget):
    client, who = budget
    share_with_bob(client, who)
    forked = client.post(
        "/api/quills/mine/fork", json={"id": "budget", "new_id": "spending", "name": "Spending"}, headers=who["bob"]
    )
    assert forked.status_code == 201, forked.text
    shelf = {q["id"]: q for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert shelf["spending"]["mine"] is True and shelf["spending"]["name"] == "Spending"
    assert "~bob.spending.envelope" in shelf["spending"]["models"]
    assert state_of(client).quills.personal["bob"]["spending"].origin["forked_from"] == "~alice.budget"
    assert (
        client.post(
            "/api/quills/spending/actions/add-envelope", json={"fields": {"name": "Beer"}}, headers=who["bob"]
        ).status_code
        == 200
    )
    assert (
        client.post("/api/quills/mine/fork", json={"id": "budget", "new_id": "budget"}, headers=who["bob"]).status_code
        == 400
    )


# -- the server's Quills, for some ------------------------------------------------------------------------
def test_an_administrator_installs_for_circles_or_people_and_the_rest_do_not_see_it(server):
    client, who = server
    admin = who[ADMIN[0]]
    state = state_of(client)
    parents = state.circles.create("Parents", rules={"*": "write"})
    state.circles.join(parents.id, "alice")
    installed = client.post("/api/quills", json={"id": "tasks", "audience": {"circles": ["Parents"]}}, headers=admin)
    assert installed.status_code == 201, installed.text
    assert "tasks" in {q["id"] for q in client.get("/api/quills", headers=who["alice"]).json()}
    assert "tasks" not in {q["id"] for q in client.get("/api/quills", headers=who["bob"]).json()}
    assert client.get("/api/quills/tasks", headers=who["bob"]).status_code == 404
    assert client.get("/api/quills/tasks", headers=who["alice"]).json()["audience"] == {
        "circles": ["Parents"],
        "people": [],
    }
    # The data is still the gate's business: the audience is about the software.
    assert client.get("/api/records/task", headers=who["bob"]).status_code == 200


def test_the_owners_machine_is_offered_a_shared_quills_handlers(budget, tmp_path):
    client, who = budget
    share_with_bob(client, who)
    state = state_of(client)
    _, token = state.agents.enroll_for_user("bob", name="laptop")
    offered = client.get("/api/agent/quills", headers={"Authorization": f"Bearer {token}"}).json()
    assert [q["id"] for q in offered] == ["budget"] and offered[0]["owner"] == "bob"
    code = client.get("/api/agent/quills/budget/code", headers={"Authorization": f"Bearer {token}"})
    assert code.status_code == 200
    answer = client.post(
        "/api/agent/quills/budget/host",
        json={"op": "records.list", "args": {"model": "budget.envelope"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert answer.json() == {"ok": True, "value": []}
    _, carols = state.agents.enroll_for_user(ADMIN[0], name="desk")
    assert client.get("/api/agent/quills", headers={"Authorization": f"Bearer {carols}"}).json() == []
