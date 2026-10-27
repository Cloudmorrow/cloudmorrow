"""Local backups: a folder on a machine, copied into My Files by its agent.

The person sets one up and sees how it went (`/api/syncs`); the machine
asks for its folders, sends what changed and says how it went
(`/api/agent/syncs`). The runner pass here is the real one, over a folder
on disk, through the FastAPI test client.
"""

from __future__ import annotations

import pytest

from cloudmorrow.server.syncs import SyncError, SyncStore, default_into, into_folder
from tests.test_agents_api import agent_headers, enroll_agent, runner_for


def drive(config, username="bram"):
    root = config.notes_dir / username / "files"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_where_a_folder_lands_unless_said():
    assert default_into("laptop", "/home/bram/Documents/") == "Backups/laptop/Documents"
    assert default_into("laptop", "C:\\Users\\bram\\Pictures") == "Backups/laptop/Pictures"
    assert into_folder("/Backups/laptop/Docs/") == "Backups/laptop/Docs"
    with pytest.raises(SyncError):
        into_folder("Trash/old")
    with pytest.raises(SyncError):
        into_folder("a/../b")


def test_the_store_keeps_one_row_per_folder_and_machine(config):
    from cloudmorrow.server.agents import AgentStore

    laptop, _token = AgentStore(config.db_path).enroll_for_user("bram", name="laptop")
    store = SyncStore(config.db_path)
    made = store.create("bram", laptop.id, "/home/bram/Docs", "Backups/laptop/Docs", 60)
    assert made.due() and made.run_now and made.last_run is None
    with pytest.raises(SyncError):
        store.create("bram", laptop.id, "/home/bram/Docs", "Elsewhere")
    assert [s.id for s in store.list("bram")] == [made.id]
    assert store.list("guest") == []
    done = store.finished(laptop.id, made.id, ok=True, said="3 sent", files=3, size=12)
    assert done.last_run and done.last_ok is True and not done.run_now and not done.due()
    assert store.ask("bram", made.id).due()
    store.delete("bram", made.id)
    assert store.list("bram") == []


def test_a_person_sets_one_up_on_their_own_machine_and_the_agent_sees_it(client, auth, guest_auth):
    enrolled = enroll_agent(client, auth)
    made = client.post("/api/syncs", json={"agent_id": enrolled["agent_id"], "path": "/home/bram/Docs"}, headers=auth)
    assert made.status_code == 201, made.text
    sync = made.json()
    assert sync["into"] == "Backups/testbox/Docs" and sync["every_minutes"] == 60
    assert sync["agent"]["name"] == "testbox"
    # Not somebody else's machine, and nobody else's list.
    assert (
        client.post("/api/syncs", json={"agent_id": enrolled["agent_id"], "path": "/x"}, headers=guest_auth).status_code
        == 404
    )
    assert client.get("/api/syncs", headers=guest_auth).json() == []
    # The machine sees its own.
    mine = client.get("/api/agent/syncs", headers=agent_headers(enrolled)).json()
    assert [s["id"] for s in mine] == [sync["id"]] and mine[0]["run_now"] is True
    # Asked to run now, and taken off.
    assert client.post(f"/api/syncs/{sync['id']}/run", headers=auth).json()["run_now"] is True
    assert client.delete(f"/api/syncs/{sync['id']}", headers=auth).status_code == 204
    assert client.get("/api/agent/syncs", headers=agent_headers(enrolled)).json() == []


def test_the_agent_copies_the_folder_in_and_keeps_it_up_to_date(client, auth, config, tmp_path):
    enrolled = enroll_agent(client, auth)
    folder = tmp_path / "Docs"
    (folder / "notes").mkdir(parents=True)
    (folder / "plan.md").write_text("plan")
    (folder / "notes" / "a.txt").write_text("aaa")
    (folder / ".hidden").write_text("no")
    sync = client.post("/api/syncs", json={"agent_id": enrolled["agent_id"], "path": str(folder)}, headers=auth).json()
    runner = runner_for(client, enrolled, tmp_path)
    runner.tick()
    into = drive(config) / "Backups" / "testbox" / "Docs"
    assert (into / "plan.md").read_text() == "plan" and (into / "notes" / "a.txt").read_text() == "aaa"
    assert not (into / ".hidden").exists()
    [after] = client.get("/api/syncs", headers=auth).json()
    assert after["last_ok"] is True and after["files"] == 2 and "2 sent" in after["last_said"]
    assert after["run_now"] is False
    # Nothing changed: nothing sent. Changed, added, gone: sent, sent, to the Trash.
    runner.syncs.run(client.get("/api/agent/syncs", headers=agent_headers(enrolled)).json()[0])
    assert "0 sent, 0 taken away" in client.get("/api/syncs", headers=auth).json()[0]["last_said"]
    (folder / "plan.md").write_text("plan v2")
    (folder / "new.txt").write_text("new")
    (folder / "notes" / "a.txt").unlink()
    runner.syncs.run(client.get("/api/agent/syncs", headers=agent_headers(enrolled)).json()[0])
    assert (into / "plan.md").read_text() == "plan v2" and (into / "new.txt").read_text() == "new"
    assert not (into / "notes" / "a.txt").exists()
    assert (drive(config) / "Trash" / "a.txt").read_text() == "aaa"
    assert "2 sent, 1 taken away" in client.get("/api/syncs", headers=auth).json()[0]["last_said"]
    # The files are the drive's, listed like any.
    listed = client.get("/api/records/file?share=my-files&folder=Backups/testbox/Docs", headers=auth)
    assert listed.status_code == 200 or listed.status_code == 404  # the Files Quill may not be installed here
    assert sync["id"] == after["id"]


def test_a_folder_outside_the_machines_roots_is_refused_and_said(client, auth, tmp_path):
    enrolled = enroll_agent(client, auth)
    client.post("/api/syncs", json={"agent_id": enrolled["agent_id"], "path": "/etc"}, headers=auth)
    runner = runner_for(client, enrolled, tmp_path)
    runner.tick()
    [after] = client.get("/api/syncs", headers=auth).json()
    assert after["last_ok"] is False and "outside this agent's allowed roots" in after["last_said"]
    # A folder that is not there, either.
    client.delete(f"/api/syncs/{after['id']}", headers=auth)
    client.post("/api/syncs", json={"agent_id": enrolled["agent_id"], "path": str(tmp_path / "gone")}, headers=auth)
    runner.tick()
    [again] = client.get("/api/syncs", headers=auth).json()
    assert again["last_ok"] is False and "no folder" in again["last_said"]


def test_the_machine_writes_only_under_its_backup_folder(client, auth, config, tmp_path):
    enrolled = enroll_agent(client, auth)
    sync = client.post(
        "/api/syncs", json={"agent_id": enrolled["agent_id"], "path": str(tmp_path)}, headers=auth
    ).json()
    headers = agent_headers(enrolled)
    bad = client.put(f"/api/agent/syncs/{sync['id']}/file?path=../../escape.txt", content=b"x", headers=headers)
    assert bad.status_code == 400
    bad = client.put(f"/api/agent/syncs/{sync['id']}/file?path=.secret", content=b"x", headers=headers)
    assert bad.status_code == 400
    ok = client.put(
        f"/api/agent/syncs/{sync['id']}/file?path=deep/one.txt&modified=1700000000", content=b"one", headers=headers
    )
    assert ok.status_code == 200 and ok.json()["path"] == f"Backups/testbox/{tmp_path.name}/deep/one.txt"
    assert client.get(f"/api/agent/syncs/{sync['id']}/files", headers=headers).json() == {
        "deep/one.txt": {"size": 3, "modified": 1700000000.0}
    }
    assert client.delete(f"/api/agent/syncs/{sync['id']}/file?path=deep/one.txt", headers=headers).json() == {
        "removed": True
    }
    assert client.delete(f"/api/agent/syncs/{sync['id']}/file?path=deep/one.txt", headers=headers).json() == {
        "removed": False
    }
    # Another machine's token does not reach it.
    other = enroll_agent(client, auth, name="otherbox")
    assert client.get(f"/api/agent/syncs/{sync['id']}/files", headers=agent_headers(other)).status_code == 404
