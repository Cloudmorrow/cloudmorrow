"""The home network: what the box announces, with zeroconf faked."""

from __future__ import annotations

import socket

from cloudmorrow.server.access_lan import (
    SERVICE_TYPE,
    Announcement,
    LanAnnouncer,
    announcer,
    hostname_label,
    local_addresses,
)
from cloudmorrow.server.app import create_app


class FakeZeroconf:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def register_service(self, info, allow_name_change=False):
        self.calls.append(("register", info))

    def update_service(self, info):
        self.calls.append(("update", info))

    def unregister_service(self, info):
        self.calls.append(("unregister", info))

    def close(self):
        self.calls.append(("close", None))


def test_hostname_labels() -> None:
    assert hostname_label("The Larsens") == "the-larsens"
    assert hostname_label("Cloudmorrow") == "cloudmorrow"
    assert hostname_label("  ÆØÅ!! ") == "cloudmorrow"
    assert len(hostname_label("x" * 100)) == 63


def test_local_addresses_leave_out_loopback_and_shared_address_space() -> None:
    for address in local_addresses():
        assert not address.startswith("127.") and not address.startswith("100.64.")


def test_the_announcer_registers_updates_and_withdraws() -> None:
    zc = FakeZeroconf()
    wanted: list[Announcement | None] = [
        Announcement("larsens", "The Larsens", "0.4.0", 8787, "http://larsens.local:8787", addresses=["192.168.1.20"])
    ]
    lan = LanAnnouncer(lambda: wanted[0], zeroconf_factory=lambda: zc)
    lan.refresh()
    kind, info = zc.calls[0]
    assert kind == "register"
    assert info.type == SERVICE_TYPE
    assert info.name == f"larsens.{SERVICE_TYPE}"
    assert info.server == "larsens.local."
    assert info.port == 8787
    assert info.addresses == [socket.inet_aton("192.168.1.20")]
    assert info.properties[b"name"] == b"The Larsens"
    assert info.properties[b"url"] == b"http://larsens.local:8787"
    assert lan.status()["hostname"] == "larsens.local"

    wanted[0] = Announcement(
        "larsens", "The Larsens", "0.4.0", 8787, "https://cloud.example.com", addresses=["192.168.1.20"]
    )
    lan.refresh()
    kind, info = zc.calls[1]
    assert kind == "update"
    assert info.properties[b"url"] == b"https://cloud.example.com"
    assert set(info.properties) == {b"name", b"version", b"url"}

    wanted[0] = None
    lan.refresh()
    assert zc.calls[2][0] == "unregister"
    assert lan.status()["on"] is False
    lan.stop()
    assert zc.calls[-1][0] == "close"


def test_a_failing_network_is_a_status_not_a_crash() -> None:
    def broken():
        raise OSError("no multicast here")

    lan = LanAnnouncer(
        lambda: Announcement("x", "X", "1", 1, "http://x.local:1", addresses=["10.0.0.2"]),
        zeroconf_factory=broken,
    )
    lan.refresh()
    assert lan.status()["error"] == "no multicast here"


def test_what_the_cloud_announces(config) -> None:
    lan = announcer(config, lambda: "The Larsens", addresses=lambda: ["192.168.1.20"])
    # Listening on loopback only, with no address of its own: nothing a neighbour could reach.
    config.host = "127.0.0.1, ::1"
    assert lan.describe() is None
    config.host = "0.0.0.0"
    home = lan.describe()
    assert (home.label, home.port, home.url) == ("the-larsens", 8787, "http://the-larsens.local:8787")
    assert home.addresses == ["192.168.1.20"] and set(home.properties()) == {"name", "version", "url"}
    # With an address of its own, that is the one to open.
    config.public_url = "https://cloud.example.com/"
    assert lan.describe().url == "https://cloud.example.com"


def test_access_lan_false_announces_nothing(config, users) -> None:
    assert create_app(config).state.cloudmorrow.lan is not None
    config.access_lan = False
    assert create_app(config).state.cloudmorrow.lan is None
