"""CRM against the real record store and gate: `cm quill test`."""

from pathlib import Path

import pytest

from cloudmorrow.quill.testing import Harness

HERE = Path(__file__).resolve().parent.parent


@pytest.fixture
def q():
    with Harness(HERE) as harness:
        yield harness


def customers(q):
    """The book everybody shares, which the Quill seeds."""
    return next(b for b in q.list("book") if b["name"] == "Customers")


def stages(q, book):
    return sorted(q.list("stage", book=book.id), key=lambda s: s.position)


def test_there_is_a_shared_book_with_the_default_pipeline(q):
    book = customers(q)
    assert book.scope == "public"
    assert [s["name"] for s in stages(q, book)] == [
        "Lead",
        "Qualified",
        "Proposal",
        "Negotiation",
        "Won",
        "Lost",
    ]
    assert [s["outcome"] for s in stages(q, book)][-2:] == ["won", "lost"]


def test_a_new_book_gets_a_pipeline_of_its_own(q):
    mine = q.seed("book", name="Consulting")
    assert len(stages(q, mine)) == 6
    assert len(stages(q, customers(q))) == 6


def test_a_deal_starts_in_the_first_stage_and_follows_its_stage(q):
    book = customers(q)
    org = q.seed("organisation", book=book.id, name="Acme")
    done = q.act("new-deal", org, title="Forty desks", value=12000)
    assert done.toast == "New deal: Forty desks"
    deal = q.list("deal")[0]
    assert q.get("stage", deal["stage"])["name"] == "Lead"
    assert deal["status"] == "open" and deal["currency"] == "EUR"

    assert q.act("won", deal).ok
    deal = q.get("deal", deal.id)
    assert deal["status"] == "won" and deal["closed_at"]
    assert q.get("stage", deal["stage"])["name"] == "Won"

    q.change("deal", deal.id, stage=stages(q, book)[1].id)
    deal = q.get("deal", deal.id)
    assert deal["status"] == "open" and not deal["closed_at"]


def test_losing_a_deal_says_why(q):
    book = customers(q)
    deal = q.seed("deal", book=book.id, title="A van")
    assert q.act("lost", deal, reason="Went with the cheaper one").ok
    deal = q.get("deal", deal.id)
    assert deal["status"] == "lost"
    assert "Went with the cheaper one" in deal["notes"]


def test_the_pipeline_can_be_extended_and_reordered(q):
    book = customers(q)
    assert q.act("add-stage", book, name="Demo", probability=40).ok
    names = [s["name"] for s in stages(q, book)]
    assert names == ["Lead", "Qualified", "Proposal", "Negotiation", "Demo", "Won", "Lost"]
    demo = next(s for s in stages(q, book) if s["name"] == "Demo")
    q.act("stage-earlier", demo)
    q.act("stage-earlier", q.get("stage", demo.id))
    assert [s["name"] for s in stages(q, book)][:4] == ["Lead", "Qualified", "Demo", "Proposal"]
    assert "already first" in q.act("stage-earlier", stages(q, book)[0]).toast


def test_follow_ups_link_to_what_they_are_about(q):
    book = customers(q)
    org = q.seed("organisation", book=book.id, name="Acme")
    person = q.seed("contact", book=book.id, name="Ada", organisation=org.id)
    q.act("follow-up-person", person, title="Call Ada", kind="call", due="2026-10-01T10:00")
    call = q.list("activity")[0]
    assert (call["contact"], call["organisation"], call["book"]) == (person.id, org.id, book.id)
    assert q.act("complete", call).ok
    assert q.get("activity", call.id)["done"] is True


def test_the_sales_page_adds_it_up(q):
    book = customers(q)
    org = q.seed("organisation", book=book.id, name="Acme")
    q.act("new-deal", org, title="Forty desks", value=10000, expected_close="2026-12-01")
    q.act("follow-up-organisation", org, title="Send the quote", kind="email")
    page = q.view("sales").text()
    assert "Forty desks" in page and "Send the quote" in page
    assert "EUR 10,000" in page and "weighted EUR 1,000" in page
    assert "Customers" in page and "Negotiation" in page


def test_a_book_of_ones_own_is_nobody_elses(q):
    # A book is shared when made, with nobody else in it until they are added.
    book = q.seed("book", name="Just me")
    q.seed("organisation", book=book.id, name="Secret client")
    sam = q.as_user("sam")
    assert [o["name"] for o in sam.list("organisation")] == []
    q.seed("organisation", book=customers(q).id, name="Everybody's client")
    assert [o["name"] for o in sam.list("organisation")] == ["Everybody's client"]


def test_won_on_the_deals_own_sheet_moves_it_to_the_won_stage(q):
    book = customers(q)
    deal = q.seed("deal", book=book.id, title="Chairs")
    q.change("deal", deal.id, status="won")
    deal = q.get("deal", deal.id)
    assert q.get("stage", deal["stage"])["name"] == "Won" and deal["closed_at"]
    q.change("deal", deal.id, status="open")
    deal = q.get("deal", deal.id)
    assert q.get("stage", deal["stage"])["name"] == "Lead" and not deal["closed_at"]
