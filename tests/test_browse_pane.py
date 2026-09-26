"""The Browse view on the Files tab: a share's folders and files, as a list
or as thumbnails, with the picture the cursor is on beside it."""

from __future__ import annotations

from textual.widgets import DataTable, Static, Tab, Tabs

from cloudmorrow.tui.panes.browse import (
    BrowsePane,
    Tile,
    TileGrid,
    format_date,
    format_size,
    kind_of,
    sort_entries,
    type_label,
)
from cloudmorrow.tui.panes.files import FilesharesPane, FilesPane
from cloudmorrow.tui.widgets.picture import Picture
from tests.tui_harness import entry_row, settle, start


async def open_browse(app, pilot):
    screen = await start(app, pilot)
    await pilot.click("#nav-files")
    await settle(app, pilot)
    await pilot.click("#files-tab-browse")
    await settle(app, pilot)
    return screen


def names(screen) -> list[str]:
    table = screen.query_one("#browse-table", DataTable)
    return [str(table.get_row_at(index)[0]) for index in range(table.row_count)]


def status(screen) -> str:
    """The bottom line, and the right of the panel's header, where the pane
    says what the row you are on is."""
    from tests.tui_harness import said

    head = screen.active_pane.query_one(".pane-read", Static).visual.plain
    return f"{said(screen)}  {head}"


# -- the pieces on their own ----------------------------------------------------
def test_a_file_is_known_by_its_type_or_failing_that_its_name():
    assert kind_of(entry_row("Holiday", is_dir=True)) == "folder"
    assert kind_of(entry_row("shot.jpg", mime="image/jpeg")) == "image"
    assert kind_of(entry_row("shot.HEIC")) == "image"
    assert kind_of(entry_row("talk.mp4", mime="video/mp4")) == "video"
    assert kind_of(entry_row("plan.pdf", mime="application/pdf")) == "document"
    assert kind_of(entry_row("notes", mime="text/plain")) == "text"
    assert kind_of(entry_row("blob")) == "file"
    assert type_label(entry_row("plan.pdf")) == "PDF"
    assert type_label(entry_row("blob")) == "File"


def test_sizes_read_the_way_the_web_app_says_them():
    assert format_size(5) == "5 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(4200000) == "4.0 MB"
    assert format_size(123456789) == "118 MB"


def test_folders_come_first_whichever_way_the_files_are_sorted():
    entries = [
        entry_row("b.txt", size=2, modified=2),
        entry_row("Zed", is_dir=True),
        entry_row("a.jpg", size=9, modified=1, mime="image/jpeg"),
        entry_row("apple", is_dir=True),
    ]
    assert [e["name"] for e in sort_entries(entries, "name", False)] == [
        "apple", "Zed", "a.jpg", "b.txt",
    ]
    assert [e["name"] for e in sort_entries(entries, "size", True)] == [
        "Zed", "apple", "a.jpg", "b.txt",
    ]
    assert [e["name"] for e in sort_entries(entries, "date", True)] == [
        "Zed", "apple", "b.txt", "a.jpg",
    ]
    # By type: pictures before text, folders still first.
    assert [e["name"] for e in sort_entries(entries, "type", False)] == [
        "apple", "Zed", "a.jpg", "b.txt",
    ]


# -- in the app -----------------------------------------------------------------
async def test_browse_starts_at_the_shares_and_enter_opens_one(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        pane = screen.query_one(FilesPane)
        assert [tab.label_text for tab in pane.query_one("#files-nav", Tabs).query(Tab)] == [
            "Local backups",
            "Fileshares",
            "Browse",
        ]
        assert isinstance(pane.active_view, BrowsePane)
        assert names(screen) == ["media", "photos"]
        assert "Shares" in screen.query_one("#browse-crumb", Static).visual.plain
        # Enter on a share is its top folder: folders first, then the files
        # by name, each with when, how big and what it is.
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.listing_calls == [("media", "")]
        table = screen.query_one("#browse-table", DataTable)
        assert [[str(c) for c in table.get_row_at(i)] for i in range(table.row_count)] == [
            ["Holiday/", format_date(1_756_800_000), "", "Folder"],
            ["readme.txt", format_date(1_756_700_000), "5 B", "TXT"],
            ["song.mp3", format_date(1_756_600_000), "4.0 MB", "MP3"],
        ]
        assert screen.query_one("#browse-crumb", Static).visual.plain == "media"


async def test_into_a_folder_and_back_up_to_the_shares(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("enter")  # Holiday, the first row
        await settle(app, pilot)
        assert app.client.listing_calls[-1] == ("media", "Holiday")
        assert names(screen) == ["beach.jpg", "dunes.png", "where.txt"]
        assert screen.query_one("#browse-crumb", Static).visual.plain == "media / Holiday"
        # The status bar says what the cursor is on.
        assert "beach.jpg" in status(screen) and "1.2 MB" in status(screen)
        await pilot.press("backspace")
        await settle(app, pilot)
        assert names(screen) == ["Holiday/", "readme.txt", "song.mp3"]
        await pilot.press("backspace")
        await settle(app, pilot)
        assert names(screen) == ["media", "photos"]
        # Backspace at the top goes nowhere.
        await pilot.press("backspace")
        await settle(app, pilot)
        assert names(screen) == ["media", "photos"]


async def test_the_picture_the_cursor_is_on_is_shown_beside_the_list(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        panel = screen.query_one("#browse-picture", Picture)
        # The cursor lands on beach.jpg: fetched small, not the whole photo.
        assert panel.display and panel.shown == "Holiday/beach.jpg"
        assert app.client.share_fetches == ["thumb:media/Holiday/beach.jpg@1024"]
        await pilot.press("down")
        await settle(app, pilot)
        assert panel.shown == "Holiday/dunes.png"
        # A text file has no picture: the panel goes.
        await pilot.press("down")
        await settle(app, pilot)
        assert not panel.display
        # Back up to a picture already fetched: nothing fetched again.
        await pilot.press("up")
        await settle(app, pilot)
        assert panel.shown == "Holiday/dunes.png"
        assert len(app.client.share_fetches) == 2


async def test_v_shows_the_folder_as_thumbnails_and_again_as_a_list(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("v")
        await settle(app, pilot)
        grid = screen.query_one(TileGrid)
        assert screen.query_one("#browse-views").current == "browse-grid"
        tiles = list(grid.query(Tile))
        assert [tile.entry["name"] for tile in tiles] == ["Holiday", "readme.txt", "song.mp3"]
        assert [tile.kind for tile in tiles] == ["folder", "text", "audio"]
        # Nothing here is a picture, so nothing was fetched for a tile.
        assert app.client.share_fetches == []
        # The first tile has the focus; the arrows walk them, enter opens.
        assert screen.focused is tiles[0]
        await pilot.press("right")
        await pilot.pause()
        assert screen.focused is tiles[1]
        assert "readme.txt" in status(screen)
        await pilot.press("left")
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.listing_calls[-1] == ("media", "Holiday")
        # Still thumbnails in the folder below, and now there are pictures:
        # each one fetched small, once, and drawn in its tile.
        tiles = list(screen.query_one(TileGrid).query(Tile))
        assert [tile.kind for tile in tiles] == ["image", "image", "text"]
        assert sorted(f for f in app.client.share_fetches if f.endswith("@256")) == [
            "thumb:media/Holiday/beach.jpg@256",
            "thumb:media/Holiday/dunes.png@256",
        ]
        assert [bool(tile.query(".tile-picture")) for tile in tiles] == [True, True, False]
        # The panel follows the focused tile, as it follows the list's cursor.
        assert screen.query_one("#browse-picture", Picture).shown == "Holiday/beach.jpg"
        # And v again is the list, at the same place.
        await pilot.press("v")
        await settle(app, pilot)
        assert screen.query_one("#browse-views").current == "browse-table"
        assert names(screen) == ["beach.jpg", "dunes.png", "where.txt"]
        assert isinstance(screen.focused, DataTable)


async def test_s_sorts_by_the_next_thing_and_shift_s_turns_it_around(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        assert names(screen) == ["beach.jpg", "dunes.png", "where.txt"]
        await pilot.press("s")  # date: newest first
        await pilot.pause()
        assert names(screen) == ["beach.jpg", "dunes.png", "where.txt"]
        await pilot.press("s")  # size: largest first
        await pilot.pause()
        assert names(screen) == ["beach.jpg", "dunes.png", "where.txt"]
        await pilot.press("S")
        await pilot.pause()
        assert names(screen) == ["where.txt", "dunes.png", "beach.jpg"]
        await pilot.press("s")  # type: pictures before text
        await pilot.pause()
        assert names(screen) == ["beach.jpg", "dunes.png", "where.txt"]
        assert "Sort: Type" in screen.query_one("#do-sort").label.plain


async def test_enter_on_a_share_in_fileshares_opens_it_in_browse(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await start(app, pilot)
        await pilot.click("#nav-files")
        await settle(app, pilot)
        pane = screen.query_one(FilesPane)
        assert isinstance(pane.active_view, FilesharesPane)
        await pilot.press("down")  # photos
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(pane.active_view, BrowsePane)
        assert set(app.client.listing_calls) == {("photos", "")}
        assert screen.query_one("#browse-crumb", Static).visual.plain == "photos"
        assert "Nothing" not in status(screen)
        assert names(screen) == []


async def test_a_machine_share_is_listed_but_says_to_mount_it(app):
    app.client.share_list.append({
        "name": "laptop", "kind": "machine", "machine": "book", "online": False,
        "path": "/home/me/stuff", "managed": False, "description": "", "url": "",
        "created_at": "", "updated_at": "",
    })
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        assert names(screen) == ["media", "photos", "laptop"]
        await pilot.press("down", "down")
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.client.listing_calls == []
        assert "mount it to browse it" in status(screen)


async def test_a_folder_that_is_gone_sends_you_back_to_the_shares(app):
    async with app.run_test(size=(120, 34)) as pilot:
        screen = await open_browse(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        del app.client.share_tree["media"]
        await pilot.press("r")
        await settle(app, pilot)
        assert names(screen) == ["media", "photos"]
        assert "no such folder" in status(screen)
