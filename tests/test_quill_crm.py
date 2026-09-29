"""CRM, as a Quill, and what the core grew for it.

A pipeline is a board whose lanes are records — each book's own stages,
which people add to and reorder — so the kit's board takes a link as its
`lane` as well as an enum. Every book starts with the default stages
because a dataset can be seeded once in every space (`seed = "per-space"`).
Organisations and people are kept in books the whole company shares, and a
record of a datamodel that lives in spaces, put in none, is its writer's own.
A foundational datamodel that grows (contact v2, in a book) reaches a server
that has the older one when a Quill that needs it is installed.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from textual.app import App

from cloudmorrow.cli import quillrun
from cloudmorrow.server.quills import QuillError, QuillRegistry, load_manifest
from cloudmorrow.server.records import Principal, RecordStore
from cloudmorrow.tui.panes.kit_board import BoardPane
from cloudmorrow.tui.widgets.kit import Lane, RecordCard
from tests.conftest import ADMIN, GUEST, QUILL_CATALOG, token_for

FIXTURES = Path(__file__).parent / "fixtures" / "quills"
DATAMODELS = FIXTURES / "datamodels"
PIPELINE = ["Lead", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]


@pytest.fixture()
def crm(client):
    """The CRM Quill from the local catalog, and a way to call it as bram or guest."""
    client.app.state.cloudmorrow.quills.install_from_catalog("crm")
    bram = {"Authorization": f"Bearer {token_for(client, *ADMIN)}"}
    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}

    def call(method, path, body=None, *, who=bram, expect=200, params=None):
        response = client.request(method, path, json=body, headers=who, params=params)
        assert response.status_code == expect, response.text
        return response.json() if response.content else None

    call.bram, call.guest, call.state = bram, guest, client.app.state.cloudmorrow
    return call


def book_named(crm, name, who=None):
    return next(b for b in crm("GET", "/api/records/book", who=who or crm.bram) if b["fields"]["name"] == name)


def stage_names(crm, book_id, who=None):
    rows = crm("GET", "/api/records/stage", params={"book": book_id}, who=who or crm.bram)
    return [s["fields"]["name"] for s in sorted(rows, key=lambda s: s["position"])]


# -- the seeds -------------------------------------------------------------------------
def test_one_book_for_everybody_and_every_book_gets_the_pipeline(crm):
    customers = book_named(crm, "Customers")
    assert customers["scope"] == "public"
    assert stage_names(crm, customers["id"]) == PIPELINE
    # Somebody else looking finds the same book and the same stages, not a second set.
    assert book_named(crm, "Customers", who=crm.guest)["id"] == customers["id"]
    assert stage_names(crm, customers["id"], who=crm.guest) == PIPELINE
    # A book made later gets a pipeline of its own the first time its stages are read.
    team = crm("POST", "/api/records/book", {"fields": {"name": "Team"}}, expect=201)
    assert stage_names(crm, team["id"]) == PIPELINE
    assert len(crm("GET", "/api/records/stage")) == 12


def test_a_per_space_dataset_is_for_a_datamodel_in_a_space(tmp_path):
    folder = tmp_path / "qq"
    folder.mkdir()
    (folder / "quill.toml").write_text(
        '[quill]\nid = "qq"\nname = "Q"\nversion = "1.0.0"\n'
        '[uses]\ndatamodels = ["book"]\n'
        '[[datasets]]\nid = "seeds"\nmodel = "book"\nseed = "per-space"\nrecords = [{ name = "x" }]\n'
    )
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    with pytest.raises(QuillError, match="seeded per space, and book is in none"):
        registry.install(folder, DATAMODELS)


# -- personal when in no space -------------------------------------------------------------
def test_a_contact_in_no_book_is_its_writers_own_and_one_in_a_book_is_the_books(crm):
    mine = crm("POST", "/api/records/contact", {"fields": {"name": "My dentist"}}, expect=201)
    customers = book_named(crm, "Customers")
    shared = crm(
        "POST",
        "/api/records/contact",
        {"fields": {"name": "Ada", "book": customers["id"], "email": "ada@example.com"}},
        expect=201,
    )
    theirs = [c["fields"]["name"] for c in crm("GET", "/api/records/contact", who=crm.guest)]
    assert theirs == ["Ada"]
    crm("GET", f"/api/records/contact/{mine['id']}", who=crm.guest, expect=404)
    assert crm("GET", f"/api/records/contact/{shared['id']}", who=crm.guest)["fields"]["email"] == "ada@example.com"
    # Moved into the book, it is sealed to the book, and everybody there reads it.
    crm(
        "PATCH",
        f"/api/records/contact/{mine['id']}",
        {"fields": {"book": customers["id"], "notes": "Tuesdays"}},
    )
    assert crm("GET", f"/api/records/contact/{mine['id']}", who=crm.guest)["fields"]["notes"] == "Tuesdays"


def test_a_space_link_that_clears_is_refused():
    from cloudmorrow.server.datamodels import DatamodelError, parse_datamodel

    with pytest.raises(DatamodelError, match="cascade, not clear"):
        parse_datamodel(
            {
                "datamodel": {"id": "thing", "in_space": "room"},
                "fields": {
                    "name": {"kind": "string"},
                    "room": {"kind": "link", "to": "room", "on_delete": "clear"},
                },
            }
        )


# -- the board, with record lanes --------------------------------------------------------------
def test_the_pipeline_is_a_board_whose_lanes_are_stages():
    manifest = load_manifest(FIXTURES / "quill-crm")
    board = next(s for s in manifest.screens if s["id"] == "pipeline")
    assert (board["kit"], board["lane"], board["group"], board["done"]) == (
        "board",
        "stage",
        "book",
        {"outcome": "won"},
    )


@pytest.mark.parametrize(
    ("done", "problem"),
    [
        ('"won"', "done = { field = value }"),
        ('{ nope = "won" }', "names 'nope', which stage does not have"),
    ],
)
def test_record_lanes_say_done_by_what_the_lane_has(tmp_path, done, problem):
    source = (FIXTURES / "quill-crm" / "quill.toml").read_text()
    folder = tmp_path / "crm"
    folder.mkdir()
    (folder / "quill.toml").write_text(source.replace('done = { outcome = "won" }', f"done = {done}"))
    (folder / "quill.py").write_text((FIXTURES / "quill-crm" / "quill.py").read_text())
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    with pytest.raises(QuillError, match=re.escape(problem)):
        registry.install(folder, DATAMODELS)


def test_moving_a_deal_to_won_marks_it_won(crm):
    customers = book_named(crm, "Customers")
    stages = sorted(
        crm("GET", "/api/records/stage", params={"book": customers["id"]}),
        key=lambda s: s["position"],
    )
    deal = crm(
        "POST",
        "/api/records/deal",
        {
            "fields": {
                "book": customers["id"],
                "title": "Desks",
                "stage": stages[0]["id"],
                "value": 900,
            }
        },
        expect=201,
    )
    crm(
        "POST",
        f"/api/records/deal/{deal['id']}/move",
        {"fields": {"stage": stages[4]["id"]}, "index": 0},
    )
    crm.state.code.drain()  # hooks run on a thread of their own
    moved = crm("GET", f"/api/records/deal/{deal['id']}")
    assert moved["fields"]["status"] == "won" and moved["fields"]["closed_at"]
    assert moved["fields"]["currency"] == "EUR"


def test_the_sheet_offers_only_the_stages_of_the_deals_own_book():
    kit = (Path(__file__).parent.parent / "src/cloudmorrow/server/web/kit.js").read_text()
    assert 'linkTitles(quill, fields.filter((f) => f.kind === "link"), record, model)' in kit
    assert "function sameHome(target, linked, model, record, through)" in kit
    assert "async function recordLanes(laneModel, groupModel, group)" in kit


# -- a foundational datamodel that grew -------------------------------------------------------
def test_an_older_contact_is_brought_up_to_date_by_a_quill_that_needs_the_newer(tmp_path):
    old = tmp_path / "old"
    (old / "crm").mkdir(parents=True)
    for name in ("contact", "organisation"):
        text = (DATAMODELS / "crm" / f"{name}.toml").read_text()
        lines = [
            line for line in text.splitlines() if not line.startswith(("book =", "in_space", "role =", "industry ="))
        ]
        (old / "crm" / f"{name}.toml").write_text("\n".join(lines).replace("version = 2", "version = 1"))
    registry = QuillRegistry(tmp_path / "quills", tmp_path / "datamodels")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "quill.toml").write_text(
        '[quill]\nid = "people"\nname = "People"\nversion = "1.0.0"\n[uses]\ndatamodels = ["contact"]\n'
    )
    registry.install(plain, old)
    assert registry.datamodels["contact"].version == 1
    store = RecordStore(tmp_path / "cm.db", registry.models, registry.expiries)
    bram = Principal.person("bram")
    kept = store.create(bram, "contact", {"name": "Ada", "notes": "from before"})

    registry.install(FIXTURES / "quill-crm", DATAMODELS)
    assert registry.datamodels["contact"].version == 2
    assert registry.datamodels["contact"].in_space == "book"
    # What was there before is still its owner's, and still opens.
    assert store.get(bram, "contact", kept.id).fields["notes"] == "from before"
    assert store.list(Principal.person("sam"), "contact") == []


# -- the terminal ------------------------------------------------------------------------------
class FakeRecords:
    """Just enough of the API for a board: books, their stages, the deals."""

    def __init__(self) -> None:
        self.rows = {
            "book": [{"id": "r_book1", "fields": {"name": "Customers"}, "position": 0}],
            "stage": [
                {
                    "id": f"r_st{i}",
                    "position": i,
                    "fields": {"book": "r_book1", "name": name, "outcome": outcome},
                }
                for i, (name, outcome) in enumerate(
                    [("Lead", "open"), ("Proposal", "open"), ("Won", "won"), ("Lost", "lost")]
                )
            ],
            "organisation": [{"id": "r_org1", "fields": {"name": "Acme"}, "position": 0}],
            "deal": [
                {
                    "id": "r_d1",
                    "position": 0,
                    "rev": 1,
                    "fields": {
                        "book": "r_book1",
                        "stage": "r_st1",
                        "title": "Desks",
                        "organisation": "r_org1",
                        "value": 900,
                    },
                },
                {
                    "id": "r_d2",
                    "position": 0,
                    "rev": 1,
                    "fields": {"book": "r_book1", "stage": None, "title": "Chairs"},
                },
            ],
        }
        self.moves: list[tuple] = []

    async def records(self, model, **where):
        return [r for r in self.rows.get(model, []) if all(r["fields"].get(k) == v for k, v in where.items())]

    async def move_record(self, model, record_id, fields, index):
        self.moves.append((model, record_id, fields, index))
        for row in self.rows[model]:
            if row["id"] == record_id:
                row["fields"].update(fields)


def crm_quill() -> tuple[dict, dict]:
    from cloudmorrow.server.datamodels import load_datamodel

    models = {}
    for name in ("book", "stage", "deal", "organisation", "contact"):
        model = load_datamodel(DATAMODELS / "crm" / f"{name}.toml", source="foundation").to_dict()
        models[name] = {**model, "access": "write"}
    manifest = load_manifest(FIXTURES / "quill-crm")
    screen = next(s for s in manifest.screens if s["id"] == "pipeline")
    return {"id": "crm", "name": "CRM", "models": models, "jobs": []}, screen


class BoardApp(App):
    def __init__(self, client) -> None:
        super().__init__()
        self.client = client

    def compose(self):
        quill, screen = crm_quill()
        yield BoardPane(quill, screen, id="pane-crm")


def test_the_terminal_board_draws_a_books_stages_as_its_lanes():
    fake = FakeRecords()

    async def run():
        app = BoardApp(fake)
        async with app.run_test(size=(160, 40)) as pilot:
            pane = app.query_one(BoardPane)
            pane.reload()
            for _ in range(20):
                await pilot.pause()
            assert [lane.label for lane in pane.query(Lane)] == ["Lead", "Proposal", "Won", "Lost"]
            assert pane.done == "r_st2"
            by_lane = {lane.label: [c.record["id"] for c in lane.cards()] for lane in pane.query(Lane)}
            # A deal in no stage is drawn in the first, where it can be moved from.
            assert by_lane == {"Lead": ["r_d2"], "Proposal": ["r_d1"], "Won": [], "Lost": []}
            card = next(c for c in pane.query(RecordCard) if c.record["id"] == "r_d1")
            assert "Acme" in str(card.render_card()) and "900" in str(card.render_card())
            pane.post_message(RecordCard.Ticked(card.record))
            for _ in range(10):
                await pilot.pause()
            assert fake.moves[-1] == ("deal", "r_d1", {"stage": "r_st2"}, None)

    asyncio.run(run())


# -- the command line --------------------------------------------------------------------------
def test_the_command_line_names_record_lanes_by_what_they_are_called():
    fake = FakeRecords()
    quill, spec = crm_quill()
    screen = quillrun.Screen(quill, spec)
    lanes, done = asyncio.run(quillrun._lanes(fake, screen, "r_book1"))
    assert [label for _, label in lanes] == ["Lead", "Proposal", "Won", "Lost"]
    assert done == "r_st2"
    assert quillrun._lane_named(lanes, "proposal") == "r_st1"


def test_the_local_catalog_shelves_crm_under_business():
    from cloudmorrow.server.quills import load_catalog

    catalog = load_catalog(str(QUILL_CATALOG))
    entry = next(q for q in catalog.quills if q["id"] == "crm")
    assert entry["category"] == "business" and not entry.get("foundation")
