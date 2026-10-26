"""Backups: everything into a bucket, every day, and back (server/backups.py, server/s3.py).

Against a bucket on the loopback (tests/fake_s3.py) that answers the way
a store does and turns away anything unsigned. What a real store would
make of the signature is not tried here; its shape is.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import sqlite3
import tarfile
import time

import pytest

from cloudmorrow.server import backups as backups_module
from cloudmorrow.server.backups import PARTS, BackupError, Choice, key_fingerprint
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
    keys = store.keys("home/")
    assert (
        keys
        == [
            f"home/{stamp}/database.sqlite.gz" if state.db.engine.name == "sqlite" else f"home/{stamp}/database.pgdump",
            f"home/{stamp}/drives/bram.tar.gz",
            f"home/{stamp}/drives/guest.tar.gz",
            f"home/{stamp}/keys.tar.gz",
            f"home/{stamp}/manifest.json",
            f"home/{stamp}/quills.tar.gz",
            f"home/{stamp}/shares/{share.name}.tar.gz",
        ]
        or state.db.engine.name != "sqlite"
    )

    manifest = json.loads(store.objects[f"home/{stamp}/manifest.json"])
    assert manifest["cloudmorrow_backup"] == 1 and manifest["stamp"] == stamp
    assert manifest["parts"] == list(PARTS)
    assert manifest["sealed_with"] == key_fingerprint(state.sealer.master)
    assert [d["name"] for d in manifest["drives"]] == ["bram", "guest"]
    bram = manifest["drives"][0]
    assert bram["files"] == 2 and bram["size"] > 0 and len(bram["sha256"]) == 64
    assert manifest["shares"][0]["name"] == share.name and manifest["shares"][0]["files"] == 1
    assert manifest["keys"]["sealing_key"] is True
    assert "sealing.key" in manifest["keys"]["files"] and "secret.key" in manifest["keys"]["files"]
    assert manifest["size"] == sum(
        p["size"]
        for p in (manifest["database"], manifest["quills"], manifest["keys"], *manifest["drives"], *manifest["shares"])
    )
    # The drive's archive holds the files by their path in the drive.
    with tarfile.open(fileobj=io.BytesIO(store.objects[bram["key"]]), mode="r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers() if m.isfile())
    assert names == ["files/Notes/hello.md", "files/Photos/cat.jpg"]
    # And the lines said what went.
    assert any(line.startswith("bram's files:") for line in status["last"]["lines"])
    assert status["last"]["lines"][-1].startswith("Done:")

    listed = client.get("/api/server/backups", headers=auth)
    assert listed.status_code == 200
    assert [b["stamp"] for b in listed.json()] == [stamp]
    assert listed.json()[0]["drives"] == 2 and listed.json()[0]["key_matches"] is True
    described = client.get(f"/api/server/backups/{stamp}", headers=auth)
    assert described.status_code == 200 and described.json()["key_matches"] is True


@sqlite_only
def test_the_database_copy_is_whole_and_opens(client, auth, store, config):
    set_up(client, auth, store, parts=["database"])
    client.post("/api/server/backup/run", headers=auth, json={})
    status = wait_done(client)
    assert status["last"]["ok"], status["last"]
    key = f"home/{status['last']['stamp']}/database.sqlite.gz"
    unpacked = config.data_dir.parent / "copy.sqlite"
    unpacked.write_bytes(gzip.decompress(store.objects[key]))
    copy = sqlite3.connect(unpacked)
    assert copy.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
    copy.close()
    # Nothing left in the tmp folder.
    assert not list((client.app.state.cloudmorrow.config.data_dir / "tmp").iterdir())


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
        f"home/{stamp}/drives/bram.tar.gz",
        f"home/{stamp}/drives/guest.tar.gz",
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
    assert backups.tick(dt.datetime(2026, 10, 23, 9, 0, tzinfo=tz)) is False
    assert backups.tick(dt.datetime(2026, 10, 24, 3, 0, tzinfo=tz)) is True
    wait_done(client)
    stamps = {key.split("/")[1] for key in store.keys("home/")}
    assert len(stamps) == 2, "two backups, each in a folder of its own"


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

    gone = backups.sweep()
    assert sorted(gone) == sorted([stamped(8), stamped(30), stamped(3)])
    left = {k.split("/")[1] for k in store.keys("home/")}
    assert left == {stamped(1), stamped(6), stamped(0.1), "notes.txt"}
    listed = client.get("/api/server/backups", headers=auth).json()
    assert [b["stamp"] for b in listed] == [stamped(1), stamped(6)], "newest first, finished only"


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
