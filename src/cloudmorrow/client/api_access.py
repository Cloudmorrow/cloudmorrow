"""The client's calls for reaching a cloud (server/routes/access.py).

A file of its own, mixed into `CloudmorrowClient`, so the access feature
does not grow the client every other feature shares.
"""

from __future__ import annotations

from typing import Any

import httpx


class AccessCalls:
    """Needs `_request`, which `CloudmorrowClient` has."""

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:  # pragma: no cover
        raise NotImplementedError

    async def access(self) -> dict:
        """How the cloud is reached. An administrator gets the workings too."""
        return (await self._request("GET", "/api/access")).json()

    async def start_link(self) -> dict:
        """A code to enter at cloudmorrow.com/link (admin). The answer is the status, with `link`."""
        return (await self._request("POST", "/api/access/link")).json()

    async def cancel_link(self) -> dict:
        return (await self._request("DELETE", "/api/access/link")).json()

    async def unlink(self) -> dict:
        """Give the name back; the mesh and its devices go too (admin)."""
        return (await self._request("POST", "/api/access/unlink")).json()

    async def access_setup(self) -> dict:
        """Try again to put a linked cloud on its mesh (admin)."""
        return (await self._request("POST", "/api/access/setup")).json()

    async def mesh_key(self) -> dict:
        """A one-time key for one of your computers: {key, login_server, expires_at, hostname, host}."""
        return (await self._request("POST", "/api/access/mesh/key")).json()

    async def mesh_invite(self) -> dict:
        """An invite code for a device: {code, expires_at, login_server, host, command}."""
        return (await self._request("POST", "/api/access/mesh/invite")).json()

    async def claim_mesh_device(self, address: str, device: str = "") -> dict:
        """Tell the cloud the computer at *address* on its mesh is yours."""
        body = {"address": address, "device": device}
        return (await self._request("POST", "/api/access/mesh/mine", json=body)).json()

    async def mesh_devices(self, *, everyone: bool = False) -> list[dict]:
        response = await self._request("GET", "/api/access/mesh/devices", params={"everyone": everyone})
        return response.json()["devices"]

    async def label_mesh_device(self, device_id: str, owner: str, device: str) -> dict:
        body = {"owner": owner, "device": device}
        return (await self._request("PUT", f"/api/access/mesh/devices/{device_id}", json=body)).json()

    async def remove_mesh_device(self, device_id: str) -> None:
        await self._request("DELETE", f"/api/access/mesh/devices/{device_id}")
