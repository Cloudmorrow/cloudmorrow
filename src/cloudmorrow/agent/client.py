"""HTTP client the agent uses to talk to the Cloudmorrow server."""

from __future__ import annotations

from pathlib import Path

import httpx

from cloudmorrow import __version__
from cloudmorrow.agent.config import AgentConfig
from cloudmorrow.httpcommon import ServerError
from cloudmorrow.httpcommon import detail as _detail

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class AgentApiError(ServerError):
    """What the agent's client raises: the server's refusal, or no server at all."""


class AgentClient:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        AgentApiError.refuse_insecure(config.server_url, allow_insecure=config.allow_insecure_http)
        self._client = httpx.Client(
            base_url=config.server_url,
            timeout=TIMEOUT,
            verify=config.verify_tls,
            headers={"User-Agent": f"cloudmorrow-agent/{__version__}"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AgentClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _headers(self, authenticated: bool = True) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.agent_token}"} if authenticated else {}

    def _check(self, response: httpx.Response) -> dict | None:
        if response.status_code >= 400:
            detail = _detail(response)
            raise AgentApiError(str(detail), status_code=response.status_code, payload=detail)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _post(self, url: str, payload: dict, *, authenticated: bool = True) -> dict | None:
        try:
            response = self._client.post(url, json=payload, headers=self._headers(authenticated))
        except httpx.HTTPError as exc:
            raise AgentApiError.unreachable(self.config.server_url, exc) from exc
        return self._check(response)

    def _get(self, url: str) -> dict | None:
        try:
            response = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentApiError.unreachable(self.config.server_url, exc) from exc
        return self._check(response)

    def enroll(self, enrollment_token: str, name: str, hostname: str, platform: str) -> dict:
        payload = {
            "enrollment_token": enrollment_token,
            "name": name,
            "hostname": hostname,
            "platform": platform,
            "version": __version__,
            "capabilities": self.config.capabilities,
        }
        return self._post("/api/agent/enroll", payload, authenticated=False) or {}

    def heartbeat(self, hostname: str, platform: str) -> dict:
        payload = {
            "hostname": hostname,
            "platform": platform,
            "version": __version__,
            "capabilities": self.config.capabilities,
        }
        return self._post("/api/agent/heartbeat", payload) or {}

    def claim_job(self) -> dict | None:
        return self._post("/api/agent/jobs/claim", {})

    # -- local backups (agent/sync.py) --------------------------------------
    def syncs(self) -> list[dict]:
        """The folders on this machine to back up, with when each last ran."""
        return self._get("/api/agent/syncs") or []  # type: ignore[return-value]

    def sync_files(self, sync_id: int) -> dict:
        """What the drive holds under a backup's folder: {path: {size, modified}}."""
        return self._get(f"/api/agent/syncs/{sync_id}/files") or {}  # type: ignore[return-value]

    def sync_put(self, sync_id: int, rel: str, source: Path, modified: float) -> dict:
        """One file up, streamed from *source*, written over what the drive had."""
        try:
            with open(source, "rb") as handle:
                response = self._client.put(
                    f"/api/agent/syncs/{sync_id}/file",
                    params={"path": rel, "modified": f"{modified:.3f}"},
                    content=handle,
                    headers={**self._headers(), "Content-Type": "application/octet-stream"},
                    timeout=httpx.Timeout(600.0, connect=10.0),
                )
        except httpx.HTTPError as exc:
            raise AgentApiError.unreachable(self.config.server_url, exc) from exc
        return self._check(response) or {}

    def sync_remove(self, sync_id: int, rel: str) -> dict:
        try:
            response = self._client.delete(
                f"/api/agent/syncs/{sync_id}/file", params={"path": rel}, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise AgentApiError.unreachable(self.config.server_url, exc) from exc
        return self._check(response) or {}

    def sync_done(self, sync_id: int, result: dict) -> dict:
        return self._post(f"/api/agent/syncs/{sync_id}/done", result) or {}

    def report(self, job_id: int, status: str, result: dict) -> None:
        self._post(f"/api/agent/jobs/{job_id}/result", {"status": status, "result": result})

    # -- a Quill's code on this machine -------------------------------------
    def machine_quills(self) -> list[dict]:
        """The Quills with machine handlers that are on for this machine's owner."""
        return self._get("/api/agent/quills") or []  # type: ignore[return-value]

    def runtimes(self) -> dict:
        """The catalog's runtimes, for a handler that needs a program fetched for this machine."""
        return self._get("/api/agent/quills/runtimes") or {}  # type: ignore[return-value]

    def quill_code(self, quill: str) -> bytes:
        """The installed copy of a Quill, as a tarball."""
        try:
            response = self._client.get(f"/api/agent/quills/{quill}/code", headers=self._headers())
        except httpx.HTTPError as exc:
            raise AgentApiError.unreachable(self.config.server_url, exc) from exc
        if response.status_code >= 400:
            raise AgentApiError(str(_detail(response)), status_code=response.status_code)
        return response.content

    def quill_host(self, quill: str, op: str, args: dict, *, machine: str = "") -> dict:
        """One request from a machine handler: {ok, value} or {ok: false, kind, message}."""
        return self._post(f"/api/agent/quills/{quill}/host", {"op": op, "args": args, "machine": machine}) or {}

    def notify(self, *, kind: str, title: str, body: str = "") -> dict:
        return self._post("/api/agent/notifications", {"kind": kind, "title": title, "body": body}) or {}
