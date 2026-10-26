"""Backups: everything into a bucket, every day, and back (server/backups.py, server/s3.py).

Against a bucket on the loopback (tests/fake_s3.py) that answers the way
a store does and turns away anything unsigned. What a real store would
make of the signature is not tried here; its shape is.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sqlite3
import tarfile
import time

import pytest

from cloudmorrow.server import backups as backups_module
from cloudmorrow.server.backups import PARTS, BackupError, Choice, key_fingerprint, split_path
from cloudmorrow.server.s3 import Bucket, S3Error, Uploader, region_of
from tests.conftest import GUEST, sqlite_only, token_for
from tests.fake_s3 import FakeS3

SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.fixture()
def store():
    fake = FakeS3().start()
    yield fake
    fake.stop()


@pytest.fixture()
def bucket(store) -> Bucket:
    return Bucket(store.endpoint, store.bucket, store.access_key, SECRET)


def set_up(client, auth, store, **more) -> dict:
    body = {
        "endpoint": store.endpoint,
        "bucket": store.bucket,
        "access_key": store.access_key,
        "secret_key": SECRET,
        "prefix": "home",
        **more,
    }
    response = client.patch("/api/server/backup", headers=auth, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def backups_of(client):
    return client.app.state.cloudmorrow.backups


def wait_done(client, timeout: float = 30.0) -> dict:
    backups_of(client).wait(timeout)
    return backups_of(client).status()


def a_drive_with_files(client, config):
    state = client.app.state.cloudmorrow
    state.ensure_drive("bram")
    (config.files_root("bram") / "Notes" / "hello.md").write_text("# Hello\n", encoding="utf-8")
    (config.files_root("bram") / "Photos").mkdir()
    (config.files_root("bram") / "Photos" / "cat.jpg").write_bytes(b"\xff\xd8" + b"cat" * 100)
    state.ensure_drive(GUEST[0])
    (config.files_root(GUEST[0]) / "Notes" / "mine.md").write_text("guest's\n", encoding="utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def index_of(store, key: str) -> dict:
    return json.loads(gzip.decompress(store.objects[key]))


def object_puts(store) -> list[str]:
    return [key for method, key in store.requests if method == "PUT" and "/objects/" in key]


def back_up(client, auth, parts=None) -> str:
    body = {"parts": parts} if parts else {}
    started = client.post("/api/server/backup/run", headers=auth, json=body)
    assert started.status_code == 202, started.text
    status = wait_done(client)
    assert status["last"]["ok"], status["last"]
    return status["last"]["stamp"]


# -- the bucket -----------------------------------------------------------------------
def test_an_object_goes_up_and_comes_down_signed(bucket, store):
    bucket.put("a/b.txt", b"hello")
    assert bucket.get("a/b.txt") == b"hello"
    listed = bucket.list("a/")
    assert listed.keys == [("a/b.txt", 5)]
    bucket.delete("a/b.txt")
    with pytest.raises(S3Error) as refused:
        bucket.get("a/b.txt")
    assert refused.value.status == 404
    assert all(method in ("GET", "PUT", "DELETE") for method, _ in store.requests)


def test_a_wrong_key_is_turned_away_in_words(store):
    wrong = Bucket(store.endpoint, store.bucket, "SOMEBODYELSE", SECRET)
    with pytest.raises(S3Error, match="secret key"):
        wrong.put("x", b"y")


def test_a_large_object_goes_up_in_parts(bucket, store):
    data = bytes(range(256)) * 40  # 10240 bytes
    up = Uploader(bucket, "big.bin", part_size=4096)
    up.write(data[:5000])
    up.write(data[5000:])
    up.close()
    assert up.size == len(data)
    assert store.objects["big.bin"] == data
    posts = [key for method, key in store.requests if method == "POST"]
    assert posts == ["big.bin", "big.bin"], "begun and completed"
    assert not store.uploads, "nothing left half way"


def test_a_small_object_is_one_put(bucket, store):
    up = Uploader(bucket, "small.bin", part_size=4096)
    up.write(b"tiny")
    up.close()
    assert store.objects["small.bin"] == b"tiny"
    assert [m for m, _ in store.requests] == ["PUT"]


def test_an_abandoned_upload_leaves_nothing(bucket, store):
    up = Uploader(bucket, "gone.bin", part_size=1024)
    up.write(b"x" * 3000)
    up.abandon()
    assert "gone.bin" not in store.objects
    assert not store.uploads


def test_amazon_is_spoken_to_by_host_and_everybody_else_by_path():
    amazon = Bucket("https://s3.eu-north-1.amazonaws.com", "my-cloud", "k", "s")
    assert amazon.host == "my-cloud.s3.eu-north-1.amazonaws.com"
    assert amazon.base_path == ""
    assert amazon.region == "eu-north-1"
    other = Bucket("https://fsn1.your-objectstorage.com", "my-cloud", "k", "s")
    assert other.host == "fsn1.your-objectstorage.com"
    assert other.base_path == "/my-cloud"
    assert other.region == "us-east-1"
    minio = Bucket("http://minio:9000", "backups", "k", "s", region="home")
    assert minio.host == "minio:9000" and minio.region == "home"
    assert region_of("https://s3.us-west-2.amazonaws.com") == "us-west-2"
    with pytest.raises(S3Error, match="URL"):
        Bucket("minio:9000", "backups", "k", "s")
    with pytest.raises(S3Error, match="bucket name"):
        Bucket("http://minio:9000", "Not A Bucket", "k", "s")


# -- settings -----------------------------------------------------------------------
def test_the_settings_keep_the_secret_sealed_and_never_send_it_back(client, auth, store):
    told = set_up(client, auth, store)
    s = told["settings"]
    assert s["has_secret"] and s["configured"]
    assert "secret_key" not in s
    assert s["endpoint"] == store.endpoint and s["prefix"] == "home"
    assert s["parts"] == list(PARTS) and s["time"] == "03:00" and s["keep_days"] == 30 and not s["enabled"]
    # Sealed on disk, not plain.
    stored = client.app.state.cloudmorrow.settings.get("backup.secret")
    assert stored and SECRET not in stored
    assert backups_of(client)._secret() == SECRET
    # A blank secret keeps the old one; a new one replaces it.
    client.patch("/api/server/backup", headers=auth, json={"secret_key": ""})
    assert backups_of(client)._secret() == SECRET
    client.patch("/api/server/backup", headers=auth, json={"secret_key": "another"})
    assert backups_of(client)._secret() == "another"


def test_what_the_settings_refuse(client, auth, store):
    refused = client.patch("/api/server/backup", headers=auth, json={"enabled": True})
    assert refused.status_code == 400 and "where backups go" in refused.text
    set_up(client, auth, store)
    assert client.patch("/api/server/backup", headers=auth, json={"time": "25:00"}).status_code == 400
    assert client.patch("/api/server/backup", headers=auth, json={"parts": ["everything"]}).status_code == 400
    assert client.patch("/api/server/backup", headers=auth, json={"parts": [], "enabled": True}).status_code == 400
    assert client.patch("/api/server/backup", headers=auth, json={"endpoint": "not a url"}).status_code == 400
    ok = client.patch("/api/server/backup", headers=auth, json={"time": "4:30", "keep_days": 7, "enabled": True})
    assert ok.status_code == 200
    assert ok.json()["settings"]["time"] == "04:30" and ok.json()["settings"]["enabled"]


def test_backups_are_for_administrators(client, guest_auth):
    assert client.get("/api/server/backup", headers=guest_auth).status_code == 403
    assert client.post("/api/server/backup/run", headers=guest_auth, json={}).status_code == 403
    assert client.get("/api/server/backups", headers=guest_auth).status_code == 403


def test_trying_the_bucket_writes_a_probe_and_takes_it_away(client, auth, store):
    set_up(client, auth, store)
    told = client.post("/api/server/backup/test", headers=auth)
    assert told.status_code == 200, told.text
    assert told.json()["ok"] and told.json()["backups"] == 0
    assert store.objects == {}
    assert ("PUT", "home/.cloudmorrow-probe") in store.requests
    # The wrong secret is said in words, not a 500.
    client.patch("/api/server/backup", headers=auth, json={"access_key": "NOBODY"})
    refused = client.post("/api/server/backup/test", headers=auth)
    assert refused.status_code == 400 and "secret key" in refused.text


# -- backing up --------------------------------------------------------------------------
def test_back_up_now_puts_every_part_in_the_bucket_with_a_manifest(client, auth, store, config):
    a_drive_with_files(client, config)
    state = client.app.state.cloudmorrow
    share, _ = state.shares.create("bram", "Photos", admin=True)
    (share.path / "holiday.jpg").write_bytes(b"sun")
    (config.data_dir / "secret.key").write_text("signing\n", encoding="utf-8")
    set_up(client, auth, store, seal_key=True)

    started = client.post("/api/server/backup/run", headers=auth, json={})
    assert started.status_code == 202, started.text
    assert started.json()["running"] == "backup"
    status = wait_done(client)
    assert status["running"] is None
    assert status["last"]["ok"], status["last"]
    stamp = status["last"]["stamp"]
    snapshot = [k for k in store.keys("home/") if not k.startswith("home/objects/")]
    sqlite = state.db.engine.name == "sqlite"
    assert snapshot == [
        f"home/{stamp}/database.index.gz" if sqlite else f"home/{stamp}/database.pgdump",
        f"home/{stamp}/drives/bram.index.gz",
        f"home/{stamp}/drives/guest.index.gz",
        f"home/{stamp}/keys.tar.gz",
        f"home/{stamp}/manifest.json",
        f"home/{stamp}/quills.tar.gz",
        f"home/{stamp}/shares/{share.name}.index.gz",
    ]
    # The store holds each file's content once, under its digest, in a folder by its first two letters.
    hello, cat, mine, sun = (sha(b"# Hello\n"), sha(b"\xff\xd8" + b"cat" * 100), sha(b"guest's\n"), sha(b"sun"))
    assert {hello, cat, mine, sun} <= store.digests("home/")
    assert store.objects[f"home/objects/{hello[:2]}/{hello}"] == b"# Hello\n"

    manifest = json.loads(store.objects[f"home/{stamp}/manifest.json"])
    assert manifest["cloudmorrow_backup"] == 2 and manifest["stamp"] == stamp
    assert manifest["parts"] == list(PARTS)
    assert manifest["sealed_with"] == key_fingerprint(state.sealer.master)
    assert [d["name"] for d in manifest["drives"]] == ["bram", "guest"]
    bram = manifest["drives"][0]
    assert bram["files"] == 2 and bram["size"] == 8 + 302 and bram["added"] == 8 + 302 and bram["unchanged"] == 0
    assert manifest["shares"][0]["name"] == share.name and manifest["shares"][0]["files"] == 1
    assert manifest["keys"]["sealing_key"] is True
    assert "sealing.key" in manifest["keys"]["files"] and "secret.key" in manifest["keys"]["files"]
    assert manifest["files"] == 4
    assert manifest["size"] == sum(
        p["size"]
        for p in (manifest["database"], manifest["quills"], manifest["keys"], *manifest["drives"], *manifest["shares"])
    )
    assert manifest["added"] > 0 and manifest["rehash"] is False
    # The drive's index names its files by their path in the drive, with digest, size, mtime and mode.
    index = index_of(store, bram["key"])
    assert sorted(index["files"]) == ["files/Notes/hello.md", "files/Photos/cat.jpg"]
    assert index["dirs"] == ["files", "files/Notes", "files/Photos"]
    digest, size, mtime_ns, mode = index["files"]["files/Notes/hello.md"]
    assert digest == hello and size == 8
    assert mtime_ns == (config.files_root("bram") / "Notes" / "hello.md").stat().st_mtime_ns
    assert mode == 0o644
    # And the lines said what went.
    assert any(line.startswith("bram's files: 310 B, 2 files, 310 B new") for line in status["last"]["lines"])
    assert status["last"]["lines"][-1].startswith("Done:")
    assert status["last"]["added"] == manifest["added"] and status["last"]["files"] == 4
    assert status["last"]["store"]["objects"] == len(store.digests("home/"))
    assert status["store"]["objects"] == len(store.digests("home/"))

    listed = client.get("/api/server/backups", headers=auth)
    assert listed.status_code == 200
    assert [b["stamp"] for b in listed.json()] == [stamp]
    assert listed.json()[0]["drives"] == 2 and listed.json()[0]["key_matches"] is True
    assert listed.json()[0]["format"] == 2 and listed.json()[0]["added"] == manifest["added"]
    described = client.get(f"/api/server/backups/{stamp}", headers=auth)
    assert described.status_code == 200 and described.json()["key_matches"] is True


def test_the_second_backup_sends_only_what_changed(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    first = back_up(client, auth)
    sent_first = object_puts(store)
    assert len(sent_first) == 3, "every file once"
    store.requests.clear()

    files = config.files_root("bram")
    (files / "Notes" / "hello.md").write_text("# Hello again\n", encoding="utf-8")  # changed
    (files / "Notes" / "new.md").write_text("new\n", encoding="utf-8")  # new
    (files / "Photos" / "cat.jpg").rename(files / "Photos" / "kitten.jpg")  # renamed
    (files / "Photos" / "copy.jpg").write_bytes(b"\xff\xd8" + b"cat" * 100)  # a copy of one there
    second = back_up(client, auth)
    assert second != first
    sent = object_puts(store)
    assert sorted(k.rsplit("/", 1)[-1] for k in sent) == sorted([sha(b"# Hello again\n"), sha(b"new\n")]), (
        "the changed and the new file; the rename and the copy cost nothing"
    )
    manifest = json.loads(store.objects[f"home/{second}/manifest.json"])
    bram = manifest["drives"][0]
    assert bram["files"] == 4 and bram["added_files"] == 2 and bram["added"] == 14 + 4
    assert bram["unchanged"] == 0, "kitten.jpg is a new path: read and hashed, then found in the store"
    assert manifest["drives"][1]["unchanged"] == 1, "the guest's note, by size and mtime, unread"
    index = index_of(store, bram["key"])
    assert sorted(index["files"]) == [
        "files/Notes/hello.md",
        "files/Notes/new.md",
        "files/Photos/copy.jpg",
        "files/Photos/kitten.jpg",
    ]
    assert index["files"]["files/Photos/kitten.jpg"][0] == index["files"]["files/Photos/copy.jpg"][0]
    # The first snapshot is still whole: its index names the content it saw.
    old = index_of(store, f"home/{first}/drives/bram.index.gz")
    assert old["files"]["files/Notes/hello.md"][0] == sha(b"# Hello\n")
    assert (
        f"home/objects/{sha(b'# Hello' + chr(10).encode())[:2]}/{sha(b'# Hello' + chr(10).encode())}" in store.objects
    )
    status = client.get("/api/server/backup", headers=auth).json()
    assert status["store"]["objects"] == len(store.digests("home/")) == 5
    assert status["last"]["added"] < json.loads(store.objects[f"home/{first}/manifest.json"])["added"]
    assert any("18 B new" in line for line in status["last"]["lines"])


def test_a_file_untouched_by_size_and_mtime_is_not_read_until_the_monthly_check(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    first = back_up(client, auth)
    assert client.app.state.cloudmorrow.settings.get(backups_module.LAST_REHASH), "the first run counts as a full read"
    hello = config.files_root("bram") / "Notes" / "hello.md"
    was = hello.stat()
    # Changed under the same size and the same mtime: what rsync's quick check misses too.
    hello.write_text("# Hallo\n", encoding="utf-8")
    os.utime(hello, ns=(was.st_atime_ns, was.st_mtime_ns))
    store.requests.clear()
    second = back_up(client, auth)
    assert object_puts(store) == [], "trusted: nothing sent"
    assert index_of(store, f"home/{second}/drives/bram.index.gz")["files"]["files/Notes/hello.md"][0] == sha(
        b"# Hello\n"
    )
    # A month on, every file is read again and the change is caught.
    client.app.state.cloudmorrow.settings.set(backups_module.LAST_REHASH, "2020-01-01")
    third = back_up(client, auth)
    assert [k.rsplit("/", 1)[-1] for k in object_puts(store)] == [sha(b"# Hallo\n")]
    manifest = json.loads(store.objects[f"home/{third}/manifest.json"])
    assert manifest["rehash"] is True and manifest["drives"][0]["unchanged"] == 0
    status = client.get("/api/server/backup", headers=auth).json()
    assert any("monthly check" in line for line in status["last"]["lines"])
    assert client.app.state.cloudmorrow.settings.get(backups_module.LAST_REHASH) == dt.date.today().isoformat()
    assert first != second != third


def test_a_large_file_goes_up_in_parts_and_is_checked(client, auth, store, config, monkeypatch):
    monkeypatch.setattr(backups_module, "IN_MEMORY", 1024)
    monkeypatch.setattr(backups_module, "PART_SIZE", 4096)
    a_drive_with_files(client, config)
    big = bytes(range(256)) * 40
    (config.files_root("bram") / "big.bin").write_bytes(big)
    set_up(client, auth, store, parts=["drives"])
    stamp = back_up(client, auth)
    key = f"home/objects/{sha(big)[:2]}/{sha(big)}"
    assert store.objects[key] == big
    assert ("POST", key) in store.requests, "begun as a multipart upload"
    assert not store.uploads
    assert index_of(store, f"home/{stamp}/drives/bram.index.gz")["files"]["files/big.bin"][1] == len(big)
    # Up again: known, so hashed and not sent.
    store.requests.clear()
    back_up(client, auth)
    assert object_puts(store) == []


def test_a_backup_that_fails_half_way_takes_its_new_objects_back(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    first = back_up(client, auth)
    (config.files_root("bram") / "Notes" / "later.md").write_text("later\n", encoding="utf-8")
    store.fail_keys.add("manifest.json")
    client.post("/api/server/backup/run", headers=auth, json={})
    status = wait_done(client)
    assert status["last"]["ok"] is False and "500" in status["last"]["error"]
    assert sha(b"later\n") not in store.digests("home/"), "the failed run's object is gone"
    assert sha(b"# Hello\n") in store.digests("home/"), "the first backup's are not"
    assert store.stamps("home/") == {first, status["last"]["stamp"]}, "the half folder is swept as unfinished later"
    assert client.get("/api/server/backup", headers=auth).json()["store"]["objects"] == 3


def pieces_of(store, stamp: str) -> bytes:
    index = index_of(store, f"home/{stamp}/database.index.gz")
    whole = b""
    for digest, size, _stored in index["chunks"]:
        data = gzip.decompress(store.objects[f"home/objects/{digest[:2]}/{digest}"])
        assert sha(data) == digest and len(data) == size
        whole += data
    assert len(whole) == index["size"]
    return whole


@sqlite_only
def test_the_database_goes_up_in_pieces_and_only_the_changed_ones_again(client, auth, store, config, monkeypatch):
    monkeypatch.setattr(backups_module, "CHUNK_SIZE", 16 * 1024)
    set_up(client, auth, store, parts=["database"])
    first = back_up(client, auth)
    index = index_of(store, f"home/{first}/database.index.gz")
    assert index["engine"] == "sqlite" and index["chunk_size"] == 16 * 1024 and len(index["chunks"]) > 4
    unpacked = config.data_dir.parent / "copy.sqlite"
    unpacked.write_bytes(pieces_of(store, first))
    copy = sqlite3.connect(unpacked)
    assert copy.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    copy.close()
    # Nothing left in the tmp folder.
    assert not list((client.app.state.cloudmorrow.config.data_dir / "tmp").iterdir())
    manifest = json.loads(store.objects[f"home/{first}/manifest.json"])
    assert manifest["database"]["chunked"] and manifest["database"]["chunks"] == len(index["chunks"])
    assert manifest["database"]["added"] > 0

    # One row changed: a few pages, so a few pieces, not the file.
    client.app.state.cloudmorrow.settings.set_name("Renamed")
    store.requests.clear()
    second = back_up(client, auth)
    sent = object_puts(store)
    assert 0 < len(sent) < len(index["chunks"]), f"{len(sent)} of {len(index['chunks'])} pieces"
    again = index_of(store, f"home/{second}/database.index.gz")
    assert len(again["chunks"]) >= len(index["chunks"])
    assert sum(a[0] == b[0] for a, b in zip(index["chunks"], again["chunks"], strict=False)) > 0, "most pieces the same"
    whole = pieces_of(store, second)
    unpacked.write_bytes(whole)
    copy = sqlite3.connect(unpacked)
    assert copy.execute("SELECT value FROM settings WHERE key = 'name'").fetchone()[0] == "Renamed"
    copy.close()


def test_a_backup_that_fails_says_so_and_leaves_no_manifest(client, auth, store):
    set_up(client, auth, store, parts=["drives"])
    store.stop()  # the bucket is gone
    started = client.post("/api/server/backup/run", headers=auth, json={})
    assert started.status_code == 202
    status = wait_done(client)
    assert status["last"]["ok"] is False
    assert "could not reach" in status["last"]["error"]


def test_only_some_parts_when_asked(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store)
    client.post("/api/server/backup/run", headers=auth, json={"parts": ["drives"]})
    status = wait_done(client)
    stamp = status["last"]["stamp"]
    assert store.keys(f"home/{stamp}/") == [
        f"home/{stamp}/drives/bram.index.gz",
        f"home/{stamp}/drives/guest.index.gz",
        f"home/{stamp}/manifest.json",
    ]
    manifest = json.loads(store.objects[f"home/{stamp}/manifest.json"])
    assert manifest["database"] is None and manifest["parts"] == ["drives"]
    refused = client.post("/api/server/backup/run", headers=auth, json={"parts": ["nothing"]})
    assert refused.status_code == 400


def test_one_run_at_a_time(client, auth, store, config, monkeypatch):
    set_up(client, auth, store)
    slow = backups_of(client)
    started = slow._begin("backup", "test")  # noqa: F841 - holds the slot
    refused = client.post("/api/server/backup/run", headers=auth, json={})
    assert refused.status_code == 400 and "running already" in refused.text
    slow._end()


# -- the clock ---------------------------------------------------------------------------
def test_the_clock_runs_todays_backup_once_its_time_has_come(client, auth, store, config):
    set_up(client, auth, store, parts=["drives"], time="03:00", enabled=True)
    backups = backups_of(client)
    # Local times of that day, in that day's own offset: today's offset
    # pinned on an October date is an hour out once the clocks have gone
    # back, and 02:59 lands past three.
    early = dt.datetime(2026, 10, 23, 2, 59).astimezone()
    assert backups.tick(early) is False
    due = dt.datetime(2026, 10, 23, 3, 1).astimezone()
    assert backups.tick(due) is True
    wait_done(client)
    assert backups.status()["last"]["ok"]
    assert backups.status()["last"]["by"] == "the clock"
    # Not again today; again tomorrow.
    assert backups.tick(dt.datetime(2026, 10, 23, 9, 0).astimezone()) is False
    assert backups.tick(dt.datetime(2026, 10, 24, 3, 0).astimezone()) is True
    wait_done(client)
    assert len(store.stamps("home/")) == 2, "two backups, each in a folder of its own"


def test_the_clock_does_nothing_when_backups_are_off_or_unset(client, auth, store):
    backups = backups_of(client)
    assert backups.tick() is False
    set_up(client, auth, store, enabled=False)
    assert backups.tick(dt.datetime(2026, 10, 23, 23, 59).astimezone()) is False


def test_the_sweep_takes_old_and_unfinished_backups_away(client, auth, store, bucket):
    set_up(client, auth, store, keep_days=7)
    backups = backups_of(client)
    now = dt.datetime(2026, 10, 23, 12, 0, tzinfo=dt.UTC)
    backups.now = lambda: now

    def stamped(days_ago: float) -> str:
        return (now - dt.timedelta(days=days_ago)).strftime(backups_module.STAMP)

    manifest = json.dumps({"cloudmorrow_backup": 1, "stamp": "x", "parts": []}).encode()
    for days in (1, 6, 8, 30):
        bucket.put(f"home/{stamped(days)}/manifest.json", manifest)
        bucket.put(f"home/{stamped(days)}/quills.tar.gz", b"q")
    # Two that never finished: one from this morning, one from three days ago.
    bucket.put(f"home/{stamped(0.1)}/quills.tar.gz", b"q")
    bucket.put(f"home/{stamped(3)}/quills.tar.gz", b"q")
    # And somebody else's folder, which is not a backup and is left alone.
    bucket.put("home/notes.txt", b"mine")

    swept = backups.sweep()
    assert sorted(swept["backups"]) == sorted([stamped(8), stamped(30), stamped(3)])
    assert swept["objects"] == 0 and swept["totals"]["objects"] == 0, "nothing from before the store"
    left = {k.split("/")[1] for k in store.keys("home/")}
    assert left == {stamped(1), stamped(6), stamped(0.1), "notes.txt"}
    listed = client.get("/api/server/backups", headers=auth).json()
    assert [b["stamp"] for b in listed] == [stamped(1), stamped(6)], "newest first, finished only"


def test_the_sweep_takes_the_objects_only_old_backups_named_and_keeps_the_shared_ones(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"], keep_days=7)
    backups = backups_of(client)
    day = dt.datetime(2026, 10, 1, 3, 0, tzinfo=dt.UTC)
    backups.now = lambda: day
    first = back_up(client, auth)
    hello_old = sha(b"# Hello\n")
    (config.files_root("bram") / "Notes" / "hello.md").write_text("# Hello again\n", encoding="utf-8")
    day = dt.datetime(2026, 10, 5, 3, 0, tzinfo=dt.UTC)
    second = back_up(client, auth)
    assert hello_old in store.digests("home/"), "the first snapshot still names it"
    # Ten days on: the first is past the seven kept, the second is not.
    day = dt.datetime(2026, 10, 11, 3, 0, tzinfo=dt.UTC)
    swept = backups.sweep()
    assert swept["backups"] == [first] and swept["objects"] == 1
    assert store.stamps("home/") == {second}
    assert hello_old not in store.digests("home/"), "named by the first only: gone"
    assert sha(b"# Hello again\n") in store.digests("home/")
    assert sha(b"guest's\n") in store.digests("home/"), "shared by both: kept"
    assert swept["totals"]["objects"] == len(store.digests("home/")) == 3
    assert swept["totals"]["bytes"] == 14 + 302 + 8
    # A third backup on the same day: the running totals carry on from the sweep's count.
    (config.files_root("bram") / "Notes" / "third.md").write_text("3\n", encoding="utf-8")
    back_up(client, auth)
    status = client.get("/api/server/backup", headers=auth).json()
    assert status["store"]["objects"] == 4 and status["store"]["bytes"] == 14 + 302 + 8 + 2


def test_deleting_a_backup_takes_the_objects_only_it_named(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    first = back_up(client, auth)
    (config.files_root("bram") / "Notes" / "hello.md").write_text("# Changed\n", encoding="utf-8")
    second = back_up(client, auth)
    gone = client.delete(f"/api/server/backups/{first}", headers=auth)
    assert gone.status_code == 204
    assert store.stamps("home/") == {second}
    assert sha(b"# Hello\n") not in store.digests("home/")
    assert store.digests("home/") == {sha(b"# Changed\n"), sha(b"\xff\xd8" + b"cat" * 100), sha(b"guest's\n")}


# -- restoring ------------------------------------------------------------------------------
def test_a_drive_and_a_share_come_back_over_what_is_there(client, auth, store, config):
    a_drive_with_files(client, config)
    state = client.app.state.cloudmorrow
    share, _ = state.shares.create("bram", "Photos", admin=True)
    (share.path / "holiday.jpg").write_bytes(b"sun")
    set_up(client, auth, store, parts=["drives", "shares"])
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]

    # Life goes on: a file is lost, one is changed, one is new.
    (config.files_root("bram") / "Photos" / "cat.jpg").unlink()
    (config.files_root("bram") / "Notes" / "hello.md").write_text("changed\n", encoding="utf-8")
    (config.files_root("bram") / "Notes" / "new.md").write_text("new\n", encoding="utf-8")
    (share.path / "holiday.jpg").unlink()
    guest_note = config.files_root(GUEST[0]) / "Notes" / "mine.md"
    guest_note.write_text("guest changed\n", encoding="utf-8")

    asked = client.post(
        f"/api/server/backups/{stamp}/restore",
        headers=auth,
        json={"drives": ["bram"], "shares": [share.name], "restart": False},
    )
    assert asked.status_code == 202, asked.text
    status = wait_done(client)
    done = status["last_restore"]
    assert done["ok"], done
    assert done["drives"] == ["bram"] and done["shares"] == [share.name]
    assert done["restart_needed"] is False and done["restarting"] is False
    assert (config.files_root("bram") / "Photos" / "cat.jpg").read_bytes().startswith(b"\xff\xd8")
    assert (config.files_root("bram") / "Notes" / "hello.md").read_text(encoding="utf-8") == "# Hello\n"
    assert (config.files_root("bram") / "Notes" / "new.md").exists(), "what the backup does not have is left alone"
    assert (share.path / "holiday.jpg").read_bytes() == b"sun"
    assert guest_note.read_text(encoding="utf-8") == "guest changed\n", "only the drive asked for"
    assert any(line.startswith("bram's files: 2 files put back") for line in done["lines"])
    # Each file comes back with the mtime and mode it had.
    index = index_of(store, f"home/{stamp}/drives/bram.index.gz")
    assert (config.files_root("bram") / "Photos" / "cat.jpg").stat().st_mtime_ns == index["files"][
        "files/Photos/cat.jpg"
    ][2]
    # Restored again, nothing is written: every file is already there as it was.
    client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json={"drives": ["bram"], "restart": False})
    done = wait_done(client)["last_restore"]
    assert done["ok"] and any("0 files put back, 2 files already there" in line for line in done["lines"])


def test_one_file_or_one_folder_comes_back_as_it_was_that_day(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    stamp = back_up(client, auth)
    files = config.files_root("bram")
    (files / "Notes" / "hello.md").write_text("changed\n", encoding="utf-8")
    (files / "Notes" / "new.md").write_text("new\n", encoding="utf-8")
    (files / "Photos" / "cat.jpg").unlink()

    asked = client.post(
        f"/api/server/backups/{stamp}/restore",
        headers=auth,
        json={"paths": ["drives/bram/files/Notes/hello.md"], "restart": False},
    )
    assert asked.status_code == 202, asked.text
    done = wait_done(client)["last_restore"]
    assert done["ok"], done
    assert done["paths"] == ["drives/bram/files/Notes/hello.md"] and done["drives"] == []
    assert (files / "Notes" / "hello.md").read_text(encoding="utf-8") == "# Hello\n"
    assert (files / "Notes" / "new.md").exists() and not (files / "Photos" / "cat.jpg").exists(), "only the one file"
    assert any(line.startswith("From bram's files, files/Notes/hello.md: 1 file put back") for line in done["lines"])

    # A folder, with the slash, brings everything under it.
    asked = client.post(
        f"/api/server/backups/{stamp}/restore",
        headers=auth,
        json={"paths": ["drives/bram/files/Photos/"], "restart": False},
    )
    assert asked.status_code == 202, asked.text
    done = wait_done(client)["last_restore"]
    assert done["ok"] and (files / "Photos" / "cat.jpg").read_bytes().startswith(b"\xff\xd8")

    # What is not there, or not a single thing, is said before anything starts.
    restore = lambda body: client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json=body)  # noqa: E731
    assert "has no files/Notes/gone.md" in restore({"paths": ["drives/bram/files/Notes/gone.md"]}).text
    assert "has no files of ada" in restore({"paths": ["drives/ada/x"]}).text
    assert "whole drive" in restore({"paths": ["drives/bram"]}).text
    assert restore({"paths": ["elsewhere/bram/x"]}).status_code == 400
    assert restore({"paths": ["drives/bram/../x"]}).status_code == 400
    # A path inside a drive restored whole is not restored twice.
    asked = restore({"drives": ["bram"], "paths": ["drives/bram/files/Notes/hello.md"], "restart": False})
    assert asked.status_code == 202
    done = wait_done(client)["last_restore"]
    assert done["ok"] and done["paths"] == []


def test_a_backup_can_be_browsed_and_one_file_pulled_out(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    stamp = back_up(client, auth)
    top = client.get(f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "drives/bram"})
    assert top.status_code == 200, top.text
    assert top.json()["where"] == "drives/bram" and top.json()["path"] == ""
    assert [(f["name"], f["files"], f["size"]) for f in top.json()["folders"]] == [("files", 2, 310)]
    assert top.json()["files"] == []
    inside = client.get(
        f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "drives/bram", "path": "files/"}
    )
    assert inside.json()["path"] == "files"
    assert [(f["name"], f["files"], f["size"]) for f in inside.json()["folders"]] == [
        ("Notes", 1, 8),
        ("Photos", 1, 302),
    ]
    notes = client.get(
        f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "drives/bram", "path": "files/Notes"}
    )
    assert notes.json()["folders"] == []
    assert [(f["name"], f["size"]) for f in notes.json()["files"]] == [("hello.md", 8)]
    assert notes.json()["files"][0]["modified"].startswith("20")
    assert (
        client.get(f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "drives/ada"}).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "drives/bram", "path": "Nowhere"}
        ).status_code
        == 400
    )
    assert client.get(f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "bram"}).status_code == 400

    pulled = client.get(
        f"/api/server/backups/{stamp}/file", headers=auth, params={"path": "drives/bram/files/Notes/hello.md"}
    )
    assert pulled.status_code == 200, pulled.text
    assert pulled.content == b"# Hello\n"
    assert pulled.headers["content-length"] == "8" and "hello.md" in pulled.headers["content-disposition"]
    assert pulled.headers["content-type"].startswith("text/markdown")
    assert (
        client.get(f"/api/server/backups/{stamp}/file", headers=auth, params={"path": "drives/bram/nope"}).status_code
        == 400
    )
    assert (
        client.get(f"/api/server/backups/{stamp}/file", headers=auth, params={"path": "drives/bram"}).status_code == 400
    )


def test_a_backup_from_before_the_store_is_still_listed_and_restored_whole(client, auth, store, config, bucket):
    """Format 1: an archive per drive. Whole drives come back; there is nothing to browse."""
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    stamp = "20261001T030000Z"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(config.files_root("bram"), arcname="files")
    bucket.put(f"home/{stamp}/drives/bram.tar.gz", buffer.getvalue())
    manifest = {
        "cloudmorrow_backup": 1,
        "stamp": stamp,
        "made_at": "2026-10-01T03:00:00+00:00",
        "parts": ["drives"],
        "database": None,
        "drives": [{"name": "bram", "key": f"home/{stamp}/drives/bram.tar.gz", "size": 1, "files": 1}],
        "shares": [],
        "quills": None,
        "keys": None,
        "size": 1,
        "sealed_with": key_fingerprint(client.app.state.cloudmorrow.sealer.master),
    }
    bucket.put(f"home/{stamp}/manifest.json", json.dumps(manifest).encode())
    listed = client.get("/api/server/backups", headers=auth).json()
    assert [(b["stamp"], b["format"]) for b in listed] == [(stamp, 1)]
    browse = client.get(f"/api/server/backups/{stamp}/files", headers=auth, params={"where": "drives/bram"})
    assert browse.status_code == 400 and "before single files" in browse.text
    refused = client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json={"paths": ["drives/bram/Notes/x"]})
    assert refused.status_code == 400 and "before single files" in refused.text
    (config.files_root("bram") / "Notes" / "hello.md").unlink()
    asked = client.post(
        f"/api/server/backups/{stamp}/restore", headers=auth, json={"drives": ["bram"], "restart": False}
    )
    assert asked.status_code == 202, asked.text
    done = wait_done(client)["last_restore"]
    assert done["ok"], done
    assert (config.files_root("bram") / "Notes" / "hello.md").read_text(encoding="utf-8") == "# Hello\n"
    # A new backup lands beside it in the same folder, and the old one is swept by age like any other.
    back_up(client, auth)
    assert stamp in store.stamps("home/")


@sqlite_only
def test_the_database_comes_back_and_a_copy_of_today_is_kept(client, auth, store, config):
    state = client.app.state.cloudmorrow
    state.settings.set_name("Before")
    set_up(client, auth, store, parts=["database"])
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]

    state.settings.set_name("After")
    state.users.create("newcomer", "x" * 20)
    assert state.cloud_name() == "After"

    asked = client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json={"database": True, "restart": False})
    assert asked.status_code == 202, asked.text
    done = wait_done(client)["last_restore"]
    assert done["ok"], done
    assert done["database"] is True and done["restart_needed"] is True
    assert done["restarting"] is False and "restart the server" in done["restart_blocked"]
    assert state.cloud_name() == "Before"
    assert state.users.get("newcomer") is None
    # What the database was a moment ago, kept beside it.
    kept = list((config.data_dir / "before-restore").glob("*.sqlite"))
    assert len(kept) == 1
    before = sqlite3.connect(kept[0])
    assert before.execute("SELECT value FROM settings WHERE key = 'name'").fetchone()[0] == "After"
    assert before.execute("SELECT COUNT(*) FROM users WHERE username = 'newcomer'").fetchone()[0] == 1
    before.close()
    # And the server still works on the restored database: a sign-in, a listing.
    assert token_for(client, "bram", "supersecret1")
    assert client.get("/api/server/backup", headers=auth).status_code == 200


def test_what_a_restore_refuses(client, auth, store, config):
    a_drive_with_files(client, config)
    set_up(client, auth, store, parts=["drives"])
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]
    restore = lambda body: client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json=body)  # noqa: E731
    assert restore({}).status_code == 400
    assert "no database" in restore({"database": True}).text
    assert "no files of ada" in restore({"drives": ["ada"]}).text
    assert "no share called Photos" in restore({"shares": ["Photos"]}).text
    assert "no Quills" in restore({"quills": True}).text
    assert client.get("/api/server/backups/20000101T000000Z", headers=auth).status_code == 404
    assert client.get("/api/server/backups/not-a-stamp", headers=auth).status_code == 404


def test_a_database_sealed_with_another_key_is_refused_unless_forced_or_the_key_comes_too(client, auth, store):
    set_up(client, auth, store, parts=["database", "keys"], seal_key=True)
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]
    key = f"home/{stamp}/manifest.json"
    manifest = json.loads(store.objects[key])
    manifest["sealed_with"] = "0000000000000000"
    store.objects[key] = json.dumps(manifest).encode()

    listed = client.get("/api/server/backups", headers=auth).json()
    assert listed[0]["key_matches"] is False
    refused = client.post(
        f"/api/server/backups/{stamp}/restore", headers=auth, json={"database": True, "restart": False}
    )
    assert refused.status_code == 400 and "another key" in refused.text
    # With the keys part, which carries the sealing key, it may go ahead.
    backups = backups_of(client)
    backups._check_choice(backups.describe(stamp), Choice(database=True, keys=True))
    backups._check_choice(backups.describe(stamp), Choice(database=True, force=True))
    with pytest.raises(BackupError, match="another key"):
        backups._check_choice(backups.describe(stamp), Choice(database=True))


def test_the_sealing_key_goes_back_only_with_the_database(client, auth, store, config):
    (config.data_dir / "secret.key").write_text("signing\n", encoding="utf-8")
    set_up(client, auth, store, parts=["keys"], seal_key=True)
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]
    key_path = config.secrets_key_path
    was = key_path.read_bytes()
    key_path.write_bytes(b"changed-since\n")
    asked = client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json={"keys": True, "restart": False})
    assert asked.status_code == 202, asked.text
    done = wait_done(client)["last_restore"]
    assert done["ok"], done
    assert key_path.read_bytes() == b"changed-since\n", "a key in use is not written over on its own"
    assert "sealing.key" not in done["keys"] and "secret.key" in done["keys"]
    assert any("sealing key stays" in line for line in done["lines"])
    # Gone, it is put back — the server has no key, so nothing is locked by it.
    key_path.unlink()
    client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json={"keys": True, "restart": False})
    done = wait_done(client)["last_restore"]
    assert done["ok"] and "sealing.key" in done["keys"]
    assert key_path.read_bytes() == was
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"


def test_quills_come_back_into_the_data_directory(client, auth, store, config):
    client.app.state.cloudmorrow.quills.install_from_catalog("tasks")
    set_up(client, auth, store, parts=["quills"])
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]
    manifest = json.loads(store.objects[f"home/{stamp}/manifest.json"])
    assert manifest["quills"]["files"] > 0
    installed = config.quills_dir / "tasks"
    assert installed.is_dir()
    marker = next(p for p in installed.rglob("*.toml"))
    marker.unlink()
    asked = client.post(f"/api/server/backups/{stamp}/restore", headers=auth, json={"quills": True, "restart": False})
    assert asked.status_code == 202, asked.text
    done = wait_done(client)["last_restore"]
    assert done["ok"], done
    assert marker.exists()
    assert done["quills"] is True and done["restart_needed"] is True


def test_a_backup_can_be_deleted_from_the_bucket(client, auth, store, config):
    set_up(client, auth, store, parts=["keys"])
    client.post("/api/server/backup/run", headers=auth, json={})
    stamp = wait_done(client)["last"]["stamp"]
    assert store.keys(f"home/{stamp}/")
    gone = client.delete(f"/api/server/backups/{stamp}", headers=auth)
    assert gone.status_code == 204
    assert store.keys(f"home/{stamp}/") == []
    assert client.get("/api/server/backups", headers=auth).json() == []


def test_an_archive_cannot_reach_outside_where_it_is_put(client, auth, store, config, bucket):
    """A tar with a path that climbs out is skipped, member by member."""
    set_up(client, auth, store)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        good = tarfile.TarInfo("files/ok.txt")
        good.size = 2
        tar.addfile(good, io.BytesIO(b"ok"))
        bad = tarfile.TarInfo("../../escaped.txt")
        bad.size = 3
        tar.addfile(bad, io.BytesIO(b"bad"))
    bucket.put("evil.tar.gz", buffer.getvalue())
    dest = config.notes_dir / "victim"
    files, skipped = backups_of(client)._restore_folder(bucket, "evil.tar.gz", dest)
    assert (files, skipped) == (1, 1)
    assert (dest / "files" / "ok.txt").read_bytes() == b"ok"
    assert not (config.notes_dir.parent / "escaped.txt").exists()
    assert not list(config.notes_dir.parent.glob("escaped.txt"))


def test_an_index_cannot_reach_outside_where_it_is_put_either(client, auth, store, config, bucket):
    """An index with a path that climbs out, or an object that is not what it says, is skipped."""
    set_up(client, auth, store)
    backups = backups_of(client)
    good, bad = sha(b"ok"), sha(b"bad")
    bucket.put(f"home/objects/{good[:2]}/{good}", b"ok")
    bucket.put(f"home/objects/{bad[:2]}/{bad}", b"bad")
    wrong = sha(b"what the index says")
    bucket.put(f"home/objects/{wrong[:2]}/{wrong}", b"something else")
    index = {
        "files": {
            "ok.txt": [good, 2, 1_700_000_000_000_000_000, 0o600],
            "../../escaped.txt": [bad, 3, 0, 0o644],
            "/abs.txt": [bad, 3, 0, 0o644],
            "sub/../../up.txt": [bad, 3, 0, 0o644],
            "liar.txt": [wrong, 19, 0, 0o644],
        },
        "dirs": ["sub", "../out"],
    }
    bucket.put("home/evil.index.gz", gzip.compress(json.dumps(index).encode()))
    dest = config.notes_dir / "victim"
    told = backups._restore_index(backups_module.Store(bucket, "home/"), "home/evil.index.gz", dest)
    assert told == {"files": 1, "unchanged": 0, "skipped": 4}
    assert (dest / "ok.txt").read_bytes() == b"ok"
    assert oct((dest / "ok.txt").stat().st_mode & 0o777) == "0o600"
    assert (dest / "ok.txt").stat().st_mtime_ns == 1_700_000_000_000_000_000
    assert (dest / "sub").is_dir() and not (config.notes_dir / "out").exists()
    assert not (dest / "liar.txt").exists() and not list(dest.glob(".cloudmorrow-restore-*"))
    assert not (config.notes_dir.parent / "escaped.txt").exists() and not (config.notes_dir / "up.txt").exists()


def test_paths_are_read_strictly():
    assert split_path("drives/bram/Notes/a.md") == ("drives", "bram", "Notes/a.md")
    assert split_path("shares/photos/2024/") == ("shares", "photos", "2024/")
    assert split_path("drives/bram") == ("drives", "bram", "")
    for bad in ("bram/Notes", "drives", "drives//x", "drives/bram/../x", "drives/bram/a/./b", "quills/x"):
        with pytest.raises(BackupError):
            split_path(bad)


def test_the_status_says_what_is_going_on_while_it_goes(client, auth, store, config):
    set_up(client, auth, store, parts=["drives"])
    backups = backups_of(client)
    backups._begin("backup", "bram")
    backups._at("Backing up bram's files")
    backups._say("Database: 1.0 MB")
    told = client.get("/api/server/backup", headers=auth).json()
    assert told["running"] == "backup" and told["by"] == "bram"
    assert told["step"] == "Backing up bram's files" and told["lines"] == ["Database: 1.0 MB"]
    backups._end()
    assert client.get("/api/server/backup", headers=auth).json()["running"] is None


def test_the_time_is_checked_as_the_clock_reads_it():
    assert backups_module.validate_time("3:05") == "03:05"
    assert backups_module.validate_time(" 23:59 ") == "23:59"
    for bad in ("24:00", "3", "03:60", "", "three"):
        with pytest.raises(BackupError):
            backups_module.validate_time(bad)


def test_timing_of_a_wait_is_bounded(client, auth, store):
    """`wait` answers when nothing runs, at once."""
    started = time.monotonic()
    backups_of(client).wait(5.0)
    assert time.monotonic() - started < 1.0
