"""HTTP client the agent uses to talk to the Cloudmorrow server."""

from __future__ import annotations

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

    def report(self, job_id: int, status: str, result: dict) -> None:
        self._post(f"/api/agent/jobs/{job_id}/result", {"status": status, "result": result})

    # -- config bundles ----------------------------------------------------
    def config_state(self, bundle: str) -> dict:
        """The manifest: revision and hashes, without the contents."""
        return self._get(f"/api/agent/config/{bundle}") or {}

    def config_files(self, bundle: str) -> dict:
        """The whole bundle, contents and all."""
        return self._get(f"/api/agent/config/{bundle}/files") or {}

    def push_config(self, bundle: str, files: list[dict], *, base_revision: int | None) -> dict:
        """Offer this machine's copy. 409 means somebody else got there first."""
        return (
            self._post(
                f"/api/agent/config/{bundle}",
                {"files": files, "base_revision": base_revision},
            )
            or {}
        )

    # -- a Quill's code on this machine -------------------------------------
    def machine_quills(self) -> list[dict]:
        """The Quills with machine handlers that are on for this machine's owner."""
        return self._get("/api/agent/quills") or []  # type: ignore[return-value]

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
