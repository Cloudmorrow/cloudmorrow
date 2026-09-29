"""The access calls the TUI makes, answered the way routes/access.py answers them."""

from __future__ import annotations

import copy

from cloudmorrow.client.api import ApiError

ZONE = "cloudmorrow.test"
LINK = {
    "code": "KXRT-4829",
    "url": "https://cloudmorrow.test/link",
    "link": "https://cloudmorrow.test/link?code=KXRT-4829",
    "place": "cloudmorrow.test/link",
    "expires_at": "2026-09-29T12:15:00+00:00",
}


def access_status(name: str = "", *, waiting: bool = False, on_mesh: bool = True) -> dict:
    """What an administrator sees: not linked, a code waiting, or linked as *name*."""
    host = f"{name}.{ZONE}" if name else ""
    linked = bool(name)
    mesh_on = linked and on_mesh
    return {
        "address": f"https://{host}" if mesh_on else "",
        "linked": linked,
        "name": name,
        "host": host,
        "lan": {
            "on": True,
            "announced": True,
            "hostname": f"{name or 'the-larsens'}.local",
            "url": "",
            "addresses": ["192.168.1.20"],
            "error": "",
        },
        "mesh": {
            "on": mesh_on,
            "login_server": "https://mesh.cloudmorrow.test" if mesh_on else "",
            "box": {
                "installed": True,
                "state": "Running" if mesh_on else "NeedsLogin",
                "address": "100.64.0.7" if mesh_on else "",
                "hostname": "cloud",
                "error": "",
            },
            "address": "100.64.0.7" if mesh_on else "",
        },
        "control": "https://relay.cloudmorrow.test",
        "zone": ZONE if linked else "",
        "link": dict(LINK) if waiting and not linked else None,
        "link_state": "linked" if linked else ("waiting" if waiting else ""),
        "link_error": "",
        "setup_error": "" if mesh_on or not linked else "tailscale up failed: access denied",
        "caddy": {"configured": True, "site": "", "error": ""},
    }


class FakeAccess:
    """Access state and what was asked of it."""

    def setup_access(self) -> None:
        self.access_state = access_status()
        self.access_calls: list[tuple] = []
        self.device_list: list[dict] = [
            {
                "id": "d1",
                "label": "anna: phone",
                "owner": "anna",
                "device": "phone",
                "box": False,
                "address": "100.64.0.9",
                "online": True,
                "last_seen": "",
            },
            {
                "id": "d2",
                "label": "",
                "owner": "",
                "device": "",
                "box": False,
                "address": "100.64.0.10",
                "online": False,
                "last_seen": "2026-09-28T10:00:00+00:00",
            },
        ]

    async def access(self) -> dict:
        return copy.deepcopy(self.access_state)

    async def start_link(self) -> dict:
        self.access_calls.append(("link",))
        if self.access_state["linked"]:
            raise ApiError("this cloud is already linked", status_code=409)
        self.access_state = access_status(waiting=True)
        return await self.access()

    def code_entered(self, name: str = "larsens") -> None:
        """Somebody entered the code on the website; the box linked itself."""
        self.access_state = access_status(name)

    async def cancel_link(self) -> dict:
        self.access_calls.append(("cancel",))
        self.access_state = access_status()
        return await self.access()

    async def unlink(self) -> dict:
        self.access_calls.append(("unlink",))
        self.access_state = access_status()
        return await self.access()

    async def access_setup(self) -> dict:
        self.access_calls.append(("setup",))
        self.access_state = access_status(self.access_state["name"])
        return await self.access()

    async def mesh_invite(self) -> dict:
        self.access_calls.append(("invite",))
        if not self.access_state["mesh"]["on"]:
            raise ApiError("this cloud is not linked to a cloudmorrow.com account", status_code=409)
        host = self.access_state["host"]
        return {
            "code": "7QX2MP",
            "expires_at": "2026-09-29T12:10:00+00:00",
            "login_server": "https://mesh.cloudmorrow.test",
            "host": host,
            "command": f"curl -fsSL https://{host}/install.sh | sh",
        }

    async def mesh_devices(self, *, everyone: bool = False) -> list[dict]:
        return [dict(d) for d in self.device_list]

    async def label_mesh_device(self, device_id: str, owner: str, device: str) -> dict:
        self.access_calls.append(("label", device_id, owner, device))
        for d in self.device_list:
            if d["id"] == device_id:
                d.update(owner=owner, device=device, label=f"{owner}: {device}")
                return dict(d)
        raise ApiError("no such device", status_code=404)
