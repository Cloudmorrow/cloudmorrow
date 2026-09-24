"""Config bundles: claiming one, adopting it, and changing it afterwards.

The interesting behaviour is all in the three-way conversation between two
machines and the server, so most of this drives two real AgentClients against
the FastAPI test client and checks what landed on each machine's disk.
"""

from __future__ import annotations

import pytest

from cloudmorrow.agent.client import AgentApiError, AgentClient
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.agent.sync import SyncState, sync_bundle
from cloudmorrow.bundles import InvalidPathError, validate_path
from tests.conftest import GUEST, token_for


class Machine:
    """One enrolled agent, its ~/.config, and the state it keeps beside it."""

    def __init__(self, test_client, auth, tmp_path, name: str) -> None:
        self.name = name
        self.root = tmp_path / name / "config"
        self.root.mkdir(parents=True)
        self.state_dir = tmp_path / name / "state"
        self.api = test_client
        enrolled = test_client.post(
            "/api/agents/enroll-self",
            json={
                "name": name,
                "hostname": f"{name}.local",
                "platform": "Linux-omarchy",
                "capabilities": ["ping", "sysinfo", "omarchy"],
            },
            headers=auth,
        ).json()
        self.agent_id = enrolled["agent_id"]
        self.config = AgentConfig(
            server_url="", agent_token=enrolled["agent_token"], name=name
        )
        self.client = AgentClient(self.config)
        self.client._client.close()
        self.client._client = test_client

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def sync(self):
        return sync_bundle(
            self.client,
            self.config,
            "omarchy",
            root=self.root,
            state_directory=self.state_dir,
        )

    def state(self) -> SyncState:
        return SyncState.load("omarchy", self.state_dir)


@pytest.fixture(autouse=True)
def pretend_omarchy(monkeypatch):
    """These machines are Omarchy boxes. The one running the tests is not."""
    monkeypatch.setattr(AgentConfig, "is_omarchy", staticmethod(lambda: True))


@pytest.fixture()
def enable_sync(client, auth):
    def enable(machine: Machine, bundles=("omarchy",)) -> None:
        response = client.patch(
            f"/api/agents/{machine.agent_id}/sync",
            json={"sync_bundles": list(bundles)},
            headers=auth,
        )
        assert response.status_code == 200, response.text

    return enable


@pytest.fixture()
def laptop(client, auth, tmp_path) -> Machine:
    return Machine(client, auth, tmp_path, "laptop")


@pytest.fixture()
def desktop(client, auth, tmp_path) -> Machine:
    return Machine(client, auth, tmp_path, "desktop")


# -- the path rules ----------------------------------------------------------
@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "../../.ssh/authorized_keys", "hypr/../../x", "~/.bashrc", ""],
)
def test_a_bundle_path_cannot_leave_the_bundle(bad):
    with pytest.raises(InvalidPathError):
        validate_path(bad)


def test_ordinary_paths_survive_validation():
    assert validate_path("hypr/hyprland.conf") == "hypr/hyprland.conf"
    assert validate_path("hypr\\bindings.conf") == "hypr/bindings.conf"


# -- claiming ----------------------------------------------------------------
def test_the_first_machine_to_sync_decides_the_configuration(laptop, desktop, enable_sync):
    laptop.write("hypr/hyprland.conf", "monitor=,preferred,auto,1\n")
    desktop.write("hypr/hyprland.conf", "monitor=DP-1,3840x2160,0x0,1\n")
    enable_sync(laptop)
    enable_sync(desktop)

    assert laptop.sync().action == "claimed"
    outcome = desktop.sync()

    assert outcome.action == "adopted"
    # The desktop's own copy lost, and was kept beside it rather than deleted.
    assert desktop.read("hypr/hyprland.conf") == "monitor=,preferred,auto,1\n"
    backup = desktop.root / "hypr" / "hyprland.conf.cloudmorrow-backup"
    assert backup.read_text() == "monitor=DP-1,3840x2160,0x0,1\n"


def test_a_machine_that_is_not_syncing_cannot_push(laptop):
    laptop.write("hypr/hyprland.conf", "x\n")
    with pytest.raises(AgentApiError) as exc:
        laptop.client.push_config(
            "omarchy", [{"path": "hypr/hyprland.conf", "content": "x\n"}], base_revision=None
        )
    assert exc.value.status_code == 403


def test_syncing_needs_nothing_to_claim_with(laptop, enable_sync):
    enable_sync(laptop)
    assert laptop.sync().action == "idle"


# -- changing afterwards -----------------------------------------------------
def test_a_change_on_one_machine_reaches_the_other(laptop, desktop, enable_sync):
    laptop.write("hypr/hyprland.conf", "bind = SUPER, Q, killactive\n")
    enable_sync(laptop)
    enable_sync(desktop)
    laptop.sync()
    desktop.sync()

    laptop.write("hypr/hyprland.conf", "bind = SUPER, W, killactive\n")
    pushed = laptop.sync()
    assert pushed.action == "pushed"
    assert pushed.revision == 2

    pulled = desktop.sync()
    assert pulled.action == "updated"
    assert desktop.read("hypr/hyprland.conf") == "bind = SUPER, W, killactive\n"
    # Its own copy was ours to overwrite this time, so nothing was set aside.
    assert not (desktop.root / "hypr" / "hyprland.conf.cloudmorrow-backup").exists()


def test_a_new_file_and_a_deleted_one_both_travel(laptop, desktop, enable_sync):
    laptop.write("hypr/hyprland.conf", "source = bindings.conf\n")
    laptop.write("hypr/bindings.conf", "bind = SUPER, Q, killactive\n")
    enable_sync(laptop)
    enable_sync(desktop)
    laptop.sync()
    desktop.sync()
    assert desktop.read("hypr/bindings.conf") == "bind = SUPER, Q, killactive\n"

    (laptop.root / "hypr" / "bindings.conf").unlink()
    laptop.write("hypr/monitors.conf", "monitor=eDP-1,preferred,auto,1\n")
    laptop.sync()
    desktop.sync()

    assert not (desktop.root / "hypr" / "bindings.conf").exists()
    assert desktop.read("hypr/monitors.conf") == "monitor=eDP-1,preferred,auto,1\n"


def test_a_backup_is_never_swept_into_the_bundle(laptop, desktop, enable_sync):
    """Otherwise the file kept aside on one machine lands on all of them."""
    laptop.write("hypr/hyprland.conf", "the laptop's\n")
    desktop.write("hypr/hyprland.conf", "the desktop's\n")
    enable_sync(laptop)
    enable_sync(desktop)
    laptop.sync()
    desktop.sync()
    assert (desktop.root / "hypr" / "hyprland.conf.cloudmorrow-backup").exists()

    # The desktop edits something and pushes. Its backup must not go with it.
    desktop.write("hypr/hyprland.conf", "changed here\n")
    assert desktop.sync().action == "pushed"
    laptop.sync()

    assert not (laptop.root / "hypr" / "hyprland.conf.cloudmorrow-backup").exists()
    assert sorted(f.path for f in _bundle_files(laptop)) == ["hypr/hyprland.conf"]


def _bundle_files(machine: Machine):
    from cloudmorrow.agent import omarchy

    return omarchy.scan(machine.root)


def test_nothing_happens_when_nothing_changed(laptop, enable_sync):
    laptop.write("hypr/hyprland.conf", "x\n")
    enable_sync(laptop)
    laptop.sync()
    assert laptop.sync().action == "idle"
    assert laptop.state().revision == 1


def test_two_machines_editing_at_once_settle_on_the_one_that_pushed(
    laptop, desktop, enable_sync
):
    """Both edit while both believe they are at revision 1. Nobody loses work."""
    laptop.write("hypr/hyprland.conf", "one\n")
    enable_sync(laptop)
    enable_sync(desktop)
    laptop.sync()
    desktop.sync()

    laptop.write("hypr/hyprland.conf", "from the laptop\n")
    desktop.write("hypr/hyprland.conf", "from the desktop\n")
    assert laptop.sync().action == "pushed"

    # The desktop sees the higher revision before it gets as far as pushing,
    # so it takes the laptop's copy and keeps its own beside it.
    assert desktop.sync().action == "updated"
    assert desktop.read("hypr/hyprland.conf") == "from the laptop\n"
    backup = desktop.root / "hypr" / "hyprland.conf.cloudmorrow-backup"
    assert backup.read_text() == "from the desktop\n"


def test_a_push_that_loses_the_race_is_told_so_and_waits(laptop, desktop, enable_sync):
    """The narrow race: the bundle moves between reading it and pushing to it."""
    laptop.write("hypr/hyprland.conf", "one\n")
    enable_sync(laptop)
    enable_sync(desktop)
    laptop.sync()
    desktop.sync()

    laptop.write("hypr/hyprland.conf", "from the laptop\n")
    laptop.sync()

    # The desktop pushes from revision 1, which is no longer where the bundle is.
    desktop.write("hypr/hyprland.conf", "from the desktop\n")
    outcome = _push_from(desktop, base_revision=1)
    assert outcome.action == "stale"
    # Nothing was written, and the next ordinary pass sorts it out.
    assert desktop.state().revision == 1
    assert desktop.sync().action == "updated"


def _push_from(machine: Machine, *, base_revision: int):
    """One push at a revision of our choosing, through the engine's own path."""
    from cloudmorrow.agent import omarchy
    from cloudmorrow.agent.sync import _push

    return _push(
        machine.client,
        "omarchy",
        omarchy.scan(machine.root),
        base=base_revision,
        state=machine.state(),
        claim=False,
    )


def test_a_machine_can_refuse_syncing_whatever_the_server_says(laptop, enable_sync):
    laptop.write("hypr/hyprland.conf", "x\n")
    enable_sync(laptop)
    laptop.config.allow_config_sync = False
    outcome = laptop.sync()
    assert outcome.action == "refused"
    assert laptop.state().revision == 0


# -- what the operator sees --------------------------------------------------
def test_the_bundle_reports_who_claimed_it_and_who_is_keeping_it(
    client, auth, laptop, desktop, enable_sync
):
    laptop.write("hypr/hyprland.conf", "x\n")
    enable_sync(laptop)
    enable_sync(desktop)
    laptop.sync()

    payload = client.get("/api/config/omarchy", headers=auth).json()
    assert payload["revision"] == 1
    assert payload["claimed_by"] == "laptop"
    assert payload["origin"] == "laptop"
    assert sorted(payload["machines"]) == ["desktop", "laptop"]
    assert [f["path"] for f in payload["files"]] == ["hypr/hyprland.conf"]


def test_claiming_and_changing_both_leave_a_notification(client, auth, laptop, enable_sync):
    laptop.write("hypr/hyprland.conf", "x\n")
    enable_sync(laptop)
    laptop.sync()
    laptop.write("hypr/hyprland.conf", "y\n")
    laptop.sync()

    notes = client.get("/api/notifications", headers=auth).json()
    kinds = [note["kind"] for note in notes]
    assert kinds == ["config.updated", "config.claimed"]
    assert notes[0]["machine"] == "laptop"
    assert all(note["unread"] for note in notes)

    marked = client.post("/api/notifications/read", json={}, headers=auth).json()
    assert marked == {"marked": 2, "unread": 0}


def test_a_machine_learns_it_is_syncing_from_its_heartbeat(client, auth, laptop, enable_sync):
    beat = laptop.client.heartbeat("laptop.local", "Linux-omarchy")
    assert beat["sync_bundles"] == []

    enable_sync(laptop)
    assert laptop.client.heartbeat("laptop.local", "Linux-omarchy")["sync_bundles"] == ["omarchy"]


def test_a_machine_that_is_not_omarchy_is_never_told_to_sync(client, auth, laptop, enable_sync):
    """The tick is remembered, but a machine without the capability is left be."""
    enable_sync(laptop)
    laptop.config.allow_config_sync = False
    beat = laptop.client.heartbeat("laptop.local", "Linux-plain")
    assert beat["sync_bundles"] == []


def test_one_users_bundle_is_not_another_users(client, auth, laptop, enable_sync, tmp_path):
    laptop.write("hypr/hyprland.conf", "mine\n")
    enable_sync(laptop)
    laptop.sync()

    guest = {"Authorization": f"Bearer {token_for(client, *GUEST)}"}
    payload = client.get("/api/config/omarchy", headers=guest).json()
    assert payload["revision"] == 0
    assert payload["files"] == []


def test_an_unknown_bundle_is_a_404(client, auth):
    assert client.get("/api/config/emacs", headers=auth).status_code == 404
