"""Pages: text files through the record API, which is what the editor kit draws.

A note is a Markdown file in the Notes folder of a person's drive and
nothing more, so the `file` datamodel does what the editor needs of it:
a text file's words as its `text`, read one file at a time and written
back with a `rev`; everything under a folder listed at once, with a line
of each page for a list; a search through names and lines; the folders
under a root; and the pictures a page points at, kept in its `img` folder.
"""

from __future__ import annotations

import pytest

from tests.conftest import GUEST
from tests.test_files_quill import call, drive, png


@pytest.fixture()
def files(client):
    """The client with the Files Quill installed from the local catalog."""
    client.app.state.cloudmorrow.quills.install_from_catalog("files")
    return client


def notes(config, username="bram"):
    root = drive(config, username) / "Notes"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_a_text_file_has_its_words_and_a_picture_has_none(files, config):
    root = notes(config)
    (root / "Garden.md").write_text("# Garden\n\nTomatoes, beans.\n")
    (root / "red.png").write_bytes(png())
    listed = call(files, "GET", "/api/records/file?share=my-files&folder=Notes")
    by_name = {f["fields"]["name"]: f for f in listed}
    # A listing never carries the words: reading the one file does.
    assert by_name["Garden.md"]["fields"]["text"] is None
    page = call(files, "GET", f"/api/records/file/{by_name['Garden.md']['id']}")
    assert page["fields"]["text"] == "# Garden\n\nTomatoes, beans.\n"
    picture = call(files, "GET", f"/api/records/file/{by_name['red.png']['id']}")
    assert picture["fields"]["text"] is None


def test_everything_under_a_folder_is_listed_at_once_with_a_line_of_each_page(files, config):
    root = notes(config)
    (root / "Garden.md").write_text("# Garden\n\nTomatoes, beans.\n")
    (root / "ideas").mkdir()
    (root / "ideas" / "Shed.md").write_text("A bigger one.\n")
    (root / "ideas" / "plan.pdf").write_bytes(b"%PDF")
    (root / "img").mkdir()
    (root / "img" / "x.png").write_bytes(png())
    (drive(config) / "cv.txt").write_text("not a note")
    everything = call(files, "GET", "/api/records/file?share=my-files&within=Notes&previews=true")
    assert [(f["fields"]["path"], f["fields"]["kind"]) for f in everything] == [
        ("Notes/Garden.md", "file"),
        ("Notes/ideas", "folder"),
        ("Notes/ideas/plan.pdf", "file"),
        ("Notes/ideas/Shed.md", "file"),
    ]
    assert [f["preview"] for f in everything] == ["Tomatoes, beans.", "", "", "A bigger one."]
    # With a suffix, only the files called so: the pages, and no folders.
    pages = call(files, "GET", "/api/records/file?share=my-files&within=Notes&suffix=.md")
    assert [f["fields"]["path"] for f in pages] == ["Notes/Garden.md", "Notes/ideas/Shed.md"]
    # A root at the top of the drive lists the drive, pictures folder aside.
    assert "Notes/img" not in [f["fields"]["path"] for f in everything]
    assert call(files, "GET", "/api/records/file?share=my-files&within=Nowhere", expect=400)
    assert call(files, "GET", "/api/records/file?share=my-files&within=.git", expect=400)


def test_a_search_reads_names_and_every_line(files, config):
    root = notes(config)
    (root / "Garden.md").write_text("# Garden\n\nTomatoes, beans.\n")
    (root / "ideas").mkdir()
    (root / "ideas" / "Shed.md").write_text("A bigger one, with room for the beans.\n")
    (root / "ideas" / "Beans.md").write_text("Nothing yet.\n")
    found = call(files, "GET", "/api/records/file?share=my-files&within=Notes&suffix=.md&q=beans")
    assert {f["fields"]["path"]: f["preview"] for f in found} == {
        "Notes/Garden.md": "Tomatoes, beans.",
        "Notes/ideas/Shed.md": "A bigger one, with room for the beans.",
        "Notes/ideas/Beans.md": "Beans.md",
    }
    assert call(files, "GET", "/api/records/file?share=my-files&within=Notes&q=carrots") == []


def test_a_page_is_written_from_its_text_and_written_back_with_its_rev(files, config):
    root = notes(config)
    made = call(
        files,
        "POST",
        "/api/records/file",
        {"fields": {"share": "my-files", "path": "Notes/ideas/Shed.md", "text": "# Shed\n\n"}},
        expect=201,
    )
    assert (root / "ideas" / "Shed.md").read_text() == "# Shed\n\n"
    assert made["fields"]["text"] == "# Shed\n\n" and made["fields"]["name"] == "Shed.md"
    # Written back with the rev it was read at; a stale one is refused with the current page.
    saved = call(
        files,
        "PATCH",
        f"/api/records/file/{made['id']}",
        {"fields": {"text": "# Shed\n\nBigger.\n"}, "rev": made["rev"]},
    )
    assert (root / "ideas" / "Shed.md").read_text() == "# Shed\n\nBigger.\n"
    stale = call(
        files, "PATCH", f"/api/records/file/{made['id']}", {"fields": {"text": "no"}, "rev": made["rev"]}, expect=409
    )
    current = stale["detail"]["current"]
    assert current["fields"]["text"] == "# Shed\n\nBigger.\n" and current["rev"] == saved["rev"]
    # Renamed and written in one change; the id follows the path.
    renamed = {"fields": {"name": "Workshop.md", "text": "# Workshop\n"}}
    moved = call(files, "PATCH", f"/api/records/file/{saved['id']}", renamed)
    assert moved["fields"]["path"] == "Notes/ideas/Workshop.md" and moved["fields"]["text"] == "# Workshop\n"
    assert not (root / "ideas" / "Shed.md").exists()
    assert (root / "ideas" / "Workshop.md").read_text() == "# Workshop\n"
    # A second of the same name is refused, and so is text for a name that is not a text file's.
    call(
        files,
        "POST",
        "/api/records/file",
        {"fields": {"share": "my-files", "path": "Notes/ideas/Workshop.md", "text": ""}},
        expect=400,
    )
    call(
        files,
        "POST",
        "/api/records/file",
        {"fields": {"share": "my-files", "path": "Notes/a.png", "text": "x"}},
        expect=400,
    )
    (root / "red.png").write_bytes(png())
    red = next(
        f
        for f in call(files, "GET", "/api/records/file?share=my-files&folder=Notes")
        if f["fields"]["name"] == "red.png"
    )
    assert (
        "not a text file"
        in call(files, "PATCH", f"/api/records/file/{red['id']}", {"fields": {"text": "x"}}, expect=400)["detail"]
    )


def test_pages_are_their_owners_alone(files, config):
    root = notes(config)
    (root / "Private.md").write_text("mine")
    mine = call(files, "GET", "/api/records/file?share=my-files&within=Notes")
    assert [f["fields"]["name"] for f in mine] == ["Private.md"]
    assert call(files, "GET", "/api/records/file?share=my-files&within=Notes", who=GUEST) == []
    assert call(files, "GET", f"/api/records/file/{mine[0]['id']}", who=GUEST, expect=404)
