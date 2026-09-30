"""After signing in: this computer onto the cloud's mesh, without being asked to.

A linked cloud is reached from anywhere through the relay, but a native
client does better than that: once signed in it joins the cloud's mesh
(docs/HOSTING.md, "Native clients on the mesh"), and from then on the
cloud's name resolves to the box and the traffic goes straight there. No
code and no key for the person: the key comes from the cloud, asked for
with the sign-in just made.

It is never in the way. A cloud that is not on a mesh, a computer already
on this one, `mesh = false` in the client's config, or a `--no-mesh` all
mean nothing happens; a failure is one sentence and the client carries on
through the relay. Declining to install Tailscale is remembered as
`mesh = false`, so it is asked once; `cm access join` asks again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from cloudmorrow.client import meshjoin
from cloudmorrow.client.config import ClientConfig


@dataclass(slots=True)
class Joined:
    # "joined", "already", "declined", "failed", or "" when there was nothing to do.
    outcome: str = ""
    address: str = ""
    detail: str = ""

    def sentence(self, host: str = "") -> str:
        where = host or "the cloud"
        if self.outcome == "joined":
            return f"on {where}'s mesh at {self.address or '?'}: this computer now goes straight to it"
        if self.outcome == "already":
            return f"on {where}'s mesh already, at {self.address}"
        if self.outcome == "declined":
            return "not on the mesh: it works through the relay; cloudmorrow access join puts it on later"
        if self.outcome == "failed":
            return f"not on the mesh ({self.detail}); it works through the relay; cloudmorrow access join tries again"
        return ""


async def wanted(api, config: ClientConfig, run: meshjoin.Runner | None = None) -> bool:
    """Would join_after_signin do anything here: a cloud on a mesh this computer is not on?

    For the TUI, which has to give the terminal up for sudo, and does not
    want to for nothing.
    """
    if not config.mesh:
        return False
    try:
        mesh = (await api.access()).get("mesh") or {}
    except Exception:
        return False
    login_server = str(mesh.get("login_server") or "")
    if not mesh.get("on") or not login_server:
        return False
    here = meshjoin.state(run or meshjoin._run)
    return not (here.running and here.login_server and here.on(login_server))


async def join_after_signin(
    api,
    config: ClientConfig,
    *,
    ask_install: Callable[[], bool] | None,
    graphical: bool = False,
    device: str = "",
    run: meshjoin.Runner | None = None,
) -> Joined:
    """Onto the mesh of the cloud *api* is signed in to, if it has one and this computer is not on it."""
    if not config.mesh:
        return Joined()
    try:
        status = await api.access()
    except Exception:  # an older cloud, or none reachable: nothing to join
        return Joined()
    mesh = status.get("mesh") or {}
    login_server = str(mesh.get("login_server") or "")
    if not mesh.get("on") or not login_server:
        return Joined()
    runner = run or meshjoin._run
    here = meshjoin.state(runner)
    name = device or meshjoin.device_name()
    if here.running and here.login_server and here.on(login_server):
        if here.address:
            await _claim(api, here.address, name)
        return Joined("already", here.address)
    if meshjoin.tailscale_binary() is None and ask_install is None:
        return Joined("failed", detail="Tailscale is not installed")

    declined = False

    def consent() -> bool:
        nonlocal declined
        yes = bool(ask_install and ask_install())
        declined = not yes
        return yes

    try:
        key = await api.mesh_key()
        joined = meshjoin.join(key, install=consent, graphical=graphical, run=runner)
    except meshjoin.JoinError as exc:
        if declined:
            config.mesh = False
            config.save()
            return Joined("declined")
        return Joined("failed", detail=str(exc))
    except Exception as exc:  # the cloud would not give a key
        return Joined("failed", detail=str(exc))
    if joined.address:
        await _claim(api, joined.address, name)
    return Joined("joined", joined.address)


async def _claim(api, address: str, device: str) -> None:
    """Tell the cloud the computer at *address* is the signed-in person's. Best effort."""
    try:
        await api.claim_mesh_device(address, device)
    except Exception:
        pass
