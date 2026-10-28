"""`cm backup …`: the server's backups from the command line, against a real server and a bucket on the loopback."""

from __future__ import annotations

import httpx
import pytest
import typer
from typer.testing import CliRunner

from cloudmorrow.cli import backup as backup_cli
from cloudmorrow.client.api import CloudmorrowClient
from cloudmorrow.client.config import ClientConfig
from tests.conftest import ADMIN, token_for
from tests.fake_s3 import FakeS3
from tests.test_backups import a_drive_with_files, set_up

runner = CliRunner(env={"COLUMNS": "200"})


@pytest.fixture()
def store():
    fake = FakeS3().start()
    yield fake
    fake.stop()


@pytest.fixture()
def cm(client, auth, store, config, monkeypatch):
    """`cm backup` signed in as the administrator, with the bucket set up."""
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    token = token_for(client, *ADMIN)

    def api_for():
        api = CloudmorrowClient(ClientConfig(api_url="http://testserver"), token=token)
        api._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver")
        return None, api

    monkeypatch.setattr(backup_cli, "client", api_for)
    monkeypatch.setattr(backup_cli, "POLL", 0.05)
    # The list is a table, and a narrow console cuts the stamps short. rich
    # reads COLUMNS when the console is made, at import, so the runner's own
    # COLUMNS comes too late when the machine had one set: pin the width.
    monkeypatch.setattr(backup_cli.console, "_width", 200)
    app = typer.Typer()
    app.add_typer(backup_cli.app, name="backup")

    def invoke(*argv: str, input: str | None = None):
        return runner.invoke(app, list(argv), input=input)

    invoke.store = store
    invoke.config = config
    return invoke


def test_status_says_where_and_that_nothing_ran_yet(cm):
    told = cm("backup", "status")
    assert told.exit_code == 0, told.output
    assert cm.store.endpoint in told.output
    assert "switched off" in told.output
    assert "Last backup: none yet" in told.output


def test_now_backs_up_and_watches_then_list_and_show(cm):
    ran = cm("backup", "now")
    assert ran.exit_code == 0, ran.output
    assert "bram's files:" in ran.output
    assert "Done:" in ran.output
    stamps = cm.store.stamps("home/")
    assert len(stamps) == 1
    stamp = stamps.pop()
    assert "new" in ran.output

    listed = cm("backup", "list")
    assert listed.exit_code == 0, listed.output
    assert stamp in listed.output and "this server's" in listed.output and "New" in listed.output

    shown = cm("backup", "show", stamp)
    assert shown.exit_code == 0, shown.output
    assert "drive bram:" in shown.output and "2 files" in shown.output and "new" in shown.output

    status = cm("backup", "status")
    assert "The bucket holds" in status.output and "3 objects" in status.output


def test_files_looks_in_a_backup_and_get_pulls_one_out(cm, tmp_path):
    assert cm("backup", "now").exit_code == 0
    stamp = next(iter(cm.store.stamps("home/")))
    top = cm("backup", "files", stamp, "drives/bram", "files")
    assert top.exit_code == 0, top.output
    assert "Notes/" in top.output and "Photos/" in top.output and "1 file" in top.output
    notes = cm("backup", "files", stamp, "drives/bram", "files/Notes")
    assert notes.exit_code == 0, notes.output
    assert "hello.md" in notes.output and "8 B" in notes.output
    out = tmp_path / "hello-then.md"
    got = cm("backup", "get", stamp, "drives/bram/files/Notes/hello.md", "-o", str(out))
    assert got.exit_code == 0, got.output
    assert out.read_text(encoding="utf-8") == "# Hello\n"
    missing = cm("backup", "files", stamp, "drives/nobody")
    assert missing.exit_code != 0 and "no files of nobody" in missing.output


def test_restore_puts_a_drive_back_and_asks_first(cm):
    assert cm("backup", "now").exit_code == 0
    stamp = next(iter(cm.store.stamps("home/")))
    note = cm.config.files_root("bram") / "Notes" / "hello.md"
    note.unlink()
    said_no = cm("backup", "restore", stamp, "--drive", "bram", input="n\n")
    assert said_no.exit_code == 1
    assert not note.exists()
    restored = cm("backup", "restore", stamp, "--drive", "bram", "--yes")
    assert restored.exit_code == 0, restored.output
    assert "Restored." in restored.output
    assert note.read_text(encoding="utf-8") == "# Hello\n"
    # Nothing to restore is said, not sent.
    nothing = cm("backup", "restore", stamp, "--yes")
    assert nothing.exit_code == 1 and "say what to restore" in nothing.output
    # --all takes every part the backup has, and only those.
    everything = cm("backup", "restore", stamp, "--all", "--yes")
    assert everything.exit_code == 0, everything.output
    assert "the files of bram, guest" in everything.output
    # One file by its path.
    note.write_text("changed\n", encoding="utf-8")
    one = cm("backup", "restore", stamp, "--path", "drives/bram/files/Notes/hello.md", "--yes")
    assert one.exit_code == 0, one.output
    assert "drives/bram/files/Notes/hello.md" in one.output and note.read_text(encoding="utf-8") == "# Hello\n"


def test_delete_takes_a_backup_out(cm):
    assert cm("backup", "now").exit_code == 0
    stamp = next(iter(cm.store.stamps("home/")))
    gone = cm("backup", "delete", stamp, "--yes")
    assert gone.exit_code == 0, gone.output
    assert cm.store.keys("home/") == [], "the snapshot and the objects only it named"
    assert "No backups" in cm("backup", "list").output
