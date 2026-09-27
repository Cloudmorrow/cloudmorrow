"""The access calls the TUI makes, answered the way routes/access.py answers them."""

from __future__ import annotations

import copy

from cloudmorrow.client.api import ApiError

ZONE = "cloudmorrow.test"


def access_status(name: str = "", *, public: bool = False, private: bool = False) -> dict:
    host = f"{name}.{ZONE}" if name else ""
    return {
        "address": f"https://{host}" if host and (public or private) else "",
        "name": name,
        "host": host,
        "lan": {"on": True, "hostname": f"{name or 'cloudmorrow'}.local", "url": "",
                "addresses": ["192.168.1.20"], "error": ""},
        "public": {
            "on": public,
            "tunnel": {
                "state": "connected" if public else "off",
                "host": host,
                "connected_since": "2026-09-27T12:00:00+00:00" if public else "",
                "reconnects": 2 if public else 0,
                "bytes_in": 1_234_567 if public else 0,
                "bytes_out": 45_678_901 if public else 0,
                "streams": 1 if public else 0,
                "error": "",
            },
        },
        "private": {
            "on": private,
            "login_server": "https://mesh.cloudmorrow.test" if private else "",
            "mesh": {"installed": True, "state": "Running" if private else "Stopped",
                     "address": "100.64.0.7" if private else "", "hostname": "cloud", "error": ""},
            "address": "100.64.0.7" if private else "",
            "error": "",
        },
        "control": "https://relay.cloudmorrow.test",
        "enrolled": bool(name),
        "zone": ZONE if name else "",
        "suggested_name": "cloudmorrow",
        "caddy": {"configured": True, "site": "", "error": ""},
    }


class FakeAccess:
    """Access state and what was asked of it."""

    def setup_access(self) -> None:
        self.access_state = access_status()
        self.access_calls: list[tuple] = []
        self.device_list: list[dict] = [
            {"id": "d1", "name": "annas-phone", "for": "anna: phone", "owner": "anna",
             "address": "100.64.0.9", "online": True, "last_seen": ""},
        ]

    async def access(self) -> dict:
        return copy.deepcopy(self.access_state)

    def _reshape(self) -> dict:
        s = self.access_state
        self.access_state = access_status(
            s["name"], public=s["public"]["on"], private=s["private"]["on"]
        )
        return copy.deepcopy(self.access_state)

    async def claim_name(self, name: str, *, public: bool = True, private: bool = False) -> dict:
        self.access_calls.append(("claim", name, public, private))
        if name == "taken":
            raise ApiError("taken is taken; try another name", status_code=409)
        self.access_state = access_status(name, public=public, private=private)
        return await self.access()

    async def rename_access(self, name: str) -> dict:
        self.access_calls.append(("rename", name))
        self.access_state["name"] = name
        return self._reshape()

    async def release_name(self) -> dict:
        self.access_calls.append(("release",))
        self.access_state = access_status()
        return await self.access()

    async def set_public(self, on: bool) -> dict:
        self.access_calls.append(("public", on))
        self.access_state["public"]["on"] = on
        return self._reshape()

    async def set_private(self, on: bool) -> dict:
        self.access_calls.append(("private", on))
        self.access_state["private"]["on"] = on
        return self._reshape()

    async def mesh_devices(self, *, everyone: bool = False) -> list[dict]:
        return [dict(d) for d in self.device_list]
